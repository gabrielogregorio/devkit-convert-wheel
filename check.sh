#!/usr/bin/env bash
# Every check, without touching the running desktop. Same commands the CI runs.
# Usage: ./check.sh [all|lint|unit|e2e|smoke] [--office]
#   all    lint (if ruff/shellcheck are installed) + unit + e2e + smoke (if xvfb-run exists)  [default]
#   lint   ruff + shellcheck
#   unit   fast tests, no external tools
#   e2e    real conversions on tiny samples + wheel render (PNGs in tmp/check/)
#   smoke  starts the app in an isolated X server and D-Bus session (tools/smoke.sh)
#   --office  e2e also converts through LibreOffice
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
STEP="${1:-all}"
[[ "${1:-}" == --office ]] && STEP=all
[[ " $* " == *" --office "* ]] && export CONVERT_WHEEL_OFFICE=1

lint() {
  local strict="${1:-}" ran=0
  if command -v ruff > /dev/null; then
    echo "== ruff"; ruff check .; ran=1
  elif [[ -n "$strict" ]]; then echo "ruff not found"; return 1; fi
  if command -v shellcheck > /dev/null; then
    echo "== shellcheck"; shellcheck --severity=warning ./*.sh tools/*.sh; ran=1
  elif [[ -n "$strict" ]]; then echo "shellcheck not found"; return 1; fi
  [[ $ran == 1 ]] || echo "== lint skipped (install ruff and shellcheck to run it)"
}
# No display and no D-Bus for unit/e2e: GTK/GIO would otherwise wake services (portals, gvfs) on the
# session bus, which touch the desktop locally and outlive the job on CI.
HEADLESS=(env -u DISPLAY -u WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent/bus
          GIO_USE_VFS=local GIO_USE_VOLUME_MONITOR=unix GSETTINGS_BACKEND=memory NO_AT_BRIDGE=1)
unit() { echo "== unit"; "${HEADLESS[@]}" /usr/bin/python3 -m unittest discover -s tests/unit -t . "${@}"; }
e2e() {
  echo "== e2e"
  "${HEADLESS[@]}" /usr/bin/python3 -m unittest discover -s tests/e2e -t . -p "test_[cr]*.py" -v
}
smoke() { echo "== smoke"; tools/smoke.sh; }

case "$STEP" in
  lint) lint strict ;;
  unit) unit -v ;;
  e2e) e2e ;;
  smoke) smoke ;;
  all)
    lint
    unit
    e2e
    if command -v xvfb-run > /dev/null && command -v dbus-run-session > /dev/null; then smoke
    else echo "== smoke skipped (sudo apt install xvfb dbus)"; fi
    echo OK ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
