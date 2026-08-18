"""Tests for read-only controller schedule calendars."""

import asyncio
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from pyrinnaitouch import (
    RinnaiCapabilities,
    RinnaiSchedule,
    RinnaiScheduleDay,
    RinnaiScheduleDayGroup,
    RinnaiScheduleEntry,
    RinnaiSchedulePeriod,
    RinnaiSystemMode,
)

from custom_components.rinnaitouch import RinnaiData
from custom_components.rinnaitouch.calendar import schedule_events
from custom_components.rinnaitouch.entity import setup_discovered_entities


def _entry(day, period, start, temperature):
    return RinnaiScheduleEntry(
        day=day,
        period=period,
        start_time=time.fromisoformat(start),
        temperature=temperature,
    )


def test_weekday_calendar_expands_disabled_periods_as_off():
    schedule = RinnaiSchedule(
        mode=RinnaiSystemMode.HEATING,
        day_group=RinnaiScheduleDayGroup.WEEKDAYS_WEEKENDS,
        temperature_unit="°C",
        zone="B",
        entries=(
            _entry(
                RinnaiScheduleDay.WEEKDAYS,
                RinnaiSchedulePeriod.WAKE,
                "06:00",
                20,
            ),
            _entry(
                RinnaiScheduleDay.WEEKDAYS,
                RinnaiSchedulePeriod.LEAVE,
                "08:00",
                0,
            ),
            _entry(
                RinnaiScheduleDay.WEEKDAYS,
                RinnaiSchedulePeriod.RETURN,
                "17:30",
                22,
            ),
            _entry(
                RinnaiScheduleDay.WEEKDAYS,
                RinnaiSchedulePeriod.SLEEP,
                "22:30",
                17,
            ),
            _entry(
                RinnaiScheduleDay.WEEKENDS,
                RinnaiSchedulePeriod.WAKE,
                "08:00",
                20,
            ),
            _entry(
                RinnaiScheduleDay.WEEKENDS,
                RinnaiSchedulePeriod.SLEEP,
                "23:00",
                17,
            ),
        ),
    )
    timezone = ZoneInfo("Australia/Sydney")
    start = datetime(2026, 8, 17, 0, 0, tzinfo=timezone)  # Monday
    end = datetime(2026, 8, 18, 0, 0, tzinfo=timezone)

    events = schedule_events(schedule, start, end, timezone)

    wake = next(event for event in events if event.summary.startswith("Wake"))
    assert wake.start == datetime(2026, 8, 17, 6, 0, tzinfo=timezone)
    assert wake.end == datetime(2026, 8, 17, 8, 0, tzinfo=timezone)
    leave = next(event for event in events if event.summary.startswith("Leave"))
    assert leave.summary == "Leave · Off"
    assert leave.start == datetime(2026, 8, 17, 8, 0, tzinfo=timezone)
    assert leave.end == datetime(2026, 8, 17, 17, 30, tzinfo=timezone)
    assert "zone is off" in leave.description
    assert any(event.summary == "Return · 22 °C" for event in events)


def test_calendar_shows_disabled_sleep_period_overnight():
    schedule = RinnaiSchedule(
        mode=RinnaiSystemMode.HEATING,
        day_group=RinnaiScheduleDayGroup.ALL_DAYS,
        temperature_unit="°C",
        zone="A",
        entries=(
            _entry(
                RinnaiScheduleDay.ALL_DAYS,
                RinnaiSchedulePeriod.WAKE,
                "06:25",
                19,
            ),
            _entry(
                RinnaiScheduleDay.ALL_DAYS,
                RinnaiSchedulePeriod.PRE_SLEEP,
                "21:45",
                18,
            ),
            _entry(
                RinnaiScheduleDay.ALL_DAYS,
                RinnaiSchedulePeriod.SLEEP,
                "22:15",
                0,
            ),
        ),
    )
    timezone = ZoneInfo("Australia/Sydney")

    events = schedule_events(
        schedule,
        datetime(2026, 8, 18, 0, 0, tzinfo=timezone),
        datetime(2026, 8, 19, 0, 0, tzinfo=timezone),
        timezone,
    )

    sleep_events = [event for event in events if event.summary == "Sleep · Off"]
    assert [(event.start, event.end) for event in sleep_events] == [
        (
            datetime(2026, 8, 17, 22, 15, tzinfo=timezone),
            datetime(2026, 8, 18, 6, 25, tzinfo=timezone),
        ),
        (
            datetime(2026, 8, 18, 22, 15, tzinfo=timezone),
            datetime(2026, 8, 19, 6, 25, tzinfo=timezone),
        ),
    ]
    pre_sleep = next(
        event
        for event in events
        if event.start == datetime(2026, 8, 18, 21, 45, tzinfo=timezone)
    )
    assert pre_sleep.summary == "Pre-Sleep · 18 °C"
    assert pre_sleep.end == datetime(2026, 8, 18, 22, 15, tzinfo=timezone)


