"""GPU Monitor — macOS menu-bar app.

A native NSStatusItem in the menu bar. Left-click opens a popover hosting the
gpumon web UI (WKWebView -> http://127.0.0.1:PORT). Right-click (or ctrl-click)
shows a Quit menu. The menu-bar title summarises state at a glance (idle GPU
count, or a warning when the VPN is off). The HTTP server is started in-process,
so launching this app is the only thing the user does — no separate app to open.

Run:  uv run python -m macapp.menubar
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

import objc
from AppKit import (
    NSApp, NSApplication, NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular, NSAttributedString, NSBackingStoreBuffered,
    NSColor, NSEventMaskLeftMouseUp, NSEventMaskRightMouseUp, NSEventTypeRightMouseUp,
    NSForegroundColorAttributeName, NSMenu, NSMenuItem, NSPopover,
    NSPopoverBehaviorTransient, NSStatusBar, NSVariableStatusItemLength,
    NSViewController, NSWindow, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import (
    NSMakeRect, NSMakeSize, NSObject, NSTimer, NSURL, NSURLRequest,
)
from WebKit import WKWebView, WKWebViewConfiguration

from gpumon import config

HOST, PORT = config.HOST, config.PORT
BASE = f"http://{HOST}:{PORT}"
POPOVER_WIDTH = 720
POPOVER_SIZE = (POPOVER_WIDTH, 500)   # initial; height auto-fits to content

try:
    from AppKit import NSMinYEdge
except ImportError:  # pragma: no cover
    NSMinYEdge = 1


# ---------- in-process HTTP server ----------
def _server_responds() -> bool:
    try:
        urllib.request.urlopen(BASE + "/api/state", timeout=1)
        return True
    except Exception:  # noqa: BLE001
        return False


def _run_uvicorn() -> None:
    import uvicorn
    uvicorn.run("gpumon.server:app", host=HOST, port=PORT, log_level="warning")


def ensure_server() -> bool:
    """Start the server in a daemon thread unless one is already answering, then
    wait until it does. Probes by HTTP response (not a bind test) so a port lingering
    in TIME_WAIT after a restart doesn't make us skip starting our own — uvicorn
    binds with SO_REUSEADDR anyway."""
    if _server_responds():
        return True
    threading.Thread(target=_run_uvicorn, name="gpumon-http", daemon=True).start()
    for _ in range(80):                 # up to ~20s for first (cold) poll
        if _server_responds():
            return True
        time.sleep(0.25)
    return False


def _fetch_badge() -> dict | None:
    try:
        with urllib.request.urlopen(BASE + "/api/badge", timeout=2) as r:
            return json.load(r)
    except Exception:  # noqa: BLE001
        return None


# ---------- app ----------
class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _notification):
        self.statusItem = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength)
        btn = self.statusItem.button()
        btn.setTitle_("GPU …")
        btn.setTarget_(self)
        btn.setAction_("statusClicked:")
        btn.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)

        # popover + webview
        self.popover = NSPopover.alloc().init()
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setContentSize_(NSMakeSize(*POPOVER_SIZE))
        self.popover.setDelegate_(self)
        vc = NSViewController.alloc().init()
        conf = WKWebViewConfiguration.alloc().init()
        conf.userContentController().addScriptMessageHandler_name_(self, "resize")
        self.web = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, *POPOVER_SIZE), conf)
        self.web.loadRequest_(NSURLRequest.requestWithURL_(
            NSURL.URLWithString_(BASE + "/?embed=1")))
        vc.setView_(self.web)
        self.popover.setContentViewController_(vc)

        # right-click menu
        self.menu = NSMenu.alloc().init()
        self.menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open GPU Monitor", "openPopover:", ""))
        self.menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Setup…", "openSetup:", ""))
        self.menu.addItem_(NSMenuItem.separatorItem())
        self.menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit GPU Monitor", "terminate:", "q"))

        self.setup_win = None
        # first run (or forced): open the setup wizard window automatically
        if not config.CONFIGURED or os.environ.get("GPUMON_FORCE_SETUP"):
            self._open_setup_window()

        # periodic title refresh (cheap cached /api/badge read)
        self._refresh_title()
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            5.0, self, "tick:", None, True)

        # one-shot diagnostic after layout: did the status item get a width, or
        # is it being clipped (notch / full menu bar)?
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.5, self, "diag:", None, False)

        # headless self-test: confirm the WKWebView actually loaded the localhost UI
        if os.environ.get("GPUMON_SELFTEST"):
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                6.0, self, "selfTest:", None, False)

    def diag_(self, _timer):
        try:
            b = self.statusItem.button()
            win = b.window() if b else None
            screen = win.screen() if win else None
            sframe = screen.frame().size if screen else None
            wframe = win.frame() if win else None
            diag = {
                "created": self.statusItem is not None,
                "visible": bool(self.statusItem.isVisible()),
                "length": float(self.statusItem.length()),
                "btn_w": float(b.frame().size.width) if b else None,
                "btn_title": str(b.title()) if b else None,
                "has_window": win is not None,
                "win_x": float(wframe.origin.x) if wframe else None,
                "screen_w": float(sframe.width) if sframe else None,
            }
        except Exception as e:  # noqa: BLE001
            diag = {"error": repr(e)}
        with open("/tmp/gpumon-statusitem.json", "w") as f:
            json.dump(diag, f)

    def selfTest_(self, _timer):
        js = ("JSON.stringify({title:document.title,"
              "panel:!!document.querySelector('.panel'),"
              "pill:(document.querySelector('#vpn-pill')||{}).textContent||'',"
              "gpus:document.querySelectorAll('.gpu').length,"
              "hosts:[...document.querySelectorAll('.host-name')].map(e=>e.textContent)})")

        def handler(result, error):
            with open("/tmp/gpumon-webcheck.json", "w") as f:
                json.dump({"error": str(error) if error else None,
                           "result": str(result) if result else None}, f)
            NSApp.terminate_(None)

        self.web.evaluateJavaScript_completionHandler_(js, handler)

    # -- status item interaction --
    @objc.python_method
    def _refresh_title(self):
        b = _fetch_badge()
        cmap = {
            "green": NSColor.systemGreenColor(),
            "orange": NSColor.systemOrangeColor(),
            "red": NSColor.systemRedColor(),
            "gray": NSColor.secondaryLabelColor(),
        }
        if not b or not b.get("vpn"):
            text, col = "● ⚠", NSColor.secondaryLabelColor()
        else:
            col = cmap.get(b.get("color", "gray"), NSColor.secondaryLabelColor())
            text = f"● {b.get('idle', 0)}"

        attr = NSAttributedString.alloc().initWithString_attributes_(
            text, {NSForegroundColorAttributeName: col})
        self.statusItem.button().setAttributedTitle_(attr)

    def tick_(self, _timer):
        self._refresh_title()

    # web -> native messages: "resize" (popover height) and "setup" (wizard done)
    def userContentController_didReceiveScriptMessage_(self, _ucc, message):
        if message.name() == "setup":
            self._finish_setup()
            return
        try:
            h = max(220.0, min(1000.0, float(message.body())))
            self.popover.setContentSize_(NSMakeSize(POPOVER_WIDTH, h))
        except Exception:  # noqa: BLE001
            pass

    # -- setup wizard window --
    @objc.python_method
    def _open_setup_window(self):
        if self.setup_win is not None:
            self.setup_win.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            return
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)  # real window + focus
        rect = NSMakeRect(0, 0, 700, 780)
        mask = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                | NSWindowStyleMaskResizable)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, mask, NSBackingStoreBuffered, False)
        win.setTitle_("GPU Monitor — Setup")
        win.setReleasedWhenClosed_(False)
        win.setDelegate_(self)
        conf = WKWebViewConfiguration.alloc().init()
        conf.userContentController().addScriptMessageHandler_name_(self, "setup")
        web = WKWebView.alloc().initWithFrame_configuration_(rect, conf)
        web.loadRequest_(NSURLRequest.requestWithURL_(
            NSURL.URLWithString_(BASE + "/setup")))
        win.setContentView_(web)
        win.center()
        win.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.setup_win = win

    def openSetup_(self, _sender):
        self._open_setup_window()

    @objc.python_method
    def _finish_setup(self):
        if self.setup_win is not None:
            self.setup_win.close()      # triggers windowWillClose_ -> Accessory
        self._refresh_title()
        self._toggle_popover()          # show the working app

    def windowWillClose_(self, _notification):
        self.setup_win = None
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # -- popover open/close drive the server's poll cadence (fast vs slow) --
    @objc.python_method
    def _post_active(self, on):
        def go():
            try:
                req = urllib.request.Request(
                    BASE + f"/api/active?on={1 if on else 0}", method="POST")
                urllib.request.urlopen(req, timeout=2)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=go, daemon=True).start()

    def popoverWillShow_(self, _n):
        self._post_active(True)

    def popoverDidClose_(self, _n):
        self._post_active(False)

    def statusClicked_(self, sender):
        ev = NSApp.currentEvent()
        right = ev is not None and (ev.type() == NSEventTypeRightMouseUp
                                    or (ev.modifierFlags() & (1 << 18)))  # ctrl
        if right:
            self.statusItem.setMenu_(self.menu)
            self.statusItem.button().performClick_(None)
            self.statusItem.setMenu_(None)
        else:
            self._toggle_popover()

    def openPopover_(self, _sender):
        if not self.popover.isShown():
            self._toggle_popover()

    @objc.python_method
    def _toggle_popover(self):
        if self.popover.isShown():
            self.popover.performClose_(None)
        else:
            btn = self.statusItem.button()
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                btn.bounds(), btn, NSMinYEdge)
            NSApp.activateIgnoringOtherApps_(True)


def main():
    ok = ensure_server()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # no dock icon
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    if not ok:
        print("warning: server did not come up on", BASE)
    app.run()


if __name__ == "__main__":
    main()
