"""Read-only calendars backed by the controller's cached schedule."""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from pyrinnaitouch import (
    RinnaiSchedule,
    RinnaiScheduleDay,
    RinnaiScheduleEntry,
    RinnaiSchedulePeriod,
)

from . import RinnaiData, schedule_signal
from .const import DEFAULT_NAME, DOMAIN
from .entity import setup_discovered_entities, zone_display_name

_PERIOD_NAMES = {
    RinnaiSchedulePeriod.WAKE: "Wake",
    RinnaiSchedulePeriod.LEAVE: "Leave",
    RinnaiSchedulePeriod.RETURN: "Return",
    RinnaiSchedulePeriod.PRE_SLEEP: "Pre-Sleep",
    RinnaiSchedulePeriod.SLEEP: "Sleep",
}

_WEEKDAY_DAYS = {
    0: RinnaiScheduleDay.MONDAY,
    1: RinnaiScheduleDay.TUESDAY,
    2: RinnaiScheduleDay.WEDNESDAY,
    3: RinnaiScheduleDay.THURSDAY,
    4: RinnaiScheduleDay.FRIDAY,
    5: RinnaiScheduleDay.SATURDAY,
    6: RinnaiScheduleDay.SUNDAY,
}


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up read-only schedule calendars."""
    host = entry.data.get(CONF_HOST)
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME
    data: RinnaiData = hass.data[DOMAIN][entry.entry_id]
    if not data.has_fixed_temperature_unit:
        return True
    home_timezone = (
        dt_util.get_time_zone(hass.config.time_zone) or dt_util.DEFAULT_TIME_ZONE
    )

    if not data.topology.multi_set_point:
        async_add_entities(
            [RinnaiScheduleCalendar(host, name, data, home_timezone=home_timezone)]
        )
        return True

    setup_discovered_entities(
        hass,
        entry,
        async_add_entities,
        host,
        lambda: (
            (
                f"zone_schedule_calendar_{zone}",
                lambda zone=zone: RinnaiScheduleCalendar(
                    host, name, data, zone, home_timezone
                ),
            )
            for zone in data.thermostat_zones
        ),
    )
    return True


def _entry_applies(entry: RinnaiScheduleEntry, event_date: date) -> bool:
    """Return whether a grouped controller entry applies to a date."""
    if entry.day == RinnaiScheduleDay.ALL_DAYS:
        return True
    if entry.day == RinnaiScheduleDay.WEEKDAYS:
        return event_date.weekday() < 5
    if entry.day == RinnaiScheduleDay.WEEKENDS:
        return event_date.weekday() >= 5
    return entry.day == _WEEKDAY_DAYS[event_date.weekday()]


def schedule_events(
    schedule: RinnaiSchedule,
    start_date: datetime,
    end_date: datetime,
    home_timezone: tzinfo,
) -> list[CalendarEvent]:
    """Expand a recurring controller schedule into calendar events."""
    # pylint: disable=too-many-locals
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=home_timezone)
    else:
        start_date = start_date.astimezone(home_timezone)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=home_timezone)
    else:
        end_date = end_date.astimezone(home_timezone)
    if end_date <= start_date:
        return []
    first_date = start_date.date() - timedelta(days=7)
    last_date = end_date.date() + timedelta(days=7)
    starts: dict[datetime, RinnaiScheduleEntry] = {}

    event_date = first_date
    while event_date <= last_date:
        for entry in schedule.entries:
            if _entry_applies(entry, event_date):
                starts[
                    datetime.combine(
                        event_date, entry.start_time, tzinfo=home_timezone
                    )
                ] = entry
        event_date += timedelta(days=1)

    ordered = sorted(starts.items())
    events = []
    for index, (event_start, entry) in enumerate(ordered[:-1]):
        event_end = ordered[index + 1][0]
        if event_end <= start_date or event_start >= end_date:
            continue
        period_name = _PERIOD_NAMES[entry.period]
        setpoint = (
            f"{entry.temperature} {schedule.temperature_unit}"
            if entry.enabled
            else "Off"
        )
        summary = f"{period_name} · {setpoint}"
        description = (
            f"{period_name} controller schedule period in "
            f"{schedule.mode.name.lower()} mode."
        )
        if not entry.enabled:
            description += " The zone is off for this period."
        if entry.enabled_zones:
            description += " Enabled zones: " + ", ".join(
                sorted(entry.enabled_zones)
            )
        events.append(
            CalendarEvent(
                start=event_start,
                end=event_end,
                summary=summary,
                description=description,
                uid=(
                    f"{schedule.mode.name}:{schedule.zone or 'main'}:"
                    f"{event_start.isoformat()}:{entry.period.value}"
                ),
            )
        )
    return events


class RinnaiScheduleCalendar(CalendarEntity):  # pylint: disable=abstract-method
    """A read-only calendar generated from the cached controller schedule."""

    _attr_icon = "mdi:calendar-clock"
    _attr_supported_features = 0

    def __init__(
        self,
        host: str,
        name: str,
        data: RinnaiData,
        zone: str | None = None,
        home_timezone: tzinfo = dt_util.DEFAULT_TIME_ZONE,
    ) -> None:
        self._host = host
        self._data = data
        self._zone = zone
        self._home_timezone = home_timezone
        host_id = host.replace(".", "_")
        suffix = zone.lower() if zone else "main"
        self._attr_unique_id = f"rinnaischedulecalendar_{suffix}_{host_id}"
        if zone:
            zone_name = zone_display_name(data.system, zone)
            self._attr_name = f"{name} {zone_name} Schedule"
        else:
            self._attr_name = f"{name} Schedule"
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
    def available(self) -> bool:
        """Return whether at least one schedule has been synchronized."""
        return self._zone in self._data.schedule_cache

    @property
    def extra_state_attributes(self):
        """Expose synchronization and controller schedule metadata."""
        schedule = self._data.schedule_cache.get(self._zone)
        return {
            "last_sync": self._data.schedule_last_sync.isoformat()
            if self._data.schedule_last_sync
            else None,
            "sync_error": self._data.schedule_sync_error,
            "controller_mode": schedule.mode.name.lower() if schedule else None,
            "day_grouping": schedule.day_group.name.lower() if schedule else None,
        }

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next cached schedule event."""
        schedule = self._data.schedule_cache.get(self._zone)
        if schedule is None:
            return None
        now = datetime.now(self._home_timezone)
        events = schedule_events(
            schedule,
            now - timedelta(days=1),
            now + timedelta(days=8),
            self._home_timezone,
        )
        return next((event for event in events if event.end > now), None)

    async def async_get_events(
        self,
        hass,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events from memory without querying the controller."""
        schedule = self._data.schedule_cache.get(self._zone)
        if schedule is None:
            return []
        return schedule_events(
            schedule, start_date, end_date, self._home_timezone
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to completed schedule cache refreshes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                schedule_signal(self._host),
                self._schedule_updated,
            )
        )

    @callback
    def _schedule_updated(self) -> None:
        """Publish the latest cached schedule."""
        self.async_write_ha_state()