def test_single_set_point_calendar_describes_enabled_zones():
    schedule = RinnaiSchedule(
        mode=RinnaiSystemMode.HEATING,
        day_group=RinnaiScheduleDayGroup.ALL_DAYS,
        temperature_unit="°C",
        entries=(
            RinnaiScheduleEntry(
                day=RinnaiScheduleDay.ALL_DAYS,
                period=RinnaiSchedulePeriod.WAKE,
                start_time=time(6, 0),
                temperature=20,
                enabled_zones=frozenset({"A", "B"}),
            ),
            _entry(
                RinnaiScheduleDay.ALL_DAYS,
                RinnaiSchedulePeriod.SLEEP,
                "22:00",
                17,
            ),
        ),
    )
    timezone = ZoneInfo("Australia/Sydney")

    events = schedule_events(
        schedule,
        datetime(2026, 8, 17, 0, 0, tzinfo=timezone),
        datetime(2026, 8, 18, 0, 0, tzinfo=timezone),
        timezone,
    )

    wake = next(event for event in events if event.summary.startswith("Wake"))
    assert "Enabled zones: A, B" in wake.description


def test_calendar_uses_home_timezone_across_dst_change():
    schedule = RinnaiSchedule(
        mode=RinnaiSystemMode.HEATING,
        day_group=RinnaiScheduleDayGroup.ALL_DAYS,
        temperature_unit="°C",
        entries=(
            _entry(
                RinnaiScheduleDay.ALL_DAYS,
                RinnaiSchedulePeriod.WAKE,
                "06:00",
                20,
            ),
            _entry(
                RinnaiScheduleDay.ALL_DAYS,
                RinnaiSchedulePeriod.SLEEP,
                "22:00",
                17,
            ),
        ),
    )
    home_timezone = ZoneInfo("Australia/Sydney")
    utc = ZoneInfo("UTC")

    events = schedule_events(
        schedule,
        datetime(2026, 10, 3, 14, 0, tzinfo=utc),
        datetime(2026, 10, 4, 14, 0, tzinfo=utc),
        home_timezone,
    )

    wake = next(
        event
        for event in events
        if event.start.date().isoformat() == "2026-10-04"
        and event.summary.startswith("Wake")
    )
    assert wake.start.hour == 6
    assert wake.start.utcoffset() == timedelta(hours=11)


def test_schedule_sync_is_queued_in_background_and_registered_for_local_night(
    monkeypatch,
):
    """Startup must not await the controller scan and nightly sync uses HA local time."""

    async def run_test():
        tracker = {}
        queued = {}

        def track_time_change(hass, action, **kwargs):
            tracker.update(kwargs)
            tracker["action"] = action
            return lambda: None

        def create_task(coro, *, name):
            queued["name"] = name
            return asyncio.create_task(coro, name=name)

        monkeypatch.setattr(
            "custom_components.rinnaitouch.async_track_time_change",
            track_time_change,
        )
        monkeypatch.setattr(
            "custom_components.rinnaitouch.dispatcher_send", lambda *_args: None
        )
        hass = SimpleNamespace(async_create_task=create_task)
        schedule = RinnaiSchedule(
            mode=RinnaiSystemMode.HEATING,
            day_group=RinnaiScheduleDayGroup.ALL_DAYS,
            entries=(),
            temperature_unit="°C",
        )

        async def read_schedule(*, zone):
            assert zone is None
            return schedule

        system = SimpleNamespace(
            get_stored_status=lambda: SimpleNamespace(mode=RinnaiSystemMode.HEATING),
            async_read_schedule=read_schedule,
        )
        data = RinnaiData(
            hass=hass,
            host="192.0.2.1",
            system=system,
            topology=SimpleNamespace(multi_set_point=False),
            capabilities={RinnaiCapabilities.HEATER},
        )

        data.start_schedule_sync()

        assert queued["name"] == "rinnaitouch schedule sync (startup)"
        assert tracker == {
            "hour": 3,
            "minute": 5,
            "second": 0,
            "action": data._nightly_schedule_sync,
        }
        assert data._schedule_sync_task is not None
        await data._schedule_sync_task
        assert data.schedule_cache == {None: schedule}

    asyncio.run(run_test())


