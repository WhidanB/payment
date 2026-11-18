#!/usr/bin/env bash
#
# One command to check the service: lint, format, tests, coverage (same as CI).
#
#   ./scripts/verify.sh
#
# Needs the dev dependencies:  pip install -r requirements-dev.txt

set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
fi

echo "== ruff check ==";           "$PY" -m ruff check .
echo "== ruff format --check =="; "$PY" -m ruff format --check .
echo "== pytest + coverage ==";    "$PY" -m pytest -q --cov
echo "OK"
