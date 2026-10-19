import time
import config, llm, safety, tools, ui, voice

SAY = {"open_app": "Opening {name}.", "open_url": "Opening the page.", "search_files": "Searching your files.",
       "summarize_file": "Reading the file.", "remove_background": "Removing the background.", "draw": "Drawing now.",
       "sketch": "Drawing {subject}.", "youtube": "Opening YouTube.", "look": "Let me look."}


def run(goal):
    ui.agent(True)
    try:
        _run(goal)
    finally:
        ui.agent(False)


def _run(goal):
    history, recent = [], []
    app = tools.front_bundle() or "unknown"
    for step in range(config.MAX_STEPS):
        if safety.cancelled():
            return voice.speak("Stopped.")
        ui.state("thinking")
        jpeg, size = tools.capture()
        name, args = llm.next_action(goal, jpeg, size, history, app)
        ui.log(f"{step + 1}. {name} {args}")
        if name == "done":
            return voice.speak(args.get("summary", "Done."))
        sig = (name, str(sorted((k, str(v)) for k, v in args.items() if k != "double")))
        seen = recent[-10:].count(sig)  # catches loops like cmd+p, type, enter, cmd+p, type, enter...
        recent.append(sig)
        if seen >= 2:
            return voice.speak("Hmm, I'm going in circles, so I stopped. Can you tell me another way?")
        verdict = safety.check(name, args)
        if verdict == "block":
            return voice.speak("I will not do that.")
        if verdict == "confirm" and not voice.confirm(f"About to press {args.get('combo')}."):
            return voice.speak("Cancelled.")
        if name in SAY:
            voice.speak(SAY[name].format(name=args.get("name", ""), subject=args.get("subject", "it")))
        ui.state("acting")
        try:
            fn = tools.TOOLS.get(name)
            result = fn(**args) if fn else f"error: unknown tool {name}"
        except Exception as e:
            if type(e).__name__ == "FailSafeException":
                return voice.speak("Stopped by the corner failsafe.")
            result = f"error: {e}"
        safety.log(step, name, args, result)
        history.append(f"{step + 1}. {name}({args}) -> {str(result)[:200]}"
                       + (" NOTE: you already tried this and it did not work. Do something different or call done." if seen else ""))
        time.sleep(0.35)
    voice.speak("That took too many steps, so I stopped. Want me to try differently?")
