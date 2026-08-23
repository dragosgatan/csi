#!/usr/bin/env bash
# arch and kali both refuse pip into the system python (PEP 668), so the deps
# live in a venv. --system-site-packages keeps the distro numpy instead of
# rebuilding it, which is slow on a laptop.
set -euo pipefail

cd "$(dirname "$0")"

python3 -m venv --system-site-packages .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "ready. run the dashboard with:"
echo "  .venv/bin/python software/dashboard.py"
