"""FastAPI app: serves the menu-bar web UI and a small JSON API backed by the
background poller.

For zero-wait first paint, GET "/" embeds the current snapshot into the HTML as
`window.__INITIAL_STATE__`, so the UI renders immediately with data — no initial
fetch round-trip.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import alarms, config, names, vpn
from .poller import poller


@asynccontextmanager
async def lifespan(app: FastAPI):
    poller.poll_once()      # one synchronous poll so the first GET has data
    poller.start()
    yield
    poller.stop()


app = FastAPI(title="GPU Monitor", lifespan=lifespan)


class NameBody(BaseModel):
    username: str
    name: str | None = None


def _full_state() -> dict:
    snap = poller.latest()
    return {
        **snap,
        "names": names.load_names(),
        "alarm_config": alarms.load_config(),
        "configured": config.CONFIGURED,
        "config_file": str(config.CONFIG_FILE),
        "vpn_configured": bool(config.VPN),
        "vpn_label": (config.VPN or {}).get("label", "VPN client"),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    html = (config.WEBUI_DIR / "index.html").read_text()
    inject = (f"<script>window.__INITIAL_STATE__={json.dumps(_full_state())};"
              f"</script>")
    return HTMLResponse(html.replace("</head>", inject + "</head>"))


@app.get("/api/state")
def get_state():
    return _full_state()


@app.get("/api/badge")
def get_badge():
    return poller.badge()


@app.post("/api/active")
def set_active(on: int = 1):
    poller.set_active(bool(on))
    return {"active": bool(on)}


@app.post("/api/names")
def post_name(body: NameBody):
    return {"names": names.set_name(body.username, body.name)}


@app.get("/api/alarms")
def get_alarms():
    return alarms.load_config()


@app.post("/api/alarms")
def post_alarms(cfg: dict):
    saved = alarms.save_config(cfg)
    poller.rearm()
    return saved


@app.post("/api/alarm/test")
def test_alarm():
    cfg = alarms.load_config()
    ok = alarms.notify("Test alarm — notifications are working.",
                       sound=cfg.get("sound", "Glass"))
    return {"ok": ok}


@app.post("/api/vpn/open")
def open_vpn():
    return vpn.open_vpn_client()


@app.post("/api/refresh")
def refresh():
    return poller.poll_once()


@app.exception_handler(Exception)
async def _unhandled(_request, exc):
    return JSONResponse(status_code=500, content={"error": str(exc)})


# Static assets (style.css, app.js). Added last so explicit routes win.
app.mount("/", StaticFiles(directory=str(config.WEBUI_DIR), html=True), name="webui")
