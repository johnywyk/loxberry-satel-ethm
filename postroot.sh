#!/bin/sh
# SATEL ETHM Bridge - Post-install script run as ROOT

PLUGIN="satel_ethm"
CONFIG_DIR="${LBHOMEDIR}/config/plugins/$PLUGIN"
LOG_DIR="${LBHOMEDIR}/log/plugins/$PLUGIN"
DATA_DIR="${LBHOMEDIR}/data/plugins/$PLUGIN"
SYSTEM_DIR="${LBHOMEDIR}/data/system/$PLUGIN"
SERVICE_SCRIPT="${LBHOMEDIR}/bin/plugins/$PLUGIN/satel_ethm_service.sh"

# 1. Utwórz katalogi z właściwymi uprawnieniami
mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$DATA_DIR" "$SYSTEM_DIR"
chown -R loxberry:loxberry "$CONFIG_DIR" "$LOG_DIR" "$DATA_DIR" 2>/dev/null || true

# 2. # Migracja ze starej lokalizacji (data/system/ -> config/plugins/)
if [ ! -f "$CONFIG_DIR/config.json" ] && [ -f "$SYSTEM_DIR/config.json" ]; then
    cp "$SYSTEM_DIR/config.json" "$CONFIG_DIR/config.json"
    echo "Migrated config from data/system/ to config/plugins/"
fi
if [ ! -f "$CONFIG_DIR/config.json" ] && [ -f "$DATA_DIR/config.json" ]; then
    cp "$DATA_DIR/config.json" "$CONFIG_DIR/config.json"
    echo "Migrated config from data/plugins/ to config/plugins/"
fi

# 3. Merge config (jako root, bo katalog może należeć do roota)
python3 - "$CONFIG_DIR/config.json" <<'PY' || true
import json
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1])

# Wykryj MQTT z systemu LoxBerry
lb_mqtt = {}
try:
    import os
    lbhome = os.environ.get("LBHOMEDIR", "")
    mqtt_cfg = Path(lbhome) / "config/system/mqtt.json"
    if mqtt_cfg.exists():
        d = json.loads(mqtt_cfg.read_text(encoding="utf-8"))
        lb_mqtt = {
            "host": d.get("Hostname") or d.get("hostname") or "",
            "port": int(d.get("Port") or d.get("port") or 1883),
            "username": d.get("Username") or d.get("username") or "",
            "password": d.get("Password") or d.get("password") or "",
        }
except Exception:
    pass

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
    # ZMIANA 6: heartbeat
    "heartbeat_interval": 30.0,
    "push_keepalive_interval": 5.0,
    # ZMIANA 5: MQTT - auto-fill z systemu LoxBerry
    "mqtt_enabled": True,
    "mqtt_host": lb_mqtt.get("host", ""),
    "mqtt_port": lb_mqtt.get("port", 1883),
    "mqtt_timeout": 3.0,
    "mqtt_keepalive": 60,
    "mqtt_reconnect_interval": 10.0,
    "mqtt_base_topic": "satel",
    "mqtt_username": lb_mqtt.get("username", ""),
    "mqtt_password": lb_mqtt.get("password", ""),
    "mqtt_client_id": "",
    "mqtt_retain": True,
    "mqtt_publish_raw": False,
    "mqtt_control_enabled": True,
    "loxberry_control_url": "",
    "control_token": "",
    "allowed_control_ips": "",
    "default_control_partition": 1,
    "control_confirm_enabled": True,
    "control_confirm_blocking": False,
    "control_confirm_timeout": 20.0,
    "control_confirm_interval": 0.5,
    "send_masks": True,
    "send_trouble_details": True,
    # ZMIANA 7: poll_zones domyślnie True
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
            changed = merge_missing(current[key], value) or changed
    return changed

if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a dict")
    except Exception:
        backup = path.with_suffix(".json.broken")
        try: path.rename(backup)
        except Exception: pass
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
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    print(f"Config saved: {path}")
else:
    print(f"Config unchanged: {path}")
PY

# 4. Ustaw ownership config na loxberry
chown -R loxberry:loxberry "$CONFIG_DIR" 2>/dev/null || true

# 5. Zarejestruj daemon w systemie LoxBerry
DAEMON_DIR="${LBHOMEDIR}/system/daemons/plugins/${PLUGIN}"
DAEMON_SCRIPT="${LBHOMEDIR}/daemon/plugins/${PLUGIN}/${PLUGIN}"
DAEMON_SRC="${LBHOMEDIR}/bin/plugins/${PLUGIN}/satel_ethm_service.sh"

mkdir -p "$DAEMON_DIR"
# Stwórz skrypt daemona jeśli nie istnieje
if [ ! -f "$DAEMON_DIR/satel_ethm" ]; then
    cat > "$DAEMON_DIR/satel_ethm" << DAEMONEOF
#!/bin/sh
exec "${LBHOMEDIR}/bin/plugins/${PLUGIN}/satel_ethm_service.sh" "\${1:-status}"
DAEMONEOF
    chmod +x "$DAEMON_DIR/satel_ethm"
    echo "Daemon script created: $DAEMON_DIR/satel_ethm"
fi

# 6. Utwórz wpis sudoers żeby loxberry mógł uruchamiać service script bez hasła
SUDOERS_FILE="/etc/sudoers.d/${PLUGIN}"
cat > "$SUDOERS_FILE" << SUDOEOF
# SATEL ETHM Bridge - allow loxberry to manage service without password
loxberry ALL=(ALL) NOPASSWD: $SERVICE_SCRIPT start
loxberry ALL=(ALL) NOPASSWD: $SERVICE_SCRIPT stop
loxberry ALL=(ALL) NOPASSWD: $SERVICE_SCRIPT restart
loxberry ALL=(ALL) NOPASSWD: $SERVICE_SCRIPT status
SUDOEOF
chmod 440 "$SUDOERS_FILE"
echo "Sudoers entry created: $SUDOERS_FILE"

echo "=== SATEL ETHM Bridge post-root complete ==="
exit 0
