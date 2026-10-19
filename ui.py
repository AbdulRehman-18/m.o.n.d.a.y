"""UI facade: the Jarvis HUD on macOS, a small Tk window elsewhere, console only when OVERLAY=0."""
import json, os, queue
import config, safety

SETTINGS = config.HOME / ".monday" / "settings.json"

_ov = None
ESC = 53  # macOS key code


class Overlay:
    def __init__(self):
        import tkinter as tk
        self.q, self.lines = queue.Queue(), []
        self.root = tk.Tk()
        self.root.title("Monday")
        self.root.attributes("-topmost", True)
        self.root.geometry("380x200+20+60")
        self.root.configure(bg="#111111")
        self.lbl = tk.Label(self.root, text="Monday is starting", justify="left", anchor="nw", fg="#ffffff",
                            bg="#111111", font=("Menlo", 11), wraplength=360)
        self.lbl.pack(fill="both", expand=True, padx=10, pady=8)
        self.root.after(150, self.poll)

    def poll(self):
        while not self.q.empty():
            self.lines = (self.lines + [self.q.get()])[-8:]
        self.lbl.config(text="\n".join(self.lines))
        self.root.after(150, self.poll)

    def log(self, s):
        self.q.put(str(s)[:90])

    def run(self):
        self.root.mainloop()


def _key(code):
    if code == ESC and not safety.SELF.is_set():
        safety.STOP.set()
        import voice
        voice.hush()
        voice.end_conversation()
        state("idle")


def start():
    global _ov
    if os.getenv("OVERLAY", "1") != "1":
        return None
    try:
        if config.OS == "Darwin":
            import hud
            _ov = hud.start(on_key=_key, mode=_load().get("hud_mode", config.HUD_MODE), on_toggle=toggle_mode)
        else:
            _ov = Overlay()
    except Exception as e:
        print("overlay off:", e)
    return _ov


def _load():
    try:
        return json.loads(SETTINGS.read_text())
    except Exception:
        return {}


def set_mode(mode):
    """full: orb at the bottom and glowing screen edges. island: Monday lives in the notch."""
    if not hasattr(_ov, "set_mode"):
        return False
    _ov.set_mode(mode)
    try:
        SETTINGS.parent.mkdir(exist_ok=True)
        SETTINGS.write_text(json.dumps({**_load(), "hud_mode": mode}))
    except Exception:
        pass
    return True


def toggle_mode():
    if hasattr(_ov, "get_mode"):
        set_mode("full" if _ov.get_mode() == "island" else "island")


def handles_keys():
    """True when the HUD already watches the kill key, so pynput is not needed for it."""
    return _ov is not None and config.OS == "Darwin" and config.KILL_KEY == "esc"


def _call(name, *a):
    f = getattr(_ov, name, None)
    if f:
        try:
            f(*a)
        except Exception:
            pass


def log(s):
    print(s, flush=True)
    _call("log", s)


def say(who, text):
    """Caption: who is "you" or "monday"."""
    if who == "you":
        print(f"you: {text}", flush=True)
    if hasattr(_ov, "say"):
        _call("say", who, text)
    else:
        _call("log", f"{who}: {text}")


def state(mode, ttl=None): _call("state", mode, ttl)
def level(x): _call("level", x)
def click(x, y): _call("click", x, y)
def wake(): _call("wake")
def agent(on): _call("agent", on)
def speaking(on): _call("speaking", on)
def show_image(jpeg): _call("show_image", jpeg)
