#!/bin/sh
# SATEL ETHM Bridge - Pre-install script (run as ROOT before file installation)
# Tworzy wymagane katalogi z właściwymi uprawnieniami

PLUGIN="satel_ethm"
CONFIG_DIR="${LBHOMEDIR}/config/plugins/${PLUGIN}"
LOG_DIR="${LBHOMEDIR}/log/plugins/${PLUGIN}"
DATA_DIR="${LBHOMEDIR}/data/plugins/${PLUGIN}"
SYSTEM_DIR="${LBHOMEDIR}/data/system/${PLUGIN}"

# Utwórz katalogi z właściwymi uprawnieniami PRZED postinstall.sh
mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$DATA_DIR" "$SYSTEM_DIR"
chown -R loxberry:loxberry "$CONFIG_DIR" "$LOG_DIR" "$DATA_DIR" 2>/dev/null || true

echo "Directories created with correct permissions"
exit 0
