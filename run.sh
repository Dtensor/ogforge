#!/usr/bin/env bash
# Launch ogforge dev server. Usage: ./run.sh  (from project root)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$HERE/.venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8810 --app-dir "$HERE"
