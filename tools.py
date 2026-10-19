import functools, io, math, os, random, re, shutil, subprocess, time, urllib.parse, urllib.request, webbrowser
from pathlib import Path
import config, llm, rag, safety, ui, voice

scale = 1.0  # real screen points per screenshot pixel, updated on every capture
_pg = None


def pg():
    global _pg
    if _pg is None:
        import pyautogui
        pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort
        pyautogui.PAUSE = 0.12
        _pg = pyautogui
    return _pg


def selfinput(f):
    @functools.wraps(f)
    def w(*a, **k):
        safety.SELF.set()
        try:
            return f(*a, **k)
        finally:
            time.sleep(0.3)
            safety.SELF.clear()
    return w


def capture():
    """Screenshot of the primary display, downscaled. Returns (jpeg bytes, (w, h))."""
    global scale
    import mss
    from PIL import Image
    with mss.mss() as s:
        raw = s.grab(s.monitors[1])
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    w = config.SHOT_W
    h = round(img.height * w / img.width)
    scale = pg().size().width / w  # handles Retina: pixels vs points
    buf = io.BytesIO()
    img.resize((w, h), Image.LANCZOS).save(buf, "JPEG", quality=80)
    return buf.getvalue(), (w, h)


def _xy(x, y):
    sw, sh = pg().size()
    return min(max(int(float(x) * scale), 0), sw - 1), min(max(int(float(y) * scale), 0), sh - 1)


def glide(X, Y):
    """Move the real cursor along a slight curve with ease in-out, like a person would."""
    p = pg()
    x0, y0 = p.position()
    d = math.hypot(X - x0, Y - y0)
    if d < 3:
        return
    n = int(min(60, max(12, d / 12)))
    off = random.uniform(-0.18, 0.18) * d
    cx, cy = (x0 + X) / 2 - (Y - y0) / d * off, (y0 + Y) / 2 + (X - x0) / d * off
    dur = min(0.7, 0.25 + d / 3000)
    for i in range(1, n + 1):
        s = i / n
        s = s * s * (3 - 2 * s)
        p.moveTo(int((1 - s) ** 2 * x0 + 2 * (1 - s) * s * cx + s * s * X),
                 int((1 - s) ** 2 * y0 + 2 * (1 - s) * s * cy + s * s * Y), _pause=False)
        time.sleep(dur / n)


def click(x, y, double=False):
    X, Y = _xy(x, y)
    glide(X, Y)
    ui.click(X, Y)
    pg().click(clicks=2 if double else 1)
    return f"clicked {X},{Y}"


@selfinput
def type_text(text, press_enter=False):
    if text.isascii():
        pg().write(text, interval=0.02)
    else:
        import pyperclip
        pyperclip.copy(text)
        pg().hotkey(*safety.norm_combo("cmd+v"))
    if press_enter:
        pg().press("enter")
    return "typed"


@selfinput
def key(combo):
    pg().hotkey(*safety.norm_combo(combo))
    return f"pressed {combo}"


def scroll(direction, amount=5):
    pg().scroll(int(amount) * (1 if str(direction).lower().startswith("u") else -1) * 100)
    return "scrolled"


def wait(seconds):
    time.sleep(min(max(float(seconds), 0), 10))
    return "waited"


def open_app(name):
    n = name.strip()
    if n.lower() in ("browser", "web browser", "default browser"):
        webbrowser.open("https://www.google.com")
    elif config.OS == "Darwin":
        r = subprocess.run(["open", "-a", n], capture_output=True, text=True)
        if r.returncode:
            return f"error: could not open {n}: {r.stderr.strip()}"
    elif config.OS == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", n])
    else:
        exe = shutil.which(n.lower()) or shutil.which(n.lower().replace(" ", "-"))
        if not exe:
            return f"error: {n} not found"
        subprocess.Popen([exe])
    time.sleep(1.5)
    return f"opened {n}"


def open_url(url, wait=2.0):
    webbrowser.open(url if re.match(r"\w+://", url) else "https://" + url)
    time.sleep(wait)
    return f"opened {url}"


_SKIP = re.compile(r"/(\.[^/]+|node_modules|site-packages|Library|__pycache__|dist|build)/")


