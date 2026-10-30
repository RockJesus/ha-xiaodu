"""Vacuum platform for XiaoDu (小度) integration.

Supports robot cleaners (SWEEPING_ROBOT / ROBOT_VACUUM / SWEEPER).
Controls start / pause / stop / return-to-base through the DuerOS
cleaning directives.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import XiaoDuAPI
from .appliance_types import ApplianceTypes
from .const import DOMAIN
from .coordinator import XiaoDuDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up XiaoDu vacuums from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]
    hub_device_id = entry_data["hub_device_id"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_vacuum(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        entities.append(XiaoDuVacuum(api, coordinator, hub_device_id, appliance))

    async_add_entities(entities)


class XiaoDuVacuum(CoordinatorEntity, StateVacuumEntity):
    """Representation of a XiaoDu robot vacuum."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        hub_device_id: str,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the vacuum."""
        super().__init__(coordinator)
        self._hub_device_id = hub_device_id
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_vacuum"
        self._attr_name = appliance.get("friendlyName", "小度扫地机")
        self._attr_should_poll = False
        self._attr_supported_features = (
            VacuumEntityFeature.START
            | VacuumEntityFeature.STOP
            | VacuumEntityFeature.PAUSE
            | VacuumEntityFeature.RETURN_HOME
            | VacuumEntityFeature.STATE
        )

        self._manufacturer = appliance.get("botName", "小度")
        self._model = appliance.get("model", "")

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": self._model or "小度扫地机",
            "via_device_id": self._hub_device_id,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the current vacuum activity."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        raw = None
        for key in ("cleaningState", "cleaningStatus", "workStatus"):
            if key in state:
                raw = state[key].get("value")
                break
        if raw is None:
            on_off = state.get("turnOnState", {}).get("value")
            raw = "CLEANING" if str(on_off).lower() == "on" else "DOCKED"

        value = str(raw).upper()
        if value in ("CLEANING", "SWEEPING", "RUNNING"):
            return VacuumActivity.CLEANING
        if value in ("PAUSED", "PAUSE", "PAUSING"):
            return VacuumActivity.PAUSED
        if value in ("RETURNING", "RETURN_TO_BASE", "GOING_HOME", "DOCKING"):
            return VacuumActivity.RETURNING
        if value in ("CHARGING", "DOCKED", "CHARGED", "IDLE", "STANDBY"):
            return VacuumActivity.DOCKED
        if value in ("STOPPED", "STOP", "OFF"):
            return VacuumActivity.IDLE
        return VacuumActivity.IDLE

    @property
    def battery_level(self) -> int | None:
        """Return the current battery level."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        for key in ("battery", "batteryLevel", "batteryPower"):
            if key in state:
                try:
                    return int(state[key].get("value"))
                except (TypeError, ValueError):
                    return None
        return None

    async def async_start(self) -> None:
        """Start the vacuum."""
        await self._api.vacuum_start()
        await self.coordinator.async_request_refresh()

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the vacuum."""
        await self._api.vacuum_stop()
        await self.coordinator.async_request_refresh()

    async def async_pause(self) -> None:
        """Pause the vacuum."""
        await self._api.vacuum_pause()
        await self.coordinator.async_request_refresh()

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return the vacuum to its dock."""
        await self._api.vacuum_return_to_base()
        await self.coordinator.async_request_refresh()
