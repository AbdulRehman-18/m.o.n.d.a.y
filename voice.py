import difflib, queue, random, re, subprocess, threading, time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import config, safety, ui

SR, FRAME = 16000, 480  # 30 ms frames for the wake engine
TEXT = False  # typed input mode, no microphone
SPEAKING = threading.Event()  # Monday is talking, so the mic ignores its own voice
HUSH = threading.Event()  # cut the current speech short
_audio, _done, _held = [], threading.Event(), threading.Event()
_stream = _stt = None
_q = queue.Queue()
_cmds, _direct, _want_direct = queue.Queue(), queue.Queue(), threading.Event()
_mute_until = _follow_until = _converse_until = 0.0
_busy = False
_last_cmd = ["", 0.0]  # last command heard, to ignore an instant repeat that came without the wake word
_saying, _said_log = "", deque(maxlen=4)  # what Monday is saying or just said, to remove its own echo

WAKE = re.compile(r"^\W*(?:(?:hey|hi|hello|ok|okay|yo|oi|wake up|good morning)\W+)*"
                  r"(?:monday|munday|mundy|mon day|mondays)\b\W*(.*)$", re.I)
DADDY = re.compile(r"\bwake up\W+daddy'?s home\b", re.I)
JUNK = {"", "you", "thank you", "thanks for watching", "bye", "so", "uh", "um", "hmm", "oh"}
ACKS = ["Yes?", "Hi! I'm listening.", "Mm-hmm?", "I'm here!", "Yes yes?", "Tell me!"]
VOCAB = "Monday, YouTube, Excalidraw, Safari, Chrome, Spotify, WhatsApp, VS Code, Finder."


def _is(k, name):
    from pynput import keyboard as kb
    names = [name] + (["alt_gr"] if name == "alt_r" else [])
    return any(k == getattr(kb.Key, n) for n in names if hasattr(kb.Key, n)) or getattr(k, "char", None) == name


def _cb(indata, frames, t, status):
    _audio.append(indata[:, 0].copy())


def start_listener(ptt=True):
    """pynput listener for push-to-talk and/or the kill key."""
    from pynput import keyboard as kb
    import sounddevice as sd

    def press(k):
        global _stream
        if ptt and _is(k, config.PTT_KEY) and not _held.is_set():
            _held.set(); _audio.clear()
            _stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=_cb)
            _stream.start()
            ui.wake(); ui.state("listening")
        elif _is(k, config.KILL_KEY) and not safety.SELF.is_set():
            safety.STOP.set(); HUSH.set()

    def release(k):
        if ptt and _is(k, config.PTT_KEY) and _held.is_set():
            _held.clear(); _stream.stop(); _stream.close(); _done.set()
            ui.state("thinking")

    kb.Listener(on_press=press, on_release=release, daemon=True).start()


# ---------- speech to text: Whisper large-v3-turbo on the Apple GPU, faster-whisper elsewhere ----------

