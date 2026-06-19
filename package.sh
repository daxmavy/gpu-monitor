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
  <key>CFBundleVersion</key><string>0.1.1</string>
  <key>CFBundleShortVersionString</key><string>0.1.1</string>
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

UV_VER="${UV_VER:-0.9.0}"
echo "→ bundling uv ${UV_VER} for both arches (no uv needed on the target Mac)"
for pair in "aarch64:arm64" "x86_64:x86_64"; do
  ut="${pair%%:*}"; an="${pair##*:}"
  url="https://github.com/astral-sh/uv/releases/download/${UV_VER}/uv-${ut}-apple-darwin.tar.gz"
  curl -fsSL "$url" | tar -xz -C "$RES" --strip-components=1 "uv-${ut}-apple-darwin/uv"
  mv "$RES/uv" "$RES/uv-${an}"
  chmod +x "$RES/uv-${an}"
done

echo "→ building setup-progress helper (universal)"
swiftc -swift-version 5 -O -target arm64-apple-macos11  macapp/setup_progress.swift -o "$RES/sp-arm64"
swiftc -swift-version 5 -O -target x86_64-apple-macos11 macapp/setup_progress.swift -o "$RES/sp-x86_64"
lipo -create "$RES/sp-arm64" "$RES/sp-x86_64" -o "$RES/setup-progress"
rm -f "$RES/sp-arm64" "$RES/sp-x86_64"
chmod +x "$RES/setup-progress"

echo "→ writing launcher"
cat > "$APP/Contents/MacOS/gpu-monitor" <<'LAUNCH'
#!/bin/bash
# First-run bootstrap (with a progress window), then launch the menu-bar app.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../Resources/app"
case "$(uname -m)" in
  arm64)  UV="$HERE/../Resources/uv-arm64" ;;
  x86_64) UV="$HERE/../Resources/uv-x86_64" ;;
  *)      UV="" ;;
esac
PROG="$HERE/../Resources/setup-progress"
SUPPORT="$HOME/Library/Application Support/gpu-monitor"
VENV="$SUPPORT/venv"
mkdir -p "$SUPPORT"
rm -f "$SUPPORT/setup-progress.pid"
exec >>"$SUPPORT/launch.log" 2>&1
echo "=== launch $(date) ==="

PROG_PID=""
prog() { :; }                                    # no-op until the progress window is up
stop_prog() { [ -n "$PROG_PID" ] && kill "$PROG_PID" 2>/dev/null; }
fail() {
  stop_prog
  osascript -e "display dialog \"GPU Monitor setup failed.\n\n$1\n\nSee: $SUPPORT/launch.log\" buttons {\"OK\"} with icon stop" >/dev/null 2>&1 || true
  exit 1
}

# First run: build the Python env. Show a progress window the whole time — the
# menu-bar app dismisses it the instant its own window appears (so there's never
# a stretch with nothing on screen).
if [ ! -x "$VENV/bin/python" ]; then
  if [ -x "$PROG" ]; then
    PIPE="$(mktemp -u)"; mkfifo "$PIPE"
    "$PROG" < "$PIPE" >/dev/null 2>&1 &
    PROG_PID=$!
    exec 4>"$PIPE"; rm -f "$PIPE"               # fd 4 stays open across exec -> helper lives on
    echo "$PROG_PID" > "$SUPPORT/setup-progress.pid"
    prog() { printf '%s\n' "$*" >&4 2>/dev/null || true; }
  fi

  prog "STATUS Preparing…"; prog "PROGRESS 12"

  # Pick a working uv: bundled (by arch) → on PATH → install it.
  if [ -z "${UV:-}" ] || ! "$UV" --version >/dev/null 2>&1; then
    UV="$(command -v uv || true)"; [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
    if [ -z "${UV:-}" ] || ! "$UV" --version >/dev/null 2>&1; then
      prog "STATUS Installing uv…"; prog "PULSE"
      curl -LsSf https://astral.sh/uv/install.sh | sh || fail "Could not install uv."
      UV="$HOME/.local/bin/uv"
    fi
  fi

  prog "STATUS Setting up Python…"; prog "PROGRESS 38"
  "$UV" venv "$VENV" --python 3.11 || fail "Could not create the Python environment."

  prog "STATUS Installing libraries…"; prog "PULSE"
  "$UV" pip install --python "$VENV/bin/python" \
    fastapi "uvicorn[standard]" pyobjc-framework-Cocoa pyobjc-framework-WebKit \
    || fail "Could not install Python dependencies (no internet?)."

  prog "STATUS Starting GPU Monitor…"; prog "PROGRESS 99"
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
