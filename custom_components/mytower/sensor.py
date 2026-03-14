"""MyTower sensors."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_MESSAGES, ENTITY_MONTHLY_FEE, ENTITY_PAID_MONTHS, ENTITY_GUESTS_COUNT
from .coordinator import MyTowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MyTowerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        MyTowerMessagesSensor(coordinator, entry),
        MyTowerMonthlyFeeSensor(coordinator, entry),
        MyTowerPaidMonthsSensor(coordinator, entry),
        MyTowerGuestsSensor(coordinator, entry),
    ])


class MyTowerBaseSensor(CoordinatorEntity[MyTowerCoordinator], SensorEntity):
    """Base class for MyTower sensors."""

    def __init__(
        self,
        coordinator: MyTowerCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "MyTower",
            "manufacturer": "MyTower",
            "model": "Building Management",
        }

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)


class MyTowerMessagesSensor(MyTowerBaseSensor):
    """Unread messages — displayed as Hebrew text."""

    _attr_name = "MyTower הודעות"
    _attr_icon = "mdi:message-badge"
    # No state_class / unit — this is a text sensor

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, ENTITY_MESSAGES)

    @property
    def native_value(self) -> str:
        count = self.coordinator.data.get(self._key, 0) or 0
        if count == 0:
            return "אין הודעות חדשות"
        elif count == 1:
            return "הודעה חדשה אחת"
        else:
            return f"{count} הודעות חדשות"

    @property
    def extra_state_attributes(self):
        """Expose raw count for automations."""
        return {"count": self.coordinator.data.get(self._key, 0) or 0}


class MyTowerMonthlyFeeSensor(MyTowerBaseSensor):
    """Monthly building management fee."""

    _attr_name = "MyTower דמי ניהול חודשיים"
    _attr_icon = "mdi:currency-ils"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "₪"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, ENTITY_MONTHLY_FEE)


class MyTowerPaidMonthsSensor(MyTowerBaseSensor):
    """Number of months paid this year."""

    _attr_name = "MyTower חודשים ששולמו"
    _attr_icon = "mdi:calendar-check"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "חודשים"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, ENTITY_PAID_MONTHS)


class MyTowerGuestsSensor(CoordinatorEntity[MyTowerCoordinator], SensorEntity):
    """Sensor showing number of active guests."""

    _attr_icon = "mdi:account-group"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MyTowerCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "MyTower Active Guests"
        self._attr_unique_id = f"{entry.entry_id}_{ENTITY_GUESTS_COUNT}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "MyTower",
            "manufacturer": "MyTower",
            "model": "Building Management",
        }

    @property
    def native_value(self) -> int:
        return self.coordinator.data.get("guests_count", 0)

    @property
    def extra_state_attributes(self) -> dict:
        return {"guests": self.coordinator.data.get("guests", [])}