def preload():
    global _stt
    if config.STT == "mlx":
        import mlx_whisper
        _stt = mlx_whisper
        _transcribe(np.zeros(SR // 2, "float32"))  # load weights now, not on the first command
    else:
        from faster_whisper import WhisperModel
        _stt = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")


def _transcribe(audio, prompt=None):
    if config.STT == "mlx":
        r = _stt.transcribe(audio, path_or_hf_repo=config.STT_MODEL, language=config.WHISPER_LANG, verbose=None,
                            condition_on_previous_text=False, initial_prompt=prompt)
        segs = [(s["text"], s.get("no_speech_prob", 0)) for s in r["segments"]]
    else:
        out, _ = _stt.transcribe(audio, language=config.WHISPER_LANG, beam_size=1, vad_filter=False,
                                 condition_on_previous_text=False, initial_prompt=prompt)
        segs = [(s.text, s.no_speech_prob) for s in out]
    text = " ".join(t.strip() for t, p in segs if p < 0.6).strip()
    return "" if text.lower().strip(" .!?,") in JUNK else text


def start():
    preload()
    if config.WAKE_MODE == "ptt":
        start_listener(ptt=True)
    else:
        threading.Thread(target=_engine, daemon=True).start()
        if not ui.handles_keys():
            start_listener(ptt=False)


# ---------- wake engine: "hey Monday" or a double clap, always listening ----------

def _engine():
    global _stream
    import sounddevice as sd
    frames = queue.Queue()
    _stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=FRAME,
                             callback=lambda d, n, t, s: frames.put(d[:, 0].copy()))
    _stream.start()
    noise, pre, seg, lv, quiet = 0.004, deque(maxlen=10), None, [], 0
    while True:
        f = frames.get()
        level = float(np.sqrt(np.mean(f * f)))
        talking = SPEAKING.is_set() or time.time() < _mute_until
        if not talking:
            ui.level(min(1.0, level * 12))
        if seg is None:
            if _pending:
                _flush_pending()
            if not talking:
                noise = max(0.002, 0.97 * noise + 0.03 * min(level, 0.05))
            pre.append(f)
            if level > max(noise * (6 if talking else 4), 0.012):
                seg, lv, quiet = list(pre), [level], 0
            continue
        seg.append(f); lv.append(level)
        quiet = quiet + 1 if level < max(noise * 2.5, 0.008) else 0
        if quiet >= config.END_FRAMES or len(seg) > 400:  # silence ends the phrase, 12 s max
            try:
                _segment(np.concatenate(seg), np.array(lv), noise)
            except Exception as e:
                print("wake engine error:", e)
            seg = None; pre.clear()


def _double_clap(lv, noise):
    hi = lv.max()
    if hi < 0.06 or (lv > max(noise * 4, 0.012)).sum() > 16:  # quiet, or too long to be claps
        return False
    loud = np.flatnonzero(lv > hi * 0.35)
    runs, start = [], loud[0]
    for a, b in zip(loud, loud[1:]):
        if b - a > 1:
            runs.append((start, a)); start = b
    runs.append((start, loud[-1]))
    if len(runs) != 2:
        return False
    (s1, e1), (s2, e2) = runs
    return e1 - s1 <= 3 and e2 - s2 <= 3 and 3 <= s2 - e1 <= 27  # two sharp hits 0.1 to 0.8 s apart


def _woke():
    global _follow_until, _mute_until
    if _busy or SPEAKING.is_set():  # "Monday?" mid-task: drop what it is doing and listen
        safety.STOP.set()
        interrupt()
    ui.wake(); ui.state("listening", 10)
    if config.ACK == "speak":
        ack = random.choice(ACKS)
        ui.say("monday", ack)
        _q.put(ack)
    else:
        _chime()
        _mute_until = time.time() + 0.2
    _follow_until = time.time() + 10


_NUMS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                         "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUMS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "ninety": "90", "hundred": "100"})


def _norm(w):
    """Comparable form of a word: lower case, digits for number words ("five" = "5"), no plural s."""
    w = re.sub(r"[^a-z0-9']", "", w.lower())
    w = _NUMS.get(w, w)
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _recent_speech(window=6.0):
    now = time.time()
    return " ".join([_saying] + [t for t, at in _said_log if now - at < window])


def _is_echo(text):
    """A short transcript made almost only of words Monday just said, like "five minutes" after "Timer set for 5 minutes"."""
    ref = {_norm(w) for w in _recent_speech().split()}
    words = [_norm(w) for w in text.split() if _norm(w)]
    if not ref or not words or len(words) > 8:
        return False
    if any(w.isdigit() and w not in ref for w in words):
        return False  # a different number ("10 minutes" after "5 minutes") means it is really you
    return sum(w in ref for w in words) / len(words) >= 0.75


def _strip_echo(text):
    """Remove the parts of a transcript that are Monday's own voice coming back through the mic."""
    ref = _recent_speech()
    if not ref.strip():
        return text
    words = text.split()
    tw, rw = [_norm(w) for w in words], [_norm(w) for w in ref.split()]
    keep = [True] * len(words)
    for a, _, n in difflib.SequenceMatcher(None, tw, rw, autojunk=False).get_matching_blocks():
        if n >= 2 or (n == 1 and a == 0 and len(rw) <= 4):
            keep[a:a + n] = [False] * n
    return " ".join(w for w, k in zip(words, keep) if k).strip(" ,.!?")


DANGLING = re.compile(r"(?:\.\.\.|…|-)\s*$|\b(?:to|and|the|a|an|like|so|but|or|of|with|for|my|your|um|uh|that|this|is|"
                      r"can you|could you|please|want|i|i'm|then|also|in|on|about)[,\s]*$", re.I)
_pending = None  # (text, time): a sentence that sounded unfinished, waiting for the rest


def _conversing():
    """While Monday is busy, talking, or just answered, no wake word is needed."""
    return _busy or SPEAKING.is_set() or time.time() < _converse_until


_pop = None


def _chime():
    """A soft bubble pop, generated once."""
    global _pop
    import sounddevice as sd
    if _pop is None:
        sr = 24000
        t = np.arange(int(sr * 0.16)) / sr
        f = 520 + 900 * (1 - np.exp(-t * 40))
        _pop = (0.22 * np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 26)
                + 0.08 * np.sin(2 * np.pi * 1760 * t) * np.exp(-t * 45)).astype("float32"), sr
    try:
        sd.play(*_pop)
    except Exception as e:
        print("chime failed:", e)


