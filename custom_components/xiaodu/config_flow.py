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

from .api import XiaoDuAPI
from .const import (
    CONF_APPLIANCE_TYPES,
    CONF_BAIDUID,
    CONF_COOKIE,
    CONF_DEVICES,
    CONF_HOUSE_ID,
    CONF_HOUSE_NAME,
    CONF_LOGIN_MODE,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_LOGIN_FAILED,
    ERROR_LOGIN_BLOCKED,
    ERROR_UNKNOWN,
    LOGIN_MODE_COOKIE,
    LOGIN_MODE_PASSWORD,
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> XiaoDuOptionsFlow:
        """Create the options flow."""
        return XiaoDuOptionsFlow(config_entry)

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
                    errors["base"] = ERROR_LOGIN_BLOCKED
                except BaiduLoginError as exc:
                    _LOGGER.warning("XiaoDu password login failed: %s", exc)
                    errors["base"] = ERROR_LOGIN_FAILED
                else:
                    self._cookie = result["bduss"]
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
                return await self._proceed_after_auth()

        return self.async_show_form(
            step_id="cookie",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): str,
                }
            ),
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
    """Handle options flow for XiaoDu — primarily cookie updates."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options — update cookie."""
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
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): str,
                }
            ),
            errors=errors,
        )
