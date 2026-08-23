"""Light platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
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
    """Set up XiaoDu lights from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_light(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        entities.append(XiaoDuLight(api, coordinator, appliance))

    async_add_entities(entities)


class XiaoDuLight(CoordinatorEntity, LightEntity):
    """Representation of a XiaoDu light."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_light"
        self._attr_name = appliance.get("friendlyName", "小度灯")
        self._attr_should_poll = False

        self._manufacturer = appliance.get("botName", "小度")
        self._model = appliance.get("model", "")
        self._group_name = appliance.get("groupName", "")

        # Determine capabilities from stateSetting
        state_setting = appliance.get("stateSetting", {})
        self._has_brightness = "brightness" in state_setting
        self._has_color_temp = "colorTemperatureInKelvin" in state_setting
        self._has_mode = "mode" in state_setting

        # Set color modes
        if self._has_color_temp:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif self._has_brightness:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

        # Effects (light modes)
        if self._has_mode:
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._effect_map: dict[str, str] = {}
            value_range_map = state_setting.get("mode", {}).get("valueRangeMap", {})
            for mode_key, mode_name in value_range_map.items():
                self._effect_map[mode_name] = mode_key
            self._attr_effect_list = list(self._effect_map.keys())
        else:
            self._effect_map = {}

        # Color temp range
        self._min_ct_kelvin = 2700
        self._max_ct_kelvin = 6500
        if self._has_color_temp:
            ct_range = state_setting.get("colorTemperatureInKelvin", {}).get(
                "valueKelvinRangeMap", {}
            )
            self._min_ct_kelvin = ct_range.get("min", 2700)
            self._max_ct_kelvin = ct_range.get("max", 6500)

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": self._model or "小度智能灯",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        return str(state.get("turnOnState", {}).get("value", "off")).lower() == "on"

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light (0-255)."""
        if not self._has_brightness:
            return None
        state = self.coordinator.get_state_setting(self._appliance_id)
        pct = state.get("brightness", {}).get("value")
        if pct is not None:
            return round(int(pct) / 100 * 255)
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        if not self._has_color_temp:
            return None
        state = self.coordinator.get_state_setting(self._appliance_id)
        pct = state.get("colorTemperatureInKelvin", {}).get("value")
        if pct is not None:
            range_diff = self._max_ct_kelvin - self._min_ct_kelvin
            return round(int(pct) / 100 * range_diff) + self._min_ct_kelvin
        return None

    @property
    def min_color_temp_kelvin(self) -> int:
        """Return the minimum color temperature in Kelvin."""
        return self._min_ct_kelvin

    @property
    def max_color_temp_kelvin(self) -> int:
        """Return the maximum color temperature in Kelvin."""
        return self._max_ct_kelvin

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        if not self._has_mode:
            return None
        state = self.coordinator.get_state_setting(self._appliance_id)
        mode_value = state.get("mode", {}).get("value")
        if mode_value:
            value_range_map = state.get("mode", {}).get("valueRangeMap", {})
            return value_range_map.get(mode_value)
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            pct = round(brightness / 255 * 100)
            await self._api.set_brightness(pct)
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            ct_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            range_diff = self._max_ct_kelvin - self._min_ct_kelvin
            pct = round((ct_kelvin - self._min_ct_kelvin) / range_diff * 100)
            await self._api.set_color_temperature(max(0, min(100, pct)))
        elif ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            mode_key = self._effect_map.get(effect_name)
            if mode_key:
                await self._api.set_light_mode(mode_key)
        else:
            await self._api.turn_on()

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self._api.turn_off()
        await self.coordinator.async_request_refresh()
