#!/bin/sh
PLUGIN="satel_ethm"

# Stop service
SERVICE="${LBHOMEDIR}/bin/plugins/${PLUGIN}/satel_ethm_service.sh"
if [ -f "$SERVICE" ]; then
    "$SERVICE" stop 2>/dev/null || true
fi

# Usuń sudoers entry
rm -f "/etc/sudoers.d/${PLUGIN}" 2>/dev/null || true

echo "=== SATEL ETHM Bridge uninstalled ==="
exit 0
