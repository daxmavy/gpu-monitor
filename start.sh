#!/usr/bin/env bash
# Launch the GPU Monitor menu-bar app. It starts its own local server, so this
# is the only thing you need to run. A "GPU N" item appears in the menu bar.
#
#   ./start.sh            # menu-bar app (default)
#   ./start.sh web        # web-only: serve UI, no menu-bar item, open a browser
set -euo pipefail
cd "$(dirname "$0")"

mode="${1:-menubar}"
case "$mode" in
  web)
    PORT="${GPUMON_PORT:-8765}"
    echo "GPU Monitor (web) -> http://127.0.0.1:${PORT}/"
    ( sleep 2; open "http://127.0.0.1:${PORT}/" ) &
    exec uv run uvicorn gpumon.server:app --host 127.0.0.1 --port "${PORT}"
    ;;
  menubar|*)
    # Launch as a .app via `open` so it joins the GUI session — an NSStatusItem
    # only appears for a process in that session (a plain `python …` from a
    # terminal/automation context won't show in the menu bar).
    [ -d "dist/GPU Monitor.app" ] || ./build_app.sh
    open "dist/GPU Monitor.app"
    echo "GPU Monitor launched — look for the ● item near the top-right of the menu bar."
    ;;
esac
