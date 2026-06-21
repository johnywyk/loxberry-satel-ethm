# Changelog

## 0.23.0

- Added optional MQTT publishing without external Python dependencies.
- Added MQTT topics for statuses, partitions, zones, outputs, temperatures, trouble details, push, watchdog and diagnostics.
- Added optional MQTT control subscriber:
  - `satel/control/arm`
  - `satel/control/disarm`
  - `satel/control/clear_alarm`
  - `satel/control/clear_trouble`
  - `satel/control/output/<nr>/set`
  - `satel/control/output/<nr>/toggle`
  - `satel/control/zone/<nr>/bypass`
- Added MQTT configuration section in the LoxBerry panel.
- Added MQTT runtime diagnostics in the live diagnostic panel.

## 0.22.1

- Lite UDP input XML now includes entry time and exit time values:
  - `SATEL_ENTRY_TIME`
  - `SATEL_EXIT_TIME`
  - `SATEL_EXIT_TIME_LONG`
  - `SATEL_EXIT_TIME_SHORT`
  - per-partition entry/exit time values.

## 0.22.0

- Added live diagnostic dashboard with state summary and event history.
- Added runtime tracking of last UDP values.
- Added communication watchdog UDP values:
  - `SATEL_WATCHDOG_OK`
  - `SATEL_WATCHDOG_STATUS_OK`
  - `SATEL_WATCHDOG_PUSH_OK`
- Added configuration autotest in the LoxBerry panel.
- Added control profiles and export of profiles to full and Lite control XML.
- Added DLOADX mapping preview in the panel.
- Added open source project files and GitHub build workflow.

## 0.21.0

- Control queue is released immediately after ETHM responses `EF 00` or `EF FF`.
- State confirmation is handled asynchronously by normal status reads.
- Blocking confirmation remains available as a diagnostic option.

## Older versions

Detailed historical notes are currently kept in `docs/README_PL.md`.
