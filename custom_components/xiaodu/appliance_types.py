"""XiaoDu appliance type mappings to Home Assistant platforms."""

from __future__ import annotations

from typing import Any


# ── Appliance type → HA platform mappings ───────────────────────────

# Light devices
LIGHT_TYPES = {"LIGHT"}

# Switch / outlet / generic on-off devices
SWITCH_TYPES = {
    "SOCKET",
    "SWITCH",
    "OUTLET",
    "WASHING_MACHINE",
    "HEATER",
    "AIR_FRESHER",
    "WINDOW_OPENER",
    "CLOTHES_RACK",
    "WATER_HEATER",
    "HUMIDIFIER",
    "DEHUMIDIFIER",
    "AIR_PURIFIER",
    "KETTLE",
    "RICE_COOKER",
    "MICROWAVE",
    "OVEN",
    "FRIDGE",
    "DISHWASHER",
}

# Cover / curtain devices
COVER_TYPES = {"CURTAIN", "CURTAIN_SWITCH"}

# Climate / AC devices
CLIMATE_TYPES = {"AIR_CONDITION", "AIRCONDITION", "AC"}

# Fan devices
FAN_TYPES = {"FAN", "CEILING_FAN", "AIR_CONDITIONER_FAN"}

# Lock devices
LOCK_TYPES = {"DOOR_LOCK", "SMART_LOCK"}

# Button / scene trigger devices
BUTTON_TYPES = {"SCENE_TRIGGER", "SCENE"}

# Sensor-capable devices (these may also be switches/lights but have sensor data)
SENSOR_CAPABLE_TYPES = {
    "AIR_PURIFIER",
    "HUMIDIFIER",
    "DEHUMIDIFIER",
    "HEATER",
    "AIR_CONDITION",
    "FAN",
    "WATER_HEATER",
}

# ── Sensor attribute mappings ────────────────────────────────────────
# Maps XiaoDu stateSetting key → (HA sensor name suffix, unit, device_class)

SENSOR_ATTRIBUTES: dict[str, tuple[str, str | None, str | None]] = {
    "temperature": ("温度", "°C", "temperature"),
    "humidity": ("湿度", "%", "humidity"),
    "pm25": ("PM2.5", "μg/m³", "pm25"),
    "pm2_5": ("PM2.5", "μg/m³", "pm25"),
    "co2": ("CO₂", "ppm", "carbon_dioxide"),
    "co": ("CO", "ppm", "carbon_monoxide"),
    "tvoc": ("TVOC", "mg/m³", "volatile_organic_compounds"),
    "formaldehyde": ("甲醛", "mg/m³", "formaldehyde"),
    "airQuality": ("空气质量", None, "aqi"),
    "air_quality": ("空气质量", None, "aqi"),
    "aqi": ("AQI", None, "aqi"),
    "waterTemperature": ("水温", "°C", "temperature"),
    "water_level": ("水位", "%", None),
    "battery": ("电量", "%", "battery"),
    "illumination": ("照度", "lx", "illuminance"),
    "lightLevel": ("照度", "lx", "illuminance"),
}


class ApplianceTypes:
    """Helper class to classify XiaoDu appliances."""

    @staticmethod
    def is_light(appliance_types: list[str]) -> bool:
        """Check if appliance types include a light device."""
        return any(t in LIGHT_TYPES for t in appliance_types)

    @staticmethod
    def is_switch(appliance_types: list[str]) -> bool:
        """Check if appliance types include a switch/outlet device."""
        return any(t in SWITCH_TYPES for t in appliance_types)

    @staticmethod
    def is_cover(appliance_types: list[str]) -> bool:
        """Check if appliance types include a curtain/cover device."""
        return any(t in COVER_TYPES for t in appliance_types)

    @staticmethod
    def is_climate(appliance_types: list[str]) -> bool:
        """Check if appliance types include an AC/climate device."""
        return any(t in CLIMATE_TYPES for t in appliance_types)

    @staticmethod
    def is_fan(appliance_types: list[str]) -> bool:
        """Check if appliance types include a fan device."""
        return any(t in FAN_TYPES for t in appliance_types)

    @staticmethod
    def is_lock(appliance_types: list[str]) -> bool:
        """Check if appliance types include a door lock."""
        return any(t in LOCK_TYPES for t in appliance_types)

    @staticmethod
    def is_button(appliance_types: list[str]) -> bool:
        """Check if appliance types include a scene/button trigger."""
        return any(t in BUTTON_TYPES for t in appliance_types)

    @staticmethod
    def is_clothes_rack(appliance_types: list[str]) -> bool:
        """Check if this is a clothes rack (multi-panel device)."""
        return "CLOTHES_RACK" in appliance_types

    @staticmethod
    def extract_sensors(
        state_setting: dict[str, Any],
    ) -> list[tuple[str, str, str | None, str | None, Any]]:
        """Extract sensor data from appliance stateSetting.

        Returns list of (key, name, unit, device_class, value).
        """
        sensors = []
        for key, (name, unit, device_class) in SENSOR_ATTRIBUTES.items():
            if key in state_setting:
                value = state_setting[key].get("value")
                if value is not None:
                    sensors.append((key, name, unit, device_class, value))
        return sensors

    @staticmethod
    def get_primary_type(appliance_types: list[str]) -> str:
        """Get the primary/most specific type for an appliance."""
        for type_set in [
            LIGHT_TYPES,
            CLIMATE_TYPES,
            COVER_TYPES,
            FAN_TYPES,
            LOCK_TYPES,
            BUTTON_TYPES,
            SWITCH_TYPES,
        ]:
            for t in appliance_types:
                if t in type_set:
                    return t
        return appliance_types[0] if appliance_types else "UNKNOWN"
