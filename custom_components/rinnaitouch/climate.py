"""Support for the Rinnai Touch Controller (single-zone gas heater only).

To support the controller and make it work with the HA climate entity,these are the mappings:

HVAC modes:
HVAC_MODE_HEAT -> Heating mode (gas heater)
HVAC_MODE_OFF -> Unit Off
HVAC_MODE_FAN_ONLY - Only circulation fan is on while in heating mode

PRESET modes:
PRESET_MANUAL -> Manual mode
PRESET_AUTO -> Auto mode
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

import voluptuous as vol

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_HOST,
    CONF_NAME,
    UnitOfTemperature,
)
from homeassistant.helpers import (
    config_validation as cv,
    entity_platform,
)

from pyrinnaitouch import (
    TEMP_FAHRENHEIT,
    RinnaiOperatingMode,
    RinnaiSystem,
    RinnaiSystemMode,
    RinnaiSystemStatus,
)

from .const import (
    CONF_TEMP_SENSOR,
    DEFAULT_NAME,
    PRESET_AUTO,
    PRESET_MANUAL,
    SET_DATETIME,
)


SUPPORT_FLAGS_MAIN = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.PRESET_MODE
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.TURN_ON
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=5)

SERVICE_SET_TIME = "rinnai_set_time"


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up climate entities."""
    ip_address = entry.data.get(CONF_HOST)
    name = entry.data.get(CONF_NAME)
    if name == "":
        name = DEFAULT_NAME
    temperature_entity = entry.data.get(CONF_TEMP_SENSOR)
    async_add_entities([RinnaiTouch(hass, ip_address, name, temperature_entity)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_TIME,
        {
            vol.Optional(SET_DATETIME): cv.datetime,
        },
        "set_system_time",
    )
    return True


class RinnaiTouch(ClimateEntity):
    """Main climate entity for the unit."""

    # pylint: disable=too-many-instance-attributes
    def __init__(self, hass, ip_address, name="Rinnai Touch", temperature_entity=None):
        self._host = ip_address
        _LOGGER.info("Set up RinnaiTouch entity %s", ip_address)
        self._system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
        device_id = "rinnaitouch_" + str.replace(ip_address, ".", "_")

        self._attr_unique_id = device_id
        self._attr_name = name
        self._attr_device_name = name

        self._hass = hass
        self._temerature_entity_name = temperature_entity
        self._sensor_temperature = 0
        self.update_external_temperature()

        self._support_flags = SUPPORT_FLAGS_MAIN
        self._enable_turn_on_off_backwards_compatibility = False

        self._TEMPERATURE_STEP = 1
        self._TEMPERATURE_LIMITS = {"min": 8, "max": 30}
        # N-BW2 API: fan only speed level "FL" is 01 - 16
        self._FAN_LIMITS = {"min": 1, "max": 16}
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
        self.update_external_temperature()
        # this very infrequently fails on startup so wrapping in try except
        try:
            self.schedule_update_ha_state()
        except:  # pylint: disable=bare-except
            pass

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return the unique id for this heater."""
        return self._attr_unique_id

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
    def icon(self):
        """Return the icon to use in the frontend for this device."""
        hvac_mode = self.hvac_mode

        if hvac_mode == HVACMode.OFF:
            return "mdi:hvac-off"

        if hvac_mode == HVACMode.FAN_ONLY:
            return "mdi:fan"

        if hvac_mode == HVACMode.HEAT:
            return "mdi:fire"

        return "mdi:hvac"

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        if self._system.get_stored_status().temp_unit == TEMP_FAHRENHEIT:
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if self.hvac_mode == HVACMode.OFF:
            return 0

        state: RinnaiSystemStatus = self._system.get_stored_status()
        if self.hvac_mode == HVACMode.FAN_ONLY:
            return state.unit_status.fan_speed
        return state.unit_status.set_temp

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._TEMPERATURE_STEP

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self.hvac_mode == HVACMode.FAN_ONLY:
            return self._FAN_LIMITS["min"]
        return self._TEMPERATURE_LIMITS["min"]

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self.hvac_mode == HVACMode.FAN_ONLY:
            return self._FAN_LIMITS["max"]
        return self._TEMPERATURE_LIMITS["max"]

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if not hvac_mode == self.hvac_mode:
            if hvac_mode == HVACMode.HEAT:
                # turn whatever the preset is on and put it into manual mode
                await self._system.turn_heater_on()
                await self._system.set_heater_mode()
            elif hvac_mode == HVACMode.OFF:
                await self._system.turn_unit_off()
            elif hvac_mode == HVACMode.FAN_ONLY:
                await self._system.turn_unit_off()
                await self._system.turn_unit_fan_only()

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        if not preset_mode == self.preset_mode:
            if preset_mode == PRESET_AUTO:
                await self._system.set_unit_auto()
            if preset_mode == PRESET_MANUAL:
                await self._system.set_unit_manual()

    async def set_system_time(self, set_datetime: datetime = None):
        """Set the system time."""
        await self._system.set_system_time(set_datetime)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            await self.async_set_target_temperature(kwargs.get(ATTR_TEMPERATURE))

    async def async_set_target_temperature(self, target_temperature):
        """Set the target temperature, or fan speed in fan only mode."""
        target_temperature = int(round(target_temperature))

        if not self.min_temp <= target_temperature <= self.max_temp:
            raise ValueError(
                f"Target temperature ({target_temperature}) must be between "
                f"{self.min_temp} and {self.max_temp}."
            )
        if self.hvac_mode == HVACMode.FAN_ONLY:
            await self._system.set_unit_fanspeed(target_temperature)
        else:
            await self._system.set_unit_temp(target_temperature)

    @property
    def current_temperature(self):
        """Return the current temperature."""
        # NC7 returns temp in XXX -> ZXS -> MT
        # implemented use of an external sensor (optional) which returns 0 if none selected
        temp = self._system.get_stored_status().unit_status.temperature
        _LOGGER.debug("Internal temperature sensor reports: %s", temp)

        if int(temp) < 999:
            return float(temp) / 10
        return self._sensor_temperature

    @property
    def hvac_mode(self):
        """Return current HVAC mode, ie Heat or Off."""
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if not state.system_on or state.mode != RinnaiSystemMode.HEATING:
            return HVACMode.OFF
        if state.unit_status.is_on:
            return HVACMode.HEAT
        # system on, heater mode, but heater off indicates fan only
        return HVACMode.FAN_ONLY

    @property
    def hvac_action(self):
        """Return current HVAC action."""
        state = self._system.get_stored_status()
        if not state.system_on or state.mode != RinnaiSystemMode.HEATING:
            return HVACAction.OFF
        if not state.unit_status.is_on:
            return HVACAction.FAN
        if (
            state.unit_status.gas_valve_active
            or state.unit_status.calling_for_heat
            or state.unit_status.fan_operating
            or state.unit_status.preheating
        ):
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def hvac_modes(self):
        """Return the list of available HVAC modes."""
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.FAN_ONLY]

    @property
    def preset_mode(self):
        """Return current preset mode, ie Auto or Manual."""
        state: RinnaiSystemStatus = self._system.get_stored_status()
        if state.unit_status.operating_mode == RinnaiOperatingMode.AUTO:
            return PRESET_AUTO
        return PRESET_MANUAL

    @property
    def preset_modes(self):
        """Return the list of available preset modes."""
        return [PRESET_AUTO, PRESET_MANUAL]

    def update_external_temperature(self):
        """Update external temperature reading."""
        if self._temerature_entity_name is not None:
            temperature_entity = self._hass.states.get(self._temerature_entity_name)
            if (
                temperature_entity is not None
                and temperature_entity.state != "unavailable"
            ):
                try:
                    self._sensor_temperature = float(temperature_entity.state)
                except ValueError:
                    self._sensor_temperature = 0

    @property
    def available(self):
        return (
            self._connected
            and self._system.get_stored_status().mode != RinnaiSystemMode.NONE
        )

    async def async_will_remove_from_hass(self):
        """Disconnect from the device."""
        self._system.unsubscribe_updates(self.system_updated)
        self._system.unregister_socket_state_handler(self._connection_state_handler)
        _LOGGER.debug("removing entity from hass")
