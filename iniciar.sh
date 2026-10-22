#!/usr/bin/env bash
# AutoNext en Linux. Requiere: python3, python3-venv, python3-tk (panel) y Brave instalado.
#   ./iniciar.sh         panel de escritorio + servidor movil
#   ./iniciar.sh --web   solo servidor movil (sin ventana)
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -f web/dist/index.html ] && command -v npm >/dev/null; then
  (cd web && npm install --no-audit --no-fund && npm run build)
fi
exec .venv/bin/python main.py "$@"
