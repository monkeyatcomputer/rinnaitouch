"""Config flow for rinnai-brivis-wifi."""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from pyrinnaitouch import RinnaiSystem

from .const import (
    DOMAIN,
    CONF_TEMP_SENSOR,
    CONF_TEMP_SENSOR_A,
    CONF_TEMP_SENSOR_B,
    CONF_TEMP_SENSOR_C,
    CONF_TEMP_SENSOR_D,
    DEFAULT_NAME,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_TEMP_SENSOR_A): str,
        vol.Optional(CONF_TEMP_SENSOR_B): str,
        vol.Optional(CONF_TEMP_SENSOR_C): str,
        vol.Optional(CONF_TEMP_SENSOR_D): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_TEMP_SENSOR): str,
    }
)


class RinnaiTouchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rinnai Touch."""

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            device_id = "rinnaitouch_" + str.replace(host, ".", "_")
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()
            system: RinnaiSystem = RinnaiSystem.get_instance(host)
            try:
                await system.async_get_status()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                RinnaiSystem.remove_instance(host)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
