"""MyTower Home Assistant Integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    DOMAIN, CONF_AUTH_TOKEN, CONF_USER_ID, CONF_PHONE,
    SERVICE_ADD_GUEST, SERVICE_REMOVE_GUEST, SERVICE_SUBMIT_PROBLEM,
    MEETING_PLACE_LOBBY, MEETING_PLACE_APARTMENT,
    PROBLEM_CATEGORIES, PROBLEM_SUB_CATEGORIES, PROBLEM_LOCATIONS,
)
from .coordinator import MyTowerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MyTower from a config entry."""
    coordinator = MyTowerCoordinator(
        hass,
        auth_token=entry.data[CONF_AUTH_TOKEN],
        user_id=entry.data[CONF_USER_ID],
        phone=entry.data.get(CONF_PHONE, ""),
    )

    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once — guard against multiple entries)
    if not hass.services.has_service(DOMAIN, SERVICE_ADD_GUEST):

        async def handle_add_guest(call: ServiceCall) -> None:
            name = call.data["name"]
            phone = call.data["phone"]
            guest_type = call.data.get("guest_type", "temporary")
            meeting_place_key = call.data.get("meeting_place", "lobby")
            meeting_place = MEETING_PLACE_APARTMENT if meeting_place_key == "apartment" else MEETING_PLACE_LOBBY
            date = call.data.get("date")
            coord = next(iter(hass.data[DOMAIN].values()))
            success = await coord.add_guest(name, phone, guest_type, meeting_place, date=date)
            if not success:
                _LOGGER.error("MyTower: add_guest failed for %s", name)
            await coord.async_refresh()

        async def handle_remove_guest(call: ServiceCall) -> None:
            visitor_id = call.data["visitor_id"]
            visitor_type = call.data.get("visitor_type", "temporary")
            coord = next(iter(hass.data[DOMAIN].values()))
            success = await coord.remove_guest(visitor_id, visitor_type)
            if not success:
                _LOGGER.error("MyTower: remove_guest failed for id %s", visitor_id)
            await coord.async_refresh()

        async def handle_submit_problem(call: ServiceCall) -> None:
            category_key = call.data["category"]
            location_key = call.data["location"]
            sub_category_key = call.data.get("sub_category", "maintenance_other")
            description = call.data["description"]
            phone = call.data.get("phone") or None  # None → coordinator uses registered phone
            category_id = PROBLEM_CATEGORIES.get(category_key, 35)
            location_id = PROBLEM_LOCATIONS.get(location_key, 15362)
            sub_category_id = PROBLEM_SUB_CATEGORIES.get(sub_category_key, 6113)
            coord = next(iter(hass.data[DOMAIN].values()))
            success = await coord.submit_problem(category_id, sub_category_id, location_id, description, phone=phone)
            if not success:
                _LOGGER.error("MyTower: submit_problem failed")

        hass.services.async_register(DOMAIN, SERVICE_ADD_GUEST, handle_add_guest)
        hass.services.async_register(DOMAIN, SERVICE_REMOVE_GUEST, handle_remove_guest)
        hass.services.async_register(DOMAIN, SERVICE_SUBMIT_PROBLEM, handle_submit_problem)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_ADD_GUEST)
            hass.services.async_remove(DOMAIN, SERVICE_REMOVE_GUEST)
            hass.services.async_remove(DOMAIN, SERVICE_SUBMIT_PROBLEM)
    return unload_ok
