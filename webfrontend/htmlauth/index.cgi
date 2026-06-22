#!/usr/bin/env python3
import cgi
import html
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

PLUGIN = "satel_ethm"
CONFIG_FILE = Path(os.environ.get("SATEL_ETHM_CONFIG", f"/opt/loxberry/data/system/{PLUGIN}/config.json"))
LEGACY_CONFIG_FILES = [
    Path(f"/opt/loxberry/data/plugins/{PLUGIN}/config.json"),
    Path(f"/opt/loxberry/config/plugins/{PLUGIN}/config.json"),
]
SERVICE_SCRIPT = Path(f"/opt/loxberry/bin/plugins/{PLUGIN}/satel_ethm_service.sh")
SYSTEMD_SERVICE = "satel-ethm-bridge.service"
VERSION = "0.24.0"
CONTROL_QUEUE_DIR = CONFIG_FILE.parent / "control_queue"
RUNTIME_FILE = CONFIG_FILE.parent / "runtime.json"

ARM_MODE_DESCRIPTIONS = {
    0: "pełne czuwanie",
    1: "pełne czuwanie + bypassy",
    2: "czuwanie dzienne / stay bez wewnętrznych",
    3: "czuwanie nocne / stay bez czasu na wejście",
}

DEFAULT_CONFIG = {
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

COMMAND_FORM_FIELDS = {
    "armed": "cmd_armed",
    "alarm": "cmd_alarm",
    "fire_alarm": "cmd_fire_alarm",
    "alarm_memory": "cmd_alarm_memory",
    "trouble": "cmd_trouble",
    "entry_time": "cmd_entry_time",
    "exit_time": "cmd_exit_time",
    "exit_time_short": "cmd_exit_time_short",
}


def run_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or result.stderr.strip()
    except Exception as exc:
        return str(exc)


def service_status():
    if shutil_which("systemctl"):
        status = run_command(["systemctl", "is-active", SYSTEMD_SERVICE])
        return status if status else "unknown"
    if SERVICE_SCRIPT.exists():
        return run_command([str(SERVICE_SCRIPT), "status"])
    return "unknown"


def load_runtime_state():
    if not RUNTIME_FILE.exists():
        return {}
    try:
        with RUNTIME_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        return {"runtime_error": str(exc)}


def runtime_age(runtime, key):
    try:
        ts = int(runtime.get(key, 0))
    except Exception:
        ts = 0
    if not ts:
        return ""
    return f"{max(0, int(time.time()) - ts)} s temu"


def runtime_rows(runtime, current_service_status):
    rows = [
        ("Status usługi", current_service_status),
        ("Stan runtime", runtime.get("service_state", "")),
        ("Wersja usługi", runtime.get("service_version", "")),
        ("Start usługi", runtime.get("service_started_iso", "")),
        ("Ostatnie UDP", f"{runtime.get('last_udp_iso', '')} ({runtime_age(runtime, 'last_udp_ts')})"),
        ("UDP cel", runtime.get("last_udp_target", "")),
        ("UDP payload", runtime.get("last_udp_payload", "")),
        ("UDP klucze", runtime.get("last_udp_keys", "")),
        ("Ostatni odczyt ETHM", f"{runtime.get('last_ethm_iso', '')} ({runtime_age(runtime, 'last_ethm_ts')})"),
        ("ETHM komenda", runtime.get("last_ethm_cmd", "")),
        ("ETHM transport", runtime.get("last_ethm_transport", "")),
        ("ETHM odpowiedź", runtime.get("last_ethm_response", "")),
        ("Ostatnia komenda sterująca", f"{runtime.get('last_control_iso', '')} ({runtime_age(runtime, 'last_control_ts')})"),
        ("Sterowanie akcja", runtime.get("last_control_action", "")),
        ("Sterowanie wynik", runtime.get("last_control_result_text", runtime.get("last_control_error", ""))),
        ("Sterowanie potwierdzenie", runtime.get("last_control_confirmation", "")),
        ("Ostatnia ramka push", f"{runtime.get('last_push_iso', '')} ({runtime_age(runtime, 'last_push_ts')})"),
        ("Push połączony", runtime.get("push_connected", "")),
        ("Push reconnects", runtime.get("push_reconnects", "")),
        ("Push ramka", runtime.get("last_push_frame", "")),
        ("MQTT publish", runtime.get("mqtt_last_publish_iso", "")),
        ("MQTT publish klucze", runtime.get("mqtt_last_publish_keys", "")),
        ("MQTT ostatni błąd", runtime.get("mqtt_last_error", "")),
        ("MQTT control połączony", runtime.get("mqtt_control_connected", "")),
        ("MQTT control temat", runtime.get("mqtt_control_topic", "")),
        ("MQTT control ostatni payload", runtime.get("mqtt_control_last_payload", "")),
        ("MQTT control ostatni błąd", runtime.get("mqtt_control_last_error", "")),
    ]
    return rows


def runtime_value(runtime, key, default=""):
    values = runtime.get("last_values", {})
    if isinstance(values, dict):
        return values.get(key, default)
    return default


def named_item_name(items, number, fallback):
    for item in items or []:
        try:
            if int(item.get("number", 0)) == int(number):
                return str(item.get("name", fallback))
        except Exception:
            continue
    return fallback


def dashboard_rows(runtime, config):
    values = runtime.get("last_values", {})
    if not isinstance(values, dict):
        values = {}
    rows = [
        ("Online", values.get("SATEL_ONLINE", "")),
        ("Uzbrojony", values.get("SATEL_ARMED", "")),
        ("Alarm", values.get("SATEL_ALARM", "")),
        ("Awaria", values.get("SATEL_TROUBLE", "")),
        ("Czas na wejście", values.get("SATEL_ENTRY_TIME", "")),
        ("Czas na wyjście", values.get("SATEL_EXIT_TIME", "")),
        ("Push", values.get("SATEL_PUSH_CONNECTED", runtime.get("push_connected", ""))),
        ("MQTT control", runtime.get("mqtt_control_connected", "")),
        ("Watchdog", values.get("SATEL_WATCHDOG_OK", "")),
    ]
    active_zones = []
    for zone in normalize_zones(config.get("zones", [])):
        number = int(zone["number"])
        if str(values.get(f"SATEL_ZONE_{number:03d}", "0")) in ("1", "1.0", "true", "True"):
            active_zones.append(f"{number} {zone['name']}")
    bypass_zones = []
    for zone in normalize_zones(config.get("zones", [])):
        number = int(zone["number"])
        if str(values.get(f"SATEL_ZONE_{number:03d}_BYPASS", "0")) in ("1", "1.0", "true", "True"):
            bypass_zones.append(f"{number} {zone['name']}")
    active_outputs = []
    for output in normalize_numbered_items(config.get("control_outputs", []), 128, "Wyjscie"):
        number = int(output["number"])
        if str(values.get(f"SATEL_OUTPUT_{number:03d}", "0")) in ("1", "1.0", "true", "True"):
            active_outputs.append(f"{number} {output['name']}")
    rows.extend([
        ("Naruszone wejścia", ", ".join(active_zones) if active_zones else "brak"),
        ("Bypass/blokady wejść", ", ".join(bypass_zones) if bypass_zones else "brak"),
        ("Aktywne wyjścia", ", ".join(active_outputs) if active_outputs else "brak"),
    ])
    return rows


def event_rows(runtime):
    events = runtime.get("events", [])
    if not isinstance(events, list):
        return []
    rows = []
    for event in reversed(events[-30:]):
        if not isinstance(event, dict):
            continue
        rows.append((
            event.get("iso", ""),
            event.get("kind", ""),
            event.get("title", ""),
            event.get("detail", ""),
        ))
    return rows


def shutil_which(command):
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(path) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def normalize_zones(zones):
    normalized = []
    seen = set()
    for zone in zones or []:
        try:
            number = int(zone.get("number", 0))
        except Exception:
            continue
        if number < 1 or number > 256 or number in seen:
            continue
        seen.add(number)
        name = str(zone.get("name", f"Wejscie {number}")).strip() or f"Wejscie {number}"
        try:
            partition = int(zone.get("partition", 0) or 0)
        except Exception:
            partition = 0
        if partition < 1 or partition > 32:
            partition = 0
        normalized.append({
            "number": number,
            "name": name,
            "partition": partition,
            "enabled": bool(zone.get("enabled", True)),
        })
    return sorted(normalized, key=lambda item: item["number"])


def normalize_numbered_items(items, max_number, default_prefix):
    normalized = []
    seen = set()
    for item in items or []:
        try:
            number = int(item.get("number", 0))
        except Exception:
            continue
        if number < 1 or number > max_number or number in seen:
            continue
        seen.add(number)
        name = str(item.get("name", f"{default_prefix} {number}")).strip() or f"{default_prefix} {number}"
        normalized.append({"number": number, "name": name, "enabled": bool(item.get("enabled", True))})
    return sorted(normalized, key=lambda item: item["number"])


def parse_numbered_items_text(text, max_number, default_prefix):
    items = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ";" in line:
            number_text, name = line.split(";", 1)
        elif "," in line:
            number_text, name = line.split(",", 1)
        else:
            parts = line.split(None, 1)
            number_text = parts[0]
            name = parts[1] if len(parts) > 1 else ""
        try:
            number = int(number_text.strip())
        except Exception:
            continue
        if 1 <= number <= max_number:
            items.append({"number": number, "name": name.strip() or f"{default_prefix} {number}", "enabled": True})
    return normalize_numbered_items(items, max_number, default_prefix)


def parse_zones_text(text):
    items = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        separator = ";" if ";" in line else "," if "," in line else None
        if separator:
            parts = [part.strip() for part in line.split(separator)]
        else:
            parts = line.split(None, 2)
        try:
            number = int(parts[0])
        except Exception:
            continue
        if not 1 <= number <= 256:
            continue
        name = ""
        partition = 0
        if len(parts) >= 3:
            if parts[1].isdigit():
                partition = int(parts[1])
                name = separator.join(parts[2:]).strip() if separator else parts[2].strip()
            else:
                name = parts[1]
                try:
                    partition = int(parts[2])
                except Exception:
                    partition = 0
        elif len(parts) == 2:
            name = parts[1]
        items.append({
            "number": number,
            "name": name or f"Wejscie {number}",
            "partition": partition,
            "enabled": True,
        })
    return normalize_zones(items)


def parse_partitions_text(text):
    return parse_numbered_items_text(text, 32, "Partycja")


def parse_outputs_text(text):
    return parse_numbered_items_text(text, 128, "Wyjscie")


def parse_temperature_zones_text(text):
    return parse_numbered_items_text(text, 256, "Temperatura")


CONTROL_PROFILE_ACTIONS = {
    "arm",
    "force_arm",
    "disarm",
    "clear_alarm",
    "clear_trouble",
    "output_on",
    "output_off",
    "output_toggle",
}


def normalize_control_profiles(profiles):
    normalized = []
    seen = set()
    for profile in profiles or []:
        name = str(profile.get("name", "")).strip()
        action = str(profile.get("action", "")).strip().lower()
        target = str(profile.get("target", "")).strip()
        if not name or action not in CONTROL_PROFILE_ACTIONS:
            continue
        try:
            mode = int(profile.get("mode", 0) or 0)
        except Exception:
            mode = 0
        mode = max(0, min(3, mode))
        lite = bool(profile.get("lite", False))
        key = (name.lower(), action, target, mode)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "name": name,
            "action": action,
            "target": target,
            "mode": mode,
            "lite": lite,
            "enabled": bool(profile.get("enabled", True)),
        })
    return normalized


def parse_control_profiles_text(text):
    profiles = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 2:
            continue
        name = parts[0]
        action = parts[1].lower()
        target = parts[2] if len(parts) > 2 else ""
        mode_text = parts[3] if len(parts) > 3 else "0"
        lite_text = parts[4] if len(parts) > 4 else ""
        try:
            mode = int(mode_text) if mode_text != "" else 0
        except Exception:
            mode = 0
        profiles.append({
            "name": name,
            "action": action,
            "target": target,
            "mode": mode,
            "lite": lite_text.strip().lower() in ("1", "true", "yes", "tak", "lite", "x"),
            "enabled": True,
        })
    return normalize_control_profiles(profiles)


def control_profiles_to_text(profiles):
    lines = []
    for profile in normalize_control_profiles(profiles):
        lite = "tak" if profile.get("lite", False) else ""
        lines.append(
            f"{profile['name']};{profile['action']};{profile.get('target', '')};{profile.get('mode', 0)};{lite}"
        )
    return "\n".join(lines)


def zones_to_text(zones):
    lines = []
    for zone in normalize_zones(zones):
        partition = int(zone.get("partition", 0) or 0)
        if partition:
            lines.append(f"{zone['number']};{zone['name']};{partition}")
        else:
            lines.append(f"{zone['number']};{zone['name']}")
    return "\n".join(lines)


def items_to_text(items, max_number, default_prefix):
    return "\n".join(
        f"{item['number']};{item['name']}"
        for item in normalize_numbered_items(items, max_number, default_prefix)
    )


def partition_mask_from_items(partitions):
    mask = 0
    for partition in normalize_numbered_items(partitions, 32, "Partycja"):
        number = int(partition["number"])
        mask |= 1 << (number - 1)
    return mask or int(DEFAULT_CONFIG["partition_mask"])


def is_dloadx_enabled(element):
    return str(element.attrib.get("enabled", "")).strip().lower() == "true"


def dloadx_int_attr(element, name, default=0):
    try:
        return int(str(element.attrib.get(name, default)).strip())
    except Exception:
        return default


def dloadx_partition_from_zone(element, fallback_partition=0):
    for attr in ("partition", "partitions", "partitionNo", "partitionNumber", "partition_number"):
        value = str(element.attrib.get(attr, "")).strip()
        if not value:
            continue
        for token in value.replace(",", ";").replace(" ", ";").split(";"):
            if token.strip().isdigit():
                number = int(token.strip())
                if 1 <= number <= 32:
                    return number
    return fallback_partition


def parse_dloadx_xml(data):
    root = ET.fromstring(data)
    partitions = []
    for element in root.findall(".//Partition"):
        number = dloadx_int_attr(element, "number")
        if is_dloadx_enabled(element) and 1 <= number <= 32:
            partitions.append({
                "number": number,
                "name": element.attrib.get("name", f"Partycja {number}").strip() or f"Partycja {number}",
                "enabled": True,
            })
    partitions = normalize_numbered_items(partitions, 32, "Partycja")

    fallback_partition = int(partitions[0]["number"]) if len(partitions) == 1 else 0
    zones = []
    for element in root.findall(".//Zone"):
        number = dloadx_int_attr(element, "number")
        if is_dloadx_enabled(element) and 1 <= number <= 256:
            zones.append({
                "number": number,
                "name": element.attrib.get("name", f"Wejscie {number}").strip() or f"Wejscie {number}",
                "partition": dloadx_partition_from_zone(element, fallback_partition),
                "enabled": True,
            })
    zones = normalize_zones(zones)

    outputs = []
    for element in root.findall(".//Output"):
        number = dloadx_int_attr(element, "number")
        if is_dloadx_enabled(element) and 1 <= number <= 128:
            outputs.append({
                "number": number,
                "name": element.attrib.get("name", f"Wyjscie {number}").strip() or f"Wyjscie {number}",
                "enabled": True,
            })
    outputs = normalize_numbered_items(outputs, 128, "Wyjscie")
    return partitions, zones, outputs


