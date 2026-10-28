# Rinnai/Brivis Touch Wifi – Heater Only

![Pylint](https://github.com/chickymonkey/rinnaitouch/workflows/Pylint/badge.svg)

A Home Assistant custom integration for a **single-zone Rinnai/Brivis gas heater** controlled through an **N-BW2 Networker Bridge (WiFi)**.

This is a slimmed-down fork of [funtastix/rinnaitouch](https://github.com/funtastix/rinnaitouch). Cooling (add-on), evaporative cooling and zone support have been removed so that the integration only covers what a heater-only system needs. It also uses a patched copy of the `pyrinnaitouch` library that fixes control being lost after the integration has been running for a while.

If you have cooling, evaporative cooling or zones, use the [original integration](https://github.com/funtastix/rinnaitouch) instead.

## Authors

- **chickymonkey** – maintainer of this heater-only fork and of the patched [pyrinnaitouch fork](https://github.com/chickymonkey/pyrinnaitouch)
- **[funtastix](https://github.com/funtastix)** – original author of [rinnaitouch](https://github.com/funtastix/rinnaitouch) and [pyrinnaitouch](https://github.com/funtastix/pyrinnaitouch)

The original work was inspired by [MyTouch](https://github.com/christhehoff/MyTouch), [@C-Westin](https://github.com/C-Westin/rinnai_touch_climate) and [@jerryzou](https://github.com/jerryzou/rinnai_touch_climate). Thanks to all of them for the groundwork.

The connection handling in the pyrinnaitouch fork is ported from [jerryzou/rinnai_touch_climate](https://github.com/jerryzou/rinnai_touch_climate) (MIT), which follows the [homebridge-rinnai-touch-platform](https://github.com/mantorok1/homebridge-rinnai-touch-platform) plugin.

## What's different from the original

| Area | Change |
|---|---|
| Modes | Heating only. Cooling, evaporative cooling and all zone entities are removed. |
| Setup form | Asks only for host, name and an optional external temperature sensor, with no zone questions. Fills in the bridge's IP address automatically when it hears the bridge's broadcast. |
| Entities | Removed the cooling, evap, zone, heater mode, gas valve active and time setting entities. |
| Fan speed | Fan only speed is limited to 1–16, as the N-BW2 API specifies. |
| Dependency | Uses the patched [chickymonkey/pyrinnaitouch](https://github.com/chickymonkey/pyrinnaitouch) instead of `pyrinnaitouch==0.13.4b1` from PyPI. See [Dependency](#dependency). |

Existing heater entities keep the same unique IDs, so their history carries over if you switch from the original integration.

## Entities

| Platform | Entity | Purpose |
|---|---|---|
| Climate | *Name* | Off / Heat / Fan only, target temperature (8–30 °C), Auto (schedule) or Manual preset. In Fan only, the target value sets the fan speed (1–16). |
| Switch | On Off Switch | Turns the heater on or off. |
| Switch | Auto Switch | On = follow the schedule, off = manual. |
| Switch | Circulation Fan Switch | Runs the circulation fan while the heater is off. |
| Select | Preset Select | Auto or Manual (same as the Auto switch). |
| Button | Advance Button | Advances to, or cancels advancing to, the next schedule period. Available in Auto mode. |
| Binary sensor | Connected Sensor | Whether the TCP connection to the bridge is up. |
| Binary sensor | Preheating Sensor | The heater is pre-heating. |
| Binary sensor | Calling Heat Sensor | The system is calling for heat. |
| Binary sensor | Fan Active Sensor | The fan is running. |
| Sensor | Main Temperature Sensor | Measured temperature, when the controller reports one. |
| Sensor | Main Target Temperature Sensor | Current set point. |
| Sensor | Schedule Time Period Sensor | Current schedule period (Wake, Leave, Return, Pre-Sleep, Sleep). |
| Sensor | Advance Time Period Sensor | The period the schedule has been advanced to. |
| Sensor | Connection State | Raw connection state: `WAITING` (for the bridge's broadcast), `CONNECTING`, `CONNECTED`, `TIMEOUT`, `REFUSED`, `ERROR` or `IDLE`. |

There is also a `rinnaitouch.rinnai_set_time` service that sets the controller's clock, from Home Assistant's time or from a given date and time.

## How it works

The integration talks to the N-BW2 bridge over your local network, using the protocol in the [N-BW2 API manual](doc/NBW2API_Iss1.3.pdf). No cloud service is involved.

The bridge has a single TCP connection slot and is unforgiving about how it is used. While the slot is free it broadcasts a UDP packet on port 50000 about once a second. The broadcasts stop when a client connects and resume roughly 7 seconds after it disconnects. Connecting before then is refused, and reconnecting within about a second of closing can get a client refused for minutes. The library works around this:

1. **Waiting for the slot.** Before every connection, the first one and every reconnect, the library waits at least 10 seconds after its last connection closed. It then waits for a broadcast from the configured IP address, which means the slot is free. Only if no broadcast arrives for 5 minutes does it try connecting anyway.
2. **Connection.** The library opens a TCP connection to the bridge on port 27847. It only counts as connected once the first status message arrives, not when the TCP connection opens.
3. **Status.** The bridge pushes its full status as JSON about once a second. Home Assistant doesn't poll. Entities update when the status changes.
4. **Commands.** Commands are sent one at a time, each numbered after the bridge's last sequence number (1–254, then back to 1). A command is confirmed when the status shows the new value. Where the status doesn't report that value, the bridge echoing the number counts as confirmation. An unconfirmed command is resent after 10 seconds, up to 3 attempts. A command the status already shows is skipped.
5. **Keepalive.** If nothing has been sent for 30 seconds, the library sends a bare sequence number, so the bridge doesn't drop the client after its TCP timeout. That timeout is 5 minutes by default and can be set as low as 1 minute, which 30 seconds still covers.
6. **Recovery.** If no data arrives for 5 seconds, or the bridge closes the connection, the library reconnects using step 1. After 3 failed attempts in a row it waits a minute before trying again.

The bridge only supports one client at a time. While the Rinnai/Brivis phone app, Homebridge or another integration is connected, Home Assistant waits (Connection State shows `WAITING`) until the bridge is free again.

## Dependency

This integration depends on the library [pyrinnaitouch](https://github.com/chickymonkey/pyrinnaitouch), installed from the `connection-fixes` branch of the fork and pinned to an exact commit. Home Assistant installs it automatically from the GitHub archive listed in [manifest.json](custom_components/rinnaitouch/manifest.json):

```
https://github.com/chickymonkey/pyrinnaitouch/archive/91f1fa79c8350fe1b5c2d298b717ec35de996fae.zip#pyrinnaitouch==0.13.4b1.post3
```

The fork is based on `pyrinnaitouch` 0.13.4b1 and is versioned `0.13.4b1.post3`, so Home Assistant replaces an already installed 0.13.4b1. Its connection handling is rewritten as described in [How it works](#how-it-works). Compared with 0.13.4b1:

- **Connection thread stopping silently.** An unexpected error, such as a byte that isn't valid UTF-8 arriving from the bridge, used to stop the background connection thread for good. Status then froze, commands were never sent and no reconnect was attempted, while the integration still showed as connected. The thread now logs the error and reconnects.
- **Reconnecting too soon.** The original reconnected straight after a timeout or error, which the bridge refuses and can hold against the client for minutes. Every connection now waits for the release delay and the bridge's broadcast.
- **Commands that didn't take effect.** Commands used to be fire-and-forget. They are now confirmed against the status and retried, and commands already in effect are not sent.
- **Replayed commands.** Commands queued while disconnected are discarded on reconnect instead of being sent in a burst minutes later.
- **Less traffic.** A bare keepalive every 30 seconds replaces an idle command every 10 seconds, and Home Assistant only updates when the status changes.
- **Data parsing.** Incoming data is parsed with a proper JSON decoder that copes with messages split across packets and with junk bytes.

## Installation

### HACS (recommended)

1. In HACS, open **⋮ → Custom repositories**, add `https://github.com/chickymonkey/rinnaitouch` and choose the **Integration** type.
2. Download **Rinnai Touch**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add Integration** and search for **Rinnai Touch**.
5. Enter:
   - **Hostname or IP** – the bridge's IP address. The form listens for the bridge's broadcasts for a few seconds and fills this in if it hears one (see [Bridge discovery](#bridge-discovery)). Give the bridge a fixed IP or a DHCP reservation.
   - **Name** – for example `Rinnai Touch`.
   - **External temperature sensor** (optional) – the entity ID of a temperature sensor to show as the current temperature. Use this if your controller doesn't report one: the climate entity shows 0 °C when the controller reports none and no external sensor is set.

### Switching from the original integration

1. Remove the existing Rinnai Touch entry under **Settings → Devices & services**.
2. Install this fork through HACS as above and restart Home Assistant.
3. Add the integration again.
4. Delete any leftover zone or cooling entities that show as unavailable.

If the setup form still asks about zones, the old code is still installed, or your browser is showing a cached copy of the old form. Redownload the integration in HACS, restart Home Assistant and force-refresh the browser.

### Manual installation

Copy `custom_components/rinnaitouch` into the `custom_components` folder of your Home Assistant configuration directory, restart Home Assistant and add the integration as above.

## Troubleshooting

### Bridge discovery

When you add the integration, the setup form listens for 3 seconds for the bridge's UDP broadcasts on port 50000, and fills in the IP address of the first bridge it hears that isn't already set up.

If the field stays empty:

- **Another client holds the bridge.** The bridge only broadcasts while nobody is connected. Close the Rinnai/Brivis phone app, and stop Homebridge or any other Rinnai integration, including an existing Rinnai Touch entry for the same bridge. Then open the form again.
- **Broadcasts don't reach Home Assistant.** This happens in Docker without `network_mode: host`, or when the bridge is on a different subnet or VLAN. Type the IP address in yourself. The integration still works, but every reconnect then waits 5 minutes before connecting without a broadcast.
- **The bridge is offline.** Check that its PWR and WIFI LEDs are lit (see the [manual](doc/NBW2API_Iss1.3.pdf), section 2.5).

### Automatic recovery

You shouldn't need to restart Home Assistant or reload the integration to recover from a dropout. The library reconnects by itself:

| What happens | How it's detected | What the library does |
|---|---|---|
| The connection to the bridge drops | Any of the cases below | The thermostat, switches, preset select and advance button show as **unavailable** until it reconnects, instead of showing the last known state as if it were live. Their history shows a short gap. |
| The bridge goes quiet | No data for 5 seconds (status normally arrives every second) | Closes the connection and reconnects |
| The bridge closes the connection | The connection is closed from the other end | Reconnects |
| Garbled or invalid data | Bytes that don't parse as a status message | Skips them and keeps the connection |
| An unexpected error in the library | Any error in the connection thread | Logs it with a traceback and reconnects |
| A command doesn't take effect | The status doesn't show the new value within 10 seconds | Resends it, up to 3 attempts, then gives up and logs an error |
| Commands sent while disconnected | Commands still queued when the connection comes back | Discards them, so they aren't replayed later |

Every reconnect waits at least 10 seconds after the last connection closed, then for the bridge's broadcast saying it's free, because the bridge refuses connections that come too soon. A dropout therefore usually recovers in 10–15 seconds. During that time the Connection State sensor shows `WAITING` and then `CONNECTING`, and the Connected sensor is off. If 3 attempts in a row fail, the library waits a minute before trying again.

If the Connection State sensor stays at `WAITING`, the bridge isn't broadcasting. Something else is probably connected to it (see [Bridge discovery](#bridge-discovery)). If nothing else is connected, power-cycle the bridge.

If dropouts keep happening, turn on [debug logging](#debug-logging) and check which message appears just before each one. The bridge going quiet, the bridge closing the connection and a refused reconnect each have different causes.

Reloading the integration or restarting Home Assistant closes the connection cleanly. The bridge still takes several seconds to free it, so the new connection follows the same wait as any reconnect.

### Debug logging

To enable debug logging, add this to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.rinnaitouch: debug
    pyrinnaitouch: debug
```

What to look for in the log:

| Log message | Meaning |
|---|---|
| `Sending keepalive N` / `Sending command N` then `Command N confirmed` | Normal operation (debug level). |
| `Lost the connection to the Rinnai Touch module … no data for 5 s; reconnecting` | The bridge went quiet. Check its WiFi signal, and whether another app is connected. |
| `Lost the connection … the module closed the connection; reconnecting` | The bridge dropped the connection. It reconnects once the bridge is free. |
| `The module did not confirm … resending` / `… giving up` | A command was sent but the status never showed the change. |
| `Discarded N command(s) queued while disconnected` | Commands sent during an outage were dropped instead of replayed. |
| `N connection attempts failed; next try in 60 s` | The bridge refused or didn't answer three times in a row. |
| `No broadcast from the unit at … for 300 s; connecting without one` | Another client may hold the connection, or broadcasts aren't reaching Home Assistant. Broadcasts need HA OS, or Docker with `network_mode: host`. |
| `A Rinnai Touch module is broadcasting from …` | The bridge's IP address changed. Give it a fixed address and re-add the integration. |
| `Unexpected error in connection thread, reconnecting` | An error the library recovered from. The traceback that follows shows the cause. |

The bridge's WIFI LED also helps. Solid orange means it lost your router for 3 minutes and is about to fall back to its own access point (see the [manual](doc/NBW2API_Iss1.3.pdf), section 2.5).

## License

MIT. See [LICENSE](LICENSE)