def _segment(audio, lv, noise):
    global _pending
    expecting = _want_direct.is_set() or time.time() < _follow_until or _conversing() or _pending is not None
    if config.CLAP and not expecting and _double_clap(lv, noise):
        ui.log("double clap")
        return _woke()
    if (lv > max(noise * 4, 0.012)).sum() < 6:  # under 180 ms of sound, not speech
        return
    heard = _transcribe(audio, prompt=VOCAB if expecting else None)
    if _is_echo(heard):
        return ui.log(f"(ignored my own voice: {heard})")
    text = _strip_echo(heard)
    if len(re.findall(r"\w+", text)) == 0:
        return
    if _pending:  # the rest of an unfinished sentence
        text, _pending = _pending[0] + " " + text, None
    if DANGLING.search(text) and not _want_direct.is_set():
        _pending = (text, time.time())  # wait a moment for them to finish the thought
        return
    _route(text)


def _flush_pending():
    global _pending
    if _pending and time.time() - _pending[1] > config.FINISH_S:
        text, _pending = _pending[0], None
        _route(text.rstrip(". …"))


def _route(text):
    global _follow_until
    ui.log(f"heard: {text}")
    if _want_direct.is_set():
        _want_direct.clear()
        return _direct.put(text)
    m = WAKE.match(text)
    if time.time() < _follow_until or _conversing():
        followed = time.time() < _follow_until
        _follow_until = 0.0
        if m and not m.group(1).strip():  # just "Monday?" while busy: stop and listen
            return _woke()
        cmd = m.group(1).strip() if m else text
        key = " ".join(_norm(w) for w in cmd.split())
        if not m and not followed and key == _last_cmd[0] and time.time() - _last_cmd[1] < 20:
            return ui.log(f"(ignored repeat without wake word: {cmd})")  # stops feedback loops
        _last_cmd[:] = [key, time.time()]
        ui.state("thinking")
        return _cmds.put(cmd)
    if DADDY.search(text):
        return _woke()
    if m:
        rest = m.group(1).strip()
        if len(rest.split()) >= 2:  # "hey Monday, open YouTube" in one breath
            ui.wake(); ui.state("thinking")
            return _cmds.put(rest)
        _woke()


def listen():
    """Block until the next command: typed, push-to-talk, or after the wake word."""
    if TEXT:
        return input("you> ").strip()
    if config.WAKE_MODE != "ptt":
        return _cmds.get()
    _done.clear()
    while not _done.wait(0.5):
        pass
    audio = np.concatenate(_audio) if _audio else np.zeros(0, "float32")
    if len(audio) < SR * 0.4:
        return ""
    return _transcribe(audio, prompt=VOCAB)


# ---------- text to speech: Kokoro neural voice on device, macOS say as fallback ----------

_kokoro, _cache = None, {}


def _load_kokoro():
    global _kokoro
    if _kokoro is None:
        import onnxruntime
        onnxruntime.set_default_logger_severity(3)  # errors only
        from kokoro_onnx import Kokoro
        d = config.HOME / ".monday" / "models"
        _kokoro = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
    return _kokoro


_style = None


def voice_style(spec):
    """"af_bella" or a blend like "af_bella*0.6+af_sky*0.4"."""
    k = _load_kokoro()
    parts = [p.split("*") for p in spec.replace(" ", "").split("+")]
    if len(parts) == 1:
        return parts[0][0]
    total = sum(float(p[1]) if len(p) > 1 else 1.0 for p in parts)
    return sum(k.get_voice_style(p[0]) * (float(p[1]) if len(p) > 1 else 1.0) / total for p in parts)


