# Rinnai/Brivis Touch Wifi HASS integration

![Pylint](https://github.com/monkeyatcomputer/rinnaitouch/workflows/Pylint/badge.svg)

## Fork provenance

This repository, [`monkeyatcomputer/rinnaitouch`](https://github.com/monkeyatcomputer/rinnaitouch), is a direct fork of the original [`funtastix/rinnaitouch`](https://github.com/funtastix/rinnaitouch) Home Assistant integration. It retains the original project's Git history, MIT licence, and contributor attribution. Changes made in this fork build on that work.

The original integration credits the following projects as prior art and sources of inspiration. They are acknowledged influences, not the direct GitHub parent of this fork:

- [MyTouch](https://github.com/christhehoff/MyTouch)
- [C-Westin/rinnai_touch_climate](https://github.com/C-Westin/rinnai_touch_climate)
- [jerryzou/rinnai_touch_climate](https://github.com/jerryzou/rinnai_touch_climate)

The implementation also relies on Rinnai's [NBW2API Issue 1.3 protocol documentation](https://hvac-api-docs.s3.us-east-2.amazonaws.com/NBW2API_Iss1.3.pdf).

## :blue_heart: Thanks

Thank you to the maintainers and contributors of the original integration and the related projects listed above for the groundwork on this project.

## :flight_departure: Dependencies

This component depends on the [`monkeyatcomputer/pyrinnaitouch`](https://github.com/monkeyatcomputer/pyrinnaitouch) fork. Home Assistant installs the library directly from the `v0.15.0` Git tag specified in the integration manifest; it does not use the separately published `pyrinnaitouch` package from PyPI.

The matching `pyrinnaitouch` tag must be published before the corresponding integration release. If the tag is missing or inaccessible, Home Assistant cannot install the requirement and the integration will not load.

## Capabilities

Read more details in the [wiki](https://github.com/funtastix/rinnaitouch/wiki) and feel free to send me contributions.

To support the controller and make it work with the HA climate entity, these are the mappings:

#### HVAC modes:
- HVAC_MODE_HEAT → Heating mode (gas heater)
- HVAC_MODE_COOL → Cooling Mode (evap or refrigerated)
- HVAC_MODE_OFF → Unit Off (any operating mode)
- HVAC_MODE_FAN_ONLY - Only circulation fan is on while in heating or cooling mode \
    <b>Note</b>: HVAC_MODE_FAN_ONLY is not available while in  Mode Evaporative where the water pump switch to off achieves a similar result

#### PRESET modes:
- PRESET_MANUAL → Manual mode \
  in Evaporative Mode this allow fan level control, in Heat/Cooler Mode this sets a single target temperature
- PRESET_AUTO → Auto mode \
  in Evaporative Mode this means Comfort Setting, in Heat/Cooler Mode, this means Schedule

There is now internally a cooling selector (preselected, only available if multiple cooling methods installed)
- COOLING_EVAP → Evap mode
- COOLING_COOL → Refrigerated mode

You can manipulate the Fan as required.

There is support for an external temperature sensor, to avoid having 0 degrees in the UI all the time. NC-6 Controllers do not report their temperature. (NC-7s do, and it should work. Please raise an issue if it doesn't)

<b>Cooling mode</b> has been tested by other users and seems to work well, as I do not have cooling.

Support for <b>zones</b> has come a long way, but there is still more testing to be done. I don't have zones myself.

## Zone topology

The integration reads the controller's `CFG.MTSP` flag and zone status. You no longer select installed zones during setup.

| Controller setup | Main climate | Zones A-D | Common zone U |
|---|---|---|---|
| Single set point (`MTSP=N`) | Owns the temperature target and schedule | Damper on/off switches and temperature sensors | Read-only in heating and refrigerated cooling |
| Multi set point / ZonePlus (`MTSP=Y`) | Controls system power and HVAC mode | Independent climate entities with set points and schedules | Read-only in heating and refrigerated cooling |
| Evaporative cooling | Owns comfort level or fan speed | Zone participation controls | Zone participation control when the controller reports U |

The integration adds zone entities when the bridge first reports each zone. A mode change can reveal a different zone list, so the integration keeps the zones seen in earlier modes and adds new entities without a reload. It uses the zone descriptions from the controller for entity names.

Existing config entries can keep their old zone fields. Version 0.14 ignores those fields and uses the bridge status.

## TCP connection

`pyrinnaitouch` maintains one TCP connection per bridge. It reports `CONNECTED` after the bridge sends `*HELLO*` and a valid status frame. The stream parser handles split and combined TCP frames, including sequence rollover from 255 to 0.

Commands use a bounded queue. Each command completes after the bridge returns the matching sequence number. A timeout or disconnect fails the pending command and starts a reconnect with bounded backoff.

## Further Plans

I've recently refactored the code to make it more manageable, but I don't have any further plans, not will I put in the work to integrate into core. HACS is a pretty good place to be, and I'm planning to keep the integraion updated while I have personal use (probably years to come).

## Installation

Use [HACS](https://hacs.xyz/docs/basic/getting_started) to install by adding the repository and downloading any version from 0.9.0.

## Installation for testing

1. Logon to your HA or HASS with SSH
2. Go to the HA 'custom_components' directory within the HA installation path (The directory is in the folder where the 'configuration.yaml' file is located. If this is not available - create this directory).
3. Run `cd custom_components`
4. Run `git clone https://github.com/funtastix/rinnaitouch` within the `custom_components` directory. This will create a new rinnaitouch/custom_components/rinnaitouch subdirectory.
5. Copy everything from rinnaitouch/custom_components/rinnaitouch to rinnaitouch (base of the clone): `cp -r rinnaitouch/custom_components/rinnaitouch/* rinnaitouch/`
6. Restart your HA/HASS service
7. Add your Rinnai Touch either by: HA UI by navigating to "Integrations" -> "Add Integration" -> "Rinnai Touch" (If it is not available, clear your web browser cache to renew the integrations list.)

## Enable Debug

```YAML
logger:
  default: warn
  logs:
    custom_components.rinnaitouch: debug
    custom_components.rinnaitouch.pyrinnaitouch: debug
    pyrinnaitouch: debug
```
