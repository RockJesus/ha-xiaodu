"""Data update coordinator for XiaoDu integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LoginExpired, XiaoDuAPI
from .const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .login import BaiduLogin, BaiduLoginBlocked, BaiduLoginError

_LOGGER = logging.getLogger(__name__)


class XiaoDuDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator to fetch data for all XiaoDu devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        apis: dict[str, XiaoDuAPI],
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.apis = apis
        self.entry = entry
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
        failed: list[str] = []

        login_expired = False
        for appliance_id, api in self.apis.items():
            try:
                detail = await api.get_appliance_detail(appliance_id)
                if detail and "appliance" in detail:
                    results[appliance_id] = detail
                else:
                    failed.append(appliance_id)
                    _LOGGER.debug(
                        "No data returned for appliance %s", appliance_id
                    )
            except LoginExpired:
                login_expired = True
                errors.append(f"{appliance_id}: not login")
                _LOGGER.warning(
                    "XiaoDu session expired for %s — attempting auto relogin",
                    appliance_id,
                )
                # Guard against self.data being None during the first refresh
                # (hacs review 2026-10-18) — a TypeError inside the except
                # handler would mask the real error.
                if self.data and appliance_id in self.data:
                    results[appliance_id] = self.data[appliance_id]
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{appliance_id}: {exc}")
                _LOGGER.debug(
                    "Error updating appliance %s: %s", appliance_id, exc
                )
                # Keep last known good data if available
                if self.data and appliance_id in self.data:
                    results[appliance_id] = self.data[appliance_id]
                else:
                    failed.append(appliance_id)

        # Fallback: devices whose detail endpoint returned no data still get
        # their info from the device list (single extra request, matched by
        # id) so an entity can always be created and stay available.
        if failed:
            try:
                first_api = next(iter(self.apis.values()))
                devices = await first_api.get_all_appliances(
                    first_api.house_id
                )
                by_id = {
                    d.get("applianceId"): d
                    for d in devices
                    if d.get("applianceId")
                }
                for aid in failed:
                    info = by_id.get(aid)
                    if info:
                        results[aid] = {"appliance": info}
                        _LOGGER.warning(
                            "Appliance %s detail empty — using device-list "
                            "fallback (types: %s)",
                            aid,
                            info.get("applianceTypes", []),
                        )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("Device-list fallback failed: %s", exc)

        # Session expired: try to refresh the token automatically with the
        # stored username/password before giving up.
        if login_expired:
            if await self._try_relogin():
                login_expired = False
                _LOGGER.info("XiaoDu token refreshed automatically")
            else:
                raise ConfigEntryAuthFailed(
                    "XiaoDu cookie expired and auto relogin failed — "
                    "re-authentication required"
                )

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

    async def _try_relogin(self) -> bool:
        """Relogin with stored credentials when the cookie has expired.

        Returns True when every API client now has a fresh BDUSS.
        """
        entry = self.entry
        if entry is None:
            return False
        username = entry.data.get(CONF_USERNAME, "")
        password = entry.data.get(CONF_PASSWORD, "")
        if not username or not password:
            return False
        first_api = next(iter(self.apis.values()), None)
        if first_api is None:
            return False
        try:
            client = BaiduLogin(first_api.session)
            result = await client.login(username, password)
        except (BaiduLoginBlocked, BaiduLoginError) as exc:
            _LOGGER.warning("XiaoDu auto relogin failed: %s", exc)
            return False
        new_cookie = result.get("bduss", "")
        if not new_cookie:
            return False
        for api in self.apis.values():
            api.update_cookie(new_cookie)
        return True

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
