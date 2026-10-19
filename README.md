# Monday

> Full documentation, design system and rules for AI coding agents: [AGENTS.md](AGENTS.md)

Voice-controlled computer agent for macOS, Windows and Linux. Hold a key, speak, and Monday looks at the screen and operates the computer. Whisper for speech, Gemini for vision and planning.

## Setup (10 minutes)
```
python3.11 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                       # add GEMINI_API_KEY
python selftest.py                                         # screenshot + Gemini + embeddings check
python main.py                                             # voice mode
python main.py --text                                      # typed mode, for debugging
```
Voice model (once):
```
mkdir -p ~/.monday/models && cd ~/.monday/models
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```
Linux also needs: `sudo apt install espeak portaudio19-dev python3-tk scrot`.

## macOS permissions (do this first)
System Settings, Privacy and Security: give your terminal app **Accessibility**, **Screen Recording**, **Microphone**, **Camera** and **Input Monitoring**, then restart the terminal. Trigger every prompt once before the demo.

## Use
- Say **"Hey Monday"** or **clap twice**. The screen edges flash, Monday answers, then say your command.
  One breath works too: "Hey Monday, play lofi on YouTube". Push-to-talk instead: `WAKE_MODE=ptt` (hold right Option).
- Interrupt any time: while Monday works or talks (and for 8 s after it answers) just speak, no wake word.
  A new command cancels the current one; "stop" or "never mind" just stops. Its own voice is filtered out.
- The HUD: a glass droplet falls into a Siri-style glass orb at the bottom centre, the screen edges light up and pulse with
  your voice and Monday's. Captions appear above the pool. While Monday operates, your cursor becomes Monday's
  gradient cursor with a name tag. The HUD is hidden from Monday's own screenshots. Preview it in a browser:
  `python -m http.server 8765`, then open http://localhost:8765/hud.html#demo
- Two looks: **full** (orb at the bottom, glowing screen edges) or **island** (Monday lives in the MacBook notch like
  a Dynamic Island: it grows out of the notch with a mini orb, voice bars and captions). Switch by saying
  "island mode" / "full screen mode" (or "minimise yourself" / "maximise yourself"), or press **Ctrl+Option+M**.
  The choice is remembered; `HUD_MODE` in `.env` sets the default. Macs without a notch get a floating pill.
- Siri things: "set a timer for 10 minutes", "how long is left", "remind me to call mom at 5" / "in 20 minutes"
  (Apple Reminders, so it pings your iPhone too), "add lunch with Ali tomorrow at 1 to my calendar", "what's on my
  calendar", "take a note that...", "what's the weather (in London)", "take a screenshot", "lock my Mac".
  The first time, macOS asks to let Monday control Reminders, Calendar and Notes: allow it.
- Web: live answers with sources ("latest news about SpaceX", "bitcoin price") from DuckDuckGo and Google News,
  and scraping: "scrape the prices from this page" (the tab you are on) or "scrape story titles from news.ycombinator.com"
  saves a CSV and a Markdown table to `~/Documents/Monday Notes/Scrapes/`. Pages that build themselves with
  JavaScript can't be read this way: ask "what's on my screen" instead.
- Start with your Mac like Siri: `./login.sh install` (and `./login.sh uninstall`). Logs: `~/.monday/monday.log`.
- Study notes: "make study notes from my geothermal PDF", "create questions from the hackathon report",
  "quiz me on module 3, focus on solar cells". Monday finds the PDF by name or topic (Spotlight), Gemini reads the
  whole thing (diagrams and scans too), and it writes a Markdown guide to `~/Documents/Monday Notes/`: summary, key
  concepts, facts table, MCQ, short and long answer questions, answer key and a revision checklist. Then it opens it.
- Speed: time, date, battery, volume and media keys answer instantly; questions take one fast Gemini call;
  only multi-step app work uses the screen agent.
- Speech: Whisper large-v3-turbo on the Apple GPU (first run downloads 1.6 GB). Voice: Kokoro, on device.
  Voice: a cute blend, `TTS_VOICE=af_bella*0.6+af_sky*0.4`. Listen to options in `voice_samples/` and set any
  name or blend (`af_heart`, `af_sky`, `bf_lily`, `bm_george`...). `TTS_SPEED` changes the pace.
- "What am I holding?" uses the webcam (give the terminal **Camera** permission).
- **Esc** stops the agent. Slamming the mouse into a screen corner also aborts.
- Risky requests (delete, send, pay, post...) ask for a spoken "yes" first. Actions are logged to `~/.monday/actions.log`.
- First run downloads the Whisper model, and the first background removal downloads its model (about 170 MB). Run both once on good wifi before the demo. Kokoro voice files live in `~/.monday/models` (download links in the setup notes below).

## Demo commands
1. "Open the browser, go to YouTube and search for lofi music" / "Play Believer on YouTube"
1. "Open Excalidraw and draw a cat"
1. "What am I holding?"
1. "Open the browser and search for Accelerator"
2. "Find the PDF about my project and summarize it"
3. "Remove the background from the image on my desktop"
4. "Open the drawing app and draw a rocket"
5. "Delete the file on my desktop" (shows the confirmation gate, say no)

## Files
`main.py` loop, `agent.py` observe-think-act, `llm.py` Gemini + tool schemas, `tools.py` screen and actions, `voice.py` Whisper and speech, `rag.py` file search, `router.py` instant commands, `safety.py` guardrails, `ui.py` overlay facade, `hud.py` macOS Jarvis HUD, `camera.py` webcam.

## Troubleshooting
- Clicks land in the wrong place: run `python selftest.py` and check the scale (2.0 is normal on Retina, 1.0 or 1.5 elsewhere).
- Nothing is heard: check Microphone permission, then try `WHISPER_MODEL=small`.
- Model not found error: set `GEMINI_MODEL` in `.env` to a current Gemini Flash model name.
- Overlay crashes on your Python: set `OVERLAY=0`.
