"""Switches for Auto/Manual, On/Off and circulation fan"""
# import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import Entity
from homeassistant.const import CONF_NAME, CONF_HOST

from pyrinnaitouch import (
    RinnaiSystem,
    RinnaiSystemMode,
    RinnaiOperatingMode,
    RinnaiSystemStatus,
)

from .const import DEFAULT_NAME


async def async_setup_entry(hass, entry, async_add_entities):  # pylint: disable=unused-argument
    """Set up the switch entities."""
    ip_address = entry.data.get(CONF_HOST)
    name = entry.data.get(CONF_NAME)
    if name == "":
        name = DEFAULT_NAME
    async_add_entities(
        [
            RinnaiOnOffSwitch(ip_address, name),
            RinnaiCircFanSwitch(ip_address, name),
            RinnaiAutoSwitch(ip_address, name),
        ]
    )
    return True


class RinnaiExtraEntity(Entity):
    """Base entity with a name and system update capability."""

    def __init__(self, ip_address, name):
        self._host = ip_address
        self._system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
        device_id = (
            str.lower(self.__class__.__name__) + "_" + str.replace(ip_address, ".", "_")
        )

        self._attr_unique_id = device_id
        self._attr_name = name
        self._attr_device_name = name
        self._system.subscribe_updates(self.system_updated)
        self._connected = False
        self._system.register_socket_state_handler(self._connection_state_handler)

    def _connection_state_handler(self, state):
        """Update availability even when no new heater status arrives."""
        self._connected = getattr(state, "name", None) == "CONNECTED"
        if self.hass is not None:
            self.schedule_update_ha_state()

    def system_updated(self):
        """After system is updated write the new state to HA."""
        # this very infrequently fails on startup so wrapping in try except
        try:
            self.schedule_update_ha_state()
        except:  # pylint: disable=bare-except
            pass

    @property
    def available(self):
        """Unavailable while the bridge isn't connected, rather than showing stale state."""
        return self._connected

    async def async_will_remove_from_hass(self):
        """Stop receiving updates."""
        self._system.unsubscribe_updates(self.system_updated)
        self._system.unregister_socket_state_handler(self._connection_state_handler)

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
    def name(self):
        """Name of the entity."""
        return self._attr_name


class RinnaiOnOffSwitch(RinnaiExtraEntity, SwitchEntity):
    """Main on/off switch for the system."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " On Off Switch"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:power"

    @property
    def is_on(self):
        """If the switch is currently on or off."""
        return self._system.get_stored_status().system_on

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        if self._system.get_stored_status().mode == RinnaiSystemMode.HEATING:
            await self._system.turn_unit_on()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._system.get_stored_status().mode == RinnaiSystemMode.HEATING:
            await self._system.turn_unit_off()


class RinnaiAutoSwitch(RinnaiExtraEntity, SwitchEntity):
    """A switch to change between auto and manual operation."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Auto Switch"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        if self.is_on:
            return "mdi:calendar-sync"
        return "mdi:sync"

    @property
    def available(self):
        return super().available and self._system.get_stored_status().system_on

    @property
    def is_on(self):
        if self.available:
            state: RinnaiSystemStatus = self._system.get_stored_status()
            return state.unit_status.operating_mode == RinnaiOperatingMode.AUTO
        return False

    async def async_turn_on(self, **kwargs):
        if self.available:
            await self._system.set_unit_auto()

    async def async_turn_off(self, **kwargs):
        if self.available:
            await self._system.set_unit_manual()


class RinnaiCircFanSwitch(RinnaiExtraEntity, SwitchEntity):
    """A switch to turn the circ fan on or off in heater mode when the heater is off."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Circulation Fan Switch"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        if self.is_on:
            return "mdi:fan"
        return "mdi:fan-off"

    @property
    def available(self):
        if not super().available:
            return False
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if state.mode != RinnaiSystemMode.HEATING:
            return False
        return not state.system_on or not state.unit_status.is_on

    @property
    def is_on(self):
        if self.available:
            return self._system.get_stored_status().unit_status.circulation_fan_on
        return False

    async def async_turn_on(self, **kwargs):
        if self.available:
            await self._system.turn_unit_fan_only()

    async def async_turn_off(self, **kwargs):
        if self.available:
            await self._system.turn_unit_off()
