"""Exercise entry lifecycle with fake HA and bridge objects, without a live heater.

Load the entry functions from their AST so these focused tests can run without
installing Home Assistant on the development machine.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


SOURCE = Path(__file__).parents[1] / "custom_components/rinnaitouch/__init__.py"


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    """A reload must release exactly the connection owned by that entry."""

    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        functions = ast.Module(
            body=[node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)],
            type_ignores=[],
        )
        self.system = Mock()
        self.library = Mock()
        self.library.get_instance.return_value = self.system
        self.unsubscribe = Mock()
        self.hass = SimpleNamespace(
            data={},
            bus=SimpleNamespace(async_listen_once=Mock(return_value=self.unsubscribe)),
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
            ),
        )
        self.executor_calls = []

        async def executor(func, *args):
            self.executor_calls.append((func, args))
            return func(*args)

        self.hass.async_add_executor_job = executor
        self.entry = SimpleNamespace(data={"host": "192.0.2.1"}, entry_id="heater")
        namespace = dict(
            HomeAssistant=object, ConfigEntry=object, DeviceEntry=object,
            RinnaiSystem=self.library, RinnaiData=SimpleNamespace,
            CONF_HOST="host", DOMAIN="rinnaitouch", PLATFORMS=[],
            EVENT_HOMEASSISTANT_STOP="stop", ConfigEntryNotReady=RuntimeError,
            _LOGGER=Mock(),
        )
        exec(compile(functions, str(SOURCE), "exec"), namespace)
        self.setup = namespace["async_setup_entry"]
        self.unload = namespace["async_unload_entry"]

    async def test_failed_unload_keeps_connection_and_listener(self):
        await self.setup(self.hass, self.entry)
        self.hass.config_entries.async_unload_platforms.return_value = False
        self.assertFalse(await self.unload(self.hass, self.entry))
        self.library.remove_instance.assert_not_called()
        self.unsubscribe.assert_not_called()
        self.assertIn("heater", self.hass.data["rinnaitouch"])

    async def test_successful_unload_cleans_up_in_executor(self):
        await self.setup(self.hass, self.entry)
        self.assertTrue(await self.unload(self.hass, self.entry))
        self.library.remove_instance.assert_called_once_with("192.0.2.1")
        self.unsubscribe.assert_called_once_with()
        self.assertEqual(self.hass.data["rinnaitouch"], {})
        self.assertEqual(self.executor_calls[-1][0], self.library.remove_instance)

    async def test_stop_listener_accepts_event_and_releases_instance(self):
        await self.setup(self.hass, self.entry)
        callback = self.hass.bus.async_listen_once.call_args.args[1]
        await callback(SimpleNamespace(event_type="stop"))
        self.library.remove_instance.assert_called_once_with("192.0.2.1")

    async def test_forwarding_failure_releases_connection(self):
        self.hass.config_entries.async_forward_entry_setups.side_effect = ValueError("failed")
        with self.assertRaises(ValueError):
            await self.setup(self.hass, self.entry)
        self.library.remove_instance.assert_called_once_with("192.0.2.1")
        self.unsubscribe.assert_called_once_with()
        self.assertEqual(self.hass.data["rinnaitouch"], {})

    async def test_connection_setup_failure_releases_instance(self):
        self.system.get_status.side_effect = ConnectionError("offline")
        with self.assertRaises(RuntimeError):
            await self.setup(self.hass, self.entry)
        self.library.remove_instance.assert_called_once_with("192.0.2.1")
        self.hass.bus.async_listen_once.assert_not_called()


class ClimateConnectionTests(unittest.IsolatedAsyncioTestCase):
    """Cached heater status must not hide a broken connection."""

    def setUp(self):
        source = SOURCE.with_name("climate.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        climate = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                       and node.name == "RinnaiTouch")
        methods = {"_connection_state_handler", "available", "async_will_remove_from_hass"}
        climate.bases = []
        climate.body = [node for node in climate.body if getattr(node, "name", None) in methods]
        namespace = {"RinnaiSystemMode": SimpleNamespace(NONE="NONE"), "_LOGGER": Mock()}
        exec(compile(ast.Module(body=[climate], type_ignores=[]), str(source), "exec"), namespace)
        self.entity = namespace["RinnaiTouch"]()
        self.entity.hass = object()
        self.entity._system = Mock()
        self.entity._system.get_stored_status.return_value.mode = "HEATING"
        self.entity.schedule_update_ha_state = Mock()
        self.entity.system_updated = Mock()

    async def test_disconnect_and_reconnect_change_availability(self):
        for state, available in [("CONNECTED", True), ("TIMEOUT", False),
                                 ("WAITING", False), ("CONNECTED", True)]:
            self.entity._connection_state_handler(SimpleNamespace(name=state))
            self.assertEqual(self.entity.available, available)
        self.assertEqual(self.entity.schedule_update_ha_state.call_count, 4)

    async def test_removal_unregisters_both_callbacks(self):
        await self.entity.async_will_remove_from_hass()
        self.entity._system.unsubscribe_updates.assert_called_once_with(self.entity.system_updated)
        self.entity._system.unregister_socket_state_handler.assert_called_once_with(
            self.entity._connection_state_handler
        )


class EntityConnectionTests(unittest.IsolatedAsyncioTestCase):
    """Switches, select and button follow the connection like the climate entity."""

    def load(self, filename, *classes):
        """Load the named classes, keeping only base classes that are among them."""
        source = SOURCE.with_name(filename)
        tree = ast.parse(source.read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name in classes]
        for node in nodes:
            node.bases = [base for base in node.bases
                          if isinstance(base, ast.Name) and base.id in classes]
        system = Mock()
        status = system.get_stored_status.return_value
        status.mode = "HEATING"
        status.system_on = True
        status.unit_status.operating_mode = "AUTO"
        status.unit_status.is_on = False
        namespace = {
            "RinnaiSystem": SimpleNamespace(get_instance=Mock(return_value=system)),
            "RinnaiSystemStatus": object,
            "RinnaiSystemMode": SimpleNamespace(HEATING="HEATING"),
            "RinnaiOperatingMode": SimpleNamespace(AUTO="AUTO"),
            "PRESET_AUTO": "Auto", "PRESET_MANUAL": "Manual",
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
        return namespace

    def make(self, cls):
        entity = cls("192.0.2.1", "Heater")
        entity.hass = object()
        entity.schedule_update_ha_state = Mock()
        return entity

    def assert_follows_connection(self, entity):
        for state, available in [("CONNECTED", True), ("TIMEOUT", False),
                                 ("WAITING", False), ("CONNECTED", True)]:
            entity._connection_state_handler(SimpleNamespace(name=state))
            self.assertEqual(entity.available, available, state)

    def test_switches_follow_connection(self):
        ns = self.load("switch.py", "RinnaiExtraEntity", "RinnaiOnOffSwitch",
                       "RinnaiAutoSwitch", "RinnaiCircFanSwitch")
        for name in ("RinnaiOnOffSwitch", "RinnaiAutoSwitch", "RinnaiCircFanSwitch"):
            with self.subTest(name):
                self.assert_follows_connection(self.make(ns[name]))

    def test_switch_conditions_still_apply_when_connected(self):
        ns = self.load("switch.py", "RinnaiExtraEntity", "RinnaiAutoSwitch",
                       "RinnaiCircFanSwitch")
        auto = self.make(ns["RinnaiAutoSwitch"])
        auto._connection_state_handler(SimpleNamespace(name="CONNECTED"))
        auto._system.get_stored_status.return_value.system_on = False
        self.assertFalse(auto.available)
        fan = self.make(ns["RinnaiCircFanSwitch"])
        fan._connection_state_handler(SimpleNamespace(name="CONNECTED"))
        fan._system.get_stored_status.return_value.unit_status.is_on = True
        fan._system.get_stored_status.return_value.system_on = True
        self.assertFalse(fan.available)

    def test_select_follows_connection(self):
        ns = self.load("select.py", "RinnaiSelectPresetEntity")
        self.assert_follows_connection(self.make(ns["RinnaiSelectPresetEntity"]))

    def test_button_follows_connection_and_auto_mode(self):
        ns = self.load("button.py", "RinnaiButtonEntity", "RinnaiAdvanceButton")
        button = self.make(ns["RinnaiAdvanceButton"])
        self.assert_follows_connection(button)
        button._system.get_stored_status.return_value.unit_status.operating_mode = "MANUAL"
        self.assertFalse(button.available)

    async def test_removal_unregisters_both_callbacks(self):
        ns = self.load("switch.py", "RinnaiExtraEntity", "RinnaiOnOffSwitch")
        entity = self.make(ns["RinnaiOnOffSwitch"])
        await entity.async_will_remove_from_hass()
        entity._system.unsubscribe_updates.assert_called_once_with(entity.system_updated)
        entity._system.unregister_socket_state_handler.assert_called_once_with(
            entity._connection_state_handler
        )


if __name__ == "__main__":
    unittest.main()
