"""Set up main entity."""

# pylint: disable=duplicate-code
import logging
from dataclasses import dataclass, field

import voluptuous as vol

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers import entity_registry as er
from homeassistant.const import Platform
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import dispatcher_send

from pyrinnaitouch import RinnaiCapabilities, RinnaiSystem, RinnaiTopology

from .const import (
    DOMAIN,
    SCHEDULE_DAY,
    SCHEDULE_DAYS,
    SCHEDULE_ENABLED_ZONES,
    SCHEDULE_PERIOD,
    SCHEDULE_PERIODS,
    SCHEDULE_START_TIME,
    SCHEDULE_TEMPERATURE,
    SERVICE_SET_SCHEDULE_PERIOD,
    SERVICE_SET_TIME,
    SET_DATETIME,
)

_LOGGER = logging.getLogger(__name__)


def update_signal(host: str) -> str:
    """Return the dispatcher signal used for status updates from one bridge."""
    return f"{DOMAIN}_{host}_status_update"


def connection_signal(host: str) -> str:
    """Return the dispatcher signal used for connection updates from one bridge."""
    return f"{DOMAIN}_{host}_connection_update"


PLATFORMS = [
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SELECT,
]


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register integration-level entity services."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_TIME,
        entity_domain=CLIMATE_DOMAIN,
        schema={vol.Optional(SET_DATETIME): cv.datetime},
        func="set_system_time",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_SCHEDULE_PERIOD,
        entity_domain=CLIMATE_DOMAIN,
        schema={
            vol.Required(SCHEDULE_DAY): vol.In(SCHEDULE_DAYS),
            vol.Required(SCHEDULE_PERIOD): vol.In(SCHEDULE_PERIODS),
            vol.Required(SCHEDULE_START_TIME): cv.time,
            vol.Required(SCHEDULE_TEMPERATURE): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=30)
            ),
            vol.Optional(SCHEDULE_ENABLED_ZONES): vol.All(
                cv.ensure_list,
                [vol.In(("A", "B", "C", "D"))],
            ),
        },
        func="set_schedule_period",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up the rinnaitouch integration from a config entry."""

    ip_address = entry.data.get(CONF_HOST)
    _LOGGER.debug("Get controller with IP: %s", ip_address)
    system: RinnaiSystem = RinnaiSystem.get_instance(ip_address)
    try:
        await system.async_get_status(timeout=45)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error("Get controller error: %s", err)
        RinnaiSystem.remove_instance(ip_address)
        raise ConfigEntryNotReady from err

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, system.shutdown)
    )
    data = RinnaiData(
        hass=hass,
        host=ip_address,
        system=system,
        topology=system.get_topology(),
        capabilities=system.get_stored_status().capabilities,
    )
    data.start()
    entry.async_on_unload(data.close)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    # Remove entity registry entries superseded by controls that better match
    # the controller topology.
    entity_registry = er.async_get(hass)
    host_id = str.replace(ip_address, ".", "_")
    obsolete_mode_switches = {
        f"rinnaicoolingmodeswitch_{host_id}",
        f"rinnaievapmodeswitch_{host_id}",
        f"rinnaiheatermodeswitch_{host_id}",
    }
    obsolete_mtsp_controls = {
        f"rinnaitouch_{host_id}",
        f"rinnaiautoswitch_{host_id}",
        f"rinnaicoolingtypeselect_{host_id}",
        f"rinnaiselectpresetentity_{host_id}",
    }
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if (
            entity_entry.entity_id.startswith("button.")
            and entity_entry.platform == DOMAIN
        ) or (
            entity_entry.platform == DOMAIN
            and (
                entity_entry.unique_id in obsolete_mode_switches
                or (
                    data.topology.multi_set_point
                    and entity_entry.unique_id in obsolete_mtsp_controls
                )
            )
        ):
            entity_registry.async_remove(entity_entry.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    ip_address = entry.data.get(CONF_HOST)
    _LOGGER.debug("Removing controller with IP: %s", ip_address)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    hass.data[DOMAIN].pop(entry.entry_id)
    RinnaiSystem.remove_instance(ip_address)
    _LOGGER.debug("Controller with IP: %s removed", ip_address)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    # pylint: disable=unused-argument
    return True


@dataclass
class RinnaiData:
    """Data for the Rinnai Touch integration."""

    hass: HomeAssistant
    host: str
    system: RinnaiSystem
    topology: RinnaiTopology
    capabilities: RinnaiCapabilities
    _started: bool = field(default=False, init=False)

    def start(self) -> None:
        """Bridge library worker-thread callbacks onto the HA event loop."""
        if self._started:
            return
        self.system.subscribe_updates(self._status_updated)
        self.system.register_socket_state_handler(self._connection_updated)
        self._started = True

    def close(self) -> None:
        """Detach callbacks registered for this config entry."""
        if not self._started:
            return
        self.system.unsubscribe_updates(self._status_updated)
        self.system.unregister_socket_state_handler(self._connection_updated)
        self._started = False

    def _status_updated(self) -> None:
        dispatcher_send(self.hass, update_signal(self.host))

    def _connection_updated(self, state) -> None:
        dispatcher_send(self.hass, connection_signal(self.host), state)

    @property
    def zones(self) -> tuple[str, ...]:
        """Return all zones discovered from the bridge status."""
        return tuple(sorted(self.topology.all_observed_zones()))

    @property
    def thermostat_zones(self) -> tuple[str, ...]:
        """Return zones that own set points on an MTSP installation."""
        if not self.topology.multi_set_point:
            return ()
        return tuple(zone for zone in self.zones if zone != "U")

    @property
    def enable_zones(self) -> tuple[str, ...]:
        """Return zones represented by standalone enable switches."""
        if self.topology.multi_set_point:
            return ("U",) if "U" in self.zones and self.has_evap else ()
        return tuple(zone for zone in self.zones if zone != "U" or self.has_evap)

    @property
    def temperature_zones(self) -> tuple[str, ...]:
        """Return zones that report a measured room temperature."""
        if self.topology.multi_set_point:
            return self.thermostat_zones
        if (
            RinnaiCapabilities.HEATER in self.capabilities
            or RinnaiCapabilities.COOLER in self.capabilities
        ):
            return self.zones
        return ()

    @property
    def has_evap(self) -> bool:
        """Return whether evaporative cooling is installed."""
        return RinnaiCapabilities.EVAP in self.capabilities

    @property
    def has_fixed_temperature_unit(self) -> bool:
        """Return whether heating or refrigerated cooling is installed."""
        return (
            RinnaiCapabilities.HEATER in self.capabilities
            or RinnaiCapabilities.COOLER in self.capabilities
        )
