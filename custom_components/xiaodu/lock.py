"""Lock platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
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
    """Set up XiaoDu locks from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_lock(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        entities.append(XiaoDuLock(api, coordinator, appliance))

    async_add_entities(entities)


class XiaoDuLock(CoordinatorEntity, LockEntity):
    """Representation of a XiaoDu smart door lock."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the lock."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_lock"
        self._attr_name = appliance.get("friendlyName", "小度门锁")
        self._attr_should_poll = False

        self._manufacturer = appliance.get("botName", "小度")
        self._model = appliance.get("model", "")

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": self._model or "小度智能门锁",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def is_locked(self) -> bool | None:
        """Return true if the lock is locked."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        # Try common lock state keys
        for key in ("lockState", "lock_state", "doorLockState"):
            if key in state:
                value = str(state[key].get("value", "")).lower()
                if value in ("locked", "lock", "on"):
                    return True
                if value in ("unlocked", "unlock", "off"):
                    return False
        # Fallback to turnOnState (ON = locked for some locks)
        turn_on = str(state.get("turnOnState", {}).get("value", "")).lower()
        if turn_on == "on":
            return True
        if turn_on == "off":
            return False
        return None

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the door."""
        await self._api.lock()
        await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door."""
        await self._api.unlock()
        await self.coordinator.async_request_refresh()
