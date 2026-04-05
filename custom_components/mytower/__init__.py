"""MyTower Home Assistant Integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, CONF_AUTH_TOKEN, CONF_USER_ID, CONF_PHONE,
    SERVICE_ADD_GUEST, SERVICE_REMOVE_GUEST, SERVICE_SUBMIT_PROBLEM,
    MEETING_PLACE_LOBBY, MEETING_PLACE_APARTMENT,
    PROBLEM_CATEGORIES, PROBLEM_SUB_CATEGORIES, PROBLEM_LOCATIONS,
)
from .coordinator import MyTowerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button"]

SERVICE_ADD_GUEST_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Required("phone"): cv.string,
    vol.Optional("guest_type", default="temporary"): vol.In(["temporary", "regular"]),
    vol.Optional("meeting_place", default="lobby"): vol.In(["lobby", "apartment"]),
    vol.Optional("date"): cv.string,
    vol.Optional("description", default=""): cv.string,
    vol.Optional("car_number", default=""): cv.string,
})

SERVICE_REMOVE_GUEST_SCHEMA = vol.Schema({
    vol.Required("visitor_id"): cv.string,
    vol.Optional("visitor_type", default="temporary"): vol.In(["temporary", "regular"]),
})

SERVICE_SUBMIT_PROBLEM_SCHEMA = vol.Schema({
    vol.Required("category"): vol.In(list(PROBLEM_CATEGORIES.keys())),
    vol.Required("location"): vol.In(list(PROBLEM_LOCATIONS.keys())),
    vol.Required("description"): cv.string,
    vol.Optional("sub_category", default="maintenance_other"): vol.In(list(PROBLEM_SUB_CATEGORIES.keys())),
    vol.Optional("phone"): cv.string,
})


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> MyTowerCoordinator:
    """Get the coordinator for a service call.

    If entry_id is provided in the service call data, use that specific entry.
    Otherwise fall back to the first (and usually only) entry.
    """
    entries = hass.data[DOMAIN]
    entry_id = call.data.get("entry_id")
    if entry_id and entry_id in entries:
        return entries[entry_id]
    return next(iter(entries.values()))


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
            description = call.data.get("description", "")
            car_number = call.data.get("car_number", "")
            coord = _get_coordinator(hass, call)
            success = await coord.add_guest(
                name, phone, guest_type, meeting_place,
                date=date, description=description, car_number=car_number,
            )
            if not success:
                _LOGGER.error("MyTower: add_guest failed for %s", name)
            await coord.async_refresh()

        async def handle_remove_guest(call: ServiceCall) -> None:
            visitor_id = call.data["visitor_id"]
            visitor_type = call.data.get("visitor_type", "temporary")
            coord = _get_coordinator(hass, call)
            success = await coord.remove_guest(visitor_id, visitor_type)
            if not success:
                _LOGGER.error("MyTower: remove_guest failed for id %s", visitor_id)
            await coord.async_refresh()

        async def handle_submit_problem(call: ServiceCall) -> None:
            category_key = call.data["category"]
            location_key = call.data["location"]
            sub_category_key = call.data.get("sub_category", "maintenance_other")
            description = call.data["description"]
            phone = call.data.get("phone") or None
            category_id = PROBLEM_CATEGORIES.get(category_key, 35)
            location_id = PROBLEM_LOCATIONS.get(location_key, 15362)
            sub_category_id = PROBLEM_SUB_CATEGORIES.get(sub_category_key, 6113)
            coord = _get_coordinator(hass, call)
            success = await coord.submit_problem(category_id, sub_category_id, location_id, description, phone=phone)
            if not success:
                _LOGGER.error("MyTower: submit_problem failed")

        hass.services.async_register(DOMAIN, SERVICE_ADD_GUEST, handle_add_guest, schema=SERVICE_ADD_GUEST_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_REMOVE_GUEST, handle_remove_guest, schema=SERVICE_REMOVE_GUEST_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_SUBMIT_PROBLEM, handle_submit_problem, schema=SERVICE_SUBMIT_PROBLEM_SCHEMA)

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
