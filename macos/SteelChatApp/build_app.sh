#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv-build}"

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip
pip install -r "$ROOT_DIR/../../requirements.txt"
pip install py2app build

cd "$ROOT_DIR"
python -m build --wheel --sdist
python setup.py py2app

echo "SteelChat.app available under $ROOT_DIR/dist/"
