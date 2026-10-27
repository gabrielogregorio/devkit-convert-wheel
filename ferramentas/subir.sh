#!/usr/bin/env bash
# Sobe a roda em segundo plano (mata a anterior pelo PID). Log em tmp/app.log.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
for PID in $(pgrep -f "roda_conversor[.]py"); do kill "$PID"; done
sleep 0.5
mkdir -p "$DIR/tmp"
setsid /usr/bin/python3 "$DIR/roda_conversor.py" "$@" > "$DIR/tmp/app.log" 2>&1 < /dev/null &
sleep 2
pgrep -af "roda_conversor[.]py" || echo "não subiu"
