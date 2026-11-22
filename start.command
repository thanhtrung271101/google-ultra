#!/bin/bash
# Google AI Pro 5TB & AI Ultra One-Click Wizard — Double-click to run on macOS
# Changes to the script directory and launches wizard.py.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found. Please install Python 3.9+: https://www.python.org/downloads/"
  echo "Press Enter to close."
  read -r _
  exit 1
fi

python3 wizard.py
code=$?

echo
echo "(Wizard finished. Press Enter to close this window)"
read -r _
exit $code
