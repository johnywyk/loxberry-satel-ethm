#!/bin/sh
set -eu

PLUGIN="satel_ethm"
CONFIG_DIR="/opt/loxberry/config/plugins/$PLUGIN"
DATA_DIR="/opt/loxberry/data/plugins/$PLUGIN"
SYSTEM_DIR="/opt/loxberry/data/system/$PLUGIN"

mkdir -p "$DATA_DIR" "$SYSTEM_DIR"

if [ -f "$CONFIG_DIR/config.json" ]; then
  cp "$CONFIG_DIR/config.json" "$SYSTEM_DIR/config.json.preupdate.bak" 2>/dev/null || true
  if [ ! -f "$SYSTEM_DIR/config.json" ]; then
    cp "$CONFIG_DIR/config.json" "$SYSTEM_DIR/config.json" 2>/dev/null || true
  fi
fi

if [ -f "$DATA_DIR/config.json" ]; then
  cp "$DATA_DIR/config.json" "$SYSTEM_DIR/config.json.lastgood.bak" 2>/dev/null || true
  if [ ! -f "$SYSTEM_DIR/config.json" ]; then
    cp "$DATA_DIR/config.json" "$SYSTEM_DIR/config.json" 2>/dev/null || true
  fi
fi

if [ -f "$SYSTEM_DIR/config.json" ]; then
  cp "$SYSTEM_DIR/config.json" "$SYSTEM_DIR/config.json.lastgood.bak" 2>/dev/null || true
fi

exit 0
