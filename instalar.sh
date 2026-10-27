#!/usr/bin/env bash
# Instala atalho no menu de apps, início automático no login e o script do Nautilus
# (botão direito > Scripts > Converter (roda)).
# Uso: ./instalar.sh | ./instalar.sh --sem-autostart | ./instalar.sh --remover
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="$HOME/.local/share/applications/roda-conversor.desktop"
AUTO="$HOME/.config/autostart/roda-conversor.desktop"
SCRIPT="$HOME/.local/share/nautilus/scripts/Converter (roda)"
LIXO="$DIR/lixo"

if [[ "${1:-}" == "--remover" ]]; then
  mkdir -p "$LIXO"
  for f in "$APPS" "$AUTO" "$SCRIPT"; do [[ -e "$f" ]] && mv "$f" "$LIXO/" && echo "movido p/ lixo: $f"; done
  echo "config continua em ~/.config/roda-conversor"
  exit 0
fi

mkdir -p "$(dirname "$APPS")" "$(dirname "$AUTO")" "$(dirname "$SCRIPT")"
cat > "$APPS" <<DESK
[Desktop Entry]
Type=Application
Name=Roda Conversora
Comment=Segure o botão lateral do mouse sobre um arquivo e converta
Exec=/usr/bin/python3 $DIR/roda_conversor.py --config
Icon=view-refresh
Terminal=false
Categories=Utility;
StartupNotify=false
DESK
echo "atalho: $APPS"

if [[ "${1:-}" != "--sem-autostart" ]]; then
  # no login sobe só o ícone (cinza); a roda liga pelo menu "Ligada"
  sed 's/ --config$/ --desligado/' "$APPS" > "$AUTO"
  echo "X-GNOME-Autostart-Delay=4" >> "$AUTO"
  echo "autostart: $AUTO"
fi

cat > "$SCRIPT" <<SH
#!/usr/bin/env bash
# Abre a roda para os arquivos selecionados (escolha com clique esquerdo).
IFS=\$'\n' read -r -d '' -a ARQS <<< "\$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"
exec /usr/bin/python3 "$DIR/roda_conversor.py" "\${ARQS[@]}"
SH
chmod +x "$SCRIPT"
echo "script do Nautilus: $SCRIPT"
