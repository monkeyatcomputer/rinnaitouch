"""Select entities for schedules and installed cooling types."""
# import logging

from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_NAME, CONF_HOST

from pyrinnaitouch import (
    RinnaiCapabilities,
    RinnaiOperatingMode,
    RinnaiSystem,
    RinnaiSystemMode,
)

from .const import (
    COOLING_TYPE_EVAPORATIVE,
    COOLING_TYPE_REFRIGERATED,
    DEFAULT_NAME,
    DOMAIN,
    PRESET_AUTO,
    PRESET_MANUAL,
    SYSTEM_MODE_EVAPORATIVE_COOLING,
    SYSTEM_MODE_HEATING,
    SYSTEM_MODE_REFRIGERATED_COOLING,
)
from .entity import RinnaiUpdateMixin

# _LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass, entry, async_add_entities
):  # pylint: disable=unused-argument
    """Set up the preset select entities."""
    ip_address = entry.data.get(CONF_HOST)
    name = entry.data.get(CONF_NAME)
    if name == "":
        name = DEFAULT_NAME
    data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    if data.topology.multi_set_point:
        entities.append(
            RinnaiSystemModeSelectEntity(
                ip_address, name, data.capabilities
            )
        )
    else:
        entities.append(RinnaiSelectPresetEntity(ip_address, name))
    if not data.topology.multi_set_point and {
        RinnaiCapabilities.COOLER,
        RinnaiCapabilities.EVAP,
    }.issubset(data.capabilities):
        entities.append(RinnaiCoolingTypeSelectEntity(ip_address, name))
    async_add_entities(entities)
    return True


class RinnaiSystemModeSelectEntity(RinnaiUpdateMixin, SelectEntity):
    """Select the active whole-system mode on an MTSP installation."""

    def __init__(self, ip_address, name, capabilities):
        self._host = ip_address
        self._system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
        self._attr_unique_id = (
            "rinnaisystemmodeselect_" + str.replace(ip_address, ".", "_")
        )
        self._attr_name = name + " System Mode"
        self._attr_device_name = name
        options = []
        if RinnaiCapabilities.HEATER in capabilities:
            options.append(SYSTEM_MODE_HEATING)
        if RinnaiCapabilities.COOLER in capabilities:
            options.append(SYSTEM_MODE_REFRIGERATED_COOLING)
        if RinnaiCapabilities.EVAP in capabilities:
            options.append(SYSTEM_MODE_EVAPORATIVE_COOLING)
        self._attr_options = options

    @property
    def device_info(self):
        """Return device information about this controller."""
        return {
            "identifiers": {("rinnai_touch", self._host)},
            "model": "Rinnai Touch Wifi",
            "name": self._attr_device_name,
            "manufacturer": "Rinnai/Brivis",
        }

    @property
    def icon(self):
        """Return an icon for the selected equipment mode."""
        mode = self._system.get_stored_status().mode
        if mode == RinnaiSystemMode.HEATING:
            return "mdi:fire"
        if mode == RinnaiSystemMode.COOLING:
            return "mdi:snowflake"
        if mode == RinnaiSystemMode.EVAP:
            return "mdi:snowflake-melt"
        return "mdi:hvac"

    @property
    def current_option(self):
        """Return the controller's selected system mode."""
        mode = self._system.get_stored_status().mode
        if mode == RinnaiSystemMode.HEATING:
            return SYSTEM_MODE_HEATING
        if mode == RinnaiSystemMode.COOLING:
            return SYSTEM_MODE_REFRIGERATED_COOLING
        if mode == RinnaiSystemMode.EVAP:
            return SYSTEM_MODE_EVAPORATIVE_COOLING
        return None

    async def async_select_option(self, option: str) -> None:
        """Change equipment mode without changing system power."""
        if option == self.current_option:
            return
        if option == SYSTEM_MODE_HEATING:
            await self._system.set_heater_mode()
            return
        if option == SYSTEM_MODE_REFRIGERATED_COOLING:
            await self._system.set_cooling_mode()
            return
        if option == SYSTEM_MODE_EVAPORATIVE_COOLING:
            await self._system.set_evap_mode()
            return
        raise ValueError(f"Unsupported system mode: {option}")


class RinnaiSelectPresetEntity(RinnaiUpdateMixin, SelectEntity):
    """A preset select entity."""

    def __init__(self, ip_address, name):
        self._host = ip_address
        self._system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
        device_id = (
            str.lower(self.__class__.__name__) + "_" + str.replace(ip_address, ".", "_")
        )

        self._attr_unique_id = device_id
        self._attr_name = name + " Preset Select"
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
    def name(self):
        """Name of the entity."""
        return self._attr_name

    @property
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        return "mdi:format-list-group"

    @property
    def current_option(self):
        """If the switch is currently on or off."""
        # pylint: disable=too-many-return-statements
        if (
            self._system.get_stored_status().unit_status.operating_mode
            == RinnaiOperatingMode.AUTO
        ):
            return PRESET_AUTO
        return PRESET_MANUAL

    @property
    def available(self):
        """Disable whole-unit schedules while MTSP zones own the schedule."""
        state = self._system.get_stored_status()
        return not state.is_multi_set_point or state.mode == RinnaiSystemMode.EVAP

    @property
    def options(self):
        """If the switch is currently on or off."""
        return [PRESET_MANUAL, PRESET_AUTO]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option == PRESET_AUTO:
            await self._system.set_unit_auto()
        else:
            await self._system.set_unit_manual()


class RinnaiCoolingTypeSelectEntity(RinnaiUpdateMixin, SelectEntity):
    """Select refrigerated or evaporative cooling when both are installed."""

    def __init__(self, ip_address, name):
        self._host = ip_address
        self._system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
        self._attr_unique_id = (
            "rinnaicoolingtypeselect_" + str.replace(ip_address, ".", "_")
        )
        self._attr_name = name + " Cooling Type"
        self._attr_device_name = name

    @property
    def device_info(self):
        """Return device information about this controller."""
        return {
            "identifiers": {("rinnai_touch", self._host)},
            "model": "Rinnai Touch Wifi",
            "name": self._attr_device_name,
            "manufacturer": "Rinnai/Brivis",
        }

    @property
    def icon(self):
        """Return the cooling selector icon."""
        return "mdi:air-conditioner"

    @property
    def current_option(self):
        """Return the active cooling implementation."""
        mode = self._system.get_stored_status().mode
        if mode == RinnaiSystemMode.COOLING:
            return COOLING_TYPE_REFRIGERATED
        if mode == RinnaiSystemMode.EVAP:
            return COOLING_TYPE_EVAPORATIVE
        return None

    @property
    def available(self):
        """Expose cooling type while the global mode is cooling."""
        return self._system.get_stored_status().mode in (
            RinnaiSystemMode.COOLING,
            RinnaiSystemMode.EVAP,
        )

    @property
    def options(self):
        """Return installed cooling choices."""
        return [COOLING_TYPE_REFRIGERATED, COOLING_TYPE_EVAPORATIVE]

    async def async_select_option(self, option: str) -> None:
        """Select the active cooling implementation."""
        if option == self.current_option:
            return
        if option == COOLING_TYPE_REFRIGERATED:
            await self._system.set_cooling_mode()
            return
        if option == COOLING_TYPE_EVAPORATIVE:
            await self._system.set_evap_mode()
            return
        raise ValueError(f"Unsupported cooling type: {option}")