def _resolve(path):
    """A file by path or by name: checks the usual folders, then Spotlight, newest match first."""
    p = Path(str(path).strip().strip("'\"")).expanduser()
    if p.exists():
        return p.resolve()
    for d in [Path.cwd(), *rag.DIRS]:
        if (d / p.name).exists():
            return (d / p.name).resolve()
    if config.OS == "Darwin":
        try:
            out = subprocess.run(["mdfind", "-onlyin", str(config.HOME), "-name", p.name],
                                 capture_output=True, text=True, timeout=4).stdout.splitlines()
            hits = [Path(h) for h in out if Path(h).name.lower() == p.name.lower() and not _SKIP.search(h)]
            if hits:
                return max(hits, key=lambda h: h.stat().st_mtime)
        except Exception:
            pass
    raise FileNotFoundError(f"I couldn't find {p.name}")


EDITORS = ("VSCode", "todesktop", "Xcode", "sublime", "Zed", "jetbrains", "windsurf", "TextEdit", "BBEdit", "Nova")


def front_bundle():
    if config.OS != "Darwin":
        return ""
    return subprocess.run(["osascript", "-e", 'tell application "System Events" to get bundle identifier of first '
                           'application process whose frontmost is true'], capture_output=True, text=True).stdout.strip()


def open_file(path, wait=1.0):
    p = str(_resolve(path))
    if config.OS == "Darwin":
        b = front_bundle()
        subprocess.run(["open", "-b", b, p] if any(e.lower() in b.lower() for e in EDITORS) else ["open", p])
    elif config.OS == "Windows":
        os.startfile(p)
    else:
        subprocess.Popen(["xdg-open", p])
    time.sleep(wait)
    return f"opened {p}"


def search_files(query):
    return rag.search(query)


SPOKEN = "Answer for speech: at most three short sentences, plain words, no markdown, no lists, no code."


def summarize_file(path, question="What is this and what does it do?"):
    txt = rag.read_text(_resolve(path), pages=15)[:40000]
    if not txt.strip():
        return "error: no readable text"
    return llm.text(f"{question}\n{SPOKEN}\n\nFile {Path(path).name}:\n{txt}").strip()


def read_screen(question="What is on my screen?"):
    """Answer a question about whatever is on screen, in one quick vision call."""
    jpeg, _ = capture()
    return llm.vision(f"This is the user's screen right now. They ask: {question}\n"
                      f"If it is code, explain what it does or what is wrong. {SPOKEN}", jpeg).strip()


def remove_background(path=""):
    from PIL import Image
    from rembg import remove
    if path:
        p = _resolve(path)
    else:
        imgs = [f for f in (config.HOME / "Desktop").iterdir()
                if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and "_nobg" not in f.stem]
        if not imgs:
            return "error: no image on the Desktop"
        p = max(imgs, key=lambda f: f.stat().st_mtime)
    out = p.with_name(p.stem + "_nobg.png")
    remove(Image.open(p)).save(out)
    open_file(str(out))
    return f"saved {out}"


def parse_strokes(s):
    num = r"(-?\d+(?:\.\d+)?)"
    strokes = [[(float(a), float(b)) for a, b in re.findall(num + r"\s*,\s*" + num, part)] for part in str(s).split(";")]
    return [st for st in strokes if len(st) >= 2]


def _densify(st, step=5.0):
    out = [st[0]]
    for (x0, y0), (x1, y1) in zip(st, st[1:]):
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out += [(x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k) for i in range(1, k + 1)]
    return out


def _stroke(points):
    """Press, drag smoothly through screen points, release."""
    p = pg()
    glide(*map(int, points[0]))
    p.mouseDown(_pause=False)
    try:
        for x, y in _densify(points)[1:]:
            if safety.cancelled():
                break
            p.dragTo(int(x), int(y), duration=0, button="left", mouseDownUp=False, _pause=False)
            time.sleep(0.004)
    finally:
        p.mouseUp(_pause=False)


def draw(strokes):
    strokes = parse_strokes(strokes)
    if not strokes:
        return "error: no valid strokes"
    for st in strokes:
        _stroke([_xy(x, y) for x, y in st])
    return f"drew {len(strokes)} strokes"


