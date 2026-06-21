# SATEL ETHM Bridge for LoxBerry

Unofficial community LoxBerry plugin for integrating SATEL INTEGRA alarm panels
through ETHM TCP with Loxone.

The plugin reads SATEL ETHM integration frames, decodes alarm states, zones,
outputs, diagnostics and selected control feedback, then sends simple UDP values
to Loxone. It can also publish the same values to MQTT. HTTP and MQTT control
endpoints can be used for arming, disarming, clearing alarms, switching outputs
and controlling bypass/blocking of zones.

Polish documentation: [`docs/README_PL.md`](docs/README_PL.md)

## 

SATEL ETHM Bridge to nieoficjalna wtyczka LoxBerry do integracji central SATEL INTEGRA przez ETHM z systemem Loxone.

Wtyczka odczytuje stany alarmu, uzbrojenia, awarii, wejść, wyjść, temperatur oraz diagnostyki, a następnie przekazuje je do Loxone przez UDP. Umożliwia również sterowanie alarmem z Loxone przez HTTP, m.in. uzbrajanie, rozbrajanie, kasowanie alarmu, sterowanie wyjściami oraz blokady wejść.

Dodatkowo wtyczka potrafi generować pliki XML do importu w Loxone Config, importować nazwy partycji, wejść i wyjść z pliku DLOADX XML oraz opcjonalnie publikować dane przez MQTT.

Projekt jest testowy i społecznościowy. Nie jest oficjalną integracją SATEL ani Loxone. Przy sterowaniu alarmem należy zachować zdrowy rozsądek i najpierw testować wszystko poza krytyczną automatyką.

Polska dokumentacja szczegółowa znajduje się tutaj: [docs/README_PL.md](docs/README_PL.md)

## Current status

This is a community testing build. It works in a real installation, but it should
still be tested carefully before use in production alarm logic.

Known tested direction:

- SATEL INTEGRA with ETHM integration port `7094`
- LoxBerry 3.x
- Loxone Virtual UDP Inputs
- Loxone Virtual HTTP Outputs for control
- optional MQTT broker

## Main features

- Polling of core SATEL states:
  - armed
  - alarm
  - fire alarm
  - alarm memory
  - trouble
  - entry time
  - exit time
- Zone status polling:
  - violated zones
  - bypass/block status
  - tamper
  - zone alarm
  - zone alarm memory
- Output status polling through SATEL command `0x17`.
- Optional temperature reads through SATEL command `0x7D`.
- Push-triggered polling with fallback polling.
- Optional ETHM integration encryption support.
- HTTP control bridge for Loxone.
- XML generators for Loxone Config:
  - selected UDP input sections
  - Lite UDP input XML
  - full control XML
  - Lite control XML
- DLOADX XML import for enabled partitions, zones and outputs.
- Live diagnostic panel, event history and watchdog values.
- Backup and restore of plugin configuration.
- Optional MQTT publish/control bridge.

## Example UDP values

```text
SATEL_ONLINE=1
SATEL_ARMED=0
SATEL_ALARM=0
SATEL_TROUBLE=0
SATEL_EXIT_TIME=0
SATEL_ZONE_001=0
SATEL_OUTPUT_101=1
SATEL_PUSH_CONNECTED=1
SATEL_WATCHDOG_OK=1
```

In Loxone, use a Virtual UDP Input and command recognition such as:

```text
SATEL_ARMED=\v
SATEL_ALARM=\v
SATEL_ZONE_001=\v
```

With MQTT enabled, equivalent values are published under the configured base
topic, for example:

```text
satel/status/armed
satel/zone/001/violated
satel/output/101/state
satel/watchdog/ok
```

## Installation for testers

1. Download the latest ZIP from Releases or build it locally.
2. Install the ZIP in LoxBerry Plugin Management.
3. Open the plugin panel.
4. Configure:
   - ETHM IP address and port,
   - Loxone Miniserver UDP address and port,
   - partitions, zones and outputs manually or through DLOADX XML import,
   - optional SATEL user code for control commands,
   - optional ETHM integration encryption key if enabled in DLOADX.
5. Generate XML templates and import them in Loxone Config.

The active configuration is stored on LoxBerry in:

```text
/opt/loxberry/data/system/satel_ethm/config.json
```

The plugin ZIP intentionally does not include an active `config.json`, so updates
do not overwrite user settings.

## Build locally

```bash
python3 -m py_compile bin/satel_ethm_bridge.py webfrontend/htmlauth/index.cgi webfrontend/html/control.cgi
python3 scripts/build_plugin_zip.py
```

The package is written to:

```text
dist/loxberry-satel-ethm-<version>.zip
```

## Contributing

Pull requests are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md)
before sending changes.

Useful reports include:

- LoxBerry version
- SATEL panel model
- ETHM model
- whether ETHM integration encryption is enabled
- relevant logs with secrets removed
- what was tested in Loxone Config

Do not publish SATEL user codes, control tokens, integration keys or private IP
details from real installations.

## Security

Do not expose the control endpoint to the internet.

Create a dedicated SATEL user for LoxBerry/Loxone and give it only the minimal
permissions needed for the required partitions and outputs.

See [`SECURITY.md`](SECURITY.md).

## Trademark notice

SATEL ETHM Bridge is an unofficial community project.

This project is not affiliated with, endorsed by, or supported by SATEL sp. z o.o.,
Loxone, or LoxBerry.

SATEL, INTEGRA, ETHM, Loxone and LoxBerry names or logos are trademarks or
registered trademarks of their respective owners. See [`NOTICE.md`](NOTICE.md).

## License

MIT. See [`LICENSE`](LICENSE).
