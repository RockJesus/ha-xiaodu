"""Fan platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    int_states_in_range,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

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
    """Set up XiaoDu fans from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_fan(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        entities.append(XiaoDuFan(api, coordinator, appliance))

    async_add_entities(entities)


class XiaoDuFan(CoordinatorEntity, FanEntity):
    """Representation of a XiaoDu fan."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the fan."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_fan"
        self._attr_name = appliance.get("friendlyName", "小度风扇")
        self._attr_should_poll = False

        self._manufacturer = appliance.get("botName", "小度")
        self._model = appliance.get("model", "")

        # Determine speed range
        state_setting = appliance.get("stateSetting", {})
        self._speed_min = 1
        self._speed_max = 3
        if "fanSpeed" in state_setting:
            speed_range = state_setting["fanSpeed"].get("valueRangeMap", {})
            self._speed_min = speed_range.get("min", 1)
            self._speed_max = speed_range.get("max", 3)

        # Features
        self._attr_supported_features = FanEntityFeature.SET_SPEED
        if "fanOscillation" in state_setting or "oscillation" in state_setting:
            self._attr_supported_features |= FanEntityFeature.OSCILLATE

        # Preset modes (fan modes)
        self._preset_modes: list[str] = []
        self._preset_map: dict[str, str] = {}
        if "mode" in state_setting:
            value_range_map = state_setting["mode"].get("valueRangeMap", {})
            for mode_key, mode_name in value_range_map.items():
                self._preset_modes.append(mode_name)
                self._preset_map[mode_name] = mode_key
        if self._preset_modes:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = self._preset_modes

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": self._model or "小度风扇",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def is_on(self) -> bool:
        """Return true if fan is on."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        return str(state.get("turnOnState", {}).get("value", "off")).lower() == "on"

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        speed = state.get("fanSpeed", {}).get("value")
        if speed is not None:
            return ranged_value_to_percentage(
                (self._speed_min, self._speed_max), int(speed)
            )
        return None

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return int_states_in_range((self._speed_min, self._speed_max))

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if not self._preset_map:
            return None
        state = self.coordinator.get_state_setting(self._appliance_id)
        mode_value = state.get("mode", {}).get("value")
        if mode_value:
            value_range_map = state.get("mode", {}).get("valueRangeMap", {})
            return value_range_map.get(mode_value)
        return None

    @property
    def oscillating(self) -> bool | None:
        """Return whether the fan is oscillating."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        for key in ("fanOscillation", "oscillation"):
            if key in state:
                return str(state[key].get("value", "off")).lower() == "on"
        return None

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if percentage is not None:
            await self.async_set_percentage(percentage)
        elif preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        else:
            await self._api.turn_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self._api.turn_off()
        await self.coordinator.async_request_refresh()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            await self._api.turn_off()
        else:
            speed = int(
                percentage_to_ranged_value(
                    (self._speed_min, self._speed_max), percentage
                )
            )
            # Convert speed to percentage for API (0-100)
            pct = round((speed - self._speed_min) / (self._speed_max - self._speed_min) * 100)
            await self._api.set_fan_speed(max(1, min(100, pct)))
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        mode_key = self._preset_map.get(preset_mode)
        if mode_key:
            await self._api.set_fan_mode(mode_key)
            await self.coordinator.async_request_refresh()

    async def async_oscillate(self, oscillating: bool) -> None:
        """Set oscillation."""
        await self._api.set_fan_oscillation(oscillating)
        await self.coordinator.async_request_refresh()
