#!/usr/bin/env bash
# Build Kolbe Controller as a standalone macOS .app (windowed, no terminal).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_NAME="Kolbe Controller"
SPEC="packaging/kolbe_mac.spec"

echo "==> Kolbe macOS build"
echo "    Project: $ROOT"
echo "    Output:  dist/${APP_NAME}.app"
echo

if [[ ! -d ".venv" ]]; then
  echo "ERROR: .venv not found. Create it first:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e ."
  exit 1
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

echo "==> Installing build dependencies..."
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install "pyinstaller>=6.0"

echo "==> Cleaning previous build artifacts..."
rm -rf build

if [[ -d dist ]]; then
  APP_PATH="dist/${APP_NAME}.app"
  if [[ -d "$APP_PATH" ]] && pgrep -fl "Kolbe Controller" >/dev/null 2>&1; then
    echo "ERROR: ${APP_NAME}.app is still running."
    echo "       Quit the app, then run ./build_mac.sh again."
    exit 1
  fi
  chmod -R u+w dist 2>/dev/null || true
  xattr -cr dist 2>/dev/null || true
  if ! rm -rf dist; then
    STALE_DIST="dist.stale.$$"
    echo "WARNING: Could not delete dist/ — moving aside to ${STALE_DIST}"
    if ! mv dist "$STALE_DIST"; then
      echo "ERROR: dist/ is locked (close Finder windows showing dist/, quit the app)."
      exit 1
    fi
    rm -rf "$STALE_DIST" || true
  fi
fi

echo "==> Running PyInstaller (windowed .app bundle)..."
pyinstaller "$SPEC" --noconfirm --clean

APP_PATH="dist/${APP_NAME}.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "ERROR: Expected app bundle not found at: $APP_PATH"
  exit 1
fi

echo
echo "==> Build complete!"
echo "    App bundle: $APP_PATH"
echo
echo "Run the app:"
echo "  open \"$APP_PATH\""
echo
echo "First launch on macOS:"
echo "  - If Gatekeeper blocks the app, right-click the app → Open → Open."
echo "  - Grant Input Monitoring / Bluetooth permissions when prompted for controllers."
echo
echo "Optional ad-hoc sign (helps some permission prompts on local machines):"
echo "  codesign --force --deep --sign - \"$APP_PATH\""
