"""XiaoDu (小度) Smart Home API client."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    API_APPLIANCE,
    API_APPLIANCE_DETAILS,
    API_DEVICE_LIST,
    API_DIRECTIVE_SEND,
    API_GATEWAY,
    API_MULTIHOUSE,
    DUEROS_NAMESPACE,
    XIAODU_HOST,
)

_LOGGER = logging.getLogger(__name__)


class XiaoDuAPI:
    """API client for XiaoDu smart home platform."""

    def __init__(
        self,
        cookie: str,
        session: aiohttp.ClientSession,
        house_id: str | None = None,
        appliance_id: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self.cookie = cookie
        self.session = session
        self.house_id = house_id
        self.appliance_id = appliance_id
        self.appliance_types: list[str] = []
        self._headers = self._build_headers()

    def _build_headers(self) -> dict[str, str]:
        """Build common HTTP headers."""
        return {
            "Cookie": f"BDUSS={self.cookie};BDUSS_BFESS={self.cookie}",
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Content-Type": "application/json",
            "device-id": "deviceid",
            "host": "xiaodu.baidu.com",
        }

    def update_cookie(self, cookie: str) -> None:
        """Update the authentication cookie."""
        self.cookie = cookie
        self._headers = self._build_headers()

    # ── Authentication ──────────────────────────────────────────────

    async def check_session(self) -> tuple[bool, str | None]:
        """Check if the cookie/session is still valid.

        Returns (is_valid, error_message).
        """
        payload = {"url": "dueros://smarthome.bot.dueros.ai/gateway/myspeaker"}
        try:
            async with self.session.post(
                f"{XIAODU_HOST}{API_GATEWAY}",
                json=payload,
                headers=self._headers,
            ) as resp:
                data = await resp.json()
            if data.get("status") != 0:
                return False, "invalid_auth"
            return True, None
        except aiohttp.ClientError as exc:
            _LOGGER.error("Failed to check XiaoDu session: %s", exc)
            return False, "cannot_connect"
        except (KeyError, ValueError) as exc:
            _LOGGER.error("Unexpected response checking session: %s", exc)
            return False, "unknown"

    # ── House / Home management ─────────────────────────────────────

    async def get_house_list(self) -> dict[str, str]:
        """Get list of houses (homes) for the current account.

        Returns {house_id: house_name}.
        """
        payload = {"method": "HOUSE_LIST"}
        try:
            async with self.session.post(
                f"{XIAODU_HOST}{API_MULTIHOUSE}",
                json=payload,
                headers=self._headers,
            ) as resp:
                data = await resp.json()
            houses = data.get("data", {}).get("houseList", [])
            return {h["houseId"]: h["houseName"] for h in houses}
        except (aiohttp.ClientError, KeyError, ValueError) as exc:
            _LOGGER.error("Failed to get house list: %s", exc)
            return {}

    # ── Device listing ───────────────────────────────────────────────

    async def get_all_appliances(self, house_id: str) -> list[dict[str, Any]]:
        """Get all appliances for a given house."""
        payload = {
            "method": "GET_USER_ALL_APPLIANCES",
            "params": {"from": "h5_control", "withscene": 1, "generalscene": 3},
        }
        try:
            async with self.session.post(
                f"{XIAODU_HOST}{API_APPLIANCE}",
                json=payload,
                headers=self._headers,
                cookies={"HOUSE_ID": house_id},
            ) as resp:
                data = await resp.json()
            return data.get("data", {}).get("appliances", [])
        except (aiohttp.ClientError, KeyError, ValueError) as exc:
            _LOGGER.error("Failed to get appliance list: %s", exc)
            return []

    async def get_device_dict(self, house_id: str) -> dict[str, str]:
        """Get {appliance_id: friendly_name} mapping for a house."""
        appliances = await self.get_all_appliances(house_id)
        return {a["applianceId"]: a["friendlyName"] for a in appliances}

    async def get_appliances_by_ids(
        self, house_id: str, appliance_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Get detailed appliance info for a list of IDs."""
        payload = {
            "enableCancelToken": True,
            "method": "GET_APPLIANCES_BY_ID",
            "params": {
                "from": "h5_control",
                "applianceIdList": appliance_ids,
                "clientCuidList": [],
                "enablecache": True,
            },
        }
        try:
            async with self.session.get(
                f"{XIAODU_HOST}{API_APPLIANCE}",
                json=payload,
                headers=self._headers,
                cookies={"HOUSE_ID": house_id},
            ) as resp:
                data = await resp.json()
            if data.get("status") == 0:
                return data.get("data", {}).get("appliances", [])
            return []
        except (aiohttp.ClientError, KeyError, ValueError) as exc:
            _LOGGER.error("Failed to get appliances by IDs: %s", exc)
            return []

    # ── Single appliance detail ──────────────────────────────────────

    async def get_appliance_detail(
        self, appliance_id: str | None = None
    ) -> dict[str, Any]:
        """Get detailed state for a single appliance."""
        aid = appliance_id or self.appliance_id
        if not aid:
            return {}
        payload = {"applianceId": aid, "version": 2, "from": "h5"}
        try:
            async with self.session.get(
                f"{XIAODU_HOST}{API_APPLIANCE_DETAILS}",
                json=payload,
                headers=self._headers,
                cookies={"HOUSE_ID": self.house_id or ""},
            ) as resp:
                data = await resp.json()
            if data.get("status") == 0:
                return data.get("data", {})
            return {}
        except (aiohttp.ClientError, KeyError, ValueError) as exc:
            _LOGGER.error("Failed to get appliance detail for %s: %s", aid, exc)
            return {}

    # ── Generic command sender ───────────────────────────────────────

    async def send_command(self, payload: dict[str, Any]) -> tuple[bool, str | None]:
        """Send a control directive to XiaoDu.

        Returns (success, error_message).
        """
        try:
            async with self.session.get(
                f"{XIAODU_HOST}{API_DIRECTIVE_SEND}?from=h5_control",
                json=payload,
                headers=self._headers,
                cookies={"HOUSE_ID": self.house_id or ""},
            ) as resp:
                data = await resp.json()
            if data.get("status") == 0:
                return True, None
            if data.get("msg") == "not login":
                return False, "cookie_expired"
            return False, data.get("msg", "unknown_error")
        except aiohttp.ClientError as exc:
            _LOGGER.error("Failed to send command: %s", exc)
            return False, "cannot_connect"
        except (KeyError, ValueError) as exc:
            _LOGGER.error("Unexpected response sending command: %s", exc)
            return False, "unknown"

    def _build_payload(
        self,
        name: str,
        parameters: dict[str, Any] | None = None,
        extra_state: dict[str, Any] | None = None,
        payload_version: int = 3,
    ) -> dict[str, Any]:
        """Build a standard DuerOS control payload."""
        payload: dict[str, Any] = {
            "applianceId": self.appliance_id,
            "parameters": {
                "proxyConnectStatus": False,
                **(parameters or {}),
            },
            "appliance": {"applianceId": [self.appliance_id]},
        }
        if extra_state:
            payload.update(extra_state)
        return {
            "header": {
                "namespace": DUEROS_NAMESPACE,
                "name": name,
                "payloadVersion": payload_version,
            },
            "payload": payload,
        }

    # ── Switch / On-Off control ──────────────────────────────────────

    async def turn_on(self) -> tuple[bool, str | None]:
        """Turn on the appliance."""
        payload = self._build_payload(
            "TurnOnRequest",
            extra_state={"turnOnState": {"value": "ON"}},
        )
        payload["payload"]["parameters"].update(
            {"attribute": "turnOnState", "attributeValue": "ON"}
        )
        return await self.send_command(payload)

    async def turn_off(self) -> tuple[bool, str | None]:
        """Turn off the appliance."""
        payload = self._build_payload(
            "TurnOffRequest",
            extra_state={"turnOnState": {"value": "OFF"}},
        )
        payload["payload"]["parameters"].update(
            {"attribute": "turnOnState", "attributeValue": "OFF"}
        )
        return await self.send_command(payload)

    async def get_is_on(self) -> bool | None:
        """Get current on/off state. Returns None if unavailable."""
        detail = await self.get_appliance_detail()
        if not detail or "appliance" not in detail:
            return None
        try:
            state = detail["appliance"]["stateSetting"]["turnOnState"]["value"]
            return str(state).lower() == "on"
        except (KeyError, TypeError):
            return None

    # ── Light control ────────────────────────────────────────────────

    async def set_brightness(self, percentage: int) -> tuple[bool, str | None]:
        """Set brightness (0-100 percentage)."""
        payload = self._build_payload(
            "SetBrightnessPercentageRequest",
            parameters={"attribute": "brightness", "attributeValue": percentage},
            extra_state={"brightness": {"value": percentage}},
        )
        return await self.send_command(payload)

    async def set_color_temperature(
        self, percentage: int
    ) -> tuple[bool, str | None]:
        """Set color temperature (0-100 percentage of range)."""
        payload = self._build_payload(
            "SetColorTemperatureRequest",
            parameters={
                "attribute": "colorTemperatureInKelvin",
                "attributeValue": percentage,
            },
            extra_state={"colorTemperatureInKelvin": percentage},
        )
        return await self.send_command(payload)

    async def set_light_mode(self, mode: str) -> tuple[bool, str | None]:
        """Set light mode (e.g. READING, NIGHT_UP)."""
        payload = self._build_payload(
            "SetModeRequest",
            parameters={"attribute": "mode", "attributeValue": mode},
            extra_state={"mode": {"value": mode}},
        )
        return await self.send_command(payload)

    # ── Cover / Curtain control ──────────────────────────────────────

    async def open_cover(self) -> tuple[bool, str | None]:
        """Open curtain/cover."""
        return await self.send_command(self._build_payload("TurnOnRequest"))

    async def close_cover(self) -> tuple[bool, str | None]:
        """Close curtain/cover."""
        return await self.send_command(self._build_payload("TurnOffRequest"))

    async def stop_cover(self) -> tuple[bool, str | None]:
        """Stop curtain/cover."""
        return await self.send_command(self._build_payload("PauseRequest"))

    # ── Climate / AC control ─────────────────────────────────────────

    async def set_ac_on(self) -> tuple[bool, str | None]:
        """Turn on AC (payloadVersion 1)."""
        payload = self._build_payload("TurnOnRequest", payload_version=1)
        return await self.send_command(payload)

    async def set_ac_off(self) -> tuple[bool, str | None]:
        """Turn off AC (payloadVersion 1)."""
        payload = self._build_payload("TurnOffRequest", payload_version=1)
        return await self.send_command(payload)

    async def set_ac_mode(self, mode: str) -> tuple[bool, str | None]:
        """Set AC mode: COOL, HEAT, FAN, AUTO, DEHUMIDIFICATION."""
        payload = self._build_payload(
            "SetModeRequest",
            extra_state={"mode": {"value": mode.upper()}},
            payload_version=1,
        )
        return await self.send_command(payload)

    async def set_ac_temperature(self, temperature: int) -> tuple[bool, str | None]:
        """Set AC target temperature directly."""
        payload = self._build_payload(
            "SetTargetTemperatureRequest",
            extra_state={"targetTemperature": {"value": temperature}},
            payload_version=1,
        )
        return await self.send_command(payload)

    async def increment_ac_temperature(self) -> tuple[bool, str | None]:
        """Increment AC temperature by 1 degree."""
        payload = self._build_payload(
            "IncrementTemperatureRequest", payload_version=1
        )
        return await self.send_command(payload)

    async def decrement_ac_temperature(self) -> tuple[bool, str | None]:
        """Decrement AC temperature by 1 degree."""
        payload = self._build_payload(
            "DecrementTemperatureRequest", payload_version=1
        )
        return await self.send_command(payload)

    async def increment_ac_fan(self) -> tuple[bool, str | None]:
        """Increment AC fan speed."""
        payload = self._build_payload(
            "IncrementFanSpeedRequest", payload_version=1
        )
        return await self.send_command(payload)

    async def decrement_ac_fan(self) -> tuple[bool, str | None]:
        """Decrement AC fan speed."""
        payload = self._build_payload(
            "DecrementFanSpeedRequest", payload_version=1
        )
        return await self.send_command(payload)

    # ── Fan control ───────────────────────────────────────────────────

    async def set_fan_speed(self, percentage: int) -> tuple[bool, str | None]:
        """Set fan speed percentage (0-100)."""
        payload = self._build_payload(
            "SetFanSpeedPercentageRequest",
            parameters={"attribute": "fanSpeed", "attributeValue": percentage},
            extra_state={"fanSpeed": {"value": percentage}},
        )
        return await self.send_command(payload)

    async def set_fan_mode(self, mode: str) -> tuple[bool, str | None]:
        """Set fan mode."""
        payload = self._build_payload(
            "SetModeRequest",
            parameters={"attribute": "mode", "attributeValue": mode},
            extra_state={"mode": {"value": mode}},
        )
        return await self.send_command(payload)

    async def set_fan_oscillation(self, on: bool) -> tuple[bool, str | None]:
        """Set fan oscillation on/off."""
        value = "ON" if on else "OFF"
        payload = self._build_payload(
            "SetFanOscillationRequest",
            parameters={"attribute": "fanOscillation", "attributeValue": value},
            extra_state={"fanOscillation": {"value": value}},
        )
        return await self.send_command(payload)

    # ── Lock control ──────────────────────────────────────────────────

    async def lock(self) -> tuple[bool, str | None]:
        """Lock the door lock."""
        payload = self._build_payload("LockRequest")
        return await self.send_command(payload)

    async def unlock(self) -> tuple[bool, str | None]:
        """Unlock the door lock."""
        payload = self._build_payload("UnlockRequest")
        return await self.send_command(payload)

    # ── Custom panel control (for multi-function devices) ────────────

    async def panel_switch_on(
        self,
        switch_type: str,
        type_value: str,
        header_name_on: str,
        payload_extra: dict[str, Any] | None = None,
    ) -> bool:
        """Turn on a custom panel switch (e.g. clothes rack functions)."""
        payload_data: dict[str, Any] = {
            "applianceId": self.appliance_id,
            "parameters": {
                "attribute": switch_type,
                "attributeValue": type_value,
                "proxyConnectStatus": False,
            },
            "appliance": {"applianceId": [self.appliance_id]},
            switch_type: {"value": type_value},
        }
        if payload_extra:
            payload_data.update(payload_extra)
        submit = {
            "header": {
                "namespace": DUEROS_NAMESPACE,
                "name": header_name_on,
                "payloadVersion": 3,
            },
            "payload": payload_data,
        }
        success, _ = await self.send_command(submit)
        return success

    async def panel_switch_off(
        self,
        switch_type: str,
        type_value: str,
        header_name_off: str,
        payload_extra: dict[str, Any] | None = None,
    ) -> bool:
        """Turn off a custom panel switch."""
        payload_data: dict[str, Any] = {
            "applianceId": self.appliance_id,
            "parameters": {
                "attribute": switch_type,
                "attributeValue": type_value,
                "proxyConnectStatus": False,
            },
            "appliance": {"applianceId": [self.appliance_id]},
            switch_type: {"value": type_value},
        }
        if payload_extra:
            payload_data.update(payload_extra)
        submit = {
            "header": {
                "namespace": DUEROS_NAMESPACE,
                "name": header_name_off,
                "payloadVersion": 3,
            },
            "payload": payload_data,
        }
        success, _ = await self.send_command(submit)
        return success

    async def panel_button(
        self, switch_type: str, header_name: str
    ) -> bool:
        """Press a custom panel button (e.g. clothes rack up/down)."""
        payload_data = {
            "applianceId": self.appliance_id,
            "parameters": {
                "attribute": switch_type,
                "proxyConnectStatus": False,
            },
            "appliance": {"applianceId": [self.appliance_id]},
            switch_type: {},
        }
        submit = {
            "header": {
                "namespace": DUEROS_NAMESPACE,
                "name": header_name,
                "payloadVersion": 3,
            },
            "payload": payload_data,
        }
        success, _ = await self.send_command(submit)
        return success

    async def get_panel_state(
        self, switch_type: str, type_value: str
    ) -> bool | None:
        """Get state of a custom panel switch. Returns None if unavailable."""
        detail = await self.get_appliance_detail()
        if not detail or "appliance" not in detail:
            return None
        try:
            state_setting = detail["appliance"]["stateSetting"]
            if switch_type not in state_setting:
                return None
            return state_setting[switch_type]["value"] == type_value
        except (KeyError, TypeError):
            return None
