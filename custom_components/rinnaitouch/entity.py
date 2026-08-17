"""Shared entity behavior for the Rinnai Touch integration."""

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from pyrinnaitouch import RinnaiSystem

from . import update_signal


def zone_display_name(system: RinnaiSystem, zone: str) -> str:
    """Return the configured zone description, with a stable fallback."""
    if zone == "U":
        return "Common Zone"
    return system.get_topology().zone_descriptions.get(zone) or f"Zone {zone}"


def setup_discovered_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
    host: str,
    factories: Callable[
        [], Iterable[tuple[str, Callable[[], Entity]]]
    ],
) -> None:
    """Add entities when newly observed zones appear in later operating modes."""
    added: set[str] = set()

    @callback
    def add_new_entities() -> None:
        entities = []
        for key, factory in factories():
            if key in added:
                continue
            added.add(key)
            entities.append(factory())
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, update_signal(host), add_new_entities)
    )
    add_new_entities()


class RinnaiUpdateMixin:
    """Subscribe an entity to status delivered safely on the HA event loop."""

    async def async_added_to_hass(self) -> None:
        """Register for centrally dispatched bridge updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, update_signal(self._host), self.system_updated
            )
        )

    @callback
    def system_updated(self) -> None:
        """Write the newest library status to Home Assistant."""
        self.async_write_ha_state()
