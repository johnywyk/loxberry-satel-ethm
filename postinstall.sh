#!/bin/sh
set -e

PLUGIN="satel_ethm"
BIN_DIR="${LBHOMEDIR}/bin/plugins/$PLUGIN"
LOG_DIR="${LBHOMEDIR}/log/plugins/$PLUGIN"

# Log dir (bez uprawnień roota)
mkdir -p "$LOG_DIR" 2>/dev/null || true

# Uprawnienia wykonywania
chmod +x "${BIN_DIR}/satel_ethm_bridge.py"  2>/dev/null || true
chmod +x "${BIN_DIR}/satel_ethm_service.sh" 2>/dev/null || true

# Sprawdź Python dependency
echo "Checking paho-mqtt..."
python3 -c "import paho.mqtt.client" 2>/dev/null ||     pip3 install paho-mqtt --break-system-packages 2>/dev/null ||     echo "WARNING: install paho-mqtt manually: pip3 install paho-mqtt"

echo "=== SATEL ETHM Bridge post-install (user) complete ==="
exit 0
