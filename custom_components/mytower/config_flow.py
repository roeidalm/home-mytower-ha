"""Config flow for MyTower — phone + SMS OTP."""

from __future__ import annotations

import logging
import re
import urllib.parse
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN, CONF_PHONE, CONF_AUTH_TOKEN, CONF_USER_ID,
    APP_BASE_URL, MOBILE_UA, COOKIE_AUTH, AJAX_HEADERS, LOGIN_HEADERS,
)

_LOGGER = logging.getLogger(__name__)

STEP_PHONE_SCHEMA = vol.Schema({vol.Required(CONF_PHONE): str})
STEP_OTP_SCHEMA = vol.Schema({vol.Required("otp"): str})


def _normalize_phone(phone: str) -> str:
    """
    Normalize any Israeli phone format to the digits MyTower expects.
    Input:  +972501234567 / 972501234567 / 0501234567 / 501234567
    Output: 501234567  (9 digits, no leading 0, no country code)
    """
    phone = phone.strip().replace("-", "").replace(" ", "")
    phone = re.sub(r'^\+?972', '', phone)   # strip +972 or 972
    phone = phone.lstrip('0')               # strip leading 0
    return phone


class MyTowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: phone → OTP → done."""

    VERSION = 1

    def __init__(self) -> None:
        self._phone: str = ""          # raw input (kept for display)
        self._clean_phone: str = ""    # normalized (sent to server)

    # ── Step 1: phone number ──────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            raw = user_input[CONF_PHONE].strip()
            clean = _normalize_phone(raw)

            _LOGGER.debug("checkPhone: raw=%s clean=%s", raw, clean)

            if len(clean) != 9 or not clean.isdigit():
                errors[CONF_PHONE] = "invalid_phone"
            else:
                try:
                    ok = await self._check_phone(clean)
                    _LOGGER.debug("checkPhone result: %s", ok)
                    if ok:
                        self._phone = raw
                        self._clean_phone = clean
                        return await self.async_step_otp()
                    else:
                        errors[CONF_PHONE] = "phone_not_found"
                except Exception as e:
                    _LOGGER.exception("checkPhone exception: %s", e)
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_PHONE_SCHEMA,
            errors=errors,
            description_placeholders={
                "example": "0501234567 / 972501234567 / +972501234567"
            },
        )

    # ── Re-auth ───────────────────────────────────────────────────────────────

    async def async_step_reauth(self, entry_data: dict) -> FlowResult:
        self._phone = entry_data.get(CONF_PHONE, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            raw = user_input.get(CONF_PHONE, self._phone).strip()
            clean = _normalize_phone(raw)
            try:
                ok = await self._check_phone(clean)
                if ok:
                    self._phone = raw
                    self._clean_phone = clean
                    return await self.async_step_otp()
                else:
                    errors[CONF_PHONE] = "phone_not_found"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_PHONE, default=self._phone): str
            }),
            errors=errors,
        )

    # ── Step 2: OTP ──────────────────────────────────────────────────────────

    async def async_step_otp(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            otp = user_input["otp"].strip()

            if not re.fullmatch(r'\d{4,6}', otp):
                errors["otp"] = "invalid_otp"
            else:
                try:
                    result = await self._login(self._clean_phone, otp)
                    _LOGGER.debug("login result: %s", result)
                    if result:
                        new_data = {
                            CONF_PHONE: self._phone,
                            CONF_AUTH_TOKEN: result["auth_token"],
                            CONF_USER_ID: result["user_id"],
                        }
                        await self.async_set_unique_id(result["user_id"])

                        if self.source == config_entries.SOURCE_REAUTH:
                            entry = self._get_reauth_entry()
                            self.hass.config_entries.async_update_entry(
                                entry, data=new_data
                            )
                            await self.hass.config_entries.async_reload(
                                entry.entry_id
                            )
                            return self.async_abort(reason="reauth_successful")

                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=f"MyTower ({result['user_id']})",
                            data=new_data,
                        )
                    else:
                        errors["otp"] = "invalid_auth"
                except Exception as e:
                    _LOGGER.exception("login exception: %s", e)
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="otp",
            data_schema=STEP_OTP_SCHEMA,
            errors=errors,
            description_placeholders={"phone": self._phone},
        )

    # ── HTTP helpers (use HA's managed session) ───────────────────────────────

    async def _check_phone(self, clean_phone: str) -> bool:
        """POST /api/checkPhone — triggers SMS. clean_phone = 9 digits."""
        session = async_get_clientsession(self.hass)
        data = {"phone": clean_phone, "country": "972"}

        async with session.post(
            f"{APP_BASE_URL}/api/checkPhone",
            data=data,
            headers=AJAX_HEADERS,
        ) as resp:
            text = await resp.text()
            _LOGGER.debug("checkPhone raw response: %s", text)
            try:
                import json as _json
                result = _json.loads(text)
            except Exception:
                _LOGGER.error("checkPhone non-JSON response: %s", text)
                return False
            return result.get("data") is True

    async def _login(self, clean_phone: str, otp: str) -> dict | None:
        """POST /api/login — returns {auth_token, user_id} or None."""
        import aiohttp as _aiohttp

        # Use a fresh session with cookie jar to capture Set-Cookie
        jar = _aiohttp.CookieJar(unsafe=True)
        phone_e164 = f"972{clean_phone}"
        data = {"phone": phone_e164, "code": otp}

        async with _aiohttp.ClientSession(
            cookie_jar=jar, headers=LOGIN_HEADERS
        ) as session:
            async with session.post(
                f"{APP_BASE_URL}/api/login",
                data=data,
                allow_redirects=True,
                max_redirects=5,
            ) as resp:
                final_url = str(resp.url)
                _LOGGER.debug("login final_url: %s", final_url)

                uid_m = re.search(r'user_id=(\d+)', final_url)
                if not uid_m:
                    _LOGGER.error(
                        "MyTower login: no user_id in URL %s", final_url
                    )
                    return None

                user_id = uid_m.group(1)

                auth_token = None
                for cookie in jar:
                    if cookie.key == COOKIE_AUTH:
                        auth_token = urllib.parse.unquote(cookie.value)
                        break

                if not auth_token:
                    _LOGGER.error("MyTower login: CRM_user_users cookie missing")
                    return None

                return {"auth_token": auth_token, "user_id": user_id}
