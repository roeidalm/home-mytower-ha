"""Config flow for MyTower — phone + SMS OTP."""

from __future__ import annotations

import logging
import re
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_PHONE, CONF_AUTH_TOKEN, CONF_USER_ID
from .coordinator import mytower_check_phone, mytower_login

_LOGGER = logging.getLogger(__name__)

STEP_PHONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PHONE): str,
    }
)

STEP_OTP_SCHEMA = vol.Schema(
    {
        vol.Required("otp"): str,
    }
)


class MyTowerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow: phone → OTP → done."""

    VERSION = 1

    def __init__(self) -> None:
        self._phone: str = ""

    # ── Step 1: phone number ──────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            phone = user_input[CONF_PHONE].strip()

            # Basic validation
            if not re.search(r'\d{9,10}', phone):
                errors[CONF_PHONE] = "invalid_phone"
            else:
                try:
                    ok = await mytower_check_phone(phone)
                    if ok:
                        self._phone = phone
                        return await self.async_step_otp()
                    else:
                        errors[CONF_PHONE] = "phone_not_found"
                except Exception:
                    _LOGGER.exception("checkPhone error")
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_PHONE_SCHEMA,
            errors=errors,
            description_placeholders={"phone": self._phone},
        )

    # ── Re-auth (token expired) ───────────────────────────────────────────────

    async def async_step_reauth(self, entry_data: dict) -> FlowResult:
        """Triggered by HA when the stored token stops working."""
        self._phone = entry_data.get(CONF_PHONE, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            phone = user_input.get(CONF_PHONE, self._phone).strip()
            try:
                ok = await mytower_check_phone(phone)
                if ok:
                    self._phone = phone
                    return await self.async_step_otp()
                else:
                    errors[CONF_PHONE] = "phone_not_found"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PHONE, default=self._phone): str}),
            errors=errors,
            description_placeholders={"phone": self._phone},
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
                    result = await mytower_login(self._phone, otp)
                    if result:
                        new_data = {
                            CONF_PHONE: self._phone,
                            CONF_AUTH_TOKEN: result["auth_token"],
                            CONF_USER_ID: result["user_id"],
                        }

                        # Re-auth: update existing entry instead of creating new one
                        existing = await self.async_set_unique_id(result["user_id"])
                        if self.source == config_entries.SOURCE_REAUTH:
                            self.hass.config_entries.async_update_entry(
                                self._get_reauth_entry(), data=new_data
                            )
                            await self.hass.config_entries.async_reload(
                                self._get_reauth_entry().entry_id
                            )
                            return self.async_abort(reason="reauth_successful")

                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=f"MyTower ({result['user_id']})",
                            data=new_data,
                        )
                    else:
                        errors["otp"] = "invalid_auth"
                except Exception:
                    _LOGGER.exception("login error")
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="otp",
            data_schema=STEP_OTP_SCHEMA,
            errors=errors,
            description_placeholders={"phone": self._phone},
        )
