"""MyTower DataUpdateCoordinator — login, discovery, polling."""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    APP_BASE_URL,
    API_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    COOKIE_AUTH,
    COOKIE_DEVICE,
    COOKIE_DEVICE_VALUE,
    COOKIE_PROJECT,
    COOKIE_PROJECT_VALUE,
    MOBILE_UA,
    APP_HEADERS,
)

_LOGGER = logging.getLogger(__name__)


class MyTowerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages all communication with the MyTower API."""

    def __init__(self, hass: HomeAssistant, auth_token: str, user_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        # auth_token = URL-decoded value of CRM_user_users cookie
        self.auth_token = auth_token
        self.user_id = user_id

        # Discovered at setup — list of {"uuid": ..., "name": ...}
        self.gates: list[dict[str, str]] = []

    # ──────────────────────────────────────────────
    # Auth helpers
    # ──────────────────────────────────────────────

    def _app_cookies(self) -> dict[str, str]:
        """Cookies needed for app.my-tower.co.il (PHP backend)."""
        return {
            COOKIE_AUTH: self.auth_token,
            COOKIE_DEVICE: COOKIE_DEVICE_VALUE,
            COOKIE_PROJECT: COOKIE_PROJECT_VALUE,
        }

    def _api_headers(self) -> dict[str, str]:
        """Headers needed for api.my-tower.co.il (REST API)."""
        return {
            "Auth-Token": self.auth_token,
            "Locale": "he",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": MOBILE_UA,
        }

    def _app_session(self) -> aiohttp.ClientSession:
        """aiohttp session pre-loaded with app cookies + mobile UA."""
        return aiohttp.ClientSession(
            cookies=self._app_cookies(),
            headers=APP_HEADERS,
        )

    def _api_session(self) -> aiohttp.ClientSession:
        """aiohttp session pre-loaded with REST API headers."""
        return aiohttp.ClientSession(headers=self._api_headers())

    # ──────────────────────────────────────────────
    # Setup — dynamic discovery
    # ──────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Discover gates and other dynamic resources after first login."""
        await self._discover_gates()

    async def _discover_gates(self) -> None:
        """
        Load /gates page and extract gate UUIDs + Hebrew names.

        Gate links look like:
          <a class="gate-item" href="gates/open/{uuid}">
            <label class="name">שער כניסה</label>
          </a>
        """
        try:
            async with self._app_session() as session:
                async with session.get(f"{APP_BASE_URL}/gates") as resp:
                    html = await resp.text()

            gates = []
            # Match href="gates/open/{uuid}" — relative or absolute
            for m in re.finditer(
                r'href=["\'](?:[^"\']*gates/open/)([0-9a-f-]{36})["\']',
                html,
                re.IGNORECASE,
            ):
                uuid = m.group(1)
                # Find the label closest to this href in the surrounding HTML
                context = html[max(0, m.start() - 50) : m.end() + 300]
                name_m = re.search(r'<label[^>]*>([^<]+)</label>', context)
                name = name_m.group(1).strip() if name_m else f"שער {len(gates) + 1}"
                gates.append({"uuid": uuid, "name": name})

            self.gates = gates
            _LOGGER.info(
                "MyTower: discovered %d gate(s): %s",
                len(gates),
                [g["name"] for g in gates],
            )
        except Exception as err:
            _LOGGER.error("MyTower: gate discovery failed: %s", err)

    # ──────────────────────────────────────────────
    # Polling
    # ──────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all sensor data. Called by HA every update_interval."""
        try:
            data: dict[str, Any] = {}

            async with self._app_session() as session:
                # 1. Unread messages count
                async with session.post(
                    f"{APP_BASE_URL}/api/get_msgs_num"
                ) as resp:
                    result = await resp.json(content_type=None)
                    data["messages"] = int(result.get("data", 0))

                # 2. Payment status (house committee)
                async with session.get(
                    f"{APP_BASE_URL}/houseCommittee"
                ) as resp:
                    html = await resp.text()
                data.update(self._parse_payments(html))

            _LOGGER.debug("MyTower data: %s", data)
            return data

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"MyTower update failed: {err}") from err

    # ──────────────────────────────────────────────
    # Parsers
    # ──────────────────────────────────────────────

    @staticmethod
    def _parse_payments(html: str) -> dict[str, Any]:
        """Extract payment info from /houseCommittee HTML."""
        paid_count = len(re.findall(r'status-paid', html))

        # Monthly fee amount (first ₪ occurrence)
        fee_m = re.search(r'([\d,]+\.?\d*)₪', html)
        monthly_fee = (
            float(fee_m.group(1).replace(",", "")) if fee_m else 0.0
        )

        # Year
        year_m = re.search(r'"selected-year"[^>]*>(\d{4})<', html)
        year = int(year_m.group(1)) if year_m else None

        return {
            "monthly_fee": monthly_fee,
            "paid_months": paid_count,
            "payment_year": year,
        }

    # ──────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────

    async def open_gate(self, gate_uuid: str) -> bool:
        """Send PUT to open a gate. Returns True on success."""
        try:
            async with self._api_session() as session:
                async with session.put(
                    f"{API_BASE_URL}/app/parking/gate/{gate_uuid}/open"
                ) as resp:
                    result = await resp.json(content_type=None)
                    success = result.get("successful", False)
                    if success:
                        _LOGGER.info("MyTower: gate %s opened", gate_uuid)
                    else:
                        _LOGGER.warning(
                            "MyTower: gate open failed: %s", result
                        )
                    return success
        except Exception as err:
            _LOGGER.error("MyTower: open_gate error: %s", err)
            return False


