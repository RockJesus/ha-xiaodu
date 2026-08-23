"""Climate platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import XiaoDuAPI
from .appliance_types import ApplianceTypes
from .const import DOMAIN
from .coordinator import XiaoDuDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Fan speed mapping: XiaoDu numeric → HA fan mode
FAN_SPEED_MAP = {
    1: FAN_LOW,
    2: FAN_MEDIUM,
    3: FAN_HIGH,
    4: FAN_HIGH,
    5: FAN_HIGH,
}

# HA HVAC mode → XiaoDu mode string
HVAC_MODE_TO_XIAODU = {
    HVACMode.COOL: "COOL",
    HVACMode.HEAT: "HEAT",
    HVACMode.FAN_ONLY: "FAN",
    HVACMode.DRY: "DEHUMIDIFICATION",
    HVACMode.AUTO: "AUTO",
}

# XiaoDu mode string → HA HVAC mode
XIAODU_TO_HVAC_MODE = {
    "COOL": HVACMode.COOL,
    "HEAT": HVACMode.HEAT,
    "FAN": HVACMode.FAN_ONLY,
    "DEHUMIDIFICATION": HVACMode.DRY,
    "AUTO": HVACMode.AUTO,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up XiaoDu climate devices from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_climate(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        entities.append(XiaoDuClimate(api, coordinator, appliance))

    async_add_entities(entities)


class XiaoDuClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a XiaoDu air conditioner."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_climate"
        self._attr_name = appliance.get("friendlyName", "小度空调")
        self._attr_should_poll = False

        self._manufacturer = appliance.get("botName", "小度")
        self._model = appliance.get("model", "")

        # Capabilities
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
        )
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_min_temp = 16
        self._attr_max_temp = 32
        self._attr_target_temperature_step = 1
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.FAN_ONLY,
            HVACMode.DRY,
            HVACMode.AUTO,
        ]
        self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]

        # Detect actual fan speed range from appliance data
        state_setting = appliance.get("stateSetting", {})
        if "fanSpeed" in state_setting:
            fan_range = state_setting["fanSpeed"].get("valueRangeMap", {})
            max_speed = fan_range.get("max", 3)
            if max_speed <= 3:
                self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": self._model or "小度空调",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    def _get_state(self) -> dict[str, Any]:
        """Get state setting from coordinator."""
        return self.coordinator.get_state_setting(self._appliance_id)

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        state = self._get_state()
        is_on = str(state.get("turnOnState", {}).get("value", "off")).lower() == "on"
        if not is_on:
            return HVACMode.OFF
        mode = str(state.get("mode", {}).get("value", "COOL")).upper()
        return XIAODU_TO_HVAC_MODE.get(mode, HVACMode.COOL)

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        state = self._get_state()
        temp = state.get("temperature", {}).get("value")
        if temp is not None:
            return float(temp)
        return None

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature (if available)."""
        state = self._get_state()
        # Some ACs report current/indoor temperature
        for key in ("indoorTemperature", "currentTemperature", "roomTemperature"):
            if key in state:
                val = state[key].get("value")
                if val is not None:
                    return float(val)
        return None

    @property
    def fan_mode(self) -> str | None:
        """Return the fan mode."""
        state = self._get_state()
        speed = state.get("fanSpeed", {}).get("value")
        if speed is not None:
            return FAN_SPEED_MAP.get(int(speed), FAN_MEDIUM)
        return FAN_MEDIUM

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        # Try direct set first
        success, error = await self._api.set_ac_temperature(int(temperature))
        if not success and error:
            _LOGGER.debug(
                "Direct AC temperature set failed (%s), falling back to increment/decrement",
                error,
            )
            # Fallback: use increment/decrement
            current = self.target_temperature
            if current is not None:
                diff = int(temperature - current)
                if diff > 0:
                    for _ in range(diff):
                        await self._api.increment_ac_temperature()
                elif diff < 0:
                    for _ in range(abs(diff)):
                        await self._api.decrement_ac_temperature()

        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            await self._api.set_ac_off()
        else:
            # Turn on first if off, then set mode
            xiaodu_mode = HVAC_MODE_TO_XIAODU.get(hvac_mode, "COOL")
            is_on = self.hvac_mode != HVACMode.OFF
            if not is_on:
                await self._api.set_ac_on()
            await self._api.set_ac_mode(xiaodu_mode)

        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        current = self.fan_mode
        if current == fan_mode:
            return

        # Map fan modes to numeric steps
        mode_order = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        try:
            current_idx = mode_order.index(current)
        except ValueError:
            current_idx = 1
        try:
            target_idx = mode_order.index(fan_mode)
        except ValueError:
            target_idx = 1

        diff = target_idx - current_idx
        if diff > 0:
            for _ in range(diff):
                await self._api.increment_ac_fan()
        elif diff < 0:
            for _ in range(abs(diff)):
                await self._api.decrement_ac_fan()

        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn on the AC."""
        await self._api.set_ac_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn off the AC."""
        await self._api.set_ac_off()
        await self.coordinator.async_request_refresh()
