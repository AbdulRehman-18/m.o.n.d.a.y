"""Jarvis HUD for macOS: hud.html in a transparent, click-through, always-on-top window over the main screen.
The window is hidden from screenshots so the agent never sees it. While the agent works, the real cursor is
hidden and the HUD draws Monday's own cursor in its place."""
import base64, ctypes, json, sys, threading, time
from pathlib import Path
from AppKit import NSApplication, NSBackingStoreBuffered, NSColor, NSEvent, NSScreen, NSTimer, NSWindow
from Foundation import NSURL, NSMakeRect, NSObject
from WebKit import WKWebView, WKWebViewConfiguration

BORDERLESS, ACCESSORY, SHARING_NONE, LEVEL = 0, 1, 0, 1000  # 1000 = NSScreenSaverWindowLevel
ALL_SPACES, STATIONARY, IGNORES_CYCLE, FS_AUX = 1 << 0, 1 << 4, 1 << 6, 1 << 8
KEYDOWN_MASK = 1 << 10
HTML = Path(__file__).with_name("hud.html")

_lock = threading.Lock()
_js, _keep = [], []
_st = {"mode": "idle", "until": 0.0, "level": 0.0, "sent_level": -1.0, "agent": False, "shown": False, "pos": None,
       "talking": False}
_web = None
_H = 0.0
_setup = {"mode": "full", "nx": 0, "nw": 0, "nh": 32}
_ready = False
M_KEY, CTRL, OPT = 46, 1 << 18, 1 << 19


def _send(js):
    with _lock:
        _js.append(js)


# ---- API used by ui.py (any thread) ----
def log(s): pass  # the HUD shows captions only, ui.log still prints
def say(who, text): _send(f"H.say({json.dumps(who)},{json.dumps(str(text))})")
def level(x): _st["level"] = float(x)
def wake(): _send("H.wake()")
def click(x, y): _send(f"H.click({float(x)},{float(y)})")
def agent(on): _st["agent"] = bool(on)


def state(mode, ttl=None):
    _st["mode"], _st["until"] = mode, (time.time() + ttl if ttl else 0.0)
    if not _st["talking"]:
        _send(f"H.state({json.dumps(mode)})")


def speaking(on):
    _st["talking"] = bool(on)
    _send(f"H.state({json.dumps('speaking' if on else _st['mode'])})")


def set_mode(mode):
    _setup["mode"] = mode
    _send(f"H.mode({json.dumps(mode)})")


def get_mode():
    return _setup["mode"]


def show_image(jpeg):
    _send(f"H.image('data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}')")


# ---- system cursor hide/show, works while another app is in front ----
_cg = None


def _system_cursor(visible):
    global _cg
    try:
        if _cg is None:
            cg = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cg._CGSDefaultConnection.restype = ctypes.c_int
            cg.CGSSetConnectionProperty.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
            cg.CGMainDisplayID.restype = ctypes.c_uint32
            key = cf.CFStringCreateWithCString(None, b"SetsCursorInBackground", 0x08000100)  # UTF-8
            conn = cg._CGSDefaultConnection()
            cg.CGSSetConnectionProperty(conn, conn, key, ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue"))
            _cg = cg
        (_cg.CGDisplayShowCursor if visible else _cg.CGDisplayHideCursor)(_cg.CGMainDisplayID())
    except Exception as e:
        print("cursor toggle failed:", e)


def _tick():
    global _ready
    if _web is None or _web.isLoading():
        return
    if not _ready:
        _ready = True
        _web.evaluateJavaScript_completionHandler_(f"window.H&&H.setup({json.dumps(_setup)})", None)
    if _st["until"] and time.time() > _st["until"]:
        _st["mode"], _st["until"] = "idle", 0.0
        if not _st["talking"]:
            _send('H.state("idle")')
    parts = []
    with _lock:
        parts, _js[:] = _js[:], []
    if _st["agent"] != _st["shown"]:
        _st["shown"] = _st["agent"]
        _system_cursor(not _st["agent"])
        parts.append(f"H.cursor({'true' if _st['agent'] else 'false'})")
    if _st["agent"]:
        m = NSEvent.mouseLocation()
        pos = (round(m.x, 1), round(_H - m.y, 1))
        if pos != _st["pos"]:
            _st["pos"] = pos
            parts.append(f"H.pos({pos[0]},{pos[1]})")
    lv = round(_st["level"], 2)
    if abs(lv - _st["sent_level"]) >= 0.02:
        _st["sent_level"] = lv
        parts.append(f"H.level({lv})")
    if parts:
        _web.evaluateJavaScript_completionHandler_("window.H&&(" + ",".join(parts) + ")", None)


class Ticker(NSObject):
    def tick_(self, _timer):
        try:
            _tick()
        except Exception as e:
            print("hud tick error:", e)


def _notch(scr):
    """Notch position and size in points, or zero width on screens without one."""
    try:
        top = scr.safeAreaInsets().top
        left, right = scr.auxiliaryTopLeftArea(), scr.auxiliaryTopRightArea()
        if top > 0 and left.size.width and right.size.width:
            w = scr.frame().size.width - left.size.width - right.size.width
            return {"nx": left.size.width, "nw": w, "nh": top}
    except Exception:
        pass
    return {"nx": 0, "nw": 0, "nh": 32}


def start(on_key=None, mode="full", on_toggle=None):
    global _web, _H
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(ACCESSORY)  # no dock icon, never steals focus
    scr = NSScreen.screens()[0]
    f = scr.frame()
    _H = f.size.height
    _setup.update(_notch(scr), mode=mode)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(f, BORDERLESS, NSBackingStoreBuffered, False)
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setIgnoresMouseEvents_(True)
    win.setHasShadow_(False)
    win.setLevel_(LEVEL)
    win.setCollectionBehavior_(ALL_SPACES | STATIONARY | IGNORES_CYCLE | FS_AUX)
    win.setSharingType_(SHARING_NONE)  # invisible to screenshots, so the agent sees the real screen
    cfg = WKWebViewConfiguration.alloc().init()
    web = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, f.size.width, f.size.height), cfg)
    web.setValue_forKey_(False, "drawsBackground")
    url = NSURL.fileURLWithPath_(str(HTML))
    web.loadFileURL_allowingReadAccessToURL_(url, url.URLByDeletingLastPathComponent())
    win.setContentView_(web)
    win.orderFrontRegardless()
    _web = web
    ticker = Ticker.alloc().init()
    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1 / 60, ticker, "tick:", None, True)
    def key(e):
        if e.keyCode() == M_KEY and e.modifierFlags() & CTRL and e.modifierFlags() & OPT:
            if on_toggle:
                on_toggle()  # ctrl+option+M switches between full and island
        elif on_key:
            on_key(e.keyCode())
    mon = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(KEYDOWN_MASK, key)
    _keep.extend([app, win, web, cfg, ticker, timer, mon])
    return sys.modules[__name__]


def run():
    try:
        NSApplication.sharedApplication().run()
    finally:
        if _st["shown"]:
            _system_cursor(True)