# ──────────────────────────────────────────────────────────────────────────────
# Static login helpers (used by config_flow, not the coordinator)
# ──────────────────────────────────────────────────────────────────────────────

async def mytower_check_phone(phone: str) -> bool:
    """
    POST /api/checkPhone — triggers SMS OTP.
    phone: digits only, no leading 0, no country code (e.g. "501234567")
    Returns True if server accepted the phone.
    """
    # Strip leading 0 and any country prefix
    clean = re.sub(r'^\+?972', '', phone).lstrip('0')
    payload = {"phone": clean, "country": "972"}

    async with aiohttp.ClientSession(headers=APP_HEADERS) as session:
        async with session.post(
            f"{APP_BASE_URL}/api/checkPhone",
            data=payload,
        ) as resp:
            result = await resp.json(content_type=None)
            return result.get("data") is True


async def mytower_login(phone: str, code: str) -> dict[str, str] | None:
    """
    POST /api/login — exchange OTP for session.
    Returns {"auth_token": ..., "user_id": ...} on success, None on failure.

    phone: full E.164 without '+' (e.g. "972501234567")
    code:  6-digit OTP string
    """
    # Normalise phone to E.164 without +
    clean = re.sub(r'^\+', '', phone)
    if not clean.startswith('972'):
        clean = '972' + clean.lstrip('0')

    payload = {"phone": clean, "code": code}

    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(
        cookie_jar=jar, headers=APP_HEADERS
    ) as session:
        async with session.post(
            f"{APP_BASE_URL}/api/login",
            data=payload,
            allow_redirects=True,
            max_redirects=5,
        ) as resp:
            final_url = str(resp.url)

            # Extract user_id from redirect URL: index.php?user_id=XXXXX
            uid_m = re.search(r'user_id=(\d+)', final_url)
            if not uid_m:
                _LOGGER.error("MyTower login: no user_id in redirect URL: %s", final_url)
                return None

            user_id = uid_m.group(1)

            # Extract CRM_user_users cookie (URL-decoded)
            auth_token = None
            for cookie in jar:
                if cookie.key == COOKIE_AUTH:
                    auth_token = urllib.parse.unquote(cookie.value)
                    break

            if not auth_token:
                _LOGGER.error("MyTower login: CRM_user_users cookie not found")
                return None

            return {"auth_token": auth_token, "user_id": user_id}
