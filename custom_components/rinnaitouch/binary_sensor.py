"""Binary sensors for prewetting and preheating"""
# import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import CONF_NAME, CONF_HOST, EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from pyrinnaitouch import (
    RinnaiCapabilities,
    RinnaiSystem,
    RinnaiSystemMode,
    RinnaiSystemStatus,
)
from .const import (
    DEFAULT_NAME,
    DOMAIN,
)
from .entity import (
    RinnaiUpdateMixin,
    setup_discovered_entities,
    zone_display_name,
)
from . import connection_signal

# _LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):  # pylint: disable=unused-argument
    """Set up the binary sensor entities."""
    ip_address = entry.data.get(CONF_HOST)
    name = entry.data.get(CONF_NAME)
    if name == "":
        name = DEFAULT_NAME
    data = hass.data[DOMAIN][entry.entry_id]
    entities = [
        RinnaiConnectedBinarySensorEntity(ip_address, name),
        RinnaiFaultBinarySensorEntity(ip_address, name),
        RinnaiFanOperatingBinarySensorEntity(ip_address, name),
        RinnaiTimeSettingSensorEntity(ip_address, name),
    ]
    if RinnaiCapabilities.HEATER in data.capabilities:
        entities.extend(
            [
                RinnaiPreheatBinarySensorEntity(ip_address, name),
                RinnaiGasValveBinarySensorEntity(ip_address, name),
                RinnaiCallingHeatBinarySensorEntity(ip_address, name),
            ]
        )
    if RinnaiCapabilities.COOLER in data.capabilities:
        entities.extend(
            [
                RinnaiCompressorBinarySensorEntity(ip_address, name),
                RinnaiCallingCoolBinarySensorEntity(ip_address, name),
            ]
        )
    if data.has_evap:
        entities.extend(
            [
                RinnaiPrewetBinarySensorEntity(ip_address, name),
                RinnaiPumpOperatingBinarySensorEntity(ip_address, name),
                RinnaiCoolerBusyBinarySensorEntity(ip_address, name),
            ]
        )
    zone_entity_types = [RinnaiZoneFanOperatingBinarySensorEntity]
    if RinnaiCapabilities.HEATER in data.capabilities:
        zone_entity_types.extend(
            [
                RinnaiZonePreheatBinarySensorEntity,
                RinnaiZoneGasValveBinarySensorEntity,
                RinnaiZoneCallingHeatBinarySensorEntity,
            ]
        )
    if RinnaiCapabilities.COOLER in data.capabilities:
        zone_entity_types.extend(
            [
                RinnaiZoneCompressorBinarySensorEntity,
                RinnaiZoneCallingCoolBinarySensorEntity,
            ]
        )
    async_add_entities(entities)
    setup_discovered_entities(
        hass,
        entry,
        async_add_entities,
        ip_address,
        lambda: (
            (
                f"{entity_type.__name__}_{zone}",
                lambda zone=zone, entity_type=entity_type: entity_type(
                    ip_address, zone, name
                ),
            )
            for zone in data.thermostat_zones
            for entity_type in zone_entity_types
        ),
    )
    return True


class RinnaiBinarySensorEntity(RinnaiUpdateMixin, BinarySensorEntity):
    """Base class for all binary sensor entities setting up names and system instance."""

    def __init__(self, ip_address, name) -> None:
        self._host = ip_address
        self._system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
        device_id = (
            str.lower(self.__class__.__name__) + "_" + str.replace(ip_address, ".", "_")
        )

        self._attr_unique_id = device_id
        self._attr_name = name + " Binary Sensor"
        self._attr_device_name = name

    @property
    def device_info(self):
        """Return device information about this heater."""
        return {
            # "connections": {(CONNECTION_NETWORK_MAC, self._host)},
            "identifiers": {("rinnai_touch", self._host)},
            "model": "Rinnai Touch Wifi",
            "name": self._attr_device_name,
            "manufacturer": "Rinnai/Brivis",
        }

    @property
    def name(self) -> str:
        """Name of the entity."""
        return self._attr_name.replace("Zone U", "Common Zone")

    @property
    def is_on(self) -> bool:
        return False