def import_dloadx_config(form):
    upload = form["dloadx_file"] if "dloadx_file" in form else None
    if upload is None or not getattr(upload, "file", None):
        raise ValueError("Nie wybrano pliku XML z DLOADX")
    data = upload.file.read()
    if not data:
        raise ValueError("Plik DLOADX XML jest pusty")
    partitions, zones, outputs = parse_dloadx_xml(data)
    config = load_config()
    config["control_partitions"] = partitions
    config["partition_mask"] = partition_mask_from_items(partitions)
    config["zones"] = zones
    config["control_outputs"] = outputs
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    mapped_zones = sum(1 for zone in zones if int(zone.get("partition", 0) or 0))
    return (
        "Import DLOADX OK\n"
        f"Partycje enabled=True: {len(partitions)}\n"
        f"Maska partycji ustawiona automatycznie: {config['partition_mask']}\n"
        f"Wejscia enabled=True: {len(zones)} (z przypisana partycja: {mapped_zones})\n"
        f"Wyjscia enabled=True: {len(outputs)}\n"
        "Konfiguracja zapisana. Pobierz ponownie XML wejsc i sterowania do Loxone."
    )


def load_config():
    source_file = CONFIG_FILE
    if not source_file.exists():
        for legacy_file in LEGACY_CONFIG_FILES:
            if legacy_file.exists():
                source_file = legacy_file
                break
    if source_file.exists():
        try:
            with source_file.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            merged = DEFAULT_CONFIG.copy()
            merged.update(loaded)
            merged["commands"] = DEFAULT_CONFIG["commands"] | loaded.get("commands", {})
            merged["zones"] = normalize_zones(loaded.get("zones", []))
            merged["control_partitions"] = normalize_numbered_items(
                loaded.get("control_partitions", DEFAULT_CONFIG["control_partitions"]), 32, "Partycja"
            )
            merged["control_outputs"] = normalize_numbered_items(
                loaded.get("control_outputs", []), 128, "Wyjscie"
            )
            merged["control_profiles"] = normalize_control_profiles(loaded.get("control_profiles", []))
            merged["temperature_zones"] = normalize_numbered_items(
                loaded.get("temperature_zones", []), 256, "Temperatura"
            )
            return merged
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def form_bool(form, name):
    return form.getfirst(name, "") == "1"


def form_text(form, config, name, default=None, strip_slashes=False, fallback=None):
    value = form.getfirst(name, config.get(name, default if default is not None else "")).strip()
    if strip_slashes:
        value = value.strip("/")
    if fallback is not None and not value:
        return fallback
    return value


def form_int(form, config, name, default):
    return int(float(form.getfirst(name, config.get(name, default))))


def form_float(form, config, name, default):
    return float(form.getfirst(name, config.get(name, default)))


def update_secret_from_form(config, form, key, clear_field, input_field):
    if form_bool(form, clear_field):
        config[key] = ""
        return
    new_value = form.getfirst(input_field, "").strip()
    if new_value:
        config[key] = new_value


def commands_from_form(form, config):
    current = config.get("commands", {})
    return {
        name: form.getfirst(field, current.get(name, DEFAULT_CONFIG["commands"][name])).strip()
        for name, field in COMMAND_FORM_FIELDS.items()
    }


def save_config(form):
    config = load_config()
    config["ethm_host"] = form_text(form, config, "ethm_host")
    config["ethm_port"] = form_int(form, config, "ethm_port", config["ethm_port"])
    config["ethm_timeout"] = form_float(form, config, "ethm_timeout", config["ethm_timeout"])
    config["ethm_encryption_enabled"] = form_bool(form, "ethm_encryption_enabled")
    update_secret_from_form(config, form, "ethm_integration_key", "clear_ethm_integration_key", "ethm_integration_key")
    config["debug_logging"] = form_bool(form, "debug_logging")
    update_secret_from_form(config, form, "satel_user_code", "clear_satel_user_code", "satel_user_code")
    config["status_poll_interval"] = form_float(form, config, "status_poll_interval", config["poll_interval"])
    config["poll_interval"] = config["status_poll_interval"]
    config["status_send_on_change"] = form_bool(form, "status_send_on_change")
    config["status_full_refresh_interval"] = form_float(form, config, "status_full_refresh_interval", 30.0)
    config["push_enabled"] = form_bool(form, "push_enabled")
    config["push_reconnect_interval"] = form_float(form, config, "push_reconnect_interval", 10.0)
    config["push_debounce_seconds"] = form_float(form, config, "push_debounce_seconds", 0.3)
    config["partition_mask"] = form_int(form, config, "partition_mask", config["partition_mask"])
    config["send_partition_details"] = form_bool(form, "send_partition_details")
    config["send_ready_inferred"] = form_bool(form, "send_ready_inferred")
    config["send_diagnostics"] = form_bool(form, "send_diagnostics")
    config["watchdog_status_max_age"] = form_float(form, config, "watchdog_status_max_age", 30.0)
    config["watchdog_push_max_age"] = form_float(form, config, "watchdog_push_max_age", 300.0)
    config["loxone_host"] = form_text(form, config, "loxone_host")
    config["loxone_udp_port"] = form_int(form, config, "loxone_udp_port", config["loxone_udp_port"])
    config["udp_sender_address"] = form_text(form, config, "udp_sender_address", "")
    config["mqtt_enabled"] = form_bool(form, "mqtt_enabled")
    config["mqtt_host"] = form_text(form, config, "mqtt_host", "localhost")
    config["mqtt_port"] = form_int(form, config, "mqtt_port", 1883)
    config["mqtt_timeout"] = form_float(form, config, "mqtt_timeout", 3.0)
    config["mqtt_keepalive"] = form_int(form, config, "mqtt_keepalive", 60)
    config["mqtt_reconnect_interval"] = form_float(form, config, "mqtt_reconnect_interval", 10.0)
    config["mqtt_base_topic"] = form_text(form, config, "mqtt_base_topic", "satel", strip_slashes=True, fallback="satel")
    config["mqtt_username"] = form_text(form, config, "mqtt_username", "")
    config["mqtt_client_id"] = form_text(form, config, "mqtt_client_id", "")
    config["mqtt_retain"] = form_bool(form, "mqtt_retain")
    config["mqtt_publish_raw"] = form_bool(form, "mqtt_publish_raw")
    config["mqtt_control_enabled"] = form_bool(form, "mqtt_control_enabled")
    update_secret_from_form(config, form, "mqtt_password", "clear_mqtt_password", "mqtt_password")
    config["loxberry_control_url"] = form.getfirst(
        "loxberry_control_url",
        config.get("loxberry_control_url", "http://LOXBERRY_IP/plugins/satel_ethm/control.cgi"),
    ).strip()
    token = form.getfirst("control_token", config.get("control_token", "")).strip()
    if form_bool(form, "regenerate_control_token") or not token:
        token = secrets.token_urlsafe(18)
    config["control_token"] = token
    config["allowed_control_ips"] = form_text(form, config, "allowed_control_ips", "")
    config["default_control_partition"] = form_int(form, config, "default_control_partition", 1)
    config["control_confirm_enabled"] = form_bool(form, "control_confirm_enabled")
    config["control_confirm_blocking"] = form_bool(form, "control_confirm_blocking")
    config["control_confirm_timeout"] = form_float(form, config, "control_confirm_timeout", 20.0)
    config["control_confirm_interval"] = form_float(form, config, "control_confirm_interval", 0.5)
    config["send_masks"] = form_bool(form, "send_masks")
    config["send_trouble_details"] = form_bool(form, "send_trouble_details")
    config["poll_zones"] = form_bool(form, "poll_zones")
    config["zones_poll_interval"] = form_float(form, config, "zones_poll_interval", 1.0)
    config["zones_send_on_change"] = form_bool(form, "zones_send_on_change")
    config["zones_full_refresh_interval"] = form_float(form, config, "zones_full_refresh_interval", 30.0)
    config["zone_hold_seconds"] = form_float(form, config, "zone_hold_seconds", 3.0)
    config["zone_status_command"] = form.getfirst(
        "zone_status_command",
        config.get("zone_status_command", "FE FE 00 D7 E2 FE 0D"),
    ).strip()
    config["poll_zone_bypass"] = form_bool(form, "poll_zone_bypass")
    config["zone_bypass_status_command"] = form.getfirst(
        "zone_bypass_status_command",
        config.get("zone_bypass_status_command", "FE FE 06 D7 E8 FE 0D"),
    ).strip()
    config["poll_zone_diagnostics"] = form_bool(form, "poll_zone_diagnostics")
    config["zone_tamper_status_command"] = form.getfirst(
        "zone_tamper_status_command",
        config.get("zone_tamper_status_command", "FE FE 01 D7 E3 FE 0D"),
    ).strip()
    config["zone_alarm_status_command"] = form.getfirst(
        "zone_alarm_status_command",
        config.get("zone_alarm_status_command", "FE FE 02 D7 E4 FE 0D"),
    ).strip()
    config["zone_alarm_memory_status_command"] = form.getfirst(
        "zone_alarm_memory_status_command",
        config.get("zone_alarm_memory_status_command", "FE FE 04 D7 E6 FE 0D"),
    ).strip()
    config["poll_outputs"] = form_bool(form, "poll_outputs")
    config["outputs_poll_interval"] = form_float(form, config, "outputs_poll_interval", 2.0)
    config["outputs_send_on_change"] = form_bool(form, "outputs_send_on_change")
    config["outputs_full_refresh_interval"] = form_float(form, config, "outputs_full_refresh_interval", 30.0)
    config["output_status_command"] = form_text(form, config, "output_status_command", "")
    config["poll_temperatures"] = form_bool(form, "poll_temperatures")
    config["temperature_poll_interval"] = form_float(form, config, "temperature_poll_interval", 60.0)
    config["temperature_timeout"] = form_float(form, config, "temperature_timeout", 5.0)
    config["send_temperature_raw"] = form_bool(form, "send_temperature_raw")
    zones_text = form.getfirst("zones_text", "")
    config["zones"] = parse_zones_text(zones_text)
    config["temperature_zones"] = parse_temperature_zones_text(form.getfirst("temperature_zones_text", ""))
    config["control_partitions"] = parse_partitions_text(form.getfirst("control_partitions_text", ""))
    config["control_outputs"] = parse_outputs_text(form.getfirst("control_outputs_text", ""))
    config["control_profiles"] = parse_control_profiles_text(form.getfirst("control_profiles_text", ""))
    config["commands"] = commands_from_form(form, config)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return config


def esc(value):
    return html.escape(str(value), quote=True)


def loxone_title(text):
    clean = []
    for char in str(text):
        if char.isalnum() or char in (" ", "_", "-", ".", "/"):
            clean.append(char)
    return "".join(clean).strip() or "SATEL Zone"


def add_udp_cmd(root, title, check, hint, source_low="0", source_high="1", dest_low="0", dest_high="1", min_val="0", max_val="1", unit="<v>"):
    ET.SubElement(
        root,
        "VirtualInUdpCmd",
        {
            "Title": title,
            "Comment": "",
            "Address": "",
            "Check": check,
            "Signed": "false",
            "Analog": "true",
            "SourceValLow": source_low,
            "DestValLow": dest_low,
            "SourceValHigh": source_high,
            "DestValHigh": dest_high,
            "DefVal": "0",
            "MinVal": min_val,
            "MaxVal": max_val,
            "Unit": unit,
            "HintText": hint,
        },
    )


def control_url_parts(config):
    raw_url = str(
        config.get("loxberry_control_url", "http://LOXBERRY_IP/plugins/satel_ethm/control.cgi")
    ).strip()
    loxberry_ip = str(config.get("udp_sender_address", "")).strip()
    if loxberry_ip and "LOXBERRY_IP" in raw_url:
        raw_url = raw_url.replace("LOXBERRY_IP", loxberry_ip)
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme and parsed.netloc:
        base = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/plugins/satel_ethm/control.cgi"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return base.rstrip("/"), path
    return raw_url.rstrip("/"), "/plugins/satel_ethm/control.cgi"


def with_token(config, params):
    token = str(config.get("control_token", "")).strip()
    merged = dict(params)
    if token:
        merged["token"] = token
    _base, path = control_url_parts(config)
    separator = "&" if "?" in path else "?"
    return path + separator + urllib.parse.urlencode(merged)


def add_http_cmd(root, title, command_on, command_off="", hint="", comment=""):
    attrs = {
        "Title": title,
        "Comment": comment,
        "CmdOnMethod": "GET",
        "CmdOffMethod": "GET",
        "CmdOn": command_on,
        "CmdOnHTTP": "",
        "CmdOnPost": "",
        "CmdOff": command_off,
        "CmdOffHTTP": "",
        "CmdOffPost": "",
        "CmdAnswer": "",
        "Analog": "false",
        "Repeat": "0",
        "RepeatRate": "0",
        "HintText": hint,
    }
    ET.SubElement(root, "VirtualOutCmd", attrs)


def hex_to_bytes(value):
    cleaned = str(value).replace("\\x", " ").replace(",", " ").replace("-", " ")
    parts = [part for part in cleaned.split() if part]
    return bytes(int(part, 16) for part in parts)


def command_code(frame):
    if len(frame) < 3 or frame[:2] != b"\xfe\xfe":
        raise ValueError("Komenda SATEL musi zaczynać się od FE FE")
    return frame[2]


def find_response_frame(buffer, cmd):
    marker = b"\xfe\xfe" + bytes([cmd])
    start = buffer.find(marker)
    if start < 0:
        return None
    end = buffer.find(b"\xfe\x0d", start + 3)
    if end < 0:
        return None
    return buffer[start:end + 2]


def mask_from_response(response):
    data = response[3:-4]
    mask = 0
    for index, byte in enumerate(data[:4]):
        mask |= byte << (index * 8)
    return mask


