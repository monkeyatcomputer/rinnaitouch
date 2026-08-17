"""Tests for read-only controller schedule calendars."""

import asyncio
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from pyrinnaitouch import (
    RinnaiSchedule,
    RinnaiScheduleDay,
    RinnaiScheduleDayGroup,
    RinnaiScheduleEntry,
    RinnaiSchedulePeriod,
    RinnaiSystemMode,
)

from custom_components.rinnaitouch import RinnaiData
from custom_components.rinnaitouch.calendar import schedule_events


def _entry(day, period, start, temperature):
    return RinnaiScheduleEntry(
        day=day,
        period=period,
        start_time=time.fromisoformat(start),
        temperature=temperature,
    )


def test_weekday_calendar_expands_enabled_periods_and_skips_disabled_periods():
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
    assert wake.end == datetime(2026, 8, 17, 17, 30, tzinfo=timezone)
    assert all(not event.summary.startswith("Leave") for event in events)
    assert any(event.summary == "Return · 22 °C" for event in events)


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
        system = SimpleNamespace(
            get_stored_status=lambda: SimpleNamespace(mode=RinnaiSystemMode.EVAP)
        )
        data = RinnaiData(
            hass=hass,
            host="192.0.2.1",
            system=system,
            topology=SimpleNamespace(multi_set_point=False),
            capabilities=set(),
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

    asyncio.run(run_test())


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
