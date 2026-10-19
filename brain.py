"""Decides how to handle a command, fastest path first:
1. local answers (time, date, battery, volume, media keys), instant
2. router patterns (YouTube, drawing, camera, open app), no LLM
3. one quick Gemini call: answer directly, run a single tool, or hand off to the screen agent
"""
import datetime, re, subprocess, urllib.parse
import config, llm, router, tools, ui, voice


def _osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def volume(level=None, delta=None, mute=None):
    if config.OS != "Darwin":
        return "Volume control works on macOS only."
    if mute is not None:
        _osa(f"set volume output muted {'true' if mute else 'false'}")
        return "Muted." if mute else "Sound is back on."
    cur = int(_osa("output volume of (get volume settings)") or 50)
    new = max(0, min(100, int(level) if level is not None else cur + int(delta or 0)))
    _osa(f"set volume output volume {new} without output muted")
    return f"Volume {new} percent."


def media(action="playpause"):
    key = {"playpause": "playpause", "next": "nexttrack", "previous": "prevtrack"}.get(action, "playpause")
    tools.pg().press(key)
    return "Done."


def battery():
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)%;\s*([\w ]+)", out)
    if not m:
        return "I could not read the battery."
    pct, st = m.groups()
    return f"Battery is at {pct} percent" + (", charging." if "charg" in st and "dis" not in st else ".")


def _now():
    return datetime.datetime.now()


def study_notes(query, focus="", size="normal"):
    import study
    try:
        src = study.find_document(query)
    except FileNotFoundError as e:
        return f"Hmm, {e}. Can you tell me the file name?"
    voice.speak(f"Found {src.stem}! Reading it now, give me a few seconds.")
    ui.state("thinking")
    out, summary, _ = study.make_notes(str(src), focus, size)
    tools.open_file(str(out), wait=0)
    ui.log(f"study notes: {out}")
    return f"Your study notes are ready, with questions and answers! {summary}"


def portfolio():
    tools.open_url(config.PORTFOLIO_URL, wait=0)
    return "Opening your portfolio! Looking good."


def hud_mode(mode):
    if not ui.set_mode(mode):
        return "The HUD is turned off right now."
    return "Island mode! I'll live in the notch." if mode == "island" else "Full screen mode!"


def _weather(t):
    import web
    m = re.search(r"\b(?:in|at|for)\s+([a-z][a-z .'-]+?)(?:\s+(?:today|tonight|now|right now|this week|tomorrow))?$", t, re.I)
    place = m.group(1) if m and m.group(1).lower() not in ("today", "tonight", "now", "tomorrow") else ""
    return web.weather(place)


def _timer(t):
    import siri
    return siri.set_timer(siri.parse_duration(t))


def _calendar(t):
    import siri
    try:
        return siri.calendar(1 if re.search(r"\btomorrow\b", t, re.I) else 0)
    except Exception as e:
        return "I need permission to read your Calendar. Check System Settings, Privacy, Automation." if "1743" in str(e) else f"Hmm, the calendar didn't answer: {e}"


def _siri(fn):
    import siri
    return getattr(siri, fn)()


LOCAL = [
    (r"\b(?:cancel|stop|delete|clear|remove)\b.*\btimers?\b", lambda m: _siri("cancel_timers")),
    (r"\bhow (?:much|long)\b.*\btimer\b|\btimers?\b.*\bleft\b", lambda m: _siri("timers_left")),
    (r"\btimer\b.*\d|\b\d+\s*(?:second|sec|minute|min|hour|hr)s?\s+timer\b|\btimer for (?:a|an|half)\b",
     lambda m: _timer(m.string)),
    (r"\bweather\b|\btemperature (?:outside|today|in)\b|\b(?:will|is) it (?:going to )?(?:rain|snow)\b|\bforecast\b",
     lambda m: _weather(m.string)),
    (r"\b(?:take|grab|capture) (?:a )?screenshot\b|^screenshot$", lambda m: _siri("screenshot")),
    (r"\block (?:my |the )?(?:mac|screen|computer|laptop)\b", lambda m: _siri("lock")),
    (r"^(?!.*\b(?:add|create|schedule|put|book|set up|make|move|cancel)\b).*(?:\bon my calendar\b|\bmy (?:schedule|agenda|meetings?)\b)",
     lambda m: _calendar(m.string)),
    (r"\bportfolio\b", lambda m: portfolio()),
    (r"\bdynamic island\b|\b(?:island|notch|compact|small|mini) (?:mode|view)\b|\b(?:go|move|get) (?:to|in|into|inside) "
     r"(?:the |my )?(?:notch|island)\b|\bminimi[sz]e (?:yourself|monday|the hud)\b|^minimi[sz]e$", lambda m: hud_mode("island")),
    (r"\bfull[ -]?(?:screen|window)? (?:view|mode)\b|\b(?:big|normal) mode\b|\bmaximi[sz]e (?:yourself|monday|the hud)\b"
     r"|^maximi[sz]e$|\bcome out of the notch\b", lambda m: hud_mode("full")),
    (r"\bwhat(?:'s| is)?(?: the)? time\b|\btime is it\b|\bcurrent time\b|^time$",
     lambda m: _now().strftime("It's %-I:%M %p.")),
    (r"\bwhat(?:'s| is)?(?: the| today'?s)? date\b|\bwhat day is (?:it|today)\b|\btoday'?s date\b",
     lambda m: _now().strftime("It's %A, %B %-d.")),
    (r"\bbattery\b", lambda m: battery()),
    (r"\b(?:set )?(?:the )?volume (?:to )?(\d{1,3})\b", lambda m: volume(level=m.group(1))),
    (r"\b(?:volume|sound) up\b|\blouder\b|\bincrease (?:the )?volume\b", lambda m: volume(delta=15)),
    (r"\b(?:volume|sound) down\b|\bquieter\b|\b(?:decrease|lower) (?:the )?volume\b", lambda m: volume(delta=-15)),
    (r"^(?:please )?unmute\b", lambda m: volume(mute=False)),
    (r"^(?:please )?mute\b", lambda m: volume(mute=True)),
    (r"^(?:please )?(?:pause|resume|play)(?: the)?(?: music| video| song)?$|^stop the (?:music|video|song)$",
     lambda m: media("playpause")),
    (r"^(?:next|skip)(?: the)?(?: song| track| video)?$", lambda m: media("next")),
    (r"^previous(?: song| track| video)?$", lambda m: media("previous")),
]

