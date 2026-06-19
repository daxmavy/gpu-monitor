#!/usr/bin/env bash
# Build a DISTRIBUTABLE, self-contained "GPU Monitor.app" + a .dmg.
#
# The app bundles the source + a copy of `uv` and bootstraps its own Python
# environment on first launch (no Python/uv needed on the target Mac), then runs
# the menu-bar app — which auto-opens the setup wizard when not yet configured.
#
# Dev builds (fast, uses the repo .venv) still come from build_app.sh.
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/GPU Monitor.app"
RES="$APP/Contents/Resources"
BUNDLE_ID="${GPUMON_BUNDLE_ID:-com.example.gpumonitor}"

echo "→ staging $APP"
rm -rf "$APP" "dist/GPU-Monitor.dmg"
mkdir -p "$APP/Contents/MacOS" "$RES/app"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>GPU Monitor</string>
  <key>CFBundleDisplayName</key><string>GPU Monitor</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleVersion</key><string>0.1</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleExecutable</key><string>gpu-monitor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

echo "→ copying source"
for item in gpumon webui macapp pyproject.toml config.example.json README.md; do
  cp -R "$item" "$RES/app/"
done
find "$RES/app" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "→ bundling uv ($(command -v uv))"
cp "$(command -v uv)" "$RES/uv"
chmod +x "$RES/uv"

echo "→ writing launcher"
cat > "$APP/Contents/MacOS/gpu-monitor" <<'LAUNCH'
#!/bin/bash
# First-run bootstrap, then launch the menu-bar app.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../Resources/app"
UV="$HERE/../Resources/uv"
SUPPORT="$HOME/Library/Application Support/gpu-monitor"
VENV="$SUPPORT/venv"
mkdir -p "$SUPPORT"
exec >>"$SUPPORT/launch.log" 2>&1
echo "=== launch $(date) ==="

note() { osascript -e "display notification \"$1\" with title \"GPU Monitor\"" >/dev/null 2>&1 || true; }
fail() { osascript -e "display dialog \"GPU Monitor setup failed.\n\n$1\n\nSee: $SUPPORT/launch.log\" buttons {\"OK\"} with icon stop" >/dev/null 2>&1 || true; exit 1; }

# Pick a working uv: bundled → on PATH → install it.
if ! "$UV" --version >/dev/null 2>&1; then
  UV="$(command -v uv || true)"
  [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
  if [ -z "${UV:-}" ] || ! "$UV" --version >/dev/null 2>&1; then
    note "Installing dependencies (first launch)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh || fail "Could not install uv."
    UV="$HOME/.local/bin/uv"
  fi
fi

# Bootstrap the venv on first run (downloads Python + libs; needs internet once).
if [ ! -x "$VENV/bin/python" ]; then
  note "Setting up on first launch — about a minute…"
  "$UV" venv "$VENV" --python 3.11 || fail "Could not create the Python environment."
  "$UV" pip install --python "$VENV/bin/python" \
    fastapi "uvicorn[standard]" pyobjc-framework-Cocoa pyobjc-framework-WebKit \
    || fail "Could not install Python dependencies (no internet?)."
  note "Ready! Opening setup…"
fi

cd "$SRC"
exec "$VENV/bin/python" -m macapp.menubar
LAUNCH
chmod +x "$APP/Contents/MacOS/gpu-monitor"

echo "→ building dmg"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "GPU Monitor" -srcfolder "$STAGE" -ov -quiet \
  -format UDZO "dist/GPU-Monitor.dmg"
rm -rf "$STAGE"

echo "✓ built: $APP"
echo "✓ built: dist/GPU-Monitor.dmg  ($(du -h dist/GPU-Monitor.dmg | cut -f1))"