def _points(st):
    """Accept [[x, y], ...], [{"x":..,"y":..}, ...] or a flat [x, y, x, y, ...] list."""
    if isinstance(st, dict):
        st = st.get("points", [])
    if st and all(isinstance(v, (int, float)) for v in st):
        return [(float(st[i]), float(st[i + 1])) for i in range(0, len(st) - 1, 2)]
    out = []
    for p in st:
        if isinstance(p, dict) and "x" in p and "y" in p:
            out.append((float(p["x"]), float(p["y"])))
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append((float(p[0]), float(p[1])))
    return out


def _smooth(st, n=3):
    """Chaikin corner cutting: turns polylines into smooth curves, keeping the end points."""
    for _ in range(n):
        if len(st) < 3:
            return st
        mid = [p for (x0, y0), (x1, y1) in zip(st, st[1:])
               for p in ((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))]
        st = [st[0]] + mid[1:-1] + [st[-1]]
    return st


SKETCH = """Make a clean, cute, instantly recognizable line drawing of: {subject}.
Return JSON {{"strokes": [[[x, y], ...], ...]}} on a 1000 x 1000 canvas, origin top-left.
Use 12 to 45 strokes with 4 to 60 points each; curves need many points, closed shapes end at their start.
Outline first, then the key features (eyes, ears, whiskers, windows...), then small details. Line art only."""


def plan_sketch(subject):
    try:
        data = llm.json_out(SKETCH.format(subject=subject))
    except Exception as e:
        print("sketch plan failed:", e)
        return []
    return [st for st in map(_points, data.get("strokes", []) if isinstance(data, dict) else data) if len(st) >= 2]


def sketch(subject, app="excalidraw", x1=None, y1=None, x2=None, y2=None, strokes=None):
    strokes = strokes or plan_sketch(subject)
    if not strokes:
        return "error: could not plan the drawing"
    sw, sh = pg().size()
    if None not in (x1, y1, x2, y2):
        (bx0, by0), (bx1, by1) = _xy(x1, y1), _xy(x2, y2)
    else:
        bx0, by0, bx1, by1 = sw * 0.3, sh * 0.22, sw * 0.7, sh * 0.85
    ui.agent(True)
    if "excali" in str(app).lower():
        glide(int((bx0 + bx1) / 2), int(by0))
        pg().click()
        key("esc")
        key("7")  # Excalidraw free-draw tool
        time.sleep(0.3)
    xs = [x for st in strokes for x, _ in st]
    ys = [y for st in strokes for _, y in st]
    w, h = max(xs) - min(xs) or 1, max(ys) - min(ys) or 1
    k = min((bx1 - bx0) / w, (by1 - by0) / h) * 0.9
    ox, oy = (bx0 + bx1 - w * k) / 2 - min(xs) * k, (by0 + by1 - h * k) / 2 - min(ys) * k
    for st in strokes:
        if safety.cancelled():
            ui.agent(False)
            return "stopped"
        _stroke(_smooth([(ox + x * k, oy + y * k) for x, y in st]))
    if "excali" in str(app).lower():
        key("1")  # back to the selection tool
    ui.agent(False)
    return f"drew {subject} with {len(strokes)} strokes"


def youtube(query, play=True):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    if play:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US"})
            html = urllib.request.urlopen(req, timeout=4).read().decode("utf-8", "ignore")
            ids = re.findall(r'"videoId":"([\w-]{11})"', html)
            if ids:
                open_url(f"https://www.youtube.com/watch?v={ids[0]}", wait=0)
                return f"playing the top YouTube result for {query}"
        except Exception:
            pass
    open_url(url, wait=0)
    return f"opened YouTube results for {query}"


def look(question):
    import camera
    jpeg = camera.snap()
    ui.show_image(jpeg)
    return llm.vision(f"You are Monday, an AI assistant seeing the user through their webcam. {question}\n"
                      "Answer in at most two short spoken sentences. If they hold an object, name it and add one "
                      "useful or fun tip about it.", jpeg).strip()


def confirm(question):
    return "yes" if voice.confirm(question) else "no"


TOOLS = {f.__name__: f for f in (click, type_text, key, scroll, wait, open_app, open_url, open_file, read_screen,
                                 search_files, summarize_file, remove_background, draw, sketch, youtube, look, confirm)}
