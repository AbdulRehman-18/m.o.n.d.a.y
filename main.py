import argparse, os, re, signal, sys, threading
import config, safety, voice, rag, brain, agent, ui


STOP_WORDS = re.compile(r"^\W*(?:monday\W+)?(?:stop|cancel|never ?mind|shut up|be quiet|quiet|enough|forget it)\W*$", re.I)
_task = None


def handle(text):
    voice.busy(True)
    try:
        if safety.goal_is_risky(text) and not voice.confirm("That could change or remove things."):
            return voice.speak("Okay, cancelled.")
        ui.state("thinking")
        reply, goal = brain.handle(text)
        if safety.cancelled():
            return
        if reply:
            voice.speak(reply)
        if goal:
            ui.state("acting")
            agent.run(goal)
    except Exception as e:
        ui.log(f"error: {e}")
        voice.speak("Oops, something went wrong.")
    finally:
        voice.wait_spoken()
        if not safety.cancelled():
            ui.state("idle")
            voice.busy(False)


def dispatch(text):
    """Run a command on its own thread. A new command interrupts whatever Monday is doing or saying."""
    global _task
    ui.say("you", text)
    if _task and _task.is_alive():
        ui.log("interrupted")
        safety.GEN[0] += 1
        safety.STOP.set()
        voice.interrupt()
        _task.join(timeout=3)
    else:
        safety.GEN[0] += 1
    safety.STOP.clear()
    if STOP_WORDS.match(text):
        voice.busy(False)
        ui.state("idle")
        return voice.speak("Okay!")
    _task = threading.Thread(target=handle, args=(text,), daemon=True)
    _task.gen = safety.GEN[0]
    _task.start()


def loop():
    if not voice.TEXT:
        voice.start()
    threading.Thread(target=rag.build, daemon=True).start()
    if voice.TEXT:
        voice.speak("Monday online. Type a command.")
    elif config.WAKE_MODE == "ptt":
        voice.speak("Monday online. Hold the talk key to speak.")
    else:
        ui.wake()
        voice.speak("Monday online. Say hey Monday, or clap twice.")
    voice._q.join()
    ui.state("idle")
    while True:
        text = voice.listen()
        if not text:
            continue
        if re.fullmatch(r"(quit|exit|goodbye)\W*", text, re.I):
            break
        dispatch(text)
    if _task:
        _task.join(30)
    os._exit(0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="type commands instead of speaking")
    voice.TEXT = ap.parse_args().text
    if not config.GEMINI_KEY:
        sys.exit("Set GEMINI_API_KEY in .env")
    signal.signal(signal.SIGINT, lambda *a: os._exit(0))
    ov = ui.start()
    if ov:
        threading.Thread(target=loop, daemon=True).start()
        ov.run()
    else:
        loop()
