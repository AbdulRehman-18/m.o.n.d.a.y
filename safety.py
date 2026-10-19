import json, re, threading, time
import config

STOP = threading.Event()  # set by the kill key
SELF = threading.Event()  # set while Monday itself sends keys, so they do not trigger the kill key
GEN = [0]  # task generation: bumped when a new command interrupts the current one


def cancelled():
    """True when the kill key was pressed or a newer command has replaced the task running on this thread."""
    g = getattr(threading.current_thread(), "gen", None)
    return STOP.is_set() or (g is not None and g != GEN[0])
PRIMARY = "command" if config.OS == "Darwin" else "ctrl"
_ALIAS = {"cmd": PRIMARY, "command": PRIMARY, "meta": PRIMARY, "super": PRIMARY, "control": "ctrl",
          "option": "alt", "return": "enter", "escape": "esc", "del": "delete", "windows": "win"}
RISKY_GOAL = re.compile(r"\b(delete|erase|trash|uninstall|format|shut ?down|restart|purchase|buy|pay|send|post|submit)\b", re.I)
BLOCK_TEXT = re.compile(r"rm\s+-rf|sudo\s|mkfs|format\s+c:|del\s+/[fsq]|:\(\)\s*\{", re.I)


def norm_combo(combo):
    return [_ALIAS.get(p, p) for p in re.split(r"[+\s]+", str(combo).lower().strip()) if p]


def risky_combo(parts):
    s = set(parts)
    mod = s & {"command", "ctrl", "alt", "shift"}
    return bool(mod and s & {"delete", "backspace"}) or {"alt", "f4"} <= s or {"command", "q"} <= s


def goal_is_risky(goal):
    return bool(RISKY_GOAL.search(goal))


def check(name, args):
    """Return allow, confirm or block for a proposed action."""
    if name == "type_text" and BLOCK_TEXT.search(str(args.get("text", ""))):
        return "block"
    if name == "key" and risky_combo(norm_combo(args.get("combo", ""))):
        return "confirm"
    return "allow"


def log(step, name, args, result):
    try:
        d = config.HOME / ".monday"
        d.mkdir(exist_ok=True)
        with open(d / "actions.log", "a") as f:
            f.write(json.dumps({"t": time.time(), "step": step, "tool": name, "args": args, "result": str(result)[:300]}) + "\n")
    except Exception:
        pass
