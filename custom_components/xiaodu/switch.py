"""Switch platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up XiaoDu switches from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])
        if not ApplianceTypes.is_switch(appliance_types):
            continue

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        # Clothes rack has multiple panel switches
        if ApplianceTypes.is_clothes_rack(appliance_types):
            panels = _extract_clothes_rack_panels(appliance)
            for panel in panels:
                entities.append(
                    XiaoDuPanelSwitch(api, coordinator, appliance, panel)
                )
        else:
            entities.append(XiaoDuSwitch(api, coordinator, appliance))

    async_add_entities(entities)


def _extract_clothes_rack_panels(
    appliance: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract function control panels from a clothes rack appliance."""
    panels = []
    for panel_group in appliance.get("panels", []):
        if panel_group.get("title") == "功能控制":
            for item in panel_group.get("list", []):
                actions = item.get("actions", [])
                if len(actions) >= 2:
                    panels.append(
                        {
                            "name": item.get("name", ""),
                            "value": item.get("value", ""),
                            "label": item.get("label", ""),
                            "header_on": actions[0].get("headerName", ""),
                            "header_off": actions[1].get("headerName", ""),
                            "payload_extra": actions[0].get("payload"),
                        }
                    )
            break
    return panels


class XiaoDuSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a XiaoDu switch/outlet."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_switch"
        self._attr_name = appliance.get("friendlyName", "小度开关")
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
            "model": self._model or "小度智能开关",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        return str(state.get("turnOnState", {}).get("value", "off")).lower() == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        await self._api.turn_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        await self._api.turn_off()
        await self.coordinator.async_request_refresh()


class XiaoDuPanelSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a custom panel switch (e.g. clothes rack functions)."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
        panel: dict[str, Any],
    ) -> None:
        """Initialize the panel switch."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._switch_type = panel["name"]
        self._type_value = panel["value"]
        self._header_on = panel["header_on"]
        self._header_off = panel["header_off"]
        self._payload_extra = panel.get("payload_extra")

        base_name = appliance.get("friendlyName", "小度设备")
        self._attr_unique_id = (
            f"{api.appliance_id}_switch_{self._switch_type}_{self._type_value}"
        )
        self._attr_name = f"{base_name}_{panel.get('label', self._switch_type)}"
        self._attr_should_poll = False
        self._manufacturer = appliance.get("botName", "小度")

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name.rsplit("_", 1)[0],
            "manufacturer": self._manufacturer,
            "model": "晾衣架",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    @property
    def is_on(self) -> bool:
        """Return true if panel switch is on."""
        state = self.coordinator.get_state_setting(self._appliance_id)
        return state.get(self._switch_type, {}).get("value") == self._type_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the panel switch."""
        await self._api.panel_switch_on(
            self._switch_type,
            self._type_value,
            self._header_on,
            self._payload_extra,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the panel switch."""
        await self._api.panel_switch_off(
            self._switch_type,
            self._type_value,
            self._header_off,
            self._payload_extra,
        )
        await self.coordinator.async_request_refresh()
