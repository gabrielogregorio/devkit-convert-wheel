#!/usr/bin/env bash
# Runs the app smoke test inside its own X server (Xvfb) and D-Bus session, with a throwaway HOME.
# Needs: sudo apt install xvfb dbus
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
for tool in xvfb-run dbus-run-session; do
  command -v "$tool" > /dev/null || { echo "missing $tool: sudo apt install xvfb dbus"; exit 1; }
done
cd "$DIR"
exec xvfb-run -a -s "-screen 0 1280x800x24" \
  dbus-run-session -- env CONVERT_WHEEL_SMOKE=1 PYTHONDONTWRITEBYTECODE=1 GTK_USE_PORTAL=0 NO_AT_BRIDGE=1 \
  /usr/bin/python3 -m unittest -v tests.e2e.test_app
