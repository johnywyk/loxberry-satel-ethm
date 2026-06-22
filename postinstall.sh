#!/bin/sh
set -eu

PLUGIN="satel_ethm"
CONFIG_DIR="/opt/loxberry/config/plugins/$PLUGIN"
DATA_DIR="/opt/loxberry/data/plugins/$PLUGIN"
SYSTEM_DIR="/opt/loxberry/data/system/$PLUGIN"
LOG_DIR="/opt/loxberry/log/plugins/$PLUGIN"
BIN_DIR="/opt/loxberry/bin/plugins/$PLUGIN"
HTML_DIR="/opt/loxberry/webfrontend/html/plugins/$PLUGIN"
HTMLAUTH_DIR="/opt/loxberry/webfrontend/htmlauth/plugins/$PLUGIN"

mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$SYSTEM_DIR" "$LOG_DIR"

if [ ! -f "$SYSTEM_DIR/config.json" ] && [ -f "$DATA_DIR/config.json" ]; then
  cp "$DATA_DIR/config.json" "$SYSTEM_DIR/config.json"
fi

if [ ! -f "$SYSTEM_DIR/config.json" ] && [ -f "$CONFIG_DIR/config.json" ]; then
  cp "$CONFIG_DIR/config.json" "$SYSTEM_DIR/config.json"
fi

python3 - "$SYSTEM_DIR/config.json" <<'PY' || true
import json
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1])

defaults = {
    "ethm_host": "192.168.1.39",
    "ethm_port": 7094,
    "ethm_timeout": 2.0,
    "ethm_encryption_enabled": False,
    "ethm_integration_key": "",
    "debug_logging": False,
    "satel_user_code": "",
    "poll_interval": 5.0,
    "status_poll_interval": 5.0,
    "status_send_on_change": True,
    "status_full_refresh_interval": 30.0,
    "push_enabled": True,
    "push_reconnect_interval": 10.0,
    "push_debounce_seconds": 0.3,
    "partition_mask": 1,
    "send_partition_details": True,
    "send_ready_inferred": True,
    "send_diagnostics": True,
    "watchdog_status_max_age": 30.0,
    "watchdog_push_max_age": 300.0,
    "loxone_host": "192.168.1.10",
    "loxone_udp_port": 7007,
    "udp_sender_address": "",
    "mqtt_enabled": False,
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_timeout": 3.0,
    "mqtt_keepalive": 60,
    "mqtt_reconnect_interval": 10.0,
    "mqtt_base_topic": "satel",
    "mqtt_username": "",
    "mqtt_password": "",
    "mqtt_client_id": "",
    "mqtt_retain": True,
    "mqtt_publish_raw": False,
    "mqtt_control_enabled": False,
    "loxberry_control_url": "http://LOXBERRY_IP/plugins/satel_ethm/control.cgi",
    "control_token": "",
    "allowed_control_ips": "",
    "default_control_partition": 1,
    "control_confirm_enabled": True,
    "control_confirm_blocking": False,
    "control_confirm_timeout": 20.0,
    "control_confirm_interval": 0.5,
    "send_masks": True,
    "send_trouble_details": True,
    "poll_zones": True,
    "zones_poll_interval": 1.0,
    "zones_send_on_change": True,
    "zones_full_refresh_interval": 30.0,
    "zone_hold_seconds": 3.0,
    "zone_status_command": "FE FE 00 D7 E2 FE 0D",
    "poll_zone_bypass": True,
    "zone_bypass_status_command": "FE FE 06 D7 E8 FE 0D",
    "poll_zone_diagnostics": True,
    "zone_tamper_status_command": "FE FE 01 D7 E3 FE 0D",
    "zone_alarm_status_command": "FE FE 02 D7 E4 FE 0D",
    "zone_alarm_memory_status_command": "FE FE 04 D7 E6 FE 0D",
    "zones": [],
    "poll_outputs": True,
    "outputs_poll_interval": 2.0,
    "outputs_send_on_change": True,
    "outputs_full_refresh_interval": 30.0,
    "output_status_command": "",
    "poll_temperatures": False,
    "temperature_poll_interval": 60.0,
    "temperature_timeout": 5.0,
    "temperature_zones": [],
    "send_temperature_raw": False,
    "control_partitions": [{"number": 1, "name": "Partycja 1", "enabled": True}],
    "control_outputs": [],
    "control_profiles": [],
    "commands": {
        "armed": "FE FE 0A D7 EC FE 0D",
        "alarm": "FE FE 13 D7 F5 FE 0D",
        "fire_alarm": "FE FE 14 D7 F6 FE 0D",
        "alarm_memory": "FE FE 15 D7 F7 FE 0D",
        "trouble": "FE FE 1B D7 FD FE 0D",
        "entry_time": "FE FE 0E D7 F0 FE 0D",
        "exit_time": "FE FE 0F D7 F1 FE 0D",
        "exit_time_short": "FE FE 10 D7 F2 FE 0D",
    },
}

def merge_missing(current, default):
    changed = False
    for key, value in default.items():
        if key not in current:
            current[key] = value
            changed = True
        elif isinstance(value, dict) and isinstance(current.get(key), dict):
            sub_changed = merge_missing(current[key], value)
            changed = changed or sub_changed
    return changed

if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("config root is not an object")
    except Exception:
        backup = path.with_suffix(".json.broken")
        try:
            path.rename(backup)
        except Exception:
            pass
        data = defaults.copy()
        changed = True
    else:
        changed = merge_missing(data, defaults)
else:
    data = defaults.copy()
    changed = True

if not data.get("control_token"):
    data["control_token"] = secrets.token_urlsafe(18)
    changed = True
if changed:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

chmod +x "$BIN_DIR/satel_ethm_bridge.py" "$BIN_DIR/satel_ethm_service.sh" 2>/dev/null || true
chmod +x "$HTML_DIR/control.cgi" 2>/dev/null || true

mkdir -p "$SYSTEM_DIR/control_queue" "$LOG_DIR"
touch "$LOG_DIR/satel_ethm_control.log" "$LOG_DIR/satel_ethm_bridge.log" 2>/dev/null || true
chmod 777 "$SYSTEM_DIR/control_queue" 2>/dev/null || true
chmod 666 "$LOG_DIR/satel_ethm_control.log" "$LOG_DIR/satel_ethm_bridge.log" 2>/dev/null || true

if [ -d "$HTML_DIR/icons" ]; then
  mkdir -p "$DATA_DIR/icons"
  cp "$HTML_DIR/icons"/icon_*.png "$DATA_DIR/icons/" 2>/dev/null || true
fi

if [ -d "$HTMLAUTH_DIR/icons" ]; then
  mkdir -p "$DATA_DIR/icons"
  cp "$HTMLAUTH_DIR/icons"/icon_*.png "$DATA_DIR/icons/" 2>/dev/null || true
fi

exit 0
