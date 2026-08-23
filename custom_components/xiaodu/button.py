"""Button platform for XiaoDu (小度) integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
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
    """Set up XiaoDu buttons from config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    apis: dict[str, XiaoDuAPI] = entry_data["apis"]
    coordinator: XiaoDuDataUpdateCoordinator = entry_data["coordinator"]

    entities = []
    for appliance_id, api in apis.items():
        appliance_types = getattr(api, "appliance_types", [])

        appliance = coordinator.get_appliance_info(appliance_id)
        if not appliance:
            continue

        # Scene trigger buttons
        if ApplianceTypes.is_button(appliance_types):
            entities.append(XiaoDuSceneButton(api, coordinator, appliance))

        # Clothes rack up/down buttons
        if ApplianceTypes.is_clothes_rack(appliance_types):
            buttons = _extract_clothes_rack_buttons(appliance)
            for btn in buttons:
                entities.append(
                    XiaoDuPanelButton(api, coordinator, appliance, btn)
                )

    async_add_entities(entities)


def _extract_clothes_rack_buttons(
    appliance: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract up/down control buttons from a clothes rack."""
    buttons = []
    for panel_group in appliance.get("panels", []):
        if panel_group.get("title") == "上下控制":
            for item in panel_group.get("list", []):
                actions = item.get("actions", [])
                if actions:
                    buttons.append(
                        {
                            "name": item.get("name", ""),
                            "value": item.get("value", ""),
                            "label": item.get("label", ""),
                            "header_name": actions[0].get("headerName", ""),
                        }
                    )
            break
    return buttons


class XiaoDuSceneButton(CoordinatorEntity, ButtonEntity):
    """Representation of a XiaoDu scene trigger button."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
    ) -> None:
        """Initialize the scene button."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._attr_unique_id = f"{api.appliance_id}_button_scene"
        self._attr_name = appliance.get("friendlyName", "小度场景")
        self._attr_should_poll = False
        self._attr_device_class = ButtonDeviceClass.IDENTIFY
        self._attr_icon = "mdi:gesture-tap-button"

        self._manufacturer = appliance.get("botName", "小度")

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._appliance_id)},
            "name": self._attr_name,
            "manufacturer": self._manufacturer,
            "model": "小度场景",
            "via_device": (DOMAIN, "xiaodu_hub"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.get_appliance_data(self._appliance_id) is not None

    async def async_press(self) -> None:
        """Press the button — trigger the scene."""
        # Scene triggers use TurnOnRequest
        await self._api.turn_on()
        await self.coordinator.async_request_refresh()


class XiaoDuPanelButton(CoordinatorEntity, ButtonEntity):
    """Representation of a custom panel button (e.g. clothes rack up/down)."""

    def __init__(
        self,
        api: XiaoDuAPI,
        coordinator: XiaoDuDataUpdateCoordinator,
        appliance: dict[str, Any],
        button: dict[str, Any],
    ) -> None:
        """Initialize the panel button."""
        super().__init__(coordinator)
        self._api = api
        self._appliance_id = api.appliance_id
        self._switch_type = button["name"]
        self._header_name = button["header_name"]

        base_name = appliance.get("friendlyName", "小度设备")
        self._attr_unique_id = (
            f"{api.appliance_id}_button_{self._switch_type}"
        )
        self._attr_name = f"{base_name}_{button.get('label', self._switch_type)}"
        self._attr_should_poll = False
        self._attr_device_class = ButtonDeviceClass.IDENTIFY
        self._attr_icon = "mdi:arrow-up-down"

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

    async def async_press(self) -> None:
        """Press the button."""
        await self._api.panel_button(self._switch_type, self._header_name)
        await self.coordinator.async_request_refresh()
