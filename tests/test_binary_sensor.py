"""Tests for controller diagnostic binary sensors."""

from types import SimpleNamespace

from pyrinnaitouch import RinnaiSystemMode

from custom_components.rinnaitouch.binary_sensor import (
    RinnaiServiceReminderBinarySensorEntity,
)


def test_service_reminder_reports_active_appliance(monkeypatch):
    """Expose SN with the appliance that supplied the current state."""
    state = SimpleNamespace(
        mode=RinnaiSystemMode.HEATING,
        unit_status=SimpleNamespace(service_required=True),
    )
    system = SimpleNamespace(get_stored_status=lambda: state)
    monkeypatch.setattr(
        "custom_components.rinnaitouch.binary_sensor.RinnaiSystem.get_instance",
        lambda _host: system,
    )

    entity = RinnaiServiceReminderBinarySensorEntity("192.0.2.1", "Office")

    assert entity.name == "Office Service Reminder"
    assert entity.is_on
    assert entity.available
    assert entity.extra_state_attributes == {"appliance": "Heating"}


def test_service_reminder_is_unavailable_without_an_active_appliance(monkeypatch):
    """Avoid reporting a clear reminder when no appliance status exists."""
    state = SimpleNamespace(
        mode=RinnaiSystemMode.NONE,
        unit_status=SimpleNamespace(service_required=False),
    )
    system = SimpleNamespace(get_stored_status=lambda: state)
    monkeypatch.setattr(
        "custom_components.rinnaitouch.binary_sensor.RinnaiSystem.get_instance",
        lambda _host: system,
    )

    entity = RinnaiServiceReminderBinarySensorEntity("192.0.2.1", "Office")

    assert not entity.is_on
    assert not entity.available
    assert entity.extra_state_attributes == {}
