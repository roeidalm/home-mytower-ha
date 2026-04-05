"""MyTower DataUpdateCoordinator — login, discovery, polling."""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import timedelta
from urllib.parse import unquote as url_decode
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
    CONF_PHONE,
    ENTITY_TOWER_UPDATES,
)

_LOGGER = logging.getLogger(__name__)


class MyTowerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages all communication with the MyTower API."""

    def __init__(self, hass: HomeAssistant, auth_token: str, user_id: str, phone: str = "") -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        # auth_token = URL-decoded value of CRM_user_users cookie
        self.auth_token = auth_token
        self.user_id = user_id
        self.phone = phone  # registered phone number (for problem tickets etc.)

        # Discovered at setup — list of {"uuid": ..., "name": ...}
        self.gates: list[dict[str, str]] = []

    # ──────────────────────────────────────────────
    # Auth helpers
    # ──────────────────────────────────────────────

    def _cookie_header(self) -> str:
        """
        Build a raw Cookie header string.
        We bypass aiohttp's cookies= parameter to avoid double-encoding
        the URL-encoded auth token (e.g. %2C being re-encoded to %252C).
        """
        return (
            f"{COOKIE_AUTH}={self.auth_token}; "
            f"{COOKIE_DEVICE}={COOKIE_DEVICE_VALUE}; "
            f"{COOKIE_PROJECT}={COOKIE_PROJECT_VALUE}"
        )

    def _api_headers(self) -> dict[str, str]:
        """Headers needed for api.my-tower.co.il (REST API)."""
        return {
            # Auth-Token header uses the URL-decoded value (commas, not %2C)
            "Auth-Token": url_decode(self.auth_token),
            "Locale": "he",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": MOBILE_UA,
        }

    def _app_session(self) -> aiohttp.ClientSession:
        """aiohttp session pre-loaded with app cookies + mobile UA.
        Cookie is sent as a raw header string to avoid double URL-encoding."""
        return aiohttp.ClientSession(
            headers={
                **APP_HEADERS,
                "Cookie": self._cookie_header(),
            },
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
                    _LOGGER.debug("gates page status=%s len=%d prefix=%s",
                                  resp.status, len(html), html[:200])

            gates = []
            # HTML structure:
            #   <div class="gate" data-gate-id="{uuid}">
            #     ...
            #     <div class="gate_name">שער כניסה</div>
            #   </div>
            for m in re.finditer(
                r'class=["\'][^"\']*\bgate\b[^"\']*["\'][^>]*data-gate-id=["\']([0-9a-f-]{36})["\']'
                r'|data-gate-id=["\']([0-9a-f-]{36})["\']',
                html,
                re.IGNORECASE,
            ):
                uuid = m.group(1) or m.group(2)
                context = html[m.start() : m.start() + 400]
                name_m = re.search(r'class=["\']gate_name["\'][^>]*>([^<]+)<', context)
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
                    text = await resp.text()
                    _LOGGER.debug("get_msgs_num status=%s body=%s", resp.status, text[:100])
                    import json as _json
                    result = _json.loads(text)
                    raw = result.get("data", 0)
                    try:
                        data["messages"] = int(raw) if raw != "" else 0
                    except (ValueError, TypeError):
                        _LOGGER.warning("get_msgs_num unexpected value: %r — token may be expired", raw)
                        data["messages"] = 0

                # 2. Payment status (house committee)
                async with session.get(
                    f"{APP_BASE_URL}/houseCommittee"
                ) as resp:
                    html = await resp.text()
                data.update(self._parse_payments(html))

            # 3. Tower updates — list page
            async with session.get(
                f"{APP_BASE_URL}/tower_services/towerUpdates"
            ) as resp:
                updates_html = await resp.text()
            updates_list = self._parse_tower_updates(updates_html)

            # Fetch full content for the latest update only (to avoid hammering the server)
            if updates_list:
                latest = updates_list[0]
                async with session.get(latest["url"]) as resp:
                    detail_html = await resp.text()
                latest["content"] = self._parse_update_detail(detail_html)
                updates_list[0] = latest

            data["tower_updates"] = updates_list
            data["tower_updates_count"] = len(updates_list)
            data["tower_updates_latest"] = updates_list[0] if updates_list else None

            # 4. Guests count + type split
            guests = await self.get_guests()
            data["guests_count"] = len(guests)
            data["guests"] = guests

            # Separate by type — MyTower uses "regular" / "permanent" / "קבוע" for permanent guests
            regular = [
                g for g in guests
                if g.get("type", "").lower() in ("regular", "permanent", "קבוע", "קבועים")
            ]
            temporary = [
                g for g in guests
                if g.get("type", "").lower() in ("temporary", "זמני", "זמניים", "חד פעמי")
            ]
            # Anything unclassified goes into temporary (safer default)
            classified_ids = {g["id"] for g in regular} | {g["id"] for g in temporary}
            unclassified = [g for g in guests if g["id"] not in classified_ids]
            temporary = temporary + unclassified

            data["regular_guests"] = regular
            data["regular_guests_count"] = len(regular)
            data["temporary_guests"] = temporary
            data["temporary_guests_count"] = len(temporary)

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

        # Monthly fee: look for the consistent per-row amount
        # The fee appears once per month row — take the most frequent ₪ value
        all_amounts = re.findall(r'([\d,]+\.\d{2})₪', html)
        monthly_fee = 0.0
        if all_amounts:
            # Most frequent value = the monthly fee (appears 12 times, once per month)
            from collections import Counter
            most_common = Counter(all_amounts).most_common(1)[0][0]
            monthly_fee = float(most_common.replace(",", ""))

        # Year
        year_m = re.search(r'selected-year[^>]*>(\d{4})<', html)
        if not year_m:
            year_m = re.search(r'>(\d{4})<', html)
        year = int(year_m.group(1)) if year_m else None

        return {
            "monthly_fee": monthly_fee,
            "paid_months": paid_count,
            "payment_year": year,
        }

    @staticmethod
    def _parse_update_detail(html: str) -> str:
        """Extract full text content from a single tower update page.

        Page structure:
          <h1>כותרת</h1>
          <div class="tower-update-info">
            <div class="time">DD/MM/YY</div>
            <div class="content"><p>...</p></div>
          </div>
        """
        # Find the content div
        m = re.search(r'class=["\']content["\'][^>]*>(.*?)</div>', html, re.DOTALL)
        if not m:
            return ""
        raw = m.group(1).strip()
        # Strip HTML tags, normalize whitespace
        text = re.sub(r'<[^>]+>', '', raw)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&#\d+;', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def _parse_tower_updates(html: str) -> list[dict]:
        """Extract tower update items from /tower_services/towerUpdates HTML.

        Each item looks like:
          <a href="tower_services/towerUpdate?id={uuid}" class="tower-update" data-search="{title}">
            <div class="time">DD/MM/YY</div>
            <div class="title">...</div>
            <div class="content">...</div>
          </a>
        """
        updates = []
        for m in re.finditer(
            r'<a[^>]+href=["\']tower_services/towerUpdate\?id=([0-9a-f-]{36})["\'][^>]*class=["\']tower-update["\']'
            r'|<a[^>]+class=["\']tower-update["\'][^>]*href=["\']tower_services/towerUpdate\?id=([0-9a-f-]{36})["\']',
            html,
        ):
            uuid = m.group(1) or m.group(2)

            # Extract data-search (title fallback) from the opening <a> tag itself
            tag_end = html.find('>', m.start()) + 1
            opening_tag = html[m.start(): tag_end]
            data_search_m = re.search(r'data-search=["\']([^"\']+)["\']', opening_tag)
            data_search_title = data_search_m.group(1).strip() if data_search_m else ""

            # Grab a wider block (~3000 chars) to handle large SVG icons between time and title
            block = html[m.start(): m.start() + 3000]

            date_m = re.search(r'class=["\']time["\'][^>]*>\s*([^<]+?)\s*</div>', block)
            title_m = re.search(r'class=["\']title["\'][^>]*>\s*([^<]+?)\s*</div>', block)
            content_m = re.search(r'class=["\']content["\'][^>]*>(.*?)</div>', block, re.DOTALL)
            img_m = re.search(r'<img\s+src=["\']([^"\']+)["\']', block)

            content_raw = content_m.group(1).strip() if content_m else ""
            # Strip inner HTML tags from content snippet
            content_text = re.sub(r'<[^>]+>', '', content_raw).strip()

            # Use <div class="title"> if found, otherwise fall back to data-search attribute
            title = (title_m.group(1).strip() if title_m else "") or data_search_title

            updates.append({
                "id": uuid,
                "date": date_m.group(1).strip() if date_m else "",
                "title": title,
                "summary": content_text[:200] if content_text else "",
                "url": f"{APP_BASE_URL}/tower_services/towerUpdate?id={uuid}",
                "image": img_m.group(1) if img_m else None,
            })

        _LOGGER.info("MyTower: found %d tower update(s)", len(updates))
        return updates

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

    async def get_guests(self) -> list[dict]:
        """Scrape guest list from /guests HTML page."""
        try:
            async with self._app_session() as session:
                async with session.get(f"{APP_BASE_URL}/guests") as resp:
                    html = await resp.text()
                    _LOGGER.debug(
                        "MyTower: guests page status=%s len=%d preview=%s",
                        resp.status, len(html), html[:1500],
                    )

            guests = []

            # href="guests/visitors?visitor_id={N}&visitor_type={type}"
            # This is the actual HTML structure used by MyTower
            for m in re.finditer(
                r'href=["\']guests/visitors\?visitor_id=(\d+)&amp;visitor_type=(\w+)["\']'
                r'|href=["\']guests/visitors\?visitor_id=(\d+)&visitor_type=(\w+)["\']',
                html,
            ):
                visitor_id = m.group(1) or m.group(3)
                visitor_type = m.group(2) or m.group(4)
                # Use a wider block to capture all guest-data fields (name + due date + phone)
                block = html[m.start(): m.start() + 900]

                name_m = re.search(
                    r'class=["\']guest-name["\'][^>]*>\s*([^<]+)<', block
                )
                # Due date: <label>בתוקף עד:</label> <span>DD.MM.YYYY</span>
                due_m = re.search(
                    r'בתוקף עד[^<]*</label>\s*<span>\s*([^<]+?)\s*</span>',
                    block, re.DOTALL,
                )
                # Phone: <label>טלפון:</label> <span>0XXXXXXXXX</span>
                phone_m = re.search(
                    r'טלפון[^<]*</label>\s*<span>\s*(\d+)\s*</span>',
                    block, re.DOTALL,
                )
                guests.append({
                    "id": visitor_id,
                    "name": name_m.group(1).strip() if name_m else "?",
                    "type": visitor_type,
                    "phone": phone_m.group(1).strip() if phone_m else "",
                    "due_date": due_m.group(1).strip() if due_m else "",
                })

            _LOGGER.info("MyTower: found %d guest(s)", len(guests))
            return guests

        except Exception as err:
            _LOGGER.error("MyTower: get_guests error: %s", err)
            return []



    async def add_guest(
        self,
        name: str,
        phone: str,
        guest_type: str,
        meeting_place: str,
        date: str | None = None,
        due_date: str | None = None,
        description: str = "",
        car_number: str = "",
    ) -> bool:
        """Add a guest. guest_type: 'temporary' or 'regular'.

        All form fields must be present (even empty ones) or the server
        returns HTTP 500 with empty body.  Reverse-engineered from
        /guests/visitors → new FormData($('#guestForm')[0]).
        """
        import aiohttp
        from datetime import datetime, timedelta

        today = datetime.now().strftime("%d/%m/%Y")
        next_month = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")

        form = aiohttp.FormData()
        # --- fields captured by new FormData (order matches the HTML form) ---
        form.add_field("guestType", guest_type)
        form.add_field("name", name)
        form.add_field("guestPassport", "")
        form.add_field("phone", phone)
        form.add_field("carNumber", car_number)
        form.add_field("allowBloogate", "0")
        form.add_field("meetingPlace", meeting_place)
        form.add_field("estimateDate", date or today)
        form.add_field("dueToDate", due_date or next_month)
        form.add_field("description", description)
        # --- fields appended by JS after FormData creation ---
        form.add_field("visitorType", guest_type)
        form.add_field("visitorId", "")
        try:
            async with self._app_session() as session:
                async with session.post(
                    f"{APP_BASE_URL}/api/createGuest",
                    data=form,
                ) as resp:
                    raw = await resp.text()
                    _LOGGER.debug("MyTower: add_guest raw response: %s", raw)
                    import json as _json
                    try:
                        outer = _json.loads(raw)
                        # Response: {"data": {"result": "success", "msg": "..."}}
                        result = outer.get("data", outer) if isinstance(outer, dict) else {}
                    except Exception:
                        result = {}
                    success = result.get("result") == "success"
                    _LOGGER.info("MyTower: add_guest result: %s", result)
                    return success
        except Exception as err:
            _LOGGER.error("MyTower: add_guest error: %s", err)
            return False

    async def remove_guest(self, visitor_id: str, visitor_type: str = "temporary") -> bool:
        """Remove a guest by visitor_id."""
        try:
            async with self._app_session() as session:
                async with session.post(
                    f"{APP_BASE_URL}/api/deleteGuest",
                    data={"visitorId": visitor_id, "visitorType": visitor_type},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                ) as resp:
                    raw = await resp.text()
                    _LOGGER.debug("MyTower: remove_guest raw response: %s", raw)
                    import json as _json
                    try:
                        outer = _json.loads(raw)
                        result = outer.get("data", outer) if isinstance(outer, dict) else {}
                    except Exception:
                        result = {}
                    success = result.get("result") == "success"
                    _LOGGER.info("MyTower: remove_guest result: %s", result)
                    return success
        except Exception as err:
            _LOGGER.error("MyTower: remove_guest error: %s", err)
            return False

    async def submit_problem(
        self,
        category_id: int,
        sub_category_id: int,
        location_id: int,
        description: str,
        phone: str | None = None,
        complainant_id: int = 1,
    ) -> bool:
        """Submit a problem ticket."""
        payload = {
            "category_id": category_id,
            "sub_category_id": sub_category_id,
            "location_id": location_id,
            "description": description,
            "phone": phone or self.phone,  # use registered phone as default
            "complainant_id": complainant_id,
        }
        try:
            async with self._app_session() as session:
                async with session.post(
                    f"{APP_BASE_URL}/problems/create",
                    data=payload,
                    headers={"X-Requested-With": "XMLHttpRequest", "Origin": APP_BASE_URL},
                ) as resp:
                    result = await resp.json(content_type=None)
                    success = result.get("result") == "success" or resp.status in (200, 201)
                    _LOGGER.info("MyTower: submit_problem result: %s status=%s", result, resp.status)
                    return success
        except Exception as err:
            _LOGGER.error("MyTower: submit_problem error: %s", err)
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
