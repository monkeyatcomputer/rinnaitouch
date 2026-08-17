"""Set up main entity."""

# pylint: disable=duplicate-code
import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

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
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from pyrinnaitouch import (
    RinnaiCapabilities,
    RinnaiSchedule,
    RinnaiSystem,
    RinnaiSystemMode,
    RinnaiTopology,
)

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


def schedule_signal(host: str) -> str:
    """Return the dispatcher signal used for schedule cache updates."""
    return f"{DOMAIN}_{host}_schedule_update"


PLATFORMS = [
    Platform.CALENDAR,
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

    data = RinnaiData(
        hass=hass,
        host=ip_address,
        system=system,
        topology=system.get_topology(),
        capabilities=system.get_stored_status().capabilities,
    )
    data.start()

    async def _async_cleanup() -> None:
        """Stop background work before closing the controller transport."""
        await data.async_close()
        system.shutdown()

    async def _async_stop(_event) -> None:
        """Clean up in the same order while Home Assistant is stopping."""
        await _async_cleanup()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    entry.async_on_unload(_async_cleanup)
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
    if data.has_fixed_temperature_unit:
        data.start_schedule_sync()
    # hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    ip_address = entry.data.get(CONF_HOST)
    _LOGGER.debug("Removing controller with IP: %s", ip_address)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    data: RinnaiData | None = hass.data[DOMAIN].get(entry.entry_id)
    if data is not None:
        await data.async_close()
    RinnaiSystem.remove_instance(ip_address)
    hass.data[DOMAIN].pop(entry.entry_id, None)
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

    # pylint: disable=too-many-instance-attributes

    hass: HomeAssistant
    host: str
    system: RinnaiSystem
    topology: RinnaiTopology
    capabilities: RinnaiCapabilities
    schedule_cache: dict[str | None, RinnaiSchedule] = field(
        default_factory=dict, init=False
    )
    schedule_last_sync: datetime | None = field(default=None, init=False)
    schedule_sync_error: str | None = field(default=None, init=False)
    _started: bool = field(default=False, init=False)
    _schedule_sync_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _schedule_sync_task: asyncio.Task | None = field(default=None, init=False)
    _schedule_sync_unsub: Callable[[], None] | None = field(default=None, init=False)

    def start(self) -> None:
        """Bridge library worker-thread callbacks onto the HA event loop."""
        if self._started:
            return
        self.system.subscribe_updates(self._status_updated)
        self.system.register_socket_state_handler(self._connection_updated)
        self._started = True

    async def async_close(self) -> None:
        """Stop background work before detaching the controller transport."""
        if self._schedule_sync_unsub is not None:
            self._schedule_sync_unsub()
            self._schedule_sync_unsub = None
        schedule_task = self._schedule_sync_task
        self._schedule_sync_task = None
        if schedule_task is not None and not schedule_task.done():
            schedule_task.cancel()
            try:
                await schedule_task
            except asyncio.CancelledError:
                pass
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug(
                    "Schedule task failed while the integration was unloading",
                    exc_info=True,
                )
        if self._started:
            self.system.unsubscribe_updates(self._status_updated)
            self.system.unregister_socket_state_handler(self._connection_updated)
            self._started = False

    def start_schedule_sync(self) -> None:
        """Start the non-blocking startup and nightly schedule refreshes."""
        if self._schedule_sync_unsub is None:
            self._schedule_sync_unsub = async_track_time_change(
                self.hass,
                self._nightly_schedule_sync,
                hour=3,
                minute=5,
                second=0,
            )
        self.request_schedule_sync("startup")

    def request_schedule_sync(self, reason: str) -> None:
        """Schedule a refresh without blocking the caller or HA startup."""
        if self._schedule_sync_task is not None and not self._schedule_sync_task.done():
            _LOGGER.debug("Schedule sync already running; ignoring %s request", reason)
            return
        self._schedule_sync_task = self.hass.async_create_task(
            self.async_sync_schedule(),
            name=f"{DOMAIN} schedule sync ({reason})",
        )

    def _nightly_schedule_sync(self, _now: datetime) -> None:
        """Queue the nightly controller schedule refresh."""
        self.request_schedule_sync("nightly")

    async def async_sync_schedule(self) -> None:
        """Read all active controller schedules into an atomic cache."""
        async with self._schedule_sync_lock:
            state = self.system.get_stored_status()
            if state.mode not in (
                RinnaiSystemMode.HEATING,
                RinnaiSystemMode.COOLING,
            ):
                self.schedule_sync_error = (
                    "Schedule sync requires heating or refrigerated cooling mode"
                )
                dispatcher_send(self.hass, schedule_signal(self.host))
                return

            if self.topology.multi_set_point:
                schedule_keys = tuple(
                    zone
                    for zone in self.thermostat_zones
                    if (
                        (capabilities := self.system.get_zone_capabilities(zone))
                        and capabilities.schedule
                    )
                )
            else:
                schedule_keys = (None,)

            if not schedule_keys:
                self.schedule_sync_error = "No schedule-capable zones are available"
                dispatcher_send(self.hass, schedule_signal(self.host))
                return

            try:
                refreshed = {
                    key: await self.system.async_read_schedule(zone=key)
                    for key in schedule_keys
                }
            except Exception as err:  # pylint: disable=broad-except
                self.schedule_sync_error = str(err)
                _LOGGER.warning("Schedule sync failed: %s", err)
                dispatcher_send(self.hass, schedule_signal(self.host))
                return

            self.schedule_cache = refreshed
            self.schedule_last_sync = dt_util.now()
            self.schedule_sync_error = None
            dispatcher_send(self.hass, schedule_signal(self.host))

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
