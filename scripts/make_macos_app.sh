#!/bin/bash
# Build ContentOS.app — a double-clickable macOS launcher for ContentOS.
#
# Usage:
#   bash scripts/make_macos_app.sh                 # installs to ~/Desktop
#   bash scripts/make_macos_app.sh /Applications    # optional
#
# The generated app is a thin launcher: it starts app/server.py if needed and
# opens the UI in a Chrome app-mode window. Python stays external (system
# Python 3), so there is nothing large to bundle or sign for local use.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$HOME/Desktop}"
APP_NAME="ContentOS.app"
APP="$TARGET_DIR/$APP_NAME"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

VERSION="$(python3 -c 'import json;print(json.load(open("'"$ROOT"'/frontend/package.json"))["version"])' 2>/dev/null || echo '1.0.0')"

echo "Building $APP_NAME (v$VERSION) from $ROOT"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# --- launcher -------------------------------------------------------------
cp "$ROOT/scripts/macos-app/launcher.sh" "$APP/Contents/MacOS/ContentOS"
chmod +x "$APP/Contents/MacOS/ContentOS"
printf '%s\n' "$ROOT" > "$APP/Contents/Resources/project.path"

# --- icon: SVG -> PNG (QuickLook) -> .icns (iconutil) ---------------------
ICON_PNG="$BUILD/icon.png"
ICONSET="$BUILD/ContentOS.iconset"
mkdir -p "$ICONSET"
if command -v qlmanage >/dev/null 2>&1; then
  qlmanage -t -s 1024 -o "$BUILD" "$ROOT/static/favicon.svg" >/dev/null 2>&1 || true
  if [ -f "$BUILD/favicon.svg.png" ]; then
    cp "$BUILD/favicon.svg.png" "$ICON_PNG"
  fi
fi
if [ -f "$ICON_PNG" ]; then
  for s in 16 32 128 256 512; do
    sips -z "$s" "$s" "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
  done
  for s in 16 32 128 256; do
    d=$((s * 2))
    sips -z "$d" "$d" "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/ContentOS.icns" 2>/dev/null || true
fi

# --- Info.plist -----------------------------------------------------------
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ContentOS</string>
  <key>CFBundleDisplayName</key><string>ContentOS</string>
  <key>CFBundleIdentifier</key><string>com.justmemedia.contentos</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>ContentOS</string>
  <key>CFBundleIconFile</key><string>ContentOS</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSUIElement</key><false/>
</dict>
</plist>
PLIST

touch "$APP"

echo "Created: $APP"
echo "Double-click it to launch ContentOS."
echo "Logs: ~/Library/Logs/ContentOS/launcher.log"
