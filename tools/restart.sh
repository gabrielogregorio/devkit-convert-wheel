#!/usr/bin/env bash
# Starts the wheel in the background (kills the previous one by PID). Log in tmp/app.log.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
for PID in $(pgrep -f "convert_wheel[.]py"); do kill "$PID"; done
sleep 0.5
mkdir -p "$DIR/tmp"
setsid /usr/bin/python3 "$DIR/convert_wheel.py" "$@" > "$DIR/tmp/app.log" 2>&1 < /dev/null &
sleep 2
pgrep -af "convert_wheel[.]py" || echo "did not start"
