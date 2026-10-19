"""Config flow for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

try:
    import probatio  # HA 2026.10+ data entry flow schema library
except ImportError:  # pragma: no cover - older HA
    probatio = None

from .api import XiaoDuAPI
from .const import (
    CONF_APPLIANCE_TYPES,
    CONF_BAIDUID,
    CONF_CODESTRING,
    CONF_SCAN_INTERVAL,
    CONF_COOKIE,
    CONF_DEVICES,
    CONF_HOUSE_ID,
    CONF_HOUSE_NAME,
    CONF_LOGIN_MODE,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_VERIFYCODE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_LOGIN_FAILED,
    ERROR_LOGIN_BLOCKED,
    ERROR_UNKNOWN,
    LOGIN_MODE_COOKIE,
    LOGIN_MODE_PASSWORD,
    MIN_SCAN_INTERVAL,
)
from .login import BaiduLogin, BaiduLoginBlocked, BaiduLoginError

_LOGGER = logging.getLogger(__name__)

LOGIN_MODE_LABELS = {
    LOGIN_MODE_PASSWORD: "用户名密码登录",
    LOGIN_MODE_COOKIE: "Cookie 登录（推荐）",
}


class XiaoDuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for XiaoDu."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._cookie: str | None = None
        self._house_list: dict[str, str] | None = None
        self._house_id: str | None = None
        self._house_name: str | None = None
        self._device_dict: dict[str, str] | None = None
        self._login: BaiduLogin | None = None
        self._login_state: dict[str, str] = {}
        self._reauth_entry: ConfigEntry | None = None
        self._pending_username = ""
        self._pending_password = ""
        self._pending_baiduid = ""
        self._verify_token = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> XiaoDuOptionsFlow:
        """Create the options flow.

        Note: HA 2026.10+ OptionsFlow base class exposes ``config_entry`` as a
        read-only property; the flow must be constructed without arguments
        (custom __init__/passing config_entry breaks initialisation).
        """
        return XiaoDuOptionsFlow()

    # ── Reauth (cookie expired, auto relogin failed) ─────────────────

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Re-authenticate after the stored cookie expired.

        Offer the same login-method choice as the initial flow so users who
        originally set up with a cookie get a cookie step too (hacs review
        2026-10-18).
        """
        self._reauth_entry = self._get_reauth_entry()
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_aborted")
        return await self.async_step_user()

    # ── Step 1: choose login method ──────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step — choose login method."""
        if user_input is not None:
            mode = user_input[CONF_LOGIN_MODE]
            if mode == LOGIN_MODE_PASSWORD:
                return await self.async_step_login()
            return await self.async_step_cookie()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOGIN_MODE, default=LOGIN_MODE_PASSWORD
                    ): vol.In(LOGIN_MODE_LABELS),
                }
            ),
        )

    # ── Step 2a: username / password login ───────────────────────────

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle username/password login."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            baiduid = user_input.get(CONF_BAIDUID, "").strip()
            # Remember credentials for entry creation and auto relogin —
            # always, not only on the SMS branch (hacs review 2026-10-18).
            self._pending_username = username
            self._pending_password = password
            self._pending_baiduid = baiduid
            if not username or not password:
                errors["base"] = ERROR_LOGIN_FAILED
            else:
                session = async_get_clientsession(self.hass)
                self._login = BaiduLogin(session)
                try:
                    result = await self._login.login(
                        username, password, baiduid=baiduid
                    )
                except BaiduLoginBlocked as exc:
                    _LOGGER.warning("XiaoDu password login blocked: %s", exc)
                    if exc.verify_token:
                        # Risk control wants SMS verification — remember the
                        # session, try to dispatch the code, ask for it.
                        self._verify_token = exc.verify_token
                        sent = await self._login.send_sms_code(
                            username,
                            exc.verify_token,
                            baiduid=baiduid,
                        )
                        return await self.async_step_sms_verify(
                            sms_sent=sent
                        )
                    errors["base"] = ERROR_LOGIN_BLOCKED
                except BaiduLoginError as exc:
                    _LOGGER.warning("XiaoDu password login failed: %s", exc)
                    errors["base"] = ERROR_LOGIN_FAILED
                else:
                    self._cookie = result["bduss"]
                    if self._reauth_entry is not None:
                        return await self._finish_reauth()
                    return await self._proceed_after_auth()

        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_BAIDUID): str,
                }
            ),
            errors=errors,
            description_placeholders={},
        )

    # ── Step 2a2: SMS verification code ─────────────────────────────

    async def async_step_sms_verify(
        self,
        user_input: dict[str, Any] | None = None,
        sms_sent: bool | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect the SMS verification code and retry the login."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            code = user_input.get(CONF_VERIFYCODE, "").strip()
            if not code:
                errors["base"] = ERROR_LOGIN_FAILED
            else:
                try:
                    result = await self._login.login(
                        self._pending_username,
                        self._pending_password,
                        baiduid=self._pending_baiduid,
                        verifycode=code,
                        codestring=self._verify_token,
                    )
                except BaiduLoginBlocked as exc:
                    _LOGGER.warning("SMS verify login blocked again: %s", exc)
                    self._verify_token = exc.verify_token or self._verify_token
                    errors["base"] = ERROR_LOGIN_BLOCKED
                    description_placeholders["detail"] = str(exc)
                except BaiduLoginError as exc:
                    _LOGGER.warning("SMS verify login failed: %s", exc)
                    errors["base"] = ERROR_LOGIN_FAILED
                    description_placeholders["detail"] = str(exc)
                else:
                    self._cookie = result["bduss"]
                    if self._reauth_entry is not None:
                        return await self._finish_reauth()
                    return await self._proceed_after_auth()

        placeholders = {
            "sent": "已发送短信验证码，请查收。" if sms_sent
            else "自动发送验证码失败，请在浏览器或小度 App 登录一次触发短信验证，再输入验证码。",
        }
        placeholders.update(description_placeholders)
        return self.async_show_form(
            step_id="sms_verify",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VERIFYCODE): str,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def _finish_reauth(self) -> config_entries.ConfigFlowResult:
        """Update the existing entry with the fresh cookie after reauth.

        Only overwrite username/password when they were actually provided
        (password-mode reauth); a cookie-mode reauth must keep the stored
        credentials untouched.
        """
        entry = self._reauth_entry
        if entry is None:
            return self.async_abort(reason="reauth_aborted")
        new_data = dict(entry.data)
        new_data[CONF_COOKIE] = self._cookie
        if self._pending_username:
            new_data[CONF_USERNAME] = self._pending_username
        if self._pending_password:
            new_data[CONF_PASSWORD] = self._pending_password
        self.hass.config_entries.async_update_entry(entry, data=new_data)
        return self.async_abort(reason="reauth_successful")

    # ── Step 2b: cookie login (original flow) ────────────────────────

    async def async_step_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle cookie login."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cookie = user_input[CONF_COOKIE].strip()
            session = async_get_clientsession(self.hass)
            api = XiaoDuAPI(cookie=cookie, session=session)

            valid, error = await api.check_session()
            if not valid:
                if error == "invalid_auth":
                    errors["base"] = ERROR_INVALID_AUTH
                elif error == "cannot_connect":
                    errors["base"] = ERROR_CANNOT_CONNECT
                else:
                    errors["base"] = ERROR_UNKNOWN
            else:
                self._cookie = cookie
                if self._reauth_entry is not None:
                    # Cookie reauth: refresh the stored cookie on the existing
                    # entry (username/password, if any, are kept untouched).
                    return await self._finish_reauth()
                return await self._proceed_after_auth()

        return self.async_show_form(
            step_id="cookie",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): str,
                }
            ),
            description_placeholders={
                "url": "https://xiaodu.baidu.com/saiya/smarthome/index.html",
            },
            errors=errors,
        )

    # ── Shared: house list after auth ────────────────────────────────

    async def _proceed_after_auth(
        self,
    ) -> config_entries.ConfigFlowResult:
        """After auth (cookie obtained), load houses and continue."""
        assert self._cookie is not None
        session = async_get_clientsession(self.hass)
        api = XiaoDuAPI(cookie=self._cookie, session=session)
        self._house_list = await api.get_house_list()
        if not self._house_list:
            return self.async_abort(reason="no_house_found")
        return await self.async_step_house()

    # ── House selection ──────────────────────────────────────────────

    async def async_step_house(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle house selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._house_id = user_input[CONF_HOUSE_ID]
            self._house_name = self._house_list.get(self._house_id, "")
            session = async_get_clientsession(self.hass)
            api = XiaoDuAPI(cookie=self._cookie, session=session)
            self._device_dict = await api.get_device_dict(self._house_id)
            if not self._device_dict:
                errors["base"] = ERROR_CANNOT_CONNECT
            else:
                return await self.async_step_device()

        return self.async_show_form(
            step_id="house",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOUSE_ID): vol.In(self._house_list or {}),
                }
            ),
            errors=errors,
        )

    # ── Device selection ─────────────────────────────────────────────

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle device selection step."""
        if user_input is not None:
            device_ids = user_input["device_ids"]
            if not device_ids:
                return self.async_show_form(
                    step_id="device",
                    data_schema=vol.Schema(
                        {
                            vol.Required("device_ids"): cv.multi_select(
                                self._device_dict or {}
                            ),
                        }
                    ),
                    errors={"base": "no_device_selected"},
                )

            # Fetch appliance types for selected devices
            session = async_get_clientsession(self.hass)
            api = XiaoDuAPI(cookie=self._cookie, session=session)
            appliances = await api.get_appliances_by_ids(
                self._house_id, list(device_ids)
            )

            devices = []
            appliance_types = []
            for appliance in appliances:
                aid = appliance.get("applianceId", "")
                if aid in device_ids:
                    devices.append({"applianceId": aid})
                    appliance_types.append(
                        {"applianceTypes": appliance.get("applianceTypes", [])}
                    )

            # Ensure all selected devices are included even if detail fetch failed
            for did in device_ids:
                if not any(d["applianceId"] == did for d in devices):
                    devices.append({"applianceId": did})
                    appliance_types.append({"applianceTypes": []})

            return self.async_create_entry(
                title=f"小度: {self._house_name}",
                data={
                    CONF_COOKIE: self._cookie,
                    CONF_HOUSE_ID: self._house_id,
                    CONF_HOUSE_NAME: self._house_name,
                    CONF_DEVICES: devices,
                    CONF_APPLIANCE_TYPES: appliance_types,
                    # Store credentials for automatic relogin (hacs review
                    # 2026-10-18); empty for cookie-mode setup.
                    CONF_USERNAME: self._pending_username,
                    CONF_PASSWORD: self._pending_password,
                },
            )

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required("device_ids"): cv.multi_select(
                        self._device_dict or {}
                    ),
                }
            ),
        )


class XiaoDuOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for XiaoDu — cookie, devices and scan interval.

    No custom __init__: the base class manages config_entry (available after
    initialisation, i.e. inside async_step_* via the property).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Options menu — choose an action."""
        if user_input is not None:
            action = user_input["next_step_id"]
            if action == "cookie":
                return await self.async_step_cookie()
            if action == "devices":
                return await self.async_step_devices()
            return await self.async_step_scan_interval()

        return self.async_show_menu(
            step_id="init",
            menu_options=["cookie", "devices", "scan_interval"],
        )

    async def async_step_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update the BDUSS cookie."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cookie = user_input[CONF_COOKIE].strip()
            session = async_get_clientsession(self.hass)
            api = XiaoDuAPI(cookie=cookie, session=session)

            valid, error = await api.check_session()
            if not valid:
                if error == "invalid_auth":
                    errors["base"] = ERROR_INVALID_AUTH
                elif error == "cannot_connect":
                    errors["base"] = ERROR_CANNOT_CONNECT
                else:
                    errors["base"] = ERROR_UNKNOWN
            else:
                # Update cookie in config entry data
                new_data = dict(self.config_entry.data)
                new_data[CONF_COOKIE] = cookie
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="cookie",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): str,
                }
            ),
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Re-select the devices to integrate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_ids = user_input["device_ids"]
            if not device_ids:
                errors["base"] = "no_device_selected"
            else:
                session = async_get_clientsession(self.hass)
                cookie = self.config_entry.data.get(CONF_COOKIE, "")
                house_id = self.config_entry.data.get(CONF_HOUSE_ID, "")
                api = XiaoDuAPI(cookie=cookie, session=session)
                appliances = await api.get_appliances_by_ids(
                    house_id, list(device_ids)
                )
                devices = []
                appliance_types = []
                for appliance in appliances:
                    aid = appliance.get("applianceId", "")
                    if aid in device_ids:
                        devices.append({"applianceId": aid})
                        appliance_types.append(
                            {"applianceTypes": appliance.get("applianceTypes", [])}
                        )
                for did in device_ids:
                    if not any(d["applianceId"] == did for d in devices):
                        devices.append({"applianceId": did})
                        appliance_types.append({"applianceTypes": []})

                new_data = dict(self.config_entry.data)
                new_data[CONF_DEVICES] = devices
                new_data[CONF_APPLIANCE_TYPES] = appliance_types
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})

        if getattr(self, "_device_dict", None) is None:
            session = async_get_clientsession(self.hass)
            cookie = self.config_entry.data.get(CONF_COOKIE, "")
            house_id = self.config_entry.data.get(CONF_HOUSE_ID, "")
            api = XiaoDuAPI(cookie=cookie, session=session)
            self._device_dict = await api.get_device_dict(house_id)
            if not self._device_dict:
                return self.async_abort(reason="no_house_found")

        current = [
            d.get("applianceId", "")
            for d in self.config_entry.data.get(CONF_DEVICES, [])
        ]
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "device_ids", default=current
                    ): cv.multi_select(self._device_dict),
                }
            ),
            errors=errors,
        )

    async def async_step_scan_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update the device polling interval."""
        if user_input is not None:
            interval = user_input[CONF_SCAN_INTERVAL]
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                options={
                    **self.config_entry.options,
                    CONF_SCAN_INTERVAL: interval,
                },
            )
            return self.async_create_entry(title="", data={})

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        if probatio is not None:
            data_schema = probatio.Schema(
                {
                    probatio.Required(
                        CONF_SCAN_INTERVAL, default=current
                    ): probatio.All(
                        probatio.Coerce(int),
                        probatio.Range(min=MIN_SCAN_INTERVAL),
                    ),
                }
            )
        else:
            data_schema = vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL),
                    ),
                }
            )
        return self.async_show_form(
            step_id="scan_interval",
            data_schema=data_schema,
        )
