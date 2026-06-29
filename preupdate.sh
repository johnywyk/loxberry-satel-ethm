#!/bin/sh
set -eu

PLUGIN="satel_ethm"
CONFIG_DIR="${LBHOMEDIR}/config/plugins/$PLUGIN"
DATA_DIR="${LBHOMEDIR}/data/plugins/$PLUGIN"
SYSTEM_DIR="${LBHOMEDIR}/data/system/$PLUGIN"

mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$SYSTEM_DIR"

# Backup bieżącej konfiguracji przed upgrade
if [ -f "$CONFIG_DIR/config.json" ]; then
    cp "$CONFIG_DIR/config.json" "$CONFIG_DIR/config.json.preupdate.bak" 2>/dev/null || true
    cp "$CONFIG_DIR/config.json" "$SYSTEM_DIR/config.json.preupdate.bak" 2>/dev/null || true
fi

# Zachowaj w SYSTEM_DIR jako fallback (postinstall.sh odczyta go po upgrade)
if [ -f "$CONFIG_DIR/config.json" ] && [ ! -f "$SYSTEM_DIR/config.json" ]; then
    cp "$CONFIG_DIR/config.json" "$SYSTEM_DIR/config.json" 2>/dev/null || true
fi

# Backup runtime.json
if [ -f "$CONFIG_DIR/runtime.json" ]; then
    cp "$CONFIG_DIR/runtime.json" "$SYSTEM_DIR/runtime.json.bak" 2>/dev/null || true
fi

exit 0
