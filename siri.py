"""Everyday assistant things: timers (in Monday), reminders, calendar and notes (Apple apps, so they sync to your
iPhone), screenshots and locking the screen."""
import datetime, re, subprocess, threading, time
import config, ui, voice

_timers = []  # [(label, end time, threading.Timer)]


def _osa(script, timeout=20):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout.strip()


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, text):
    try:
        _osa(f"display notification {_q(text)} with title {_q(title)} sound name \"Glass\"")
    except Exception:
        pass


# ---------- timers ----------

UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}


def parse_duration(text):
    """'10 minutes', '1 hour 30 minutes', 'an hour and a half', '90 seconds' -> seconds."""
    t = text.lower().replace("an hour and a half", "90 minutes").replace("half an hour", "30 minutes")
    t = re.sub(r"\b(a|an|one)\s+(?=(second|sec|minute|min|hour|hr))", "1 ", t)
    total = sum(float(n) * UNITS[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*(second|sec|minute|min|hour|hr)s?\b", t))
    return int(total)


def _say_duration(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{h} hour{'s' * (h != 1)}" if h else "", f"{m} minute{'s' * (m != 1)}" if m else "",
             f"{s} second{'s' * (s != 1)}" if s and not h else ""]
    return " ".join(p for p in parts if p) or "0 seconds"


def set_timer(seconds, label=""):
    if seconds <= 0:
        return "How long should the timer be?"
    name = label or _say_duration(seconds)

    def ring():
        _timers[:] = [x for x in _timers if x[2] is not th]
        notify("Monday timer", f"{name} timer is done!")
        ui.wake(); ui.state("speaking", 6)
        for _ in range(2):
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
        voice.speak(f"Ding! Your {name} timer is done!")

    th = threading.Timer(seconds, ring)
    th.daemon = True
    th.start()
    _timers.append((name, time.time() + seconds, th))
    return f"Timer set for {_say_duration(seconds)}!"


def timers_left():
    if not _timers:
        return "You don't have any timers running."
    return " ".join(f"Your {n} timer has {_say_duration(int(end - time.time()))} left." for n, end, _ in _timers)


def cancel_timers():
    n = len(_timers)
    for _, _, th in _timers:
        th.cancel()
    _timers.clear()
    return "Timer cancelled." if n == 1 else f"Cancelled {n} timers." if n else "There's no timer running."


# ---------- reminders, calendar, notes (Apple apps) ----------

def _date_script(var, when):
    """AppleScript lines that build date `var` from a datetime, independent of the Mac's date format."""
    return (f"set {var} to current date\nset day of {var} to 1\nset year of {var} to {when.year}\n"
            f"set month of {var} to {when.month}\nset day of {var} to {when.day}\n"
            f"set time of {var} to {when.hour * 3600 + when.minute * 60}")


def _parse_when(when):
    if not when:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(when.strip(), fmt)
        except ValueError:
            pass
    return None


def _spoken_time(dt):
    today = datetime.date.today()
    day = "today" if dt.date() == today else "tomorrow" if dt.date() == today + datetime.timedelta(1) else dt.strftime("%A %B %-d")
    return f"{day} at {dt.strftime('%-I:%M %p')}"


def add_reminder(text, when=""):
    """Adds to Apple Reminders, which alerts on this Mac and your iPhone."""
    dt = _parse_when(when)
    props = f"name:{_q(text)}" + (", remind me date:d" if dt else "")
    _osa((_date_script("d", dt) + "\n" if dt else "") + f'tell application "Reminders" to make new reminder with properties {{{props}}}')
    return f"Okay! I'll remind you to {text} {_spoken_time(dt)}." if dt else f"Added {text} to your reminders."


def add_event(title, start, minutes=60):
    dt = _parse_when(start)
    if not dt:
        return "When should I put it on your calendar?"
    script = (_date_script("s", dt) + f"\nset e to s + {int(minutes)} * minutes\n"
              'tell application "Calendar"\n'
              '  set cal to first calendar whose writable is true\n'
              f"  make new event at end of events of cal with properties {{summary:{_q(title)}, start date:s, end date:e}}\n"
              "end tell")
    _osa(script)
    return f"Added {title} to your calendar, {_spoken_time(dt)}."


def calendar(day_offset=0):
    """Events for today (0), tomorrow (1)... read aloud."""
    script = f"""set s to (current date) + {int(day_offset)} * days
set time of s to 0
set e to s + 1 * days
set out to ""
tell application "Calendar"
  repeat with c in calendars
    repeat with ev in (every event of c whose start date >= s and start date < e)
      set d to start date of ev
      set out to out & (hours of d) & ":" & (minutes of d) & "|" & (allday event of ev) & "|" & (summary of ev) & linefeed
    end repeat
  end repeat
end tell
return out"""
    rows = []
    for line in _osa(script, timeout=40).splitlines():
        hm, allday, title = (line.split("|", 2) + ["", ""])[:3]
        h, m = (int(x) for x in hm.split(":"))
        rows.append((allday == "true", h, m, title.strip()))
    when = "today" if day_offset == 0 else "tomorrow" if day_offset == 1 else f"in {day_offset} days"
    if not rows:
        return f"Your calendar is free {when}!"
    rows.sort()
    said = [f"{t} all day" if a else f"{t} at {datetime.time(h, m).strftime('%-I:%M %p')}" for a, h, m, t in rows]
    return f"You have {len(rows)} thing{'s' * (len(rows) != 1)} {when}: " + ", ".join(said[:6]) + "."


def add_note(text, title=""):
    title = title or (text[:40] + ("…" if len(text) > 40 else ""))
    body = f"<h1>{title}</h1><p>{text}</p>".replace('"', "'")
    _osa(f'tell application "Notes" to make new note with properties {{name:{_q(title)}, body:{_q(body)}}}')
    return "Saved it in your Notes!"


# ---------- system ----------

def screenshot():
    path = config.HOME / "Desktop" / datetime.datetime.now().strftime("Screenshot %Y-%m-%d at %H.%M.%S.png")
    subprocess.run(["screencapture", "-x", str(path)])
    return "Screenshot saved to your Desktop!"


def lock():
    threading.Timer(1.2, lambda: subprocess.run(["pmset", "displaysleepnow"])).start()
    return "Locking up. See you soon!"
