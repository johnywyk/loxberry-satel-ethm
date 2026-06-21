#!/bin/sh
set -eu

PLUGIN="satel_ethm"
BIN="/opt/loxberry/bin/plugins/$PLUGIN/satel_ethm_bridge.py"
CONFIG="/opt/loxberry/data/system/$PLUGIN/config.json"
LOGDIR="/opt/loxberry/log/plugins/$PLUGIN"
PIDFILE="/var/run/satel_ethm_bridge.pid"

start() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "SATEL ETHM Bridge is already running"
    exit 0
  fi
  mkdir -p "$LOGDIR"
  SATEL_ETHM_CONFIG="$CONFIG" nohup "$BIN" >> "$LOGDIR/stdout.log" 2>&1 &
  echo $! > "$PIDFILE"
  echo "SATEL ETHM Bridge started"
}

stop() {
  if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE")"
    if kill -0 "$PID" 2>/dev/null; then
      kill "$PID"
      sleep 1
    fi
    rm -f "$PIDFILE"
  fi
  echo "SATEL ETHM Bridge stopped"
}

status() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "running"
  else
    echo "stopped"
  fi
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *) echo "Usage: $0 start|stop|restart|status"; exit 2 ;;
esac