DECIDE = """You are Monday, a cute, cheerful, bubbly voice assistant living on the user's {os} computer. Smart like JARVIS,
but sweet and playful: warm, a little giggly, encouraging, never sarcastic or rude. Keep it natural and short.
Now: {now}. Frontmost app: {app}.
The user said (speech to text, may contain recognition mistakes, infer what they meant): "{text}"

Reply with JSON only, exactly one of:
{{"kind": "answer", "say": "..."}}
  for timeless questions, math, advice, small talk (NOT news, prices, scores or anything current: use web_answer). 1 to 2 short spoken sentences, no markdown, no lists.
{{"kind": "tool", "tool": "<name>", "args": {{...}}, "say": "very short spoken acknowledgement, 2 to 5 words"}}
  only when that one tool completes the WHOLE request (opening an app is not enough if they want something done in it). Tools:
  youtube {{"query": str, "play": bool}}   play or search videos and music (play true unless they only want results)
  open_url {{"url": str}}   google {{"query": str}}   open_app {{"name": str}}
  look {{"question": str}}   webcam: what they hold or show, how they look
  sketch {{"subject": str}}   draw a picture (opens Excalidraw)
  open_file {{"name": str}}   open a file by name or path (opens in the editor in front)
  read_screen {{"question": str}}   look at the screen: "read this", "what's on my screen", "explain this code/error/page"
  explain_file {{"name": str, "question": str}}   read a named file and answer about it out loud (nothing is written)
  study_notes {{"query": str, "focus": str, "size": "normal" | "big"}}   find a PDF or document (query = its file name or
    topic words) and WRITE a Markdown study guide: summary, key concepts, questions, answer key. Use whenever they want
    notes, a document, an MD file, questions, a quiz or revision material made from a file. focus = topic to stress or "".
  search_files {{"query": str}}   remove_background {{"path": str}}
  web_answer {{"question": str}}   live or recent info from the internet: news, prices, scores, results, release dates,
    "who is the current...", anything that may have changed after your training. Use this instead of answering from memory.
  scrape {{"target": "url, site name or empty for the page they are looking at", "what": "data to extract"}}
    pull data off a web page into a spreadsheet (CSV + Markdown): "scrape the prices from this page"
  weather {{"place": str}}   empty place = where the user is
  timer {{"seconds": int, "label": str}}   only when they say "timer". "Remind me ..." is always reminder.
  reminder {{"text": str, "when": "YYYY-MM-DD HH:MM (24-hour) or empty", "in_minutes": int or 0}}   Apple Reminders,
    syncs to their iPhone. Relative times ("in 20 minutes", "in 2 hours") go in in_minutes; clock times ("tomorrow at 9",
    "at 5" = the next 5 PM) go in when.
  event {{"title": str, "start": "YYYY-MM-DD HH:MM", "minutes": int}}   add to Apple Calendar
  calendar {{"day_offset": 0 for today, 1 for tomorrow}}   read their schedule
  note {{"text": str, "title": str}}   save to Apple Notes
  screenshot {{}}   lock {{}}
  portfolio {{}}   the user's own portfolio website
  volume {{"level": 0-100}}   media {{"action": "playpause" | "next" | "previous"}}
{{"kind": "screen", "goal": "clear one-line task"}}
  when it needs looking at the screen and clicking or typing inside apps, e.g. sending a message, filling a form,
  changing a setting in an app, anything with several steps."""


