"""Constants used by the rinnai touch component."""

RINNAI = "rinnai"
ICON = "mdi:fan"
DOMAIN = "rinnaitouch"
DEFAULT_NAME = "Rinnai Touch"
UNIT_FAN_SPEED = "ø"
UNIT_COMFORT_LEVEL = "±"
PRESET_AUTO = "Auto"
PRESET_MANUAL = "Manual"
COOLING_EVAP = "Evap"
COOLING_COOL = "Cooling"
COOLING_NONE = "None"
COOLING_TYPE_EVAPORATIVE = "Evaporative"
COOLING_TYPE_REFRIGERATED = "Refrigerated"
SYSTEM_MODE_HEATING = "Heating"
SYSTEM_MODE_REFRIGERATED_COOLING = "Refrigerated Cooling"
SYSTEM_MODE_EVAPORATIVE_COOLING = "Evaporative Cooling"
FAN_ONLY = "Fan Only"
CONF_TEMP_SENSOR = "external_temperature_sensor"
CONF_TEMP_SENSOR_A = "external_temperature_sensor_a"
CONF_TEMP_SENSOR_B = "external_temperature_sensor_b"
CONF_TEMP_SENSOR_C = "external_temperature_sensor_c"
CONF_TEMP_SENSOR_D = "external_temperature_sensor_d"
SET_DATETIME = "set_datetime"
SERVICE_SET_TIME = "rinnai_set_time"
SERVICE_SET_SCHEDULE_PERIOD = "set_schedule_period"
SCHEDULE_DAY = "day"
SCHEDULE_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "weekdays",
    "weekends",
    "all_days",
)
SCHEDULE_ENABLED_ZONES = "enabled_zones"
SCHEDULE_PERIOD = "period"
SCHEDULE_PERIODS = ("wake", "leave", "return", "pre_sleep", "sleep")
SCHEDULE_START_TIME = "start_time"
SCHEDULE_TEMPERATURE = "temperature"