def _synth(text):
    global _style
    if text in _cache:
        return _cache[text]
    if _style is None:
        _style = voice_style(config.TTS_VOICE)
    lang = "en-gb" if config.TTS_VOICE[:1] == "b" else "en-us"
    a, sr = _load_kokoro().create(text, voice=_style, speed=config.TTS_SPEED, lang=lang)
    if len(text) < 60:
        _cache[text] = (a, sr)
    return a, sr


def _play(a, sr):
    import sounddevice as sd
    sd.play(a, sr)
    t0, n, win = time.time(), len(a), sr // 20
    while True:
        i = int((time.time() - t0) * sr)
        if i >= n or HUSH.is_set():
            break
        chunk = a[i:i + win]
        ui.level(min(1.0, float(np.sqrt(np.mean(chunk * chunk))) * 6) if len(chunk) else 0)
        time.sleep(1 / 40)
    if HUSH.is_set():
        sd.stop()
    else:
        sd.wait()


def _sentences(t):
    return [s for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s]


_NOT_SPOKEN = re.compile(r"[^\w\s.,!?;:'\"()%$&@#+/=-]")


def _say(t):
    t = re.sub(r"\s+", " ", _NOT_SPOKEN.sub("", t)).strip()  # emojis and symbols the voice would stumble over
    if not t:
        return
    if config.TTS == "kokoro":
        try:
            parts = _sentences(t)
            with ThreadPoolExecutor(1) as ex:  # synthesize the next sentence while this one plays
                futs = [ex.submit(_synth, s) for s in parts]
                for f in futs:
                    if HUSH.is_set():
                        break
                    _play(*f.result())
            return
        except Exception as e:
            print("kokoro error, using say:", e)
    if config.OS == "Darwin":
        subprocess.run(["say", t])
    else:
        import pyttsx3
        e = pyttsx3.init(); e.say(t); e.runAndWait()


def _worker():
    global _mute_until, _saying
    if config.TTS == "kokoro":
        try:
            for s in ACKS + ["Okay!", "Okay, cancelled.", "Done!"]:
                _synth(s)
        except Exception as e:
            print("kokoro warmup failed:", e)
    while True:
        t = _q.get()
        HUSH.clear()
        _saying = t
        SPEAKING.set(); ui.speaking(True)
        try:
            _say(t)
        except Exception as e:
            print("tts error:", e)
        finally:
            _said_log.append((t, time.time())); _saying = ""
            _mute_until = time.time() + 0.3
            SPEAKING.clear(); ui.speaking(False); ui.level(0)
        _q.task_done()


threading.Thread(target=_worker, daemon=True).start()


def speak(t):
    if safety.cancelled():  # this task was interrupted by a newer command
        return
    print("monday>", t, flush=True)
    ui.say("monday", t)
    _q.put(t)


def hush():
    HUSH.set()


def interrupt():
    """Stop talking now and drop everything queued."""
    HUSH.set()
    while True:
        try:
            _q.get_nowait()
            _q.task_done()
        except queue.Empty:
            break


def end_conversation():
    """Esc: stop listening without the wake word until Monday is woken again."""
    global _converse_until, _follow_until, _pending, _busy
    _converse_until = _follow_until = 0.0
    _pending, _busy = None, False


def busy(on):
    global _busy, _converse_until
    _busy = bool(on)
    if not on:
        _converse_until = time.time() + config.CONVERSE_S


def wait_spoken():
    """Wait until Monday has finished talking, or the task was interrupted."""
    time.sleep(0.05)
    while (not _q.empty() or SPEAKING.is_set()) and not safety.cancelled():
        time.sleep(0.05)


def confirm(prompt):
    speak(f"{prompt} Say yes to continue.")
    wait_spoken()
    if TEXT or config.WAKE_MODE == "ptt":
        ans = listen()
    else:
        _want_direct.set(); ui.state("listening", 8)
        try:
            ans = _direct.get(timeout=8)
        except queue.Empty:
            ans = ""
        _want_direct.clear()
    return bool(re.search(r"\b(yes|yeah|yep|sure|confirm|proceed|go ahead|do it|haan|ha)\b", ans.lower()))