def test_schedule_sync_waits_for_operating_topology_then_runs_once(monkeypatch):
    """A SYST-only startup must defer, not lose, the first schedule refresh."""

    async def run_test():
        tracked = {}
        reads = []
        state = SimpleNamespace(mode=RinnaiSystemMode.NONE)
        zones = set()
        schedule = RinnaiSchedule(
            mode=RinnaiSystemMode.HEATING,
            day_group=RinnaiScheduleDayGroup.ALL_DAYS,
            entries=(),
            temperature_unit="°C",
            zone="A",
        )

        def track_time_change(_hass, action, **_kwargs):
            tracked["action"] = action
            return lambda: None

        async def read_schedule(*, zone):
            reads.append(zone)
            return schedule

        system = SimpleNamespace(
            get_stored_status=lambda: state,
            get_zone_capabilities=lambda zone: SimpleNamespace(
                schedule=zone in zones
            ),
            async_read_schedule=read_schedule,
        )
        topology = SimpleNamespace(
            multi_set_point=True,
            all_observed_zones=lambda: set(zones),
        )
        loop = asyncio.get_running_loop()
        hass = SimpleNamespace(
            loop=loop,
            async_create_task=lambda coro, *, name: loop.create_task(
                coro, name=name
            ),
        )
        monkeypatch.setattr(
            "custom_components.rinnaitouch.async_track_time_change",
            track_time_change,
        )
        monkeypatch.setattr(
            "custom_components.rinnaitouch.dispatcher_send", lambda *_args: None
        )
        data = RinnaiData(
            hass=hass,
            host="192.0.2.1",
            system=system,
            topology=topology,
            capabilities={RinnaiCapabilities.HEATER},
        )

        data.start_schedule_sync()
        assert data._schedule_sync_task is None
        assert reads == []

        state.mode = RinnaiSystemMode.HEATING
        zones.add("A")
        data._status_updated()
        await asyncio.sleep(0)
        assert data._schedule_sync_task is not None
        await data._schedule_sync_task

        assert reads == ["A"]
        assert data.schedule_cache == {"A": schedule}

        data._status_updated()
        await asyncio.sleep(0)
        assert reads == ["A"]

    asyncio.run(run_test())


def test_discovered_entities_are_added_when_a_zone_appears(monkeypatch):
    """An initially empty MTSP topology must not permanently lose zone entities."""
    callbacks = []
    unloads = []
    added = []
    zones = set()

    def connect(_hass, _signal, callback):
        callbacks.append(callback)
        return lambda: None

    monkeypatch.setattr(
        "custom_components.rinnaitouch.entity.async_dispatcher_connect", connect
    )
    entry = SimpleNamespace(async_on_unload=unloads.append)

    setup_discovered_entities(
        SimpleNamespace(),
        entry,
        lambda entities: added.extend(entities),
        "192.0.2.1",
        lambda: (
            (f"zone_schedule_calendar_{zone}", lambda zone=zone: zone)
            for zone in sorted(zones)
        ),
    )

    assert added == []
    zones.add("A")
    callbacks[0]()
    callbacks[0]()

    assert added == ["A"]
    assert len(unloads) == 1


def test_async_close_awaits_schedule_task_cleanup():
    """Transport shutdown must not race an active schedule programming session."""

    async def run_test():
        cleanup_complete = False

        async def schedule_scan():
            nonlocal cleanup_complete
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleanup_complete = True

        data = RinnaiData(
            hass=SimpleNamespace(),
            host="192.0.2.1",
            system=SimpleNamespace(),
            topology=SimpleNamespace(multi_set_point=False),
            capabilities=set(),
        )
        data._schedule_sync_task = asyncio.create_task(schedule_scan())
        await asyncio.sleep(0)

        await data.async_close()

        assert cleanup_complete
        assert data._schedule_sync_task is None

    asyncio.run(run_test())
