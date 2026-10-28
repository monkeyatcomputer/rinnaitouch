"""Advance button to move to next schedule"""
# import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_NAME, CONF_HOST

from pyrinnaitouch import (
    RinnaiSystem,
    RinnaiSystemMode,
    RinnaiOperatingMode,
    RinnaiSystemStatus,
)

from .const import DEFAULT_NAME

# _LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass, entry, async_add_entities
):  # pylint: disable=unused-argument
    """Set up the advance button entities."""
    ip_address = entry.data.get(CONF_HOST)
    name = entry.data.get(CONF_NAME)
    if name == "":
        name = DEFAULT_NAME
    async_add_entities([RinnaiAdvanceButton(ip_address, name)])
    return True


class RinnaiButtonEntity(ButtonEntity):
    """Base class button entity to set up naming and system."""

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
    def available(self) -> bool:
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


class RinnaiAdvanceButton(RinnaiButtonEntity):
    """Main advance button entity."""

    def __init__(self, ip_address, name):
        super().__init__(ip_address, name)
        self._attr_name = name + " Advance Button"

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        if self.available:
            if self._system.get_stored_status().unit_status.advanced:
                return "mdi:close-circle-outline"
        return "mdi:location-exit"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if (
            state.mode == RinnaiSystemMode.HEATING
            and state.unit_status.operating_mode == RinnaiOperatingMode.AUTO
        ):
            return state.system_on
        return False

    async def async_press(self) -> None:
        """Handle the button press."""
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if state.mode == RinnaiSystemMode.HEATING:
            if state.unit_status.advanced:
                await self._system.unit_advance_cancel()
            else:
                await self._system.unit_advance()
