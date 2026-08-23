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
    CONF_COOKIE,
    CONF_DEVICES,
    CONF_HOUSE_ID,
    CONF_HOUSE_NAME,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    ERROR_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)


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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> XiaoDuOptionsFlow:
        """Create the options flow."""
        return XiaoDuOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step — enter cookie."""
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
                self._house_list = await api.get_house_list()
                if not self._house_list:
                    errors["base"] = ERROR_CANNOT_CONNECT
                else:
                    return await self.async_step_house()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COOKIE): str,
                }
            ),
            errors=errors,
        )

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
