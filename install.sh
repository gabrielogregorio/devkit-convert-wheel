#!/usr/bin/env bash
# Installs the app menu entry, autostart at login and the Nautilus script
# (right click > Scripts > Convert (wheel)). Names follow the system language (pt-BR or English).
# Usage: ./install.sh | ./install.sh --no-autostart | ./install.sh --remove
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="$HOME/.local/share/applications/devkit-convert-wheel.desktop"
AUTO="$HOME/.config/autostart/devkit-convert-wheel.desktop"
# names used before 1.1.1: moved to trash/ on install and on --remove, or the wheel would start twice
OLD_APPS="$HOME/.local/share/applications/convert-wheel.desktop"
OLD_AUTO="$HOME/.config/autostart/convert-wheel.desktop"
LANG_NOW="${CONVERT_WHEEL_LANG:-${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}}"
if [[ "$LANG_NOW" == pt* ]]; then SCRIPT_NAME="Converter (roda)"; else SCRIPT_NAME="Convert (wheel)"; fi
SCRIPTS="$HOME/.local/share/nautilus/scripts"
TRASH="$DIR/trash"
# the menu entry and the autostart share a file name: prefix the source folder so neither overwrites the other
to_trash() { mkdir -p "$TRASH" && mv "$1" "$TRASH/$(basename "$(dirname "$1")")-$(basename "$1")"; }

if [[ "${1:-}" == "--remove" ]]; then
  mkdir -p "$TRASH"
  for f in "$APPS" "$AUTO" "$OLD_APPS" "$OLD_AUTO" "$SCRIPTS/Converter (roda)" "$SCRIPTS/Convert (wheel)"; do
    [[ -e "$f" ]] && to_trash "$f" && echo "moved to trash/: $f"
  done
  echo "the config stays in ~/.config/devkit-convert-wheel"
  exit 0
fi

mkdir -p "$(dirname "$APPS")" "$(dirname "$AUTO")" "$SCRIPTS"
for f in "$OLD_APPS" "$OLD_AUTO"; do
  [[ -e "$f" ]] && to_trash "$f" && echo "old name moved to trash/: $f"
done
cat > "$APPS" <<DESK
[Desktop Entry]
Type=Application
Name=Convert Wheel
Name[pt_BR]=Roda Conversora
Comment=Hold a mouse button over a file and pick the format on a wheel
Comment[pt_BR]=Segure um botão do mouse sobre um arquivo e escolha o formato numa roda
Exec=/usr/bin/python3 $DIR/convert_wheel.py --config
Icon=view-refresh
Terminal=false
Categories=Utility;
StartupNotify=false
DESK
echo "menu entry: $APPS"

if [[ "${1:-}" != "--no-autostart" ]]; then
  # at login only the (gray) icon comes up; the wheel turns on from the "On" menu item
  sed 's/ --config$/ --off/' "$APPS" > "$AUTO"
  echo "X-GNOME-Autostart-Delay=4" >> "$AUTO"
  echo "autostart: $AUTO"
fi

cat > "$SCRIPTS/$SCRIPT_NAME" <<SH
#!/usr/bin/env bash
# Opens the wheel for the selected files (pick with the left click).
IFS=\$'\n' read -r -d '' -a FILES <<< "\$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"
exec /usr/bin/python3 "$DIR/convert_wheel.py" "\${FILES[@]}"
SH
chmod +x "$SCRIPTS/$SCRIPT_NAME"
echo "Nautilus script: $SCRIPTS/$SCRIPT_NAME"
