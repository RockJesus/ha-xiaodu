"""XiaoDu (小度) Smart Home integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import XiaoDuAPI
from .const import (
    CONF_APPLIANCE_TYPES,
    CONF_COOKIE,
    CONF_DEVICES,
    CONF_HOUSE_ID,
    CONF_HOUSE_NAME,
    DOMAIN,
)
from .coordinator import XiaoDuDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Supported platforms
PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.COVER,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.FAN,
    Platform.LOCK,
    Platform.BUTTON,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the XiaoDu component (YAML not supported, use config flow)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up XiaoDu from a config entry."""
    session = async_get_clientsession(hass)
    cookie = entry.data.get(CONF_COOKIE, "")
    house_id = entry.data.get(CONF_HOUSE_ID, "")
    devices = entry.data.get(CONF_DEVICES, [])
    appliance_types = entry.data.get(CONF_APPLIANCE_TYPES, [])

    # Build API instances for each device
    apis: dict[str, XiaoDuAPI] = {}
    for i, device in enumerate(devices):
        appliance_id = device.get("applianceId", "")
        if not appliance_id:
            continue
        api = XiaoDuAPI(
            cookie=cookie,
            session=session,
            house_id=house_id,
            appliance_id=appliance_id,
        )
        # Attach appliance types for platform classification
        if i < len(appliance_types):
            api.appliance_types = appliance_types[i].get("applianceTypes", [])
        else:
            api.appliance_types = []
        apis[appliance_id] = api

    # Create coordinator
    coordinator = XiaoDuDataUpdateCoordinator(hass, apis)
    await coordinator.async_config_entry_first_refresh()

    # Store data
    hass.data[DOMAIN][entry.entry_id] = {
        "apis": apis,
        "coordinator": coordinator,
        "cookie": cookie,
        "house_id": house_id,
        "house_name": entry.data.get(CONF_HOUSE_NAME, ""),
        "appliance_types": appliance_types,
    }

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a XiaoDu config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the integration."""
    await hass.config_entries.async_reload(entry.entry_id)
