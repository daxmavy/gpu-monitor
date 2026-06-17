#!/usr/bin/env bash
# Build a minimal "GPU Monitor.app" bundle so the menu-bar app launches into the
# GUI (Aqua) session via `open` — an NSStatusItem only appears when the process
# is part of that session. LSUIElement=1 keeps it out of the Dock.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"
APP="dist/GPU Monitor.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>GPU Monitor</string>
  <key>CFBundleDisplayName</key><string>GPU Monitor</string>
  <key>CFBundleIdentifier</key><string>${GPUMON_BUNDLE_ID:-com.example.gpumonitor}</string>
  <key>CFBundleVersion</key><string>0.1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleExecutable</key><string>gpu-monitor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/gpu-monitor" <<LAUNCH
#!/bin/bash
cd "$REPO"
exec "$REPO/.venv/bin/python" -m macapp.menubar >> /tmp/gpumon-menubar.log 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/gpu-monitor"

echo "built: $REPO/$APP"
echo "launch with:  open \"$APP\""
