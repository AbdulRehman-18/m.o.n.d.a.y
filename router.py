import re, time, urllib.parse
import tools, voice

_NOT_APP = re.compile(r"\b(file|pdf|image|photo|document|folder|my|about)\b", re.I)
_LOOK = re.compile(r"\b(what am i holding|what(?:'s| is) (?:this|that|in my hand)|what do you see|look at (?:me|this)|"
                   r"use (?:the |my )?camera|can you see (?:me|this)|how do i look|identify this)\b", re.I)
_YT = [re.compile(r"(?i)\byoutube\b.*?\b(play|search|find|look up|put on)\b(?:\s+for)?\s+(.+)$"),
       re.compile(r"(?i)\b(play|search|find|put on)\b(?:\s+for)?\s+(.+?)\s+(?:on|in)\s+youtube\b"),
       re.compile(r"(?i)^(?:please\s+)?(play|put on)\s+(.+)$")]
_DRAW = re.compile(r"(?i)\bdraw(?:\s+me)?\s+(?:a|an|the|some)?\s*(.+)$")


def _clean(q):
    return re.sub(r"(?i)^(?:any|some|a|an|the)\s+|\s+(?:on|in)\s+youtube$", "", q.strip()).strip() or q


def draw(subject):
    """Open Excalidraw and sketch the subject. The drawing plan is generated while the page loads."""
    import threading
    voice.speak(f"Drawing {subject}.")
    plan = {}
    th = threading.Thread(target=lambda: plan.update(s=tools.plan_sketch(subject)))
    th.start()
    tools.open_url("https://excalidraw.com")
    time.sleep(2.5)
    th.join()
    r = tools.sketch(subject, app="excalidraw", strokes=plan.get("s"))
    return r.replace("error: ", "") if r.startswith("error") else f"Here's your {subject}."


def fast(text):
    """Handle known commands without the vision loop, even multi-step ones.
    Returns a reply to speak ("" when already spoken), or None when it is not a known command."""
    t = text.strip().rstrip(".!?")
    if _LOOK.search(t):
        voice.speak("Let me look.")
        return tools.look(t)
    for rx in _YT:
        m = rx.search(t)
        if m:
            q, play = _clean(m.group(2)), m.group(1).lower() in ("play", "put on")
            voice.speak(f"Playing {q}." if play else f"Searching YouTube for {q}.")
            tools.youtube(q, play)
            return ""
    m = _DRAW.search(t)
    if m and not re.search(r"\b(j?s?paint)\b", t, re.I):
        return draw(_clean(m.group(1)))
    m = re.search(r"(?i)\bopen (?:up )?(?:the |my |a )?([\w\-./~]+\.[a-z0-9]{1,6})\b(?: file)?", t)
    if m:
        try:
            p = tools.open_file(m.group(1), wait=0)
            return f"Opened {m.group(1)}!"
        except FileNotFoundError as e:
            return f"Hmm, {e}."
    if re.search(r"(?i)\b(read|explain) (?:this|that|the) (?:code|page|error|screen|text)\b|\bwhat(?:'s| is) on (?:my|the) screen\b", t):
        voice.speak("Let me see.")
        return tools.read_screen(t)
    if re.search(r"\b(and|then)\b", t, re.I):
        return None
    m = re.match(r"(?i)^(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?(.+)$", t)
    if m and len(m.group(1).split()) <= 3 and not _NOT_APP.search(m.group(1)):
        r = tools.open_app(m.group(1))
        return r.replace("error: ", "") if r.startswith("error") else f"Opened {m.group(1)}."
    m = re.match(r"(?i)^(?:please\s+)?(?:search|google)(?:\s+for)?\s+(.+)$", t)
    if m:
        voice.speak(f"Searching for {m.group(1)}.")
        tools.open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(m.group(1)), wait=0)
        return ""
    return None
