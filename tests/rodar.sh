#!/usr/bin/env bash
# Testes da Roda Conversora (stdlib unittest, sem pip).
#   tests/rodar.sh          unit + e2e
#   tests/rodar.sh unit     só unit (sem janela)
#   tests/rodar.sh e2e      só e2e (precisa de sessão gráfica)
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
case "${1:-tudo}" in
  unit) exec /usr/bin/python3 -m unittest -v test_juntar test_menu_nautilus test_roda_logica ;;
  e2e)  exec /usr/bin/python3 -m unittest -v test_e2e ;;
  *)    exec /usr/bin/python3 -m unittest -v test_juntar test_menu_nautilus test_roda_logica test_e2e ;;
esac