def write_json_atomic(path, payload):
    tmp_path = Path(f"{path}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
        fh.write("\n")
    tmp_path.replace(path)


def save_config_payload(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def normalized_config_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Plik konfiguracji musi zawierać obiekt JSON")
    if "config" in payload and isinstance(payload["config"], dict):
        payload = payload["config"]
    required_any = {"ethm_host", "loxone_host", "commands", "control_partitions", "zones", "control_outputs"}
    if not (set(payload.keys()) & required_any):
        raise ValueError("To nie wygląda jak konfiguracja SATEL ETHM Bridge")
    config = DEFAULT_CONFIG.copy()
    config.update(payload)
    config["commands"] = DEFAULT_CONFIG["commands"] | payload.get("commands", {})
    config["zones"] = normalize_zones(payload.get("zones", []))
    config["control_partitions"] = normalize_numbered_items(
        payload.get("control_partitions", DEFAULT_CONFIG["control_partitions"]), 32, "Partycja"
    )
    config["control_outputs"] = normalize_numbered_items(payload.get("control_outputs", []), 128, "Wyjscie")
    config["control_profiles"] = normalize_control_profiles(payload.get("control_profiles", []))
    config["temperature_zones"] = normalize_numbered_items(payload.get("temperature_zones", []), 256, "Temperatura")
    return config


def download_config_backup(config):
    data = json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print("Content-Type: application/json; charset=utf-8")
    print(f'Content-Disposition: attachment; filename="satel_ethm_config_{stamp}.json"')
    print(f"Content-Length: {len(data)}")
    print()
    sys.stdout.flush()
    sys.stdout.buffer.write(data)


def restore_config_backup(form):
    upload = form["config_file"] if "config_file" in form else None
    if upload is None or not getattr(upload, "file", None):
        raise ValueError("Nie wybrano pliku konfiguracji JSON")
    data = upload.file.read()
    if not data:
        raise ValueError("Plik konfiguracji jest pusty")
    payload = json.loads(data.decode("utf-8"))
    config = normalized_config_payload(payload)
    save_config_payload(config)
    return (
        "Restore konfiguracji OK\n"
        f"Partycje: {len(config.get('control_partitions', []))}\n"
        f"Wejscia: {len(config.get('zones', []))}\n"
        f"Wyjscia: {len(config.get('control_outputs', []))}\n"
        "Usługa odczyta zmiany automatycznie w następnej pętli."
    )


def queue_bridge_test(test_name):
    CONTROL_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    request_id = secrets.token_hex(12)
    request_path = CONTROL_QUEUE_DIR / f"{request_id}.request.json"
    response_path = CONTROL_QUEUE_DIR / f"{request_id}.response.json"
    write_json_atomic(
        request_path,
        {
            "created": time.time(),
            "kind": "test",
            "test": test_name,
            "source": "index.cgi",
        },
    )
    deadline = time.time() + 8.0
    while time.time() < deadline:
        if response_path.exists():
            try:
                with response_path.open("r", encoding="utf-8") as fh:
                    response = json.load(fh)
            finally:
                try:
                    response_path.unlink()
                except Exception:
                    pass
            if response.get("ok"):
                return response.get("message", "")
            raise RuntimeError(response.get("message", "bridge test failed"))
        time.sleep(0.1)
    try:
        request_path.unlink()
    except Exception:
        pass
    raise TimeoutError("bridge test timeout")


def queue_control_command(config, params):
    CONTROL_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    request_id = secrets.token_hex(12)
    request_path = CONTROL_QUEUE_DIR / f"{request_id}.request.json"
    response_path = CONTROL_QUEUE_DIR / f"{request_id}.response.json"
    write_json_atomic(
        request_path,
        {
            "created": time.time(),
            "params": params,
            "source": "index.cgi",
        },
    )
    confirm_timeout = 0.0
    if config.get("control_confirm_blocking", False):
        try:
            confirm_timeout = float(config.get("control_confirm_timeout", 20.0))
        except Exception:
            confirm_timeout = 20.0
    deadline = time.time() + max(4.0, float(config.get("ethm_timeout", 2.0)) + confirm_timeout + 5.0)
    while time.time() < deadline:
        if response_path.exists():
            try:
                with response_path.open("r", encoding="utf-8") as fh:
                    response = json.load(fh)
            finally:
                try:
                    response_path.unlink()
                except Exception:
                    pass
            prefix = "Test sterowania OK" if response.get("ok") else "Test sterowania ERROR"
            return prefix + "\n" + response.get("message", "")
        time.sleep(0.1)
    try:
        request_path.unlink()
    except Exception:
        pass
    raise TimeoutError("control queue timeout")


def query_ethm_for_test(config, command_hex):
    frame = hex_to_bytes(command_hex)
    cmd = command_code(frame)
    host = str(config.get("ethm_host", "")).strip()
    port = int(config.get("ethm_port", 7094))
    timeout = float(config.get("ethm_timeout", 2.0))
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(frame)
        buffer = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            response = find_response_frame(buffer, cmd)
            if response:
                return response
    raise TimeoutError(f"Brak odpowiedzi SATEL na komendę 0x{cmd:02X}")


def test_ethm(config):
    try:
        return queue_bridge_test("ethm")
    except Exception as queue_exc:
        prefix = f"Bridge queue niedostępna ({queue_exc}), próbuję bezpośrednio.\n"
        response = query_ethm_for_test(config, config["commands"]["armed"])
        return prefix + "Test ETHM OK\n" + f"armed response: {response.hex(' ').upper()}\nmask={mask_from_response(response)}"


def test_statuses(config):
    try:
        return queue_bridge_test("statuses")
    except Exception as queue_exc:
        lines = [f"Bridge queue niedostępna ({queue_exc}), próbuję bezpośrednio.", "Test statusów OK"]
        for name, command in config.get("commands", {}).items():
            response = query_ethm_for_test(config, command)
            lines.append(f"{name}: {response.hex(' ').upper()} mask={mask_from_response(response)}")
        return "\n".join(lines)
    lines = ["Test statusów OK"]
    for name, command in config.get("commands", {}).items():
        response = query_ethm_for_test(config, command)
        lines.append(f"{name}: {response.hex(' ').upper()} mask={mask_from_response(response)}")
    return "\n".join(lines)


def test_zones(config):
    try:
        return queue_bridge_test("zones")
    except Exception as queue_exc:
        prefix = f"Bridge queue niedostępna ({queue_exc}), próbuję bezpośrednio.\n"
    else:
        prefix = ""
    tests = [
        ("violation", config.get("zone_status_command", "FE FE 00 D7 E2 FE 0D")),
        ("bypass", config.get("zone_bypass_status_command", "FE FE 06 D7 E8 FE 0D")),
        ("tamper", config.get("zone_tamper_status_command", "FE FE 01 D7 E3 FE 0D")),
        ("alarm", config.get("zone_alarm_status_command", "FE FE 02 D7 E4 FE 0D")),
        ("alarm_memory", config.get("zone_alarm_memory_status_command", "FE FE 04 D7 E6 FE 0D")),
    ]
    lines = [prefix + "Test wejść OK"]
    for name, command in tests:
        response = query_ethm_for_test(config, command)
        lines.append(f"{name}: {response.hex(' ').upper()} mask={mask_from_response(response)}")
    return "\n".join(lines)


def test_udp(config):
    try:
        return queue_bridge_test("udp")
    except Exception as queue_exc:
        prefix = f"Bridge queue niedostępna ({queue_exc}), próbuję bezpośrednio.\n"
    else:
        prefix = ""
    host = str(config.get("loxone_host", "")).strip()
    port = int(config.get("loxone_udp_port", 7007))
    payload = b"SATEL_TEST=1"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        sent = udp.sendto(payload, (host, port))
    return prefix + f"Test UDP OK\nsent {payload.decode()} to {host}:{port} bytes={sent}"


def autotest_config(config):
    checks = []

    def add(name, ok, detail=""):
        checks.append((name, "OK" if ok else "UWAGA", detail))

    add("Plik konfiguracji", CONFIG_FILE.exists(), str(CONFIG_FILE))
    add("Adres ETHM", bool(str(config.get("ethm_host", "")).strip()), str(config.get("ethm_host", "")))
    add("Port ETHM", 1 <= int(config.get("ethm_port", 0)) <= 65535, str(config.get("ethm_port", "")))
    if config.get("ethm_encryption_enabled", False):
        add("Kodowanie ETHM", bool(str(config.get("ethm_integration_key", "")).strip()), "wlaczone")
    else:
        add("Kodowanie ETHM", True, "wylaczone")
    add("Adres UDP Loxone", bool(str(config.get("loxone_host", "")).strip()), str(config.get("loxone_host", "")))
    add("Port UDP Loxone", 1 <= int(config.get("loxone_udp_port", 0)) <= 65535, str(config.get("loxone_udp_port", "")))
    add("Token sterowania", bool(str(config.get("control_token", "")).strip()), "ustawiony" if config.get("control_token") else "brak")
    add(
        "Dozwolone IP sterowania",
        bool(str(config.get("allowed_control_ips", "")).strip()),
        str(config.get("allowed_control_ips", "")).strip() or "puste - kazdy host z tokenem moze wywolac control.cgi",
    )
    add("Kod uzytkownika SATEL", bool(str(config.get("satel_user_code", "")).strip()), "ustawiony" if config.get("satel_user_code") else "brak - sterowanie nie zadziala")
    add("Partycje", bool(config.get("control_partitions", [])), f"{len(config.get('control_partitions', []))} szt.")
    add("Wejscia", bool(config.get("zones", [])), f"{len(config.get('zones', []))} szt.")
    add("Wyjscia", True, f"{len(config.get('control_outputs', []))} szt.")
    add("Profile sterowania", True, f"{len(config.get('control_profiles', []))} szt.")
    add("Status uslugi", service_status() == "active", service_status())

    network_tests = []
    for label, fn, enabled in [
        ("ETHM", test_ethm, True),
        ("Statusy", test_statuses, True),
        ("Wejscia", test_zones, bool(config.get("poll_zones", False)) and bool(config.get("zones", []))),
        ("UDP", test_udp, True),
    ]:
        if not enabled:
            network_tests.append(f"{label}: pominieto")
            continue
        try:
            result = fn(config)
            first_line = result.splitlines()[0] if result else "OK"
            network_tests.append(f"{label}: OK - {first_line}")
        except Exception as exc:
            network_tests.append(f"{label}: ERROR - {exc}")

    lines = ["Autotest konfiguracji"]
    lines.extend(f"{name}: {status} {detail}" for name, status, detail in checks)
    lines.append("")
    lines.append("Testy komunikacji")
    lines.extend(network_tests)
    return "\n".join(lines)


def control_test_params(form):
    action = form.getfirst("action", "")
    action_map = {
        "test_control_arm": "arm",
        "test_control_force_arm": "force_arm",
        "test_control_disarm": "disarm",
        "test_control_clear_alarm": "clear_alarm",
        "test_control_clear_trouble": "clear_trouble",
        "test_control_output_on": "output_on",
        "test_control_output_off": "output_off",
        "test_control_output_toggle": "output_toggle",
    }
    if action not in action_map:
        raise ValueError(f"Nieobsługiwana akcja testu sterowania: {action}")
    params = {"action": action_map[action]}
    if action in ("test_control_arm", "test_control_force_arm"):
        params["mode"] = str(max(0, min(3, int(form.getfirst("test_mode", "0")))))
    if action in ("test_control_arm", "test_control_force_arm", "test_control_disarm", "test_control_clear_alarm"):
        partition = str(form.getfirst("test_partition", "1")).strip()
        if partition.lower() in ("all", "wszystko", "*"):
            params["partitions"] = "all"
        else:
            params["partition"] = partition
    if action in ("test_control_output_on", "test_control_output_off", "test_control_output_toggle"):
        params["output"] = str(int(form.getfirst("test_output", "0")))
    return params


def generate_zones_xml(config):
    root = ET.Element(
        "VirtualInUdp",
        {
            "Title": "SATEL ETHM Wejscia",
            "Comment": "",
            "Address": str(config.get("udp_sender_address", "")),
            "Port": str(config.get("loxone_udp_port", 7007)),
        },
    )
    ET.SubElement(root, "Info", {"templateType": "1", "minVersion": "15050304"})
    add_udp_cmd(root, "SATEL_Uzbrojony", "SATEL_ARMED=\\v", "Uzbrojenie partycji SATEL 0/1")
    add_udp_cmd(root, "SATEL_Alarm", "SATEL_ALARM=\\v", "Alarm w partycji SATEL 0/1")
    add_udp_cmd(root, "SATEL_Alarm_Pozarowy", "SATEL_FIRE_ALARM=\\v", "Alarm pozarowy partycji SATEL 0/1")
    add_udp_cmd(root, "SATEL_Pamiec_Alarmu", "SATEL_ALARM_MEMORY=\\v", "Pamiec alarmu partycji SATEL 0/1")
    add_udp_cmd(root, "SATEL_Awaria", "SATEL_TROUBLE=\\v", "Awaria SATEL 0/1")
    add_udp_cmd(root, "SATEL_Czas_Na_Wejscie", "SATEL_ENTRY_TIME=\\v", "Czas na wejscie partycji SATEL 0/1")
    add_udp_cmd(root, "SATEL_Czas_Na_Wyjscie", "SATEL_EXIT_TIME=\\v", "Czas na wyjscie partycji SATEL 0/1")
    add_udp_cmd(root, "SATEL_Czas_Na_Wyjscie_Dlugi", "SATEL_EXIT_TIME_LONG=\\v", "Czas na wyjscie powyzej 10 s 0/1")
    add_udp_cmd(root, "SATEL_Czas_Na_Wyjscie_Krotki", "SATEL_EXIT_TIME_SHORT=\\v", "Czas na wyjscie ponizej 10 s 0/1")
    add_udp_cmd(root, "SATEL_Online", "SATEL_ONLINE=\\v", "Lacznosc z ETHM 0/1")
    add_udp_cmd(root, "SATEL_Error", "SATEL_ERROR=\\v", "Blad jednej z komend odczytu 0/1")
    if config.get("send_ready_inferred", True):
        add_udp_cmd(root, "SATEL_Gotowy_Inferred", "SATEL_READY_INFERRED=\\v", "Wyliczona gotowosc do uzbrojenia 0/1")
        add_udp_cmd(root, "SATEL_Gotowy_Wejscia_OK", "SATEL_READY_ZONES_OK=\\v", "Brak naruszonych monitorowanych wejsc 0/1")
        add_udp_cmd(root, "SATEL_Gotowy_Sabotaz_OK", "SATEL_READY_TAMPER_OK=\\v", "Brak sabotazu monitorowanych wejsc 0/1")
        add_udp_cmd(root, "SATEL_Gotowy_Awarie_OK", "SATEL_READY_TROUBLE_OK=\\v", "Brak awarii systemowej 0/1")
        add_udp_cmd(root, "SATEL_Gotowy_Alarm_OK", "SATEL_READY_ALARM_OK=\\v", "Brak alarmu partycji 0/1")
    if config.get("send_partition_details", True):
        for partition in normalize_numbered_items(config.get("control_partitions", DEFAULT_CONFIG["control_partitions"]), 32, "Partycja"):
            number = int(partition["number"])
            title = loxone_title(f"SATEL_P{number:03d}_{partition['name']}")
            prefix = f"SATEL_PARTITION_{number:03d}"
            add_udp_cmd(root, f"{title}_Uzbrojona", f"{prefix}_ARMED=\\v", f"Partycja {number} uzbrojona 0/1")
            add_udp_cmd(root, f"{title}_Rozbrojona", f"{prefix}_DISARMED=\\v", f"Partycja {number} rozbrojona 0/1")
            add_udp_cmd(root, f"{title}_Alarm", f"{prefix}_ALARM=\\v", f"Alarm partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Alarm_Pozarowy", f"{prefix}_FIRE_ALARM=\\v", f"Alarm pozarowy partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Pamiec_Alarmu", f"{prefix}_ALARM_MEMORY=\\v", f"Pamiec alarmu partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Czas_Wejscia", f"{prefix}_ENTRY_TIME=\\v", f"Czas na wejscie partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Czas_Wyjscia", f"{prefix}_EXIT_TIME=\\v", f"Czas na wyjscie partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Czas_Wyjscia_Dlugi", f"{prefix}_EXIT_TIME_LONG=\\v", f"Czas na wyjscie >10 s partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Czas_Wyjscia_Krotki", f"{prefix}_EXIT_TIME_SHORT=\\v", f"Czas na wyjscie <=10 s partycji {number} 0/1")
            if config.get("send_ready_inferred", True):
                add_udp_cmd(root, f"{title}_Gotowa_Inferred", f"{prefix}_READY_INFERRED=\\v", f"Wyliczona gotowosc partycji {number} 0/1")
                add_udp_cmd(root, f"{title}_Gotowa_Wejscia_OK", f"{prefix}_READY_ZONES_OK=\\v", f"Brak naruszonych wejsc mapowanych do partycji {number} 0/1")
                add_udp_cmd(root, f"{title}_Gotowa_Sabotaz_OK", f"{prefix}_READY_TAMPER_OK=\\v", f"Brak sabotazu wejsc mapowanych do partycji {number} 0/1")
                add_udp_cmd(root, f"{title}_Gotowa_Awarie_OK", f"{prefix}_READY_TROUBLE_OK=\\v", f"Brak awarii dla gotowosci partycji {number} 0/1")
                add_udp_cmd(root, f"{title}_Gotowa_Alarm_OK", f"{prefix}_READY_ALARM_OK=\\v", f"Brak alarmu partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Wejscie_Any", f"{prefix}_ZONE_ANY=\\v", f"Dowolne naruszone wejscie mapowane do partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Bypass_Any", f"{prefix}_ZONE_BYPASS_ANY=\\v", f"Dowolne wejscie z bypass/blokada mapowane do partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Sabotaz_Any", f"{prefix}_ZONE_TAMPER_ANY=\\v", f"Dowolny sabotaz wejscia mapowanego do partycji {number} 0/1")
            add_udp_cmd(root, f"{title}_Alarm_Wejscia_Any", f"{prefix}_ZONE_ALARM_ANY=\\v", f"Dowolne wejscie mapowane do partycji {number} w alarmie 0/1")
            add_udp_cmd(root, f"{title}_Pamiec_Alarmu_Wejscia_Any", f"{prefix}_ZONE_ALARM_MEMORY_ANY=\\v", f"Dowolne wejscie mapowane do partycji {number} w pamieci alarmu 0/1")
    if config.get("send_diagnostics", True):
        add_udp_cmd(root, "SATEL_Diag_Uptime", "SATEL_DIAG_UPTIME=\\v", "Czas pracy uslugi w sekundach", source_high="999999999", dest_high="999999999", max_val="999999999")
        add_udp_cmd(root, "SATEL_Diag_Last_Status_OK_Age", "SATEL_DIAG_LAST_STATUS_OK_AGE=\\v", "Wiek ostatniego poprawnego statusu w sekundach", source_high="999999", dest_high="999999", max_val="999999")
        add_udp_cmd(root, "SATEL_Diag_Last_Push_Age", "SATEL_DIAG_LAST_PUSH_AGE=\\v", "Wiek ostatniej ramki push w sekundach", source_high="999999", dest_high="999999", max_val="999999")
        add_udp_cmd(root, "SATEL_Diag_Config_Reload_TS", "SATEL_DIAG_CONFIG_RELOAD_TS=\\v", "Znacznik czasu ostatniego cyklu diagnostyki", source_high="2147483647", dest_high="2147483647", max_val="2147483647")
        add_udp_cmd(root, "SATEL_Watchdog_OK", "SATEL_WATCHDOG_OK=\\v", "Watchdog komunikacji OK 0/1")
        add_udp_cmd(root, "SATEL_Watchdog_Status_OK", "SATEL_WATCHDOG_STATUS_OK=\\v", "Odczyt statusow SATEL w limicie czasu 0/1")
        add_udp_cmd(root, "SATEL_Watchdog_Push_OK", "SATEL_WATCHDOG_PUSH_OK=\\v", "Push SATEL w limicie czasu 0/1")
        add_udp_cmd(root, "SATEL_Watchdog_Status_Max_Age", "SATEL_WATCHDOG_STATUS_MAX_AGE=\\v", "Limit wieku statusu watchdog w sekundach", source_high="999999", dest_high="999999", max_val="999999")
        add_udp_cmd(root, "SATEL_Watchdog_Push_Max_Age", "SATEL_WATCHDOG_PUSH_MAX_AGE=\\v", "Limit wieku push watchdog w sekundach", source_high="999999", dest_high="999999", max_val="999999")
    add_udp_cmd(root, "SATEL_Control_OK", "SATEL_CONTROL_OK=\\v", "Ostatnia komenda sterujaca OK 0/1")
    add_udp_cmd(root, "SATEL_Control_Error", "SATEL_CONTROL_ERROR=\\v", "Blad ostatniej komendy sterujacej 0/1")
    add_udp_cmd(root, "SATEL_Control_Pending", "SATEL_CONTROL_PENDING=\\v", "Komenda sterujaca w trakcie potwierdzania 0/1")
    add_udp_cmd(root, "SATEL_Control_Accepted", "SATEL_CONTROL_ACCEPTED=\\v", "Ostatnia komenda przyjeta przez ETHM 0/1")
    add_udp_cmd(root, "SATEL_Control_Confirmed", "SATEL_CONTROL_CONFIRMED=\\v", "Ostatnia komenda potwierdzona odczytem stanu 0/1")
    add_udp_cmd(root, "SATEL_Control_Timeout", "SATEL_CONTROL_TIMEOUT=\\v", "Potwierdzenie ostatniej komendy przekroczylo timeout 0/1")
    add_udp_cmd(root, "SATEL_Control_Last_Code", "SATEL_CONTROL_LAST_CODE=\\v", "Kod wyniku ostatniej komendy sterujacej", source_high="999", dest_high="999", max_val="999")
    add_udp_cmd(root, "SATEL_Control_Last_Action", "SATEL_CONTROL_LAST_ACTION=\\v", "Typ ostatniej komendy sterujacej", source_high="99", dest_high="99", max_val="99")
    add_udp_cmd(root, "SATEL_Control_Seq", "SATEL_CONTROL_SEQ=\\v", "Licznik/czas ostatniej komendy sterujacej", source_high="999999999", dest_high="999999999", max_val="999999999")
    add_udp_cmd(root, "SATEL_Push_Connected", "SATEL_PUSH_CONNECTED=\\v", "Polaczenie push z ETHM 0/1")
    add_udp_cmd(root, "SATEL_Push_Reconnects", "SATEL_PUSH_RECONNECTS=\\v", "Licznik reconnectow push")
    if config.get("send_trouble_details", True):
        for title, check, hint in [
            ("SATEL_Awaria_Wejscia_Techniczne", "SATEL_TROUBLE_TECH_ZONE=\\v", "Awaria wejsc technicznych"),
            ("SATEL_Awaria_Ekspandery_AC", "SATEL_TROUBLE_EXPANDER_AC=\\v", "Awaria zasilania AC ekspanderow"),
            ("SATEL_Awaria_Ekspandery_Akumulator", "SATEL_TROUBLE_EXPANDER_BATT=\\v", "Awaria akumulatora ekspanderow"),
            ("SATEL_Awaria_Ekspandery_Brak_Akumulatora", "SATEL_TROUBLE_EXPANDER_NO_BATT=\\v", "Brak akumulatora ekspanderow"),
            ("SATEL_Awaria_Wyjscia", "SATEL_TROUBLE_OUT=\\v", "Awaria wyjsc OUT"),
            ("SATEL_Awaria_Zasilanie_KPD", "SATEL_TROUBLE_KPD_POWER=\\v", "Awaria zasilania manipulatorow"),
            ("SATEL_Awaria_Zasilanie_EXP", "SATEL_TROUBLE_EXP_POWER=\\v", "Awaria zasilania ekspanderow"),
            ("SATEL_Awaria_Akumulator", "SATEL_TROUBLE_BATTERY=\\v", "Awaria akumulatora centrali"),
            ("SATEL_Awaria_AC", "SATEL_TROUBLE_AC=\\v", "Awaria zasilania AC centrali"),
            ("SATEL_Awaria_Dialer", "SATEL_TROUBLE_DIALER=\\v", "Awaria dialera"),
            ("SATEL_Awaria_RTC", "SATEL_TROUBLE_RTC=\\v", "Awaria zegara RTC"),
            ("SATEL_Awaria_DTR", "SATEL_TROUBLE_DTR=\\v", "Brak DTR/komunikacji INT-RS"),
            ("SATEL_Awaria_Brak_Akumulatora", "SATEL_TROUBLE_NO_BATTERY=\\v", "Brak akumulatora"),
            ("SATEL_Awaria_Modem", "SATEL_TROUBLE_MODEM=\\v", "Awaria modemu"),
            ("SATEL_Awaria_Linia_Telefoniczna", "SATEL_TROUBLE_PHONE_LINE=\\v", "Awaria linii telefonicznej"),
            ("SATEL_Awaria_Monitoring", "SATEL_TROUBLE_MONITORING=\\v", "Awaria monitoringu"),
            ("SATEL_Awaria_Pamiec", "SATEL_TROUBLE_MEMORY=\\v", "Awaria/pamiec systemowa"),
        ]:
            add_udp_cmd(root, title, check, hint)
    add_udp_cmd(root, "SATEL_Zone_Any", "SATEL_ZONE_ANY=\\v", "Dowolne naruszone wejscie SATEL")
    add_udp_cmd(root, "SATEL_Zone_Bypass_Any", "SATEL_ZONE_BYPASS_ANY=\\v", "Dowolne wejscie SATEL z bypass/blokada")
    add_udp_cmd(root, "SATEL_Zone_Tamper_Any", "SATEL_ZONE_TAMPER_ANY=\\v", "Dowolny sabotaz wejscia SATEL")
    add_udp_cmd(root, "SATEL_Zone_Alarm_Any", "SATEL_ZONE_ALARM_ANY=\\v", "Dowolne wejscie w alarmie SATEL")
    add_udp_cmd(root, "SATEL_Zone_Alarm_Memory_Any", "SATEL_ZONE_ALARM_MEMORY_ANY=\\v", "Dowolne wejscie w pamieci alarmu SATEL")
    for zone in normalize_zones(config.get("zones", [])):
        number = int(zone["number"])
        title = loxone_title(f"SATEL_Z{number:03d}_{zone['name']}")
        partition_hint = f", partycja {zone['partition']}" if int(zone.get("partition", 0) or 0) else ""
        add_udp_cmd(root, title, f"SATEL_ZONE_{number:03d}=\\v", f"Wejscie {number}{partition_hint}: {zone['name']}")
        add_udp_cmd(root, f"{title}_Bypass", f"SATEL_ZONE_{number:03d}_BYPASS=\\v", f"Bypass/blokada wejscia {number}{partition_hint}: {zone['name']}")
        add_udp_cmd(root, f"{title}_Tamper", f"SATEL_ZONE_{number:03d}_TAMPER=\\v", f"Sabotaz wejscia {number}: {zone['name']}")
        add_udp_cmd(root, f"{title}_Alarm", f"SATEL_ZONE_{number:03d}_ALARM=\\v", f"Alarm wejscia {number}: {zone['name']}")
        add_udp_cmd(root, f"{title}_Alarm_Memory", f"SATEL_ZONE_{number:03d}_ALARM_MEMORY=\\v", f"Pamiec alarmu wejscia {number}: {zone['name']}")
    add_udp_cmd(root, "SATEL_Output_Any", "SATEL_OUTPUT_ANY=\\v", "Dowolne aktywne wyjscie SATEL")
    for output in normalize_numbered_items(config.get("control_outputs", []), 128, "Wyjscie"):
        number = int(output["number"])
        title = loxone_title(f"SATEL_OUT{number:03d}_{output['name']}")
        add_udp_cmd(root, title, f"SATEL_OUTPUT_{number:03d}=\\v", f"Stan wyjscia {number}: {output['name']}")
    for zone in normalize_numbered_items(config.get("temperature_zones", []), 256, "Temperatura"):
        number = int(zone["number"])
        title = loxone_title(f"SATEL_TEMP{number:03d}_{zone['name']}")
        add_udp_cmd(
            root,
            title,
            f"SATEL_TEMP_{number:03d}=\\v",
            f"Temperatura z wejscia {number}: {zone['name']}",
            source_low="-50",
            source_high="100",
            dest_low="-50",
            dest_high="100",
            min_val="-50",
            max_val="100",
            unit="C",
        )
    ET.indent(root, space=" ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


def xml_cmd_key(element):
    check = element.attrib.get("Check", "")
    return check.split("=", 1)[0]


XML_SECTION_TITLES = {
    "basic": "Statusy podstawowe",
    "partitions": "Partycje",
    "zones": "Wejscia",
    "outputs": "Wyjscia",
    "diagnostics": "Diagnostyka",
}


def section_accepts_key(section, key):
    basic_keys = {
        "SATEL_ARMED",
        "SATEL_ALARM",
        "SATEL_FIRE_ALARM",
        "SATEL_ALARM_MEMORY",
        "SATEL_TROUBLE",
        "SATEL_ENTRY_TIME",
        "SATEL_EXIT_TIME",
        "SATEL_EXIT_TIME_LONG",
        "SATEL_EXIT_TIME_SHORT",
        "SATEL_ONLINE",
        "SATEL_ERROR",
        "SATEL_READY_INFERRED",
        "SATEL_READY_ZONES_OK",
        "SATEL_READY_TAMPER_OK",
        "SATEL_READY_TROUBLE_OK",
        "SATEL_READY_ALARM_OK",
        "SATEL_ARMED_MASK",
        "SATEL_ALARM_MASK",
        "SATEL_FIRE_ALARM_MASK",
        "SATEL_ALARM_MEMORY_MASK",
        "SATEL_TROUBLE_MASK",
        "SATEL_ENTRY_TIME_MASK",
        "SATEL_EXIT_TIME_LONG_MASK",
        "SATEL_EXIT_TIME_SHORT_MASK",
    }
    if section == "basic":
        return key in basic_keys or key.startswith("SATEL_TROUBLE_")
    if section == "partitions":
        return key.startswith("SATEL_PARTITION_")
    if section == "zones":
        return key.startswith("SATEL_ZONE_")
    if section == "outputs":
        return key.startswith("SATEL_OUTPUT_")
    if section == "diagnostics":
        return (
            key.startswith("SATEL_DIAG_")
            or key.startswith("SATEL_CONTROL_")
            or key.startswith("SATEL_PUSH_")
            or key.startswith("SATEL_WATCHDOG_")
        )
    return True


def lite_accepts_key(key):
    lite_global_keys = {
        "SATEL_ARMED",
        "SATEL_ALARM",
        "SATEL_FIRE_ALARM",
        "SATEL_TROUBLE",
        "SATEL_ENTRY_TIME",
        "SATEL_EXIT_TIME",
        "SATEL_EXIT_TIME_LONG",
        "SATEL_EXIT_TIME_SHORT",
        "SATEL_ONLINE",
        "SATEL_ERROR",
        "SATEL_ZONE_ANY",
    }
    if key in lite_global_keys:
        return True
    if key.startswith("SATEL_PARTITION_"):
        return key.endswith((
            "_ARMED",
            "_DISARMED",
            "_ALARM",
            "_FIRE_ALARM",
            "_ENTRY_TIME",
            "_EXIT_TIME",
            "_EXIT_TIME_LONG",
            "_EXIT_TIME_SHORT",
            "_ZONE_ANY",
        ))
    if key.startswith("SATEL_ZONE_"):
        suffix = key.removeprefix("SATEL_ZONE_")
        return suffix.isdigit() and len(suffix) == 3
    return False


def generate_filtered_zones_xml(config, title, comment, accept_key):
    full_root = ET.fromstring(generate_zones_xml(config))
    root = ET.Element(
        "VirtualInUdp",
        {
            "Title": title,
            "Comment": comment,
            "Address": full_root.attrib.get("Address", ""),
            "Port": full_root.attrib.get("Port", str(config.get("loxone_udp_port", 7007))),
        },
    )
    for child in full_root:
        if child.tag == "Info":
            ET.SubElement(root, "Info", dict(child.attrib))
            continue
        if child.tag != "VirtualInUdpCmd":
            continue
        if accept_key(xml_cmd_key(child)):
            ET.SubElement(root, "VirtualInUdpCmd", dict(child.attrib))
    ET.indent(root, space=" ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


def generate_zones_xml_section(config, section):
    section_titles = {
        "basic": "SATEL ETHM Statusy",
        "partitions": "SATEL ETHM Partycje",
        "zones": "SATEL ETHM Wejscia",
        "outputs": "SATEL ETHM Wyjscia",
        "diagnostics": "SATEL ETHM Diagnostyka",
    }
    return generate_filtered_zones_xml(
        config,
        section_titles.get(section, "SATEL ETHM Wejscia"),
        f"Sekcja {section}",
        lambda key: section_accepts_key(section, key),
    )


def generate_zones_xml_custom(config, sections):
    selected = [section for section in sections if section in XML_SECTION_TITLES]
    if not selected:
        selected = ["basic"]
    title_suffix = ", ".join(XML_SECTION_TITLES[section] for section in selected)
    return generate_filtered_zones_xml(
        config,
        "SATEL ETHM Wybrane",
        f"Sekcje: {title_suffix}",
        lambda key: any(section_accepts_key(section, key) for section in selected),
    )


def generate_zones_xml_lite(config):
    return generate_filtered_zones_xml(
        config,
        "SATEL ETHM Lite",
        "Wersja lite: podstawowe statusy, alarmy, awarie i naruszenia wejsc bez szczegolow",
        lite_accepts_key,
    )


def create_control_root(config, title, comment):
    control_base_url, _control_path = control_url_parts(config)
    root = ET.Element(
        "VirtualOut",
        {
            "HintText": "",
            "Title": title,
            "Comment": comment,
            "Address": control_base_url,
            "CmdInit": "",
            "CloseAfterSend": "true",
            "CmdSep": "",
        },
    )
    ET.SubElement(root, "Info", {"templateType": "3", "minVersion": "17000331"})
    return root


def add_all_partitions_control_commands(root, config, modes):
    partitions = normalize_numbered_items(config.get("control_partitions", []), 32, "Partycja")
    if not partitions:
        return
    for mode in modes:
        add_http_cmd(
            root,
            loxone_title(f"SATEL Uzbroj wszystko mode {mode}"),
            with_token(config, {"action": "arm", "partitions": "all", "mode": mode}),
            hint=f"Uzbrojenie wszystkich skonfigurowanych partycji, tryb {mode}: {ARM_MODE_DESCRIPTIONS.get(mode, '')}",
            comment=f"HTTP arm all partitions, mode {mode}",
        )
        add_http_cmd(
            root,
            loxone_title(f"SATEL Wymuszone uzbroj wszystko mode {mode}"),
            with_token(config, {"action": "force_arm", "partitions": "all", "mode": mode}),
            hint=f"Wymuszone uzbrojenie wszystkich skonfigurowanych partycji, tryb {mode}: {ARM_MODE_DESCRIPTIONS.get(mode, '')}",
            comment=f"HTTP force arm all partitions, mode {mode}",
        )
    add_http_cmd(
        root,
        "SATEL Rozbroj wszystko",
        with_token(config, {"action": "disarm", "partitions": "all"}),
        hint="Rozbrojenie wszystkich skonfigurowanych partycji",
        comment="HTTP disarm all partitions",
    )
    add_http_cmd(
        root,
        "SATEL Kasuj alarm wszystko",
        with_token(config, {"action": "clear_alarm", "partitions": "all"}),
        hint="Kasowanie alarmu we wszystkich skonfigurowanych partycjach",
        comment="HTTP clear alarm all partitions",
    )


def control_profile_params(profile):
    action = str(profile.get("action", "")).strip().lower()
    target = str(profile.get("target", "")).strip()
    params = {"action": action}
    if action in ("arm", "force_arm"):
        params["mode"] = int(profile.get("mode", 0) or 0)
    if action in ("arm", "force_arm", "disarm", "clear_alarm"):
        if target.lower() in ("", "all", "wszystko", "*"):
            params["partitions"] = "all"
        elif "," in target or ";" in target:
            params["partitions"] = target.replace(";", ",")
        else:
            params["partition"] = target
    elif action in ("output_on", "output_off", "output_toggle"):
        params["output"] = target
    return params


def add_control_profile_commands(root, config, lite=False):
    for profile in normalize_control_profiles(config.get("control_profiles", [])):
        if not profile.get("enabled", True):
            continue
        if lite and not profile.get("lite", False):
            continue
        params = control_profile_params(profile)
        action = params.get("action", "")
        if action not in CONTROL_PROFILE_ACTIONS:
            continue
        if action in ("output_on", "output_off", "output_toggle") and not params.get("output"):
            continue
        title = loxone_title(f"SATEL Profil {profile['name']}")
        hint = f"Profil sterowania: {profile['name']} ({action})"
        add_http_cmd(
            root,
            title,
            with_token(config, params),
            hint=hint,
            comment=f"HTTP control profile {profile['name']}",
        )


def generate_control_xml(config):
    root = create_control_root(
        config,
        "SATEL ETHM Bridge - HTTP Control",
        "Sterowanie SATEL ETHM przez LoxBerry HTTP bridge. Po imporcie ustaw Address na adres LoxBerry, jesli jest inny.",
    )

    for partition in normalize_numbered_items(config.get("control_partitions", []), 32, "Partycja"):
        number = int(partition["number"])
        name = loxone_title(partition["name"])
        title_suffix = f" P{number}" if name.lower() in ("partycja", f"partycja {number}".lower()) else f" P{number} {name}"
        for mode in range(4):
            add_http_cmd(
                root,
                loxone_title(f"SATEL Uzbroj{title_suffix} mode {mode}"),
                with_token(config, {"action": "arm", "partition": number, "mode": mode}),
                hint=f"Uzbrojenie partycji {number}, tryb {mode}: {ARM_MODE_DESCRIPTIONS.get(mode, '')}",
                comment=f"HTTP arm partition {number}, mode {mode}",
            )
            add_http_cmd(
                root,
                loxone_title(f"SATEL Wymuszone uzbroj{title_suffix} mode {mode}"),
                with_token(config, {"action": "force_arm", "partition": number, "mode": mode}),
                hint=f"Wymuszone uzbrojenie partycji {number}, tryb {mode}: {ARM_MODE_DESCRIPTIONS.get(mode, '')}",
                comment=f"HTTP force arm partition {number}, mode {mode}",
            )
        add_http_cmd(
            root,
            loxone_title(f"SATEL Rozbroj{title_suffix}"),
            with_token(config, {"action": "disarm", "partition": number}),
            hint=f"Rozbrojenie partycji {number}",
            comment=f"HTTP disarm partition {number}",
        )
        add_http_cmd(
            root,
            loxone_title(f"SATEL Kasuj alarm{title_suffix}"),
            with_token(config, {"action": "clear_alarm", "partition": number}),
            hint=f"Kasowanie alarmu partycji {number}",
            comment=f"HTTP clear alarm partition {number}",
        )

    add_all_partitions_control_commands(root, config, range(4))
    add_control_profile_commands(root, config, lite=False)

    add_http_cmd(
        root,
        "SATEL Kasuj pamiec awarii",
        with_token(config, {"action": "clear_trouble"}),
        hint="Kasowanie pamieci awarii SATEL",
        comment="HTTP clear trouble memory",
    )

    for output in normalize_numbered_items(config.get("control_outputs", []), 128, "Wyjscie"):
        number = int(output["number"])
        name = loxone_title(output["name"])
        title = loxone_title(f"SATEL Wyjscie {number} {name}")
        add_http_cmd(
            root,
            title,
            with_token(config, {"action": "output_on", "output": number}),
            with_token(config, {"action": "output_off", "output": number}),
            hint=f"Sterowanie wyjsciem SATEL {number}: ON/OFF",
            comment=f"HTTP output {number} ON/OFF",
        )
        add_http_cmd(
            root,
            loxone_title(f"{title} Toggle"),
            with_token(config, {"action": "output_toggle", "output": number}),
            hint=f"Przelacz wyjscie SATEL {number}",
            comment=f"HTTP output {number} toggle",
        )

    for zone in normalize_zones(config.get("zones", [])):
        number = int(zone["number"])
        name = loxone_title(zone["name"])
        title = loxone_title(f"SATEL Bypass Z{number} {name}")
        add_http_cmd(
            root,
            title,
            with_token(config, {"action": "zone_bypass", "zone": number}),
            with_token(config, {"action": "zone_unbypass", "zone": number}),
            hint=f"Bypass/unbypass wejscia SATEL {number}",
            comment=f"HTTP zone {number} bypass/unbypass",
        )

    ET.indent(root, space=" ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


def generate_control_xml_lite(config):
    root = create_control_root(
        config,
        "SATEL ETHM Bridge - HTTP Control Lite",
        "Sterowanie SATEL ETHM Lite: uzbrojenie mode 0, wymuszone uzbrojenie mode 0, rozbrojenie, kasowanie alarmu i awarii.",
    )

    for partition in normalize_numbered_items(config.get("control_partitions", []), 32, "Partycja"):
        number = int(partition["number"])
        name = loxone_title(partition["name"])
        title_suffix = f" P{number}" if name.lower() in ("partycja", f"partycja {number}".lower()) else f" P{number} {name}"
        add_http_cmd(
            root,
            loxone_title(f"SATEL Uzbroj{title_suffix}"),
            with_token(config, {"action": "arm", "partition": number, "mode": 0}),
            hint=f"Uzbrojenie partycji {number}, tryb 0: {ARM_MODE_DESCRIPTIONS[0]}",
            comment=f"HTTP arm partition {number}, mode 0",
        )
        add_http_cmd(
            root,
            loxone_title(f"SATEL Wymuszone uzbroj{title_suffix}"),
            with_token(config, {"action": "force_arm", "partition": number, "mode": 0}),
            hint=f"Wymuszone uzbrojenie partycji {number}, tryb 0: {ARM_MODE_DESCRIPTIONS[0]}",
            comment=f"HTTP force arm partition {number}, mode 0",
        )
        add_http_cmd(
            root,
            loxone_title(f"SATEL Rozbroj{title_suffix}"),
            with_token(config, {"action": "disarm", "partition": number}),
            hint=f"Rozbrojenie partycji {number}",
            comment=f"HTTP disarm partition {number}",
        )
        add_http_cmd(
            root,
            loxone_title(f"SATEL Kasuj alarm{title_suffix}"),
            with_token(config, {"action": "clear_alarm", "partition": number}),
            hint=f"Kasowanie alarmu partycji {number}",
            comment=f"HTTP clear alarm partition {number}",
        )

    add_all_partitions_control_commands(root, config, [0])
    add_control_profile_commands(root, config, lite=True)

    add_http_cmd(
        root,
        "SATEL Kasuj pamiec awarii",
        with_token(config, {"action": "clear_trouble"}),
        hint="Kasowanie pamieci awarii SATEL",
        comment="HTTP clear trouble memory",
    )

    ET.indent(root, space=" ")
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="utf-8")


def download_xml(filename, xml_data):
    print("Content-Type: application/xml; charset=utf-8")
    print(f'Content-Disposition: attachment; filename="{filename}"')
    print(f"Content-Length: {len(xml_data)}")
    print()
    sys.stdout.flush()
    sys.stdout.buffer.write(xml_data)


def send_json(payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    print("Content-Type: application/json; charset=utf-8")
    print(f"Content-Length: {len(data)}")
    print()
    sys.stdout.flush()
    sys.stdout.buffer.write(data)


def main():
    form = cgi.FieldStorage()
    action = form.getfirst("action", "")
    if action == "runtime_json":
        runtime = load_runtime_state()
        config = load_config()
        current_service_status = service_status()
        send_json({
            "service_status": current_service_status,
            "runtime": runtime,
            "rows": runtime_rows(runtime, current_service_status),
            "dashboard": dashboard_rows(runtime, config),
            "events": event_rows(runtime),
            "server_iso": datetime.now().isoformat(timespec="seconds"),
        })
        return
    if action == "download_config":
        download_config_backup(load_config())
        return
    if form.getfirst("action") == "download_xml":
        download_xml("VIU_SATEL_ETHM_Wejscia.xml", generate_zones_xml(load_config()))
        return
    if action == "download_xml_custom":
        download_xml("VIU_SATEL_ETHM_Wybrane.xml", generate_zones_xml_custom(load_config(), form.getlist("xml_sections")))
        return
    if action == "download_xml_lite":
        download_xml("VIU_SATEL_ETHM_Lite.xml", generate_zones_xml_lite(load_config()))
        return

    xml_sections = {
        "download_xml_basic": ("VIU_SATEL_ETHM_01_Statusy.xml", "basic"),
        "download_xml_partitions": ("VIU_SATEL_ETHM_02_Partycje.xml", "partitions"),
        "download_xml_zones": ("VIU_SATEL_ETHM_03_Wejscia.xml", "zones"),
        "download_xml_outputs": ("VIU_SATEL_ETHM_04_Wyjscia.xml", "outputs"),
        "download_xml_diagnostics": ("VIU_SATEL_ETHM_05_Diagnostyka.xml", "diagnostics"),
    }
    if action in xml_sections:
        filename, section = xml_sections[action]
        download_xml(filename, generate_zones_xml_section(load_config(), section))
        return

    if form.getfirst("action") == "download_control_xml":
        download_xml("VO_SATEL_ETHM_Sterowanie.xml", generate_control_xml(load_config()))
        return
    if form.getfirst("action") == "download_control_xml_lite":
        download_xml("VO_SATEL_ETHM_Sterowanie_Lite.xml", generate_control_xml_lite(load_config()))
        return

    message = ""
    if action == "save":
        save_config(form)
        message = "Konfiguracja zapisana. Usługa odczyta zmiany automatycznie w następnej pętli."
    elif action == "restore_config":
        try:
            message = restore_config_backup(form)
        except Exception as exc:
            message = f"Restore konfiguracji ERROR: {exc}"
    elif action == "import_dloadx":
        try:
            message = import_dloadx_config(form)
        except Exception as exc:
            message = f"Import DLOADX ERROR: {exc}"
    elif action == "autotest":
        try:
            message = autotest_config(load_config())
        except Exception as exc:
            message = f"Autotest ERROR: {exc}"
    elif action in ("test_ethm", "test_statuses", "test_zones", "test_udp"):
        try:
            test_config = load_config()
            if action == "test_ethm":
                message = test_ethm(test_config)
            elif action == "test_statuses":
                message = test_statuses(test_config)
            elif action == "test_zones":
                message = test_zones(test_config)
            elif action == "test_udp":
                message = test_udp(test_config)
        except Exception as exc:
            message = f"Test ERROR: {exc}"
    elif action.startswith("test_control_"):
        try:
            test_config = load_config()
            params = control_test_params(form)
            message = "UWAGA: wykonano realną komendę sterującą.\n" + queue_control_command(test_config, params)
        except Exception as exc:
            message = f"Test sterowania ERROR: {exc}"

    config = load_config()
    checked = "checked" if config.get("send_masks", True) else ""
    partition_details_checked = "checked" if config.get("send_partition_details", True) else ""
    ready_inferred_checked = "checked" if config.get("send_ready_inferred", True) else ""
    diagnostics_checked = "checked" if config.get("send_diagnostics", True) else ""
    trouble_details_checked = "checked" if config.get("send_trouble_details", True) else ""
    status_change_checked = "checked" if config.get("status_send_on_change", True) else ""
    zones_checked = "checked" if config.get("poll_zones", True) else ""
    zones_change_checked = "checked" if config.get("zones_send_on_change", True) else ""
    zone_bypass_checked = "checked" if config.get("poll_zone_bypass", True) else ""
    zone_diagnostics_checked = "checked" if config.get("poll_zone_diagnostics", True) else ""
    outputs_checked = "checked" if config.get("poll_outputs", True) else ""
    outputs_change_checked = "checked" if config.get("outputs_send_on_change", True) else ""
    temperatures_checked = "checked" if config.get("poll_temperatures", False) else ""
    temperature_raw_checked = "checked" if config.get("send_temperature_raw", False) else ""
    control_confirm_checked = "checked" if config.get("control_confirm_enabled", True) else ""
    control_confirm_blocking_checked = "checked" if config.get("control_confirm_blocking", False) else ""
    debug_checked = "checked" if config.get("debug_logging", False) else ""
    encryption_checked = "checked" if config.get("ethm_encryption_enabled", False) else ""
    integration_key_saved = "tak" if config.get("ethm_integration_key") else "nie"
    push_checked = "checked" if config.get("push_enabled", True) else ""
    mqtt_checked = "checked" if config.get("mqtt_enabled", False) else ""
    mqtt_retain_checked = "checked" if config.get("mqtt_retain", True) else ""
    mqtt_raw_checked = "checked" if config.get("mqtt_publish_raw", False) else ""
    mqtt_control_checked = "checked" if config.get("mqtt_control_enabled", False) else ""
    mqtt_password_saved = "tak" if config.get("mqtt_password") else "nie"
    code_saved = "tak" if config.get("satel_user_code") else "nie"
    runtime = load_runtime_state()
    current_service_status = service_status()
    runtime_table_rows = runtime_rows(runtime, current_service_status)
    dashboard_table_rows = dashboard_rows(runtime, config)
    event_table_rows = event_rows(runtime)
    zones_text = zones_to_text(config.get("zones", []))
    zones_count = len(config.get("zones", []))
    control_partitions_text = items_to_text(config.get("control_partitions", []), 32, "Partycja")
    control_outputs_text = items_to_text(config.get("control_outputs", []), 128, "Wyjscie")
    control_profiles_text = control_profiles_to_text(config.get("control_profiles", []))
    control_partitions_count = len(config.get("control_partitions", []))
    control_outputs_count = len(config.get("control_outputs", []))
    control_profiles_count = len(config.get("control_profiles", []))
    temperature_zones_text = items_to_text(config.get("temperature_zones", []), 256, "Temperatura")
    temperature_zones_count = len(config.get("temperature_zones", []))
    partition_options = ['<option value="all">Wszystko</option>']
    for partition in normalize_numbered_items(config.get("control_partitions", []), 32, "Partycja"):
        number = int(partition["number"])
        selected = " selected" if number == int(config.get("default_control_partition", 1)) else ""
        partition_options.append(f'<option value="{number}"{selected}>P{number} - {esc(partition["name"])}</option>')
    partition_options_html = "".join(partition_options)
    arm_mode_options_html = "".join(
        f'<option value="{mode}">mode {mode} - {esc(description)}</option>'
        for mode, description in ARM_MODE_DESCRIPTIONS.items()
    )
    output_options = []
    for output in normalize_numbered_items(config.get("control_outputs", []), 128, "Wyjscie"):
        number = int(output["number"])
        output_options.append(f'<option value="{number}">OUT{number} - {esc(output["name"])}</option>')
    output_options_html = "".join(output_options)
    output_test_disabled = "" if output_options else " disabled"
    partition_preview_html = "".join(
        f"<tr><td>{int(item['number'])}</td><td>{esc(item['name'])}</td></tr>"
        for item in normalize_numbered_items(config.get("control_partitions", []), 32, "Partycja")[:20]
    )
    zone_preview_html = "".join(
        f"<tr><td>{int(zone['number'])}</td><td>{esc(zone['name'])}</td><td>{int(zone.get('partition', 0) or 0) or ''}</td></tr>"
        for zone in normalize_zones(config.get("zones", []))[:40]
    )
    output_preview_html = "".join(
        f"<tr><td>{int(item['number'])}</td><td>{esc(item['name'])}</td></tr>"
        for item in normalize_numbered_items(config.get("control_outputs", []), 128, "Wyjscie")[:40]
    )

    print("Content-Type: text/html; charset=utf-8\n")
    print(f"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>SATEL ETHM Bridge</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; max-width: 980px; }}
    label {{ display: block; margin-top: 14px; font-weight: 700; }}
    input, textarea, select {{ width: 100%; max-width: 520px; padding: 8px; box-sizing: border-box; }}
    textarea {{ max-width: 860px; min-height: 170px; font-family: monospace; }}
    .row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
    .box {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 16px 0; }}
    details.box > summary {{ cursor: pointer; font-size: 1.45em; font-weight: 700; margin: -4px 0 12px; }}
    details.box:not([open]) > summary {{ margin-bottom: -4px; }}
    .hint {{ color: #555; font-size: 0.95em; }}
    button {{ padding: 8px 14px; margin: 10px 8px 0 0; cursor: pointer; }}
    .sticky-save {{ position: fixed; top: 14px; right: 18px; z-index: 1000; background: #1b5e20; color: #fff; border: 0; border-radius: 6px; box-shadow: 0 2px 10px rgba(0,0,0,0.18); }}
    code {{ background: #f3f3f3; padding: 2px 5px; border-radius: 4px; }}
    .message {{ background: #eef7ee; border: 1px solid #b8ddb8; padding: 10px; border-radius: 6px; white-space: pre-wrap; font-family: monospace; }}
    table.diag {{ width: 100%; border-collapse: collapse; font-size: 0.92em; }}
    table.diag th, table.diag td {{ text-align: left; border-bottom: 1px solid #e6e6e6; padding: 6px 8px; vertical-align: top; }}
    table.diag th {{ width: 230px; color: #444; }}
    table.diag td {{ font-family: monospace; word-break: break-word; }}
    .checkbox-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px 16px; max-width: 900px; }}
    .checkbox-grid label {{ margin-top: 0; font-weight: 400; }}
    .checkbox-grid input {{ width: auto; margin-right: 6px; }}
  </style>
</head>
<body>
  <h1>SATEL ETHM Bridge</h1>
  <p>Odczyt stanu Integry przez ETHM TCP 7094 i wysyłka prostych wartości UDP do Loxone.</p>
  <p>Wersja pluginu: <code>{esc(VERSION)}</code></p>
  <p>Status usługi: <code>{esc(current_service_status)}</code></p>
  <p>Plik konfiguracji: <code>{esc(CONFIG_FILE)}</code></p>
  {"<p class='message'>" + esc(message) + "</p>" if message else ""}

  <details class="box">
    <summary>Diagnostyka live</summary>
    <h3>Skrót stanu</h3>
    <table class="diag" id="dashboard-table">
      <tbody>
        {"".join(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>" for label, value in dashboard_table_rows)}
      </tbody>
    </table>
    <h3>Runtime</h3>
    <table class="diag" id="runtime-table">
      <tbody>
        {"".join(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>" for label, value in runtime_table_rows)}
      </tbody>
    </table>
    <h3>Ostatnie zdarzenia</h3>
    <table class="diag" id="events-table">
      <thead><tr><th>Czas</th><th>Typ</th><th>Zdarzenie</th><th>Szczegóły</th></tr></thead>
      <tbody>
        {"".join(f"<tr><td>{esc(ts)}</td><td>{esc(kind)}</td><td>{esc(title)}</td><td>{esc(detail)}</td></tr>" for ts, kind, title, detail in event_table_rows)}
      </tbody>
    </table>
    <p class="hint">Tabela odświeża się automatycznie co 2 sekundy z pliku runtime usługi.</p>
  </details>

  <script>
  async function refreshRuntime() {{
    try {{
      const response = await fetch('?action=runtime_json', {{cache: 'no-store'}});
      if (!response.ok) return;
      const data = await response.json();
      const escHtml = function(text) {{
        return String(text).replace(/[&<>"']/g, function(ch) {{
          return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch];
        }});
      }};
      const dashboard = document.querySelector('#dashboard-table tbody');
      if (dashboard && data.dashboard) {{
        dashboard.innerHTML = data.dashboard.map(function(row) {{
          return '<tr><th>' + escHtml(row[0] || '') + '</th><td>' + escHtml(row[1] || '') + '</td></tr>';
        }}).join('');
      }}
      const tbody = document.querySelector('#runtime-table tbody');
      if (tbody && data.rows) {{
        tbody.innerHTML = data.rows.map(function(row) {{
          return '<tr><th>' + escHtml(row[0] || '') + '</th><td>' + escHtml(row[1] || '') + '</td></tr>';
        }}).join('');
      }}
      const events = document.querySelector('#events-table tbody');
      if (events && data.events) {{
        events.innerHTML = data.events.map(function(row) {{
          return '<tr><td>' + escHtml(row[0] || '') + '</td><td>' + escHtml(row[1] || '') + '</td><td>' + escHtml(row[2] || '') + '</td><td>' + escHtml(row[3] || '') + '</td></tr>';
        }}).join('');
      }}
    }} catch (err) {{}}
  }}
  setInterval(refreshRuntime, 2000);
  refreshRuntime();
  </script>

  <form method="post" enctype="multipart/form-data">
    <button type="submit" name="action" value="save" class="sticky-save">Zapisz konfigurację</button>
    <details class="box" open>
      <summary>ETHM</summary>
      <div class="row">
        <div>
          <label>Adres IP ETHM</label>
          <input name="ethm_host" value="{esc(config["ethm_host"])}">
        </div>
        <div>
          <label>Port ETHM</label>
          <input name="ethm_port" type="number" value="{esc(config["ethm_port"])}">
        </div>
        <div>
          <label>Timeout TCP [s]</label>
          <input name="ethm_timeout" value="{esc(config["ethm_timeout"])}">
          <label style="font-weight:400"><input style="width:auto" type="checkbox" name="debug_logging" value="1" {debug_checked}> Debug: loguj surowe odpowiedzi ETHM</label>
          <p class="hint">Włącz tylko do diagnozy. Przy normalnej pracy logowane są zmiany, wysyłki UDP i błędy.</p>
        </div>
        <div>
          <label style="font-weight:400"><input style="width:auto" type="checkbox" name="ethm_encryption_enabled" value="1" {encryption_checked}> Kodowanie Integracji ETHM</label>
          <input name="ethm_integration_key" type="password" autocomplete="new-password" maxlength="12" placeholder="pozostaw puste, aby nie zmieniać">
          <p class="hint">Zapisany klucz: {esc(integration_key_saved)}. Używaj tylko, gdy w DLOADX przy ETHM masz zaznaczone <code>Kodowanie Integracji</code>. Klucz integracji ma maks. 12 znaków.</p>
          <label style="font-weight:400"><input style="width:auto" type="checkbox" name="clear_ethm_integration_key" value="1"> Wyczyść zapisany klucz integracji</label>
        </div>
        <div>
          <label>Kod użytkownika SATEL / ETHM</label>
          <input name="satel_user_code" type="password" autocomplete="new-password" placeholder="pozostaw puste, aby nie zmieniać">
          <p class="hint">Zapisany kod: {esc(code_saved)}. Odczyt statusów go nie używa; pole jest przygotowane pod komendy sterujące.</p>
          <label style="font-weight:400"><input style="width:auto" type="checkbox" name="clear_satel_user_code" value="1"> Wyczyść zapisany kod</label>
        </div>
        <div>
          <label>Interwał statusów [s]</label>
          <input name="status_poll_interval" value="{esc(config.get("status_poll_interval", config["poll_interval"]))}">
          <p class="hint">Uzbrojenie, alarm, awaria, online. Zalecane: 5 s.</p>
        </div>
        <div>
          <label>Pełne odświeżenie statusów UDP [s]</label>
          <input name="status_full_refresh_interval" value="{esc(config.get("status_full_refresh_interval", 30.0))}">
          <p class="hint">Co tyle sekund wtyczka wyśle wszystkie statusy, nawet bez zmian. 0 = wyłącz.</p>
        </div>
      </div>
      <label><input style="width:auto" type="checkbox" name="status_send_on_change" value="1" {status_change_checked}> Wysyłaj statusy UDP tylko przy zmianie</label>
      <h3>Push + fallback</h3>
      <label><input style="width:auto" type="checkbox" name="push_enabled" value="1" {push_checked}> Włącz nasłuchiwanie push z ETHM</label>
      <p class="hint">Wtyczka utrzymuje dodatkowe połączenie TCP z ETHM. Każda ramka asynchroniczna wyzwala natychmiastowy odczyt statusów, wejść i wyjść. Zwykły polling nadal działa jako fallback.</p>
      <div class="row">
        <div>
          <label>Reconnect push [s]</label>
          <input name="push_reconnect_interval" value="{esc(config.get("push_reconnect_interval", 10.0))}">
          <p class="hint">Co ile sekund próbować połączenia ponownie po zerwaniu.</p>
        </div>
        <div>
          <label>Debounce zdarzeń push [s]</label>
          <input name="push_debounce_seconds" value="{esc(config.get("push_debounce_seconds", 0.3))}">
          <p class="hint">Minimalny odstęp między natychmiastowymi odczytami wyzwolonymi przez ramki ETHM.</p>
        </div>
      </div>
      <p class="hint">Do Loxone wysyłane są także: <code>SATEL_PUSH_CONNECTED=0/1</code> i <code>SATEL_PUSH_RECONNECTS=liczba</code>.</p>
    </details>

    <details class="box" open>
      <summary>Loxone UDP</summary>
      <div class="row">
        <div>
          <label>Adres IP Miniservera</label>
          <input name="loxone_host" value="{esc(config["loxone_host"])}">
        </div>
        <div>
          <label>Port UDP wejścia w Loxone</label>
          <input name="loxone_udp_port" type="number" value="{esc(config["loxone_udp_port"])}">
        </div>
        <div>
          <label>Adres IP LoxBerry / nadawcy UDP</label>
          <input name="udp_sender_address" value="{esc(config.get("udp_sender_address", ""))}" placeholder="opcjonalnie, np. 192.168.1.50">
          <p class="hint">Używane w XML wejść jako adres nadawcy UDP. Jeśli URL sterowania ma placeholder <code>LOXBERRY_IP</code>, ten adres zostanie też podstawiony w XML wyjść sterujących.</p>
        </div>
        <div>
          <label>Maska partycji</label>
          <input name="partition_mask" type="number" value="{esc(config["partition_mask"])}">
          <p class="hint">Używana dla zbiorczych statusów <code>SATEL_ARMED</code>, <code>SATEL_ALARM</code> itd. Import DLOADX ustawia ją automatycznie z aktywnych partycji. Ręcznie: P1 = 1, P2 = 2, P1+P2 = 3.</p>
        </div>
      </div>
      <label><input style="width:auto" type="checkbox" name="send_masks" value="1" {checked}> Wysyłaj także maski RAW</label>
      <label><input style="width:auto" type="checkbox" name="send_partition_details" value="1" {partition_details_checked}> Wysyłaj szczegółowe statusy per partycja</label>
      <label><input style="width:auto" type="checkbox" name="send_ready_inferred" value="1" {ready_inferred_checked}> Wysyłaj wyliczoną gotowość do uzbrojenia</label>
      <label><input style="width:auto" type="checkbox" name="send_diagnostics" value="1" {diagnostics_checked}> Wysyłaj diagnostykę pracy wtyczki</label>
      <label><input style="width:auto" type="checkbox" name="send_trouble_details" value="1" {trouble_details_checked}> Wysyłaj szczegółowe awarie</label>
      <div class="row">
        <div>
          <label>Watchdog: maks. wiek statusu [s]</label>
          <input name="watchdog_status_max_age" value="{esc(config.get("watchdog_status_max_age", 30.0))}">
        </div>
        <div>
          <label>Watchdog: maks. wiek push [s]</label>
          <input name="watchdog_push_max_age" value="{esc(config.get("watchdog_push_max_age", 300.0))}">
        </div>
      </div>
      <p class="hint">Statusy per partycja używają listy z sekcji „Wyjścia / Sterowanie z Loxone”. Gotowość do uzbrojenia jest wyliczana z monitorowanych wejść, sabotażu, alarmu i awarii.</p>
    </details>

    <details class="box">
      <summary>MQTT</summary>
      <label><input style="width:auto" type="checkbox" name="mqtt_enabled" value="1" {mqtt_checked}> Włącz publikowanie MQTT</label>
      <div class="row">
        <div>
          <label>Broker MQTT</label>
          <input name="mqtt_host" value="{esc(config.get("mqtt_host", "localhost"))}">
          <p class="hint">Najczęściej <code>localhost</code>, jeśli broker działa na LoxBerry.</p>
        </div>
        <div>
          <label>Port MQTT</label>
          <input name="mqtt_port" type="number" value="{esc(config.get("mqtt_port", 1883))}">
        </div>
        <div>
          <label>Base topic</label>
          <input name="mqtt_base_topic" value="{esc(config.get("mqtt_base_topic", "satel"))}">
          <p class="hint">Przykład: <code>satel</code>. Wtyczka opublikuje np. <code>satel/status/armed</code> i <code>satel/zone/001/violated</code>.</p>
        </div>
        <div>
          <label>Client ID</label>
          <input name="mqtt_client_id" value="{esc(config.get("mqtt_client_id", ""))}" placeholder="puste = automatycznie">
        </div>
      </div>
      <div class="row">
        <div>
          <label>Użytkownik MQTT</label>
          <input name="mqtt_username" value="{esc(config.get("mqtt_username", ""))}">
        </div>
        <div>
          <label>Hasło MQTT</label>
          <input name="mqtt_password" type="password" autocomplete="new-password" placeholder="pozostaw puste, aby nie zmieniać">
          <p class="hint">Zapisane hasło: {esc(mqtt_password_saved)}.</p>
          <label style="font-weight:400"><input style="width:auto" type="checkbox" name="clear_mqtt_password" value="1"> Wyczyść zapisane hasło MQTT</label>
        </div>
        <div>
          <label>Timeout MQTT [s]</label>
          <input name="mqtt_timeout" value="{esc(config.get("mqtt_timeout", 3.0))}">
        </div>
        <div>
          <label>Keepalive MQTT [s]</label>
          <input name="mqtt_keepalive" value="{esc(config.get("mqtt_keepalive", 60))}">
        </div>
        <div>
          <label>Reconnect MQTT [s]</label>
          <input name="mqtt_reconnect_interval" value="{esc(config.get("mqtt_reconnect_interval", 10.0))}">
        </div>
      </div>
      <label><input style="width:auto" type="checkbox" name="mqtt_retain" value="1" {mqtt_retain_checked}> Publikuj z flagą retain</label>
      <label><input style="width:auto" type="checkbox" name="mqtt_publish_raw" value="1" {mqtt_raw_checked}> Publikuj dodatkowo surowe tematy <code>satel/raw/SATEL_...</code></label>
      <label><input style="width:auto" type="checkbox" name="mqtt_control_enabled" value="1" {mqtt_control_checked}> Włącz sterowanie przez MQTT</label>
      <p class="hint">Sterowanie MQTT subskrybuje <code>{esc(config.get("mqtt_base_topic", "satel"))}/control/#</code>. Włączaj tylko w zaufanej sieci i z brokerem zabezpieczonym hasłem, jeśli MQTT jest dostępny poza LoxBerry.</p>
      <p class="hint">Przykłady sterowania: <code>satel/control/arm</code> payload <code>{{"partitions":"all","mode":0}}</code>, <code>satel/control/disarm</code> payload <code>{{"partitions":"all"}}</code>, <code>satel/control/output/101/set</code> payload <code>1</code>.</p>
    </details>

    <details class="box">
      <summary>Import z DLOADX</summary>
      <p>Wczytuje z pliku XML nazwy partycji, wejść i wyjść. Importowane są tylko rekordy z <code>enabled="True"</code>.</p>
      <input type="file" name="dloadx_file" accept=".xml,text/xml,application/xml">
      <button name="action" value="import_dloadx">Importuj DLOADX XML</button>
      <p class="hint">Importer zastępuje listę partycji, wejść i wyjść w konfiguracji wtyczki. Pozostałe ustawienia, adresy, tokeny i kod użytkownika zostają bez zmian. Maska partycji zostanie ustawiona automatycznie z aktywnych partycji.</p>
      <h3>Aktualne mapowanie z konfiguracji</h3>
      <p class="hint">Partycje: {esc(control_partitions_count)}, wejścia: {esc(zones_count)}, wyjścia: {esc(control_outputs_count)}. Pokazywane są pierwsze rekordy z każdej listy.</p>
      <div class="row">
        <div>
          <h4>Partycje</h4>
          <table class="diag"><thead><tr><th>Nr</th><th>Nazwa</th></tr></thead><tbody>{partition_preview_html or '<tr><td colspan="2">brak</td></tr>'}</tbody></table>
        </div>
        <div>
          <h4>Wejścia</h4>
          <table class="diag"><thead><tr><th>Nr</th><th>Nazwa</th><th>P</th></tr></thead><tbody>{zone_preview_html or '<tr><td colspan="3">brak</td></tr>'}</tbody></table>
        </div>
        <div>
          <h4>Wyjścia</h4>
          <table class="diag"><thead><tr><th>Nr</th><th>Nazwa</th></tr></thead><tbody>{output_preview_html or '<tr><td colspan="2">brak</td></tr>'}</tbody></table>
        </div>
      </div>
    </details>

    <details class="box">
      <summary>Wejścia</summary>
      <label><input style="width:auto" type="checkbox" name="poll_zones" value="1" {zones_checked}> Odczytuj naruszone wejścia SATEL</label>
      <div class="row">
        <div>
          <label>Interwał wejść [s]</label>
          <input name="zones_poll_interval" value="{esc(config.get("zones_poll_interval", 1.0))}">
          <p class="hint">Dla PIR i kontaktronów zalecane 0.5-1 s.</p>
        </div>
        <div>
          <label>Pełne odświeżenie UDP [s]</label>
          <input name="zones_full_refresh_interval" value="{esc(config.get("zones_full_refresh_interval", 30.0))}">
          <p class="hint">Co tyle sekund wtyczka wyśle wszystkie wejścia, nawet bez zmian. 0 = wyłącz.</p>
        </div>
        <div>
          <label>Podtrzymanie naruszenia [s]</label>
          <input name="zone_hold_seconds" value="{esc(config.get("zone_hold_seconds", 3.0))}">
          <p class="hint">Przydatne dla krótkich impulsów z czujek ruchu. 0 = bez podtrzymania.</p>
        </div>
      </div>
      <label><input style="width:auto" type="checkbox" name="zones_send_on_change" value="1" {zones_change_checked}> Wysyłaj wejścia UDP tylko przy zmianie</label>
      <p class="hint">Domyślnie naruszenia są czytane komendą <code>0x00</code>. Pola komend odczytu są w sekcji zaawansowanej.</p>
      <label><input style="width:auto" type="checkbox" name="poll_zone_bypass" value="1" {zone_bypass_checked}> Odczytuj także status bypass/blokady wejść SATEL</label>
      <p class="hint">Domyślnie <code>0x06</code>, czyli wejścia z bypass/blokadą. Status bypass/blokady nie jest podtrzymywany czasowo.</p>
      <label><input style="width:auto" type="checkbox" name="poll_zone_diagnostics" value="1" {zone_diagnostics_checked}> Odczytuj alarm, sabotaż i pamięć alarmu wejść SATEL</label>
      <p class="hint">Diagnostyka wysyła m.in. <code>SATEL_ZONE_001_ALARM</code>, <code>SATEL_ZONE_001_TAMPER</code> i <code>SATEL_ZONE_001_ALARM_MEMORY</code>.</p>
      <label>Lista wejść do monitorowania ({esc(zones_count)} zapisanych)</label>
      <textarea name="zones_text" placeholder="1;Wiatrołap;1&#10;2;Salon PIR;1&#10;15;Garaż;2">{esc(zones_text)}</textarea>
      <p class="hint">Format: <code>numer;nazwa;partycja</code>. Stary format <code>numer;nazwa</code> nadal działa, ale nie bierze udziału w gotowości per partycja. Możesz też wpisać <code>numer;partycja;nazwa</code>.</p>
      <p class="hint">Wtyczka będzie wysyłała UDP: <code>SATEL_ZONE_001=0/1</code>, <code>SATEL_ZONE_001_BYPASS=0/1</code>, <code>SATEL_PARTITION_001_ZONE_ANY=0/1</code> oraz <code>SATEL_PARTITION_001_READY_INFERRED=0/1</code>.</p>
    </details>

    <details class="box">
      <summary>Temperatury z wejść</summary>
      <label><input style="width:auto" type="checkbox" name="poll_temperatures" value="1" {temperatures_checked}> Odczytuj temperatury wejść SATEL komendą <code>0x7D</code></label>
      <div class="row">
        <div>
          <label>Interwał temperatur [s]</label>
          <input name="temperature_poll_interval" value="{esc(config.get("temperature_poll_interval", 60.0))}">
        </div>
        <div>
          <label>Timeout temperatur [s]</label>
          <input name="temperature_timeout" value="{esc(config.get("temperature_timeout", 5.0))}">
        </div>
      </div>
      <label><input style="width:auto" type="checkbox" name="send_temperature_raw" value="1" {temperature_raw_checked}> Wysyłaj także surową wartość temperatury</label>
      <label>Lista wejść temperaturowych ({esc(temperature_zones_count)} zapisanych)</label>
      <textarea name="temperature_zones_text" placeholder="17;Temperatura salon&#10;18;Temperatura garaż">{esc(temperature_zones_text)}</textarea>
      <p class="hint">Wtyczka będzie wysyłała UDP: <code>SATEL_TEMP_017=21.5</code>. Działa tylko dla wejść z obsługą temperatury.</p>
    </details>

    <details class="box">
      <summary>Wyjścia / Sterowanie z Loxone</summary>
      <div class="row">
        <div>
          <label>URL sterowania LoxBerry</label>
          <input name="loxberry_control_url" value="{esc(config.get("loxberry_control_url", "http://LOXBERRY_IP/plugins/satel_ethm/control.cgi"))}">
          <p class="hint">Przykład: <code>http://192.168.1.50/plugins/satel_ethm/control.cgi</code>. Ten adres trafi do XML Wirtualnych Wyjść HTTP.</p>
        </div>
        <div>
          <label>Token sterowania</label>
          <input name="control_token" value="{esc(config.get("control_token", ""))}">
          <label style="font-weight:400"><input style="width:auto" type="checkbox" name="regenerate_control_token" value="1"> Wygeneruj nowy token przy zapisie</label>
        </div>
        <div>
          <label>Dozwolone IP sterowania</label>
          <input name="allowed_control_ips" value="{esc(config.get("allowed_control_ips", ""))}" placeholder="np. 192.168.1.77">
          <p class="hint">Puste = zgodność wsteczna. Wpisz IP Miniservera, aby <code>control.cgi</code> odrzucał komendy z innych adresów. Kilka adresów oddziel przecinkiem, średnikiem albo spacją.</p>
        </div>
        <div>
          <label>Domyślna partycja sterowania</label>
          <input name="default_control_partition" type="number" value="{esc(config.get("default_control_partition", 1))}">
        </div>
      </div>
      <label><input style="width:auto" type="checkbox" name="control_confirm_enabled" value="1" {control_confirm_checked}> Wysyłaj status sterowania do Loxone</label>
      <p class="hint">Komendy po odpowiedzi ETHM <code>EF 00</code> lub <code>EF FF</code> zwalniają kolejkę od razu. Odczyt statusów po komendzie potwierdza stan asynchronicznie, więc rozbrojenie może przerwać czas na wyjście bez czekania na poprzednie uzbrojenie.</p>
      <label><input style="width:auto" type="checkbox" name="control_confirm_blocking" value="1" {control_confirm_blocking_checked}> Tryb diagnostyczny: blokująco czekaj na potwierdzenie stanu</label>
      <div class="row">
        <div>
          <label>Timeout potwierdzenia [s]</label>
          <input name="control_confirm_timeout" value="{esc(config.get("control_confirm_timeout", 20.0))}">
        </div>
        <div>
          <label>Interwał sprawdzania potwierdzenia [s]</label>
          <input name="control_confirm_interval" value="{esc(config.get("control_confirm_interval", 0.5))}">
        </div>
      </div>
      <p class="hint">Po komendzie wtyczka wysyła <code>SATEL_CONTROL_PENDING=1</code>, a potem potwierdza stan przez odczyty ETHM. Uzbrojenie potwierdza się przez czuwanie albo czas na wyjście.</p>
      <label>Partycje do sterowania ({esc(control_partitions_count)} zapisanych)</label>
      <textarea name="control_partitions_text" placeholder="1;Dom&#10;2;Garaż">{esc(control_partitions_text)}</textarea>
      <label>Wyjścia SATEL do sterowania ({esc(control_outputs_count)} zapisanych)</label>
      <textarea name="control_outputs_text" placeholder="101;Brama&#10;102;Oświetlenie podjazdu&#10;103;Elektrozaczep">{esc(control_outputs_text)}</textarea>
      <label>Profile sterowania ({esc(control_profiles_count)} zapisanych)</label>
      <textarea name="control_profiles_text" placeholder="Wyjscie z domu;arm;all;0;tak&#10;Noc;arm;1;3;tak&#10;Rozbroj wszystko;disarm;all;;tak&#10;Brama toggle;output_toggle;101;;">{esc(control_profiles_text)}</textarea>
      <p class="hint">Format profilu: <code>Nazwa;akcja;cel;tryb;lite</code>. Akcje: <code>arm</code>, <code>force_arm</code>, <code>disarm</code>, <code>clear_alarm</code>, <code>clear_trouble</code>, <code>output_on</code>, <code>output_off</code>, <code>output_toggle</code>. Cel partycji: numer, lista <code>1,2</code> albo <code>all</code>. Ostatnia kolumna <code>tak</code> dodaje profil też do XML Lite.</p>
      <p class="hint">Loxone będzie wywoływał HTTP, a LoxBerry wyśle do ETHM właściwą ramkę z CRC. Do sterowania wymagany jest zapisany kod użytkownika SATEL z odpowiednimi uprawnieniami.</p>

      <h3>Status wyjść SATEL</h3>
      <label><input style="width:auto" type="checkbox" name="poll_outputs" value="1" {outputs_checked}> Odczytuj status wyjść z komendy <code>0x17</code></label>
      <div class="row">
        <div>
          <label>Interwał statusu wyjść [s]</label>
          <input name="outputs_poll_interval" value="{esc(config.get("outputs_poll_interval", 2.0))}">
        </div>
        <div>
          <label>Pełne odświeżenie wyjść UDP [s]</label>
          <input name="outputs_full_refresh_interval" value="{esc(config.get("outputs_full_refresh_interval", 30.0))}">
        </div>
      </div>
      <label><input style="width:auto" type="checkbox" name="outputs_send_on_change" value="1" {outputs_change_checked}> Wysyłaj statusy wyjść tylko przy zmianie</label>
      <p class="hint">Lista wyjść jest wspólna ze sterowaniem. Wtyczka wysyła np. <code>SATEL_OUTPUT_101=0/1</code>. Komenda odczytu wyjść jest w sekcji zaawansowanej.</p>
    </details>

    <details class="box">
      <summary>Zaawansowane: komendy SATEL</summary>
      <p class="hint">Zostaw domyślne, jeżeli używasz standardowego ETHM/Integra.</p>
      <p class="hint">Dla przyszłych komend można użyć placeholderów <code>{{USER_CODE_ASCII}}</code> albo <code>{{USER_CODE_BCD}}</code>. Przy komendach SATEL z danymi trzeba pamiętać o poprawnym CRC ramki.</p>
      <h3>Komendy wejść</h3>
      <label>Komenda odczytu naruszonych wejść</label>
      <input name="zone_status_command" value="{esc(config.get("zone_status_command", "FE FE 00 D7 E2 FE 0D"))}">
      <label>Komenda odczytu bypassowanych / blokowanych wejść</label>
      <input name="zone_bypass_status_command" value="{esc(config.get("zone_bypass_status_command", "FE FE 06 D7 E8 FE 0D"))}">
      <label>Komenda odczytu sabotażu wejść</label>
      <input name="zone_tamper_status_command" value="{esc(config.get("zone_tamper_status_command", "FE FE 01 D7 E3 FE 0D"))}">
      <label>Komenda odczytu alarmu wejść</label>
      <input name="zone_alarm_status_command" value="{esc(config.get("zone_alarm_status_command", "FE FE 02 D7 E4 FE 0D"))}">
      <label>Komenda odczytu pamięci alarmu wejść</label>
      <input name="zone_alarm_memory_status_command" value="{esc(config.get("zone_alarm_memory_status_command", "FE FE 04 D7 E6 FE 0D"))}">
      <h3>Komendy wyjść</h3>
      <label>Komenda odczytu wyjść</label>
      <input name="output_status_command" value="{esc(config.get("output_status_command", ""))}" placeholder="puste = automatycznie 0x17">
      <h3>Komendy statusów partycji/systemu</h3>
      <label>Uzbrojenie partycji</label>
      <input name="cmd_armed" value="{esc(config["commands"]["armed"])}">
      <label>Alarm w partycji</label>
      <input name="cmd_alarm" value="{esc(config["commands"]["alarm"])}">
      <label>Alarm pożarowy w partycji</label>
      <input name="cmd_fire_alarm" value="{esc(config["commands"].get("fire_alarm", "FE FE 14 D7 F6 FE 0D"))}">
      <label>Pamięć alarmu w partycji</label>
      <input name="cmd_alarm_memory" value="{esc(config["commands"].get("alarm_memory", "FE FE 15 D7 F7 FE 0D"))}">
      <label>Awaria</label>
      <input name="cmd_trouble" value="{esc(config["commands"]["trouble"])}">
      <label>Czas na wejście</label>
      <input name="cmd_entry_time" value="{esc(config["commands"].get("entry_time", "FE FE 0E D7 F0 FE 0D"))}">
      <label>Czas na wyjście &gt;10 s</label>
      <input name="cmd_exit_time" value="{esc(config["commands"].get("exit_time", "FE FE 0F D7 F1 FE 0D"))}">
      <label>Czas na wyjście &lt;=10 s</label>
      <input name="cmd_exit_time_short" value="{esc(config["commands"].get("exit_time_short", "FE FE 10 D7 F2 FE 0D"))}">
    </details>

    <button type="submit" name="action" value="save">Zapisz konfigurację</button>
  </form>

  <details class="box">
    <summary>Test sterowania</summary>
    <p class="hint">Te przyciski wykonują realne komendy w centrali SATEL. Test korzysta z tej samej kolejki i tego samego potwierdzania co sterowanie z Loxone.</p>
    <form method="post">
      <div class="row">
        <div>
          <label>Partycja</label>
          <select name="test_partition">
            {partition_options_html}
          </select>
        </div>
        <div>
          <label>Tryb uzbrojenia</label>
          <select name="test_mode">
            {arm_mode_options_html}
          </select>
          <p class="hint">Nazwy trybów odpowiadają standardowym trybom Integry; faktyczne działanie zależy od konfiguracji stref i wejść w DLOADX.</p>
        </div>
      </div>
      <button name="action" value="test_control_arm">Uzbrój</button>
      <button name="action" value="test_control_force_arm">Wymuszone uzbrój</button>
      <button name="action" value="test_control_disarm">Rozbrój</button>
      <button name="action" value="test_control_clear_alarm">Kasuj alarm</button>
      <button name="action" value="test_control_clear_trouble">Kasuj pamięć awarii</button>
    </form>
    <form method="post">
      <label>Wyjście SATEL</label>
      <select name="test_output"{output_test_disabled}>
        {output_options_html if output_options_html else '<option value="">Brak skonfigurowanych wyjść</option>'}
      </select>
      <button name="action" value="test_control_output_on"{output_test_disabled}>Wyjście ON</button>
      <button name="action" value="test_control_output_off"{output_test_disabled}>Wyjście OFF</button>
      <button name="action" value="test_control_output_toggle"{output_test_disabled}>Wyjście Toggle</button>
    </form>
    <p class="hint">Po wykonaniu komendy wynik pojawi się w zielonym komunikacie u góry oraz w „Diagnostyka live”. Dla opcji „Wszystko” używane są partycje z listy „Partycje do sterowania”.</p>
  </details>

  <details class="box">
    <summary>Backup konfiguracji</summary>
    <form method="post">
      <button name="action" value="download_config">Pobierz backup config.json</button>
    </form>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="config_file" accept=".json,application/json">
      <button name="action" value="restore_config">Przywróć konfigurację z JSON</button>
    </form>
    <p class="hint">Backup zawiera całą konfigurację wtyczki, w tym token sterowania i zapisany kod użytkownika SATEL, jeżeli jest ustawiony. Przywracanie sprawdza podstawową strukturę pliku przed zapisem.</p>
  </details>

  <details class="box">
    <summary>Szablon XML</summary>
    <p>Po zapisaniu konfiguracji możesz pobrać jeden szablon wejść UDP z wybranych sekcji do importu w Loxone Config.</p>
    <form method="post">
      <div class="checkbox-grid">
        <label><input type="checkbox" name="xml_sections" value="basic" checked> Statusy podstawowe</label>
        <label><input type="checkbox" name="xml_sections" value="partitions" checked> Partycje</label>
        <label><input type="checkbox" name="xml_sections" value="zones" checked> Wejścia</label>
        <label><input type="checkbox" name="xml_sections" value="outputs"> Wyjścia</label>
        <label><input type="checkbox" name="xml_sections" value="diagnostics"> Diagnostyka</label>
      </div>
      <button name="action" value="download_xml_custom">Pobierz XML z zaznaczonych sekcji</button>
      <button name="action" value="download_xml_lite">Pobierz XML Lite</button>
      <button name="action" value="download_xml">Pobierz XML wejść UDP - wszystko</button>
    </form>
    <form method="post">
      <button name="action" value="download_control_xml">Pobierz XML sterowania SATEL</button>
      <button name="action" value="download_control_xml_lite">Pobierz XML sterowania Lite</button>
    </form>
    <p class="hint">XML Lite wejść zawiera podstawowe statusy, alarmy, awarie oraz naruszenia wejść bez szczegółów typu bypass, sabotaż, pamięć alarmu wejścia, diagnostyka i maski. XML sterowania Lite zawiera tylko podstawowe sterowanie partycjami i kasowanie awarii. Sterowanie jest osobnym plikiem, bo w Loxone to inny typ szablonu: HTTP Virtual Output.</p>
  </details>

  <details class="box">
    <summary>Testy</summary>
    <p class="hint">Testy korzystają z zapisanej konfiguracji. Nie uzbrajają i nie rozbrajają alarmu.</p>
    <form method="post">
      <button name="action" value="test_ethm">Test połączenia ETHM</button>
      <button name="action" value="test_statuses">Test statusów</button>
      <button name="action" value="test_zones">Test wejść</button>
      <button name="action" value="test_udp">Test UDP do Loxone</button>
      <button name="action" value="autotest">Autotest konfiguracji</button>
    </form>
    <p class="hint">Test UDP wysyła <code>SATEL_TEST=1</code> na adres i port Miniservera zapisany w konfiguracji.</p>
  </details>

  <details class="box">
    <summary>Usługa</summary>
    <p>Zmiany konfiguracji są czytane automatycznie w każdej pętli, restart nie jest wymagany.</p>
    <p class="hint">Jeżeli chcesz ręcznie zrestartować usługę przez SSH, użyj: <code>sudo systemctl restart satel-ethm-bridge.service</code></p>
  </details>

  <details class="box">
    <summary>Rozpoznania w Loxone</summary>
    <p>Utwórz Wirtualne Wejście UDP na porcie <code>{esc(config["loxone_udp_port"])}</code> i dodaj komendy:</p>
    <p><code>SATEL_ARMED=\\v</code> - uzbrojenie 0/1</p>
    <p><code>SATEL_ALARM=\\v</code> - alarm 0/1</p>
    <p><code>SATEL_FIRE_ALARM=\\v</code> - alarm pożarowy 0/1</p>
    <p><code>SATEL_ALARM_MEMORY=\\v</code> - pamięć alarmu 0/1</p>
    <p><code>SATEL_TROUBLE=\\v</code> - awaria 0/1</p>
    <p><code>SATEL_ENTRY_TIME=\\v</code> - czas na wejście 0/1</p>
    <p><code>SATEL_EXIT_TIME=\\v</code> - czas na wyjście 0/1</p>
    <p><code>SATEL_EXIT_TIME_LONG=\\v</code> - czas na wyjście powyżej 10 s 0/1</p>
    <p><code>SATEL_EXIT_TIME_SHORT=\\v</code> - czas na wyjście poniżej/równo 10 s 0/1</p>
    <p><code>SATEL_PARTITION_001_ARMED=\\v</code> - partycja 1 uzbrojona 0/1, analogicznie kolejne partycje</p>
    <p><code>SATEL_PARTITION_001_ALARM=\\v</code> - alarm partycji 1 0/1</p>
    <p><code>SATEL_PARTITION_001_ENTRY_TIME=\\v</code> / <code>SATEL_PARTITION_001_EXIT_TIME=\\v</code> - czas wejścia/wyjścia partycji 1 0/1</p>
    <p><code>SATEL_PARTITION_001_READY_INFERRED=\\v</code> - wyliczona gotowość partycji 1 do uzbrojenia 0/1</p>
    <p><code>SATEL_PARTITION_001_ZONE_ANY=\\v</code> - dowolne naruszone wejście przypisane do partycji 1 0/1</p>
    <p><code>SATEL_PARTITION_001_ZONE_BYPASS_ANY=\\v</code> - dowolne wejście z bypass/blokadą przypisane do partycji 1 0/1</p>
    <p><code>SATEL_PARTITION_001_ZONE_TAMPER_ANY=\\v</code> - dowolny sabotaż wejścia przypisanego do partycji 1 0/1</p>
    <p><code>SATEL_PARTITION_001_ZONE_ALARM_ANY=\\v</code> - dowolny alarm wejścia przypisanego do partycji 1 0/1</p>
    <p><code>SATEL_READY_INFERRED=\\v</code> - wyliczona gotowość systemu do uzbrojenia 0/1</p>
    <p><code>SATEL_READY_ZONES_OK=\\v</code> - brak naruszonych monitorowanych wejść 0/1</p>
    <p><code>SATEL_DIAG_UPTIME=\\v</code> - czas pracy usługi w sekundach</p>
    <p><code>SATEL_DIAG_LAST_STATUS_OK_AGE=\\v</code> - ile sekund od ostatniego poprawnego statusu</p>
    <p><code>SATEL_DIAG_LAST_PUSH_AGE=\\v</code> - ile sekund od ostatniej ramki push</p>
    <p><code>SATEL_ONLINE=\\v</code> - łączność z ETHM 0/1</p>
    <p><code>SATEL_ERROR=\\v</code> - błąd jednej z komend odczytu 0/1</p>
    <p><code>SATEL_CONTROL_OK=\\v</code> - ostatnia komenda sterująca zakończona powodzeniem 0/1</p>
    <p><code>SATEL_CONTROL_ERROR=\\v</code> - błąd ostatniej komendy sterującej 0/1</p>
    <p><code>SATEL_CONTROL_PENDING=\\v</code> - komenda w trakcie potwierdzania 0/1</p>
    <p><code>SATEL_CONTROL_ACCEPTED=\\v</code> - komenda przyjęta przez ETHM 0/1</p>
    <p><code>SATEL_CONTROL_CONFIRMED=\\v</code> - komenda potwierdzona odczytem stanu 0/1</p>
    <p><code>SATEL_CONTROL_TIMEOUT=\\v</code> - potwierdzenie przekroczyło timeout 0/1</p>
    <p><code>SATEL_CONTROL_LAST_CODE=\\v</code> - kod odpowiedzi SATEL, np. 0 = OK, 255 = przyjęto do wykonania</p>
    <p><code>SATEL_CONTROL_LAST_ACTION=\\v</code> - typ akcji: 1 arm, 2 force arm, 3 disarm, 4 clear alarm, 5 clear trouble, 6/7 output on/off, 8 toggle, 9/10 bypass/unbypass</p>
    <p><code>SATEL_CONTROL_SEQ=\\v</code> - licznik/czas ostatniego sterowania, zmienia się przy każdej komendzie</p>
    <p><code>SATEL_PUSH_CONNECTED=\\v</code> - stałe połączenie push z ETHM 0/1</p>
    <p><code>SATEL_PUSH_RECONNECTS=\\v</code> - licznik ponownych połączeń push</p>
    <p><code>SATEL_ZONE_ANY=\\v</code> - dowolne naruszone wejście 0/1</p>
    <p><code>SATEL_ZONE_001=\\v</code> - wejście 1, analogicznie kolejne numery</p>
    <p><code>SATEL_ZONE_BYPASS_ANY=\\v</code> - dowolne wejście z bypass/blokadą 0/1</p>
    <p><code>SATEL_ZONE_001_BYPASS=\\v</code> - bypass/blokada wejścia 1, analogicznie kolejne numery</p>
    <p><code>SATEL_ZONE_ALARM_ANY=\\v</code> - dowolne wejście w alarmie 0/1</p>
    <p><code>SATEL_ZONE_001_ALARM=\\v</code> - alarm wejścia 1, analogicznie kolejne numery</p>
    <p><code>SATEL_ZONE_TAMPER_ANY=\\v</code> - dowolny sabotaż wejścia 0/1</p>
    <p><code>SATEL_ZONE_001_TAMPER=\\v</code> - sabotaż wejścia 1, analogicznie kolejne numery</p>
    <p><code>SATEL_ZONE_ALARM_MEMORY_ANY=\\v</code> - dowolne wejście w pamięci alarmu 0/1</p>
    <p><code>SATEL_ZONE_001_ALARM_MEMORY=\\v</code> - pamięć alarmu wejścia 1, analogicznie kolejne numery</p>
  </details>
</body>
</html>""")


if __name__ == "__main__":
    main()