def _front_app():
    if config.OS != "Darwin":
        return "unknown"
    return _osa('tell application "System Events" to get name of first application process whose frontmost is true') or "unknown"


def _run_tool(name, args):
    if name == "youtube":
        tools.youtube(args.get("query", ""), bool(args.get("play", True)))
        return None
    if name == "google":
        tools.open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(args.get("query", "")), wait=0)
        return None
    if name == "open_url":
        tools.open_url(args.get("url", ""), wait=0)
        return None
    if name == "open_app":
        r = tools.open_app(args.get("name", ""))
        return r.replace("error: ", "") if r.startswith("error") else None
    if name == "look":
        return tools.look(args.get("question", "What do you see?"))
    if name == "sketch":
        return router.draw(args.get("subject", "a cat"))
    if name == "search_files":
        return tools.search_files(args.get("query", ""))
    if name == "open_file":
        try:
            tools.open_file(args.get("name") or args.get("path", ""), wait=0)
        except FileNotFoundError as e:
            return f"Hmm, {e}."
        return None
    if name == "read_screen":
        return tools.read_screen(args.get("question") or "What's on my screen?")
    if name in ("explain_file", "summarize_file"):
        import study
        target, q = args.get("name") or args.get("path", ""), args.get("question") or "Summarize it."
        try:
            return tools.summarize_file(target, q)
        except FileNotFoundError:
            try:
                return tools.summarize_file(str(study.find_document(target)), q)  # by topic, not just file name
            except FileNotFoundError as e:
                return f"Hmm, {e}."
    if name == "remove_background":
        r = tools.remove_background(args.get("path", ""))
        return r.replace("error: ", "") if r.startswith("error") else "Done, the background is gone."
    if name == "study_notes":
        return study_notes(args.get("query", ""), args.get("focus", ""), args.get("size", "normal"))
    if name in ("web_answer", "scrape", "weather"):
        import web
        if name == "weather":
            return web.weather(args.get("place", ""))
        if name == "web_answer":
            return web.answer(args.get("question", ""))
        msg, path = web.scrape(args.get("target", ""), args.get("what") or "the main data, as a table")
        if path:
            tools.open_file(str(path.with_suffix(".md")), wait=0)
        return msg
    if name in ("timer", "reminder", "event", "calendar", "note", "screenshot", "lock"):
        import siri
        try:
            if name == "timer":
                return siri.set_timer(int(args.get("seconds") or 0), args.get("label", ""))
            if name == "reminder":
                mins = int(args.get("in_minutes") or 0)
                when = (_now() + datetime.timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M") if mins else args.get("when", "")
                return siri.add_reminder(args.get("text", ""), when)
            if name == "event":
                return siri.add_event(args.get("title", ""), args.get("start", ""), args.get("minutes", 60))
            if name == "calendar":
                return siri.calendar(int(args.get("day_offset") or 0))
            if name == "note":
                return siri.add_note(args.get("text", ""), args.get("title", ""))
            return getattr(siri, name)()
        except Exception as e:
            if "1743" in str(e) or "not allowed" in str(e).lower():
                return "I need permission for that app. Allow it in System Settings, Privacy and Security, Automation."
            return f"Hmm, that didn't work: {e}"
    if name == "portfolio":
        return portfolio()
    if name == "volume":
        return volume(level=args.get("level", 50))
    if name == "media":
        return media(args.get("action", "playpause"))
    
    return f"I don't know how to {name} yet."


def handle(text):
    """Returns (reply, None) when handled, or (None, goal) when the screen agent should take over."""
    text = re.sub(r"(?i)\s+dot\s+(py|js|ts|tsx|jsx|md|txt|pdf|json|html|css|swift|java|cpp|go|rs|csv|png|jpg)\b", r".\1", text)
    t = text.strip().rstrip(".!?")
    for rx, fn in LOCAL:
        m = re.search(rx, t, re.I)
        if m:
            return fn(m), None
    reply = router.fast(text)
    if reply is not None:
        return reply, None
    try:
        d = llm.json_out(DECIDE.format(os={"Darwin": "Mac"}.get(config.OS, config.OS), now=_now().strftime("%A %Y-%m-%d %H:%M (24-hour clock)"),
                                       app=_front_app(), text=text), model=config.FAST_MODEL, temperature=0.3)
    except Exception as e:
        print("decide failed:", e)
        return None, text
    kind = d.get("kind")
    if kind == "answer":
        return d.get("say") or "Hmm, I'm not sure.", None
    if kind == "tool":
        if d.get("say") and d.get("tool") != "study_notes":
            voice.speak(d["say"])
        r = _run_tool(d.get("tool", ""), d.get("args") or {})
        return (r or ""), None
    return None, d.get("goal") or text
