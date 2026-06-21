#!/bin/sh
set -eu

PLUGIN="satel_ethm"
BIN_DIR="/opt/loxberry/bin/plugins/$PLUGIN"
HTML_DIR="/opt/loxberry/webfrontend/html/plugins/$PLUGIN"
HTMLAUTH_DIR="/opt/loxberry/webfrontend/htmlauth/plugins/$PLUGIN"
DATA_DIR="/opt/loxberry/data/plugins/$PLUGIN"
CONFIG_DIR="/opt/loxberry/data/system/$PLUGIN"
LOG_DIR="/opt/loxberry/log/plugins/$PLUGIN"

mkdir -p "$CONFIG_DIR" "$CONFIG_DIR/control_queue" "$LOG_DIR"
chmod +x "$BIN_DIR/satel_ethm_bridge.py" "$BIN_DIR/satel_ethm_service.sh" 2>/dev/null || true
chmod +x "$HTML_DIR/control.cgi" 2>/dev/null || true
touch "$LOG_DIR/satel_ethm_control.log" "$LOG_DIR/satel_ethm_bridge.log" 2>/dev/null || true
chmod 777 "$CONFIG_DIR/control_queue" 2>/dev/null || true
chmod 666 "$LOG_DIR/satel_ethm_control.log" "$LOG_DIR/satel_ethm_bridge.log" 2>/dev/null || true

ICON_SOURCE=""
if [ -f "$HTMLAUTH_DIR/icons/icon_128.png" ]; then
  ICON_SOURCE="$HTMLAUTH_DIR/icons"
elif [ -f "$HTML_DIR/icons/icon_128.png" ]; then
  ICON_SOURCE="$HTML_DIR/icons"
fi

if [ -n "$ICON_SOURCE" ]; then
  mkdir -p "$DATA_DIR/icons"
  cp "$ICON_SOURCE"/icon_*.png "$DATA_DIR/icons/" 2>/dev/null || true
  mkdir -p "$HTML_DIR/icons" "$HTMLAUTH_DIR/icons"
  cp "$ICON_SOURCE"/icon_*.png "$HTML_DIR/icons/" 2>/dev/null || true
  cp "$ICON_SOURCE"/icon_*.png "$HTMLAUTH_DIR/icons/" 2>/dev/null || true
  cp "$ICON_SOURCE/icon_128.png" "$HTML_DIR/icon.png" 2>/dev/null || true
  cp "$ICON_SOURCE/icon_128.png" "$HTML_DIR/pluginicon.png" 2>/dev/null || true
  cp "$ICON_SOURCE/icon_128.png" "$HTMLAUTH_DIR/icon.png" 2>/dev/null || true
  cp "$ICON_SOURCE/icon_128.png" "$HTMLAUTH_DIR/pluginicon.png" 2>/dev/null || true

  find /opt/loxberry -type f \( \
    -name '*satel_ethm*.png' -o \
    -name '*satelethm*.png' -o \
    -name '*SATEL*ETHM*.png' -o \
    -path '*/plugins/satel_ethm/icons/icon_*.png' \
  \) -print 2>/dev/null | while IFS= read -r target; do
    echo "SATEL ETHM Bridge: refreshing icon $target"
    case "$target" in
      *icon_64.png) cp "$ICON_SOURCE/icon_64.png" "$target" 2>/dev/null || true ;;
      *icon_256.png) cp "$ICON_SOURCE/icon_256.png" "$target" 2>/dev/null || true ;;
      *icon_512.png) cp "$ICON_SOURCE/icon_512.png" "$target" 2>/dev/null || true ;;
      *) cp "$ICON_SOURCE/icon_128.png" "$target" 2>/dev/null || true ;;
    esac
  done
fi

if command -v systemctl >/dev/null 2>&1; then
  cat > /etc/systemd/system/satel-ethm-bridge.service <<'EOF'
[Unit]
Description=SATEL ETHM Bridge for LoxBerry
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=SATEL_ETHM_CONFIG=/opt/loxberry/data/system/satel_ethm/config.json
ExecStart=/opt/loxberry/bin/plugins/satel_ethm/satel_ethm_bridge.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload || true
  systemctl enable satel-ethm-bridge.service || true
  systemctl restart satel-ethm-bridge.service || true
else
  "$BIN_DIR/satel_ethm_service.sh" restart || true
fi

exit 0
