"""Data update coordinator for XiaoDu integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import XiaoDuAPI
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class XiaoDuDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator to fetch data for all XiaoDu devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        apis: dict[str, XiaoDuAPI],
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.apis = apis
        self._cookie_valid = True

    @property
    def cookie_valid(self) -> bool:
        """Return whether the cookie is still valid."""
        return self._cookie_valid

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from API for all devices.

        Returns {appliance_id: appliance_detail_data}.
        """
        results: dict[str, dict[str, Any]] = {}
        errors: list[str] = []

        for appliance_id, api in self.apis.items():
            try:
                detail = await api.get_appliance_detail(appliance_id)
                if detail and "appliance" in detail:
                    results[appliance_id] = detail
                else:
                    _LOGGER.debug(
                        "No data returned for appliance %s", appliance_id
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{appliance_id}: {exc}")
                _LOGGER.debug(
                    "Error updating appliance %s: %s", appliance_id, exc
                )
                # Keep last known good data if available
                if appliance_id in self.data:
                    results[appliance_id] = self.data[appliance_id]

        # Check if cookie expired (all updates failing with auth error)
        if not results and errors:
            # Try a session check to determine if cookie is expired
            first_api = next(iter(self.apis.values()), None)
            if first_api:
                valid, error = await first_api.check_session()
                if not valid:
                    self._cookie_valid = False
                    raise UpdateFailed(
                        f"XiaoDu cookie invalid: {error}. Please reconfigure."
                    )
            self._cookie_valid = True
            raise UpdateFailed(
                f"Failed to fetch any device data: {'; '.join(errors[:3])}"
            )

        self._cookie_valid = True
        return results

    def get_appliance_data(self, appliance_id: str) -> dict[str, Any] | None:
        """Get cached appliance data by ID."""
        if self.data and appliance_id in self.data:
            return self.data[appliance_id]
        return None

    def get_state_setting(self, appliance_id: str) -> dict[str, Any]:
        """Get stateSetting for an appliance (empty dict if unavailable)."""
        data = self.get_appliance_data(appliance_id)
        if data and "appliance" in data:
            return data["appliance"].get("stateSetting", {})
        return {}

    def get_appliance_info(self, appliance_id: str) -> dict[str, Any]:
        """Get full appliance info dict (empty dict if unavailable)."""
        data = self.get_appliance_data(appliance_id)
        if data and "appliance" in data:
            return data["appliance"]
        return {}
