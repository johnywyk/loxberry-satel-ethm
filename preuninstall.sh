#!/bin/sh
set -eu

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop satel-ethm-bridge.service || true
  systemctl disable satel-ethm-bridge.service || true
  rm -f /etc/systemd/system/satel-ethm-bridge.service
  systemctl daemon-reload || true
fi

rm -f /var/run/satel_ethm_bridge.pid
exit 0

