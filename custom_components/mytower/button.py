"""MyTower gate buttons — dynamically created from discovered gates."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_GATE_PREFIX
from .coordinator import MyTowerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MyTowerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # One button per discovered gate
    buttons = [
        MyTowerGateButton(coordinator, entry, gate)
        for gate in coordinator.gates
    ]

    if not buttons:
        _LOGGER.warning("MyTower: no gates discovered, no gate buttons created")

    async_add_entities(buttons)


class MyTowerGateButton(CoordinatorEntity[MyTowerCoordinator], ButtonEntity):
    """Button to open a single gate."""

    def __init__(
        self,
        coordinator: MyTowerCoordinator,
        entry: ConfigEntry,
        gate: dict[str, str],
    ) -> None:
        super().__init__(coordinator)
        self._gate_uuid = gate["uuid"]
        self._gate_name = gate["name"]

        self._attr_name = f"MyTower {self._gate_name}"
        self._attr_unique_id = f"{entry.entry_id}_{ENTITY_GATE_PREFIX}{self._gate_uuid}"
        self._attr_icon = "mdi:boom-gate-up"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "MyTower",
            "manufacturer": "MyTower",
            "model": "Building Management",
        }

    async def async_press(self) -> None:
        """Open the gate."""
        _LOGGER.info("MyTower: pressing gate button '%s' (%s)", self._gate_name, self._gate_uuid)
        success = await self.coordinator.open_gate(self._gate_uuid)
        if not success:
            _LOGGER.error(
                "MyTower: failed to open gate '%s' (%s)",
                self._gate_name,
                self._gate_uuid,
            )
