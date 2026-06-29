#!/bin/sh
set -eu

PLUGIN="satel_ethm"
BIN="${LBHOMEDIR}/bin/plugins/$PLUGIN/satel_ethm_bridge.py"
CONFIG="${LBHOMEDIR}/config/plugins/$PLUGIN/config.json"
LOGDIR="${LBHOMEDIR}/log/plugins/$PLUGIN"
# ZMIANA: PID w katalogu log (nie wymaga roota)
PIDFILE="${LBHOMEDIR}/log/plugins/$PLUGIN/satel_ethm_bridge.pid"

start() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "SATEL ETHM Bridge is already running (PID $(cat $PIDFILE))"
        exit 0
    fi
    mkdir -p "$LOGDIR"
    SATEL_ETHM_CONFIG="$CONFIG" LBHOMEDIR="${LBHOMEDIR}" \
        nohup python3 "$BIN" >> "$LOGDIR/stdout.log" 2>&1 &
    echo $! > "$PIDFILE"
    echo "SATEL ETHM Bridge started (PID $(cat $PIDFILE))"
}

stop() {
    if [ -f "$PIDFILE" ]; then
        PID="$(cat "$PIDFILE")"
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            timeout=10
            while kill -0 "$PID" 2>/dev/null && [ $timeout -gt 0 ]; do
                sleep 1
                timeout=$((timeout - 1))
            done
            kill -9 "$PID" 2>/dev/null || true
        fi
        rm -f "$PIDFILE"
    fi
    echo "SATEL ETHM Bridge stopped"
}

status() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "running (PID $(cat $PIDFILE))"
        exit 0
    else
        echo "stopped"
        exit 1
    fi
}

case "${1:-status}" in
    start)   start   ;;
    stop)    stop    ;;
    restart) stop; sleep 1; start ;;
    status)  status  ;;
    *) echo "Usage: $0 start|stop|restart|status"; exit 2 ;;
esac
