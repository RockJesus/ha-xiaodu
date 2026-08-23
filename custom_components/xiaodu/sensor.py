"""Sensor platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import XiaoDuAPI
from .appliance_types import ApplianceTypes, SENSOR_ATTRIBUTES
from .const import DOMAIN
from .coordinator import XiaoDuDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up XiaoDu sensors from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        state_setting = appliance.get("stateSetting", {})
        base_name = appliance.get("friendlyName", "小度设备")
        manufacturer = appliance.get("botName", "小度")

        # Create sensor entities for each available sensor attribute
        for key, (name_suffix, unit, device_class) in SENSOR_ATTRIBUTES.items():
            if key in state_setting:
                entities.append(
                    XiaoDuSensor(
                        api,
                        coordinator,
                        appliance_id,
                        base_name,
                        manufacturer,
                        key,
                        name_suffix,
                        unit,
                        device_class,
                    )
                )

    async_add_entities(entities)


class XiaoDuSensor(CoordinatorEntity, SensorEntity):
    """Representation of a XiaoDu sensor."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance_id: str,
        base_name: str,
        manufacturer: str,
        sensor_key: str,
        name_suffix: str,
        unit: str | None,
        device_class: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = appliance_id
        self._sensor_key = sensor_key
        self._attr_unique_id = f"{appliance_id}_sensor_{sensor_key}"
        self._attr_name = f"{base_name} {name_suffix}"
        self._attr_should_poll = False
        self._manufacturer = manufacturer
        self._base_name = base_name

        if unit:
            self._attr_native_unit_of_measurement = unit
        if device_class:
            try:
                self._attr_device_class = SensorDeviceClass(device_class)
            except ValueError:
                pass
        # Numeric sensors get measurement state class
        if unit:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._base_name,
            "manufacturer": self._manufacturer,
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        value = state.get(self._sensor_key, {}).get("value")
        if value is not None:
            # Try to convert to number for numeric sensors
            try:
                return float(value)
            except (ValueError, TypeError):
                return value
        return None
