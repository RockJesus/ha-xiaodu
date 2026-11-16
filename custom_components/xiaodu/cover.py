"""Cover platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
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

# State keys that may carry the open percentage. XiaoDu curtains report it as
# ``degree``; the others are kept as fallbacks for other cover models.
POSITION_KEYS = (
    "degree",
    "position",
    "curtainPosition",
    "percentControl",
    "openPercent",
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up XiaoDu covers from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]
    hub_device_id = entry_data["hub_device_id"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_cover(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        entities.append(XiaoDuCover(api, coordinator, hub_device_id, appliance))

    async_add_entities(entities)


class XiaoDuCover(CoordinatorEntity, CoverEntity):
    """Representation of a XiaoDu curtain/cover."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        hub_device_id: str,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator)
        self._hub_device_id = hub_device_id
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_cover"
        self._attr_name = appliance.get("friendlyName", "小度窗帘")
        self._attr_should_poll = False

        self._manufacturer = appliance.get("botName", "小度")
        self._model = appliance.get("model", "")

        # Position support is detected from the state payload and then latched:
        # a curtain that reports its percentage once keeps the slider even if a
        # later poll misses the field (offline or a flaky cloud response), so
        # the UI never flickers between supported and unsupported.
        self._supports_position = False
        self._read_position()

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": self._model or "小度智能窗帘",
            "via_device_id": self._hub_device_id,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Return the supported cover features."""
        if not self._supports_position:
            # Cheap re-check: a curtain may only start reporting its percentage
            # after the first poll (offline, or a flaky cloud response).
            self._read_position()
        features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )
        if self._supports_position:
            features |= CoverEntityFeature.SET_POSITION
        return features

    def _read_position(self) -> int | None:
        """Return the open percentage (100 = fully open), if reported."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        for key in POSITION_KEYS:
            entry = state.get(key)
            if not isinstance(entry, dict):
                continue
            try:
                position = max(0, min(100, int(float(entry.get("value")))))
            except (TypeError, ValueError):
                continue
            # Latch support on the first successful read; never unset it.
            self._supports_position = True
            return position
        return None

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        position = self._read_position()
        if position is not None:
            return position == 0
        state = self.coordinator.get_state_setting(self._appliance_id)
        # turnOnState ON = open, OFF = closed
        return str(state.get("turnOnState", {}).get("value", "off")).lower() != "on"

    @property
    def current_cover_position(self) -> int | None:
        """Return current open percentage (100 = fully open)."""
        return self._read_position()

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

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a given open percentage (0 = closed, 100 = open)."""
        raw = kwargs.get(ATTR_POSITION)
        if raw is None:
            return
        try:
            position = int(float(raw))
        except (TypeError, ValueError):
            return
        position = max(0, min(100, position))
        if position == 0:
            await self._api.close_cover()
        elif position == 100:
            await self._api.open_cover()
        else:
            await self._api.set_cover_position(position)
        await self.coordinator.async_request_refresh()
