"""Cover platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
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
    """Set up XiaoDu covers from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_cover(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        entities.append(XiaoDuCover(api, coordinator, appliance))

    async_add_entities(entities)


class XiaoDuCover(CoordinatorEntity, CoverEntity):
    """Representation of a XiaoDu curtain/cover."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_cover"
        self._attr_name = appliance.get("friendlyName", "小度窗帘")
        self._attr_should_poll = False

        self._manufacturer = appliance.get("botName", "小度")
        self._model = appliance.get("model", "")

        # XiaoDu curtains only support open/close/stop, no position control
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": self._model or "小度智能窗帘",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        # turnOnState ON = open, OFF = closed
        return str(state.get("turnOnState", {}).get("value", "off")).lower() != "on"

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (not supported by XiaoDu API)."""
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._api.open_cover()
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._api.close_cover()
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._api.stop_cover()
        await self.coordinator.async_request_refresh()