class RinnaiUnitStateBinarySensorEntity(RinnaiBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_unit_mode = None
        self._attr_check_multi = True
        self._attr_status_attr = None

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        if not self.available:
            return "mdi:eye"
        if self.is_on:
            return "mdi:eye-check"
        return "mdi:eye-remove"

    @property
    def is_on(self):
        """If the switch is currently on or off."""
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if self.available:
            return getattr(state.unit_status, self._attr_status_attr, False)
        return False

    @property
    def available(self):
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if self._attr_check_multi:
            if state.is_multi_set_point:
                return False
        return state.mode == self._attr_unit_mode


class RinnaiPreheatBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Preheating Sensor"
        self._attr_unit_mode = RinnaiSystemMode.HEATING
        self._attr_status_attr = "preheating"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:fire-alert"


class RinnaiGasValveBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Gas Valve Active Sensor"
        self._attr_unit_mode = RinnaiSystemMode.HEATING
        self._attr_status_attr = "gas_valve_active"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:gas-burner"


class RinnaiCallingHeatBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Calling Heat Sensor"
        self._attr_unit_mode = RinnaiSystemMode.HEATING
        self._attr_status_attr = "calling_for_heat"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:thermometer-alert"


class RinnaiCompressorBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Compressor Active Sensor"
        self._attr_unit_mode = RinnaiSystemMode.COOLING
        self._attr_status_attr = "compressor_active"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:cog-clockwise"


class RinnaiCallingCoolBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Calling Cool Sensor"
        self._attr_unit_mode = RinnaiSystemMode.COOLING
        self._attr_status_attr = "calling_for_cool"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:thermometer-alert"


class RinnaiPrewetBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Evap Prewetting Sensor"
        self._attr_unit_mode = RinnaiSystemMode.EVAP
        self._attr_check_multi = False
        self._attr_status_attr = "prewetting"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:snowflake-melt"


class RinnaiPumpOperatingBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Pump Operating Sensor"
        self._attr_unit_mode = RinnaiSystemMode.EVAP
        self._attr_check_multi = False
        self._attr_status_attr = "pump_operating"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:water-alert"


class RinnaiCoolerBusyBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Cooler Busy Sensor"
        self._attr_unit_mode = RinnaiSystemMode.EVAP
        self._attr_check_multi = False
        self._attr_status_attr = "cooler_busy"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:cog-clockwise"


class RinnaiFanOperatingBinarySensorEntity(RinnaiUnitStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Fan Active Sensor"
        self._attr_status_attr = "fan_operating"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:fan-alert"

    @property
    def available(self):
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if state.mode == RinnaiSystemMode.EVAP:
            return True
        if state.is_multi_set_point:
            return False
        return True


class RinnaiTimeSettingSensorEntity(RinnaiBinarySensorEntity):
    """Binary sensor for signaling the system is in time setting mode."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Time Setting Sensor"
        self._attr_status_attr = "is_timesetting"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        if self.is_on:
            return "mdi:clock-alert-outline"
        return "mdi:clock-outline"

    @property
    def is_on(self):
        """If the sensor is currently on or off."""
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if self.available:
            return state.is_timesetting
        return False

    @property
    def available(self):
        """If the sensor is currently available."""
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if not state.has_fault:
            return True
        return False


class RinnaiFaultBinarySensorEntity(RinnaiBinarySensorEntity):
    """Report whether the controller has detected a system fault."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _APPLIANCE_NAMES = {
        "H": "Heating",
        "E": "Evaporative cooling",
        "C": "Add-on cooling",
        "R": "Reverse cycle",
        "N": "Controller",
    }
    _SEVERITY_NAMES = {
        "M": "Minor",
        "B": "Busy",
        "L": "Lockout",
    }

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Fault"

    @property
    def is_on(self) -> bool:
        """Return whether the controller reports a fault."""
        return self._system.get_stored_status().has_fault

    @property
    def available(self) -> bool:
        """Fault state is part of every valid controller status frame."""
        return True

    @property
    def extra_state_attributes(self):
        """Return controller-supplied details for the active fault."""
        state = self._system.get_stored_status()
        if not state.has_fault:
            return {}
        attributes = {
            "appliance": self._APPLIANCE_NAMES.get(
                state.fault_appliance, state.fault_appliance
            ),
            "unit": state.fault_unit,
            "severity": self._SEVERITY_NAMES.get(
                state.fault_severity, state.fault_severity
            ),
            "code": state.fault_code,
        }
        return {key: value for key, value in attributes.items() if value is not None}


class RinnaiZoneStateBinarySensorEntity(RinnaiBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, zone, name):
        super().__init__(ip_address, name)
        self._attr_zone = zone
        self._attr_zone_name = zone_display_name(self._system, zone)
        device_id = (
            str.lower(self.__class__.__name__)
            + "_"
            + zone
            + str.replace(ip_address, ".", "_")
        )
        self._attr_unique_id = device_id
        self._attr_unit_mode = None
        self._attr_status_attr = None

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        if not self.available:
            return "mdi:eye"
        if self.is_on:
            return "mdi:eye-check"
        return "mdi:eye-remove"

    @property
    def is_on(self):
        """If the switch is currently on or off."""
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if self.available:
            return getattr(
                state.unit_status.zones[self._attr_zone], self._attr_status_attr, False
            )
        return False

    @property
    def available(self):
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if state.is_multi_set_point:
            return (
                state.mode == self._attr_unit_mode
                and self._attr_zone in state.unit_status.zones
            )
        return False


class RinnaiZonePreheatBinarySensorEntity(RinnaiZoneStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, zone, name):
        super().__init__(ip_address, zone, name)
        self._attr_name = f"{name} {self._attr_zone_name} Preheating Sensor"
        self._attr_unit_mode = RinnaiSystemMode.HEATING
        self._attr_status_attr = "preheating"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:fire-alert"


class RinnaiZoneGasValveBinarySensorEntity(RinnaiZoneStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, zone, name):
        super().__init__(ip_address, zone, name)
        self._attr_name = f"{name} {self._attr_zone_name} Gas Valve Active Sensor"
        self._attr_unit_mode = RinnaiSystemMode.HEATING
        self._attr_status_attr = "gas_valve_active"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:gas-burner"


class RinnaiZoneCallingHeatBinarySensorEntity(RinnaiZoneStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, zone, name):
        super().__init__(ip_address, zone, name)
        self._attr_name = f"{name} {self._attr_zone_name} Calling Heat Sensor"
        self._attr_unit_mode = RinnaiSystemMode.HEATING
        self._attr_status_attr = "calling_for_work"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:thermometer-alert"


class RinnaiZoneCompressorBinarySensorEntity(RinnaiZoneStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, zone, name):
        super().__init__(ip_address, zone, name)
        self._attr_name = f"{name} {self._attr_zone_name} Compressor Active Sensor"
        self._attr_unit_mode = RinnaiSystemMode.COOLING
        self._attr_status_attr = "compressor_active"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:cog-clockwise"


class RinnaiZoneCallingCoolBinarySensorEntity(RinnaiZoneStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, zone, name):
        super().__init__(ip_address, zone, name)
        self._attr_name = f"{name} {self._attr_zone_name} Calling Cool Sensor"
        self._attr_unit_mode = RinnaiSystemMode.COOLING
        self._attr_status_attr = "calling_for_work"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:thermometer-alert"


class RinnaiZoneFanOperatingBinarySensorEntity(RinnaiZoneStateBinarySensorEntity):
    """Binary sensor for preheating on/off during heater operation."""

    def __init__(self, ip_address, zone, name):
        super().__init__(ip_address, zone, name)
        self._attr_name = f"{name} {self._attr_zone_name} Fan Active Sensor"
        self._attr_status_attr = "fan_operating"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:fan-alert"

    @property
    def available(self):
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if state.mode == RinnaiSystemMode.EVAP:
            return False
        if state.is_multi_set_point:
            return True
        return False


class RinnaiConnectedBinarySensorEntity(RinnaiBinarySensorEntity):
    """Binary sensor for Rinnai connection state."""

    def __init__(self, ip_address, name) -> None:
        super().__init__(ip_address, name)
        self._attr_name = name + " Connected Sensor"
        self._attr_unique_id = "connected_" + str.replace(ip_address, ".", "_")
        self._connected = None
        self._connection_state_handler(self._system.get_connection_state())

    async def async_added_to_hass(self) -> None:
        """Subscribe to centrally dispatched connection updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                connection_signal(self._host),
                self._connection_state_handler,
            )
        )

    @callback
    def _connection_state_handler(self, state):
        """Handle connection state updates from pyrinnaitouch."""
        self._connected = getattr(state, "name", None) == "CONNECTED"
        if self.hass is not None:
            self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return True if connected, False otherwise."""
        return self._connected

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        if self.is_on:
            return "mdi:lan-connect"
        return "mdi:lan-disconnect"
