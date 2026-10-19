# Monday — Project Guide and Rules for AI Agents

Monday is a voice-controlled AI assistant for macOS that can see the screen and operate the computer: a personal
JARVIS / Siri replacement. You wake it with "Hey Monday" or a double clap, speak, and it answers, opens things,
plays music, draws, reads your screen, scrapes the web, writes study notes, sets timers and reminders, and can take
over the mouse and keyboard for multi-step tasks.

This file is the single source of truth. **Any AI coding agent (Claude Code, Cursor, Codex, OpenCode, Copilot, ...)
must read it fully before changing code, and must follow section 12 ("Rules for AI agents").** The owner switches
between agents; Monday must look, sound and behave the same no matter which one edits it.

---

## 1. Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # set GEMINI_API_KEY
mkdir -p ~/.monday/models && cd ~/.monday/models
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
cd - && python selftest.py           # screenshot, Gemini, embeddings, camera
python main.py                       # voice mode
python main.py --text                # typed mode, for debugging
./login.sh install                   # start with the Mac (uninstall | status)
```

macOS permissions for the terminal (or "Python" when started by `login.sh`): Accessibility, Screen Recording,
Microphone, Camera, Input Monitoring, and Automation for Reminders, Calendar, Notes and the browser.

Hardware the defaults assume: Apple Silicon (speech runs on the GPU through MLX). Other machines fall back to
faster-whisper on the CPU automatically.

---

## 2. How it works

```
 mic (always on, 16 kHz, 30 ms frames)
   │  voice._engine: noise floor, speech segments, double-clap detector
   ▼
 Whisper large-v3-turbo (MLX, ~0.9 s)  ──►  echo filter (drops Monday's own voice)
   │                                         unfinished-sentence wait ("I want you to...")
   ▼
 wake word? "Hey Monday" / double clap / conversation window (8 s after a reply, or while busy)
   │
   ▼
 main.dispatch  ── a new command interrupts the running one (task generations, safety.cancelled())
   │
   ▼
 brain.handle (fastest path first)
   1. LOCAL regex intents      instant: time, date, battery, volume, media, timers, weather, calendar,
                               screenshot, lock, HUD mode, portfolio
   2. router.fast patterns     no LLM: YouTube, draw, camera, open <file.ext>, read screen, open app, google
   3. Gemini "decide" (~1 s)   JSON: answer | one tool | screen
   4. agent.run                screen agent: screenshot → Gemini picks one action → act → repeat (max 12 steps)
   ▼
 voice.speak  ──►  Kokoro neural TTS (on device, ~0.4 s) with live level → HUD
 ui.*         ──►  hud.py (native window) ──► hud.html (orb, glow, captions, island, AI cursor)
```

---

## 3. File map

| File | What it does |
|---|---|
| `main.py` | Entry point. Starts the HUD on the main thread, runs the listen loop, `dispatch()` runs each command on its own thread and interrupts the previous one. Stop words ("stop", "never mind"). |
| `config.py` | Every setting, read from `.env` (see section 9). |
| `voice.py` | Microphone engine, wake word, double clap, echo filter, unfinished-sentence wait, conversation window, Whisper (MLX or faster-whisper), Kokoro TTS with voice blends, speech queue, interrupt/hush, wake chime, confirm(). |
| `brain.py` | Routing: `LOCAL` instant intents, `router.fast`, Gemini `DECIDE` prompt (Monday's personality lives here), `_run_tool` for every tool. |
| `router.py` | Deterministic patterns: YouTube, draw (Excalidraw), webcam questions, open a file by name, read the screen, open apps, Google search. |
| `agent.py` | Screen agent loop: screenshot → `llm.next_action` → safety check → tool. Cycle detection, 12 step cap, cancellable. |
| `llm.py` | Gemini client. `SYSTEM` prompt and tool schema for the screen agent, `_gen` (thinking level with fallback), `text`, `vision`, `json_out`, `embed`, retries. |
| `tools.py` | Real actions: capture screen, human-like cursor glide, click, type, keys, scroll, open app/url/file, Spotlight file lookup, read screen, summarize file, sketch (Excalidraw), YouTube top result, webcam look, background removal. |
| `web.py` | Web without API keys: DuckDuckGo search, page reader, live answers, Google News RSS, weather (wttr.in, Open-Meteo fallback), scraper to CSV + Markdown, current browser tab URL. |
| `siri.py` | Timers (inside Monday), Apple Reminders, Calendar (read + add), Notes, screenshot, lock screen, notifications. |
| `study.py` | Find a PDF by name or topic (Spotlight), Gemini reads it, writes a Markdown study guide with questions and answer key. |
| `rag.py` | Embedding index of Desktop, Documents, Downloads (refreshed at most every 6 h), file text reader. |
| `safety.py` | Kill switch (`STOP`), task generations (`GEN`, `cancelled()`), risky goal words, blocked text, risky key combos, action log. |
| `ui.py` | UI facade used by everything else: `log, say, state, level, click, wake, agent, speaking, show_image, set_mode, toggle_mode`. Esc handling. Saves HUD mode to `~/.monday/settings.json`. Tk fallback for non-Mac. |
| `hud.py` | Native macOS window: transparent, click-through, above everything, hidden from screenshots. Hosts `hud.html` in WKWebView, 60 fps tick, notch detection, hides the real cursor while the agent works, Ctrl+Option+M. |
| `hud.html` | The entire look: glass orb, light from the orb, captions, Dynamic Island, AI cursor, click ripples. Open `hud.html#demo` in a browser to preview. |
| `camera.py` | One webcam frame as JPEG (OpenCV). |
| `selftest.py` | Checks screenshot scale, Gemini, embeddings, camera. |
| `login.sh` | LaunchAgent: start Monday at login. |
| `voice_samples/` | Sample WAVs of voice options. |
| `.claude/launch.json` | Local preview server for `hud.html#demo` (port 8765). |

---

## 4. Features and example phrases

| Area | Say | Path |
|---|---|---|
| Wake | "Hey Monday", "Monday, ...", "Wake up, daddy's home", double clap | voice |
| Time and system | "what's the time", "battery", "volume 40", "louder", "mute", "pause", "next song", "take a screenshot", "lock my Mac" | LOCAL |
| Timers | "set a timer for 10 minutes", "how long is left", "cancel the timer" | LOCAL → siri |
| Reminders | "remind me to call mom at 5", "... in 20 minutes", "... tomorrow at 9" | decide → Apple Reminders |
| Calendar | "what's on my calendar tomorrow", "add a meeting with Ali tomorrow at 3pm" | LOCAL / decide |
| Notes | "take a note that ..." | decide → Apple Notes |
| Weather | "what's the weather", "will it rain in London today" | LOCAL → web |
| Live web | "latest news about SpaceX", "bitcoin price right now" | decide → web.answer |
| Scraping | "scrape the prices from this page", "scrape story titles from news.ycombinator.com" | decide → web.scrape |
| Media | "play Believer on YouTube", "search YouTube for lofi", "put on some music" | router |
| Drawing | "open Excalidraw and draw a cat", "draw me a rocket" | router → tools.sketch |
| Files | "open agent.py", "explain what voice.py does", "find the PDF about my project" | router / decide |
| Screen | "read this code and tell me", "what's on my screen" | router → tools.read_screen |
| Study | "make study notes from my geothermal PDF", "quiz me on module 3, focus on solar cells" | decide → study |
| Camera | "what am I holding?", "how do I look?" | router → tools.look |
| Apps | "open Safari", "open WhatsApp and send hi to Ali" (screen agent, asks to confirm "send") | router / agent |
| Portfolio | "open my portfolio" | LOCAL |
| HUD | "island mode", "full screen mode", "minimise yourself", Ctrl+Option+M | LOCAL / hotkey |
| Control | "stop", "never mind", Esc key, slam the mouse into a screen corner | main / ui / pyautogui |

Outputs: study notes in `~/Documents/Monday Notes/`, scrapes in `~/Documents/Monday Notes/Scrapes/` (CSV + MD),
screenshots on the Desktop, background removal saves `<name>_nobg.png` next to the image.

---

## 5. Listening rules (why it behaves the way it does)

- **Always listening**, but a command needs the wake word, a double clap, or the **conversation window**: while
  Monday is busy or speaking, and for `CONVERSE_S` (8 s) after it answers, you can talk without the wake word.
- **Wake acknowledgement is a soft bubble-pop chime** (`ACK=chime`), not speech, so nothing echoes into your command.
- **Echo protection** (`voice._is_echo`, `voice._strip_echo`): the mic stays open while Monday talks, so its own
  voice is removed. Words are normalised: "five" = "5", plurals ignored. Short transcripts made mostly of words Monday
  just said are dropped; a different number counts as the user.
- **Loop guard**: the same command repeated within 20 s without the wake word is ignored.
- **Unfinished sentences** ("Like I want you to...") wait up to `FINISH_S` (1.8 s) for the rest.
- **Barge-in**: a new command cancels the running task (`safety.GEN`, `safety.cancelled()`) and cuts speech.
  Esc cancels everything and ends the conversation window.
- **Double clap**: two sharp hits 0.1–0.8 s apart, each at most 90 ms.

---

## 6. Personality and voice (do not drift)

- Monday is **cute, cheerful, bubbly and warm**, a little playful, smart like JARVIS, never sarcastic or rude.
- Replies are **short and spoken**: 1–2 sentences for answers, 2–5 words for acknowledgements, no markdown, no lists,
  no emojis (emojis and symbols are stripped before speaking anyway).
- Voice: **Kokoro on device**, default blend `af_bella*0.6+af_sky*0.4` at speed `1.12`. Never switch to a cloud TTS
  or macOS `say` as the default (they were rejected as slow or robotic). `say` exists only as a fallback.
- The personality text lives in `brain.DECIDE` (first lines) and `voice.ACKS`. Keep the tone if you edit them.

---

## 7. Visual design system (the look must not change)

All visuals are in `hud.html`; `hud.py` only hosts and feeds it. Preview: `python -m http.server 8765`, open
`http://localhost:8765/hud.html#demo` (buttons simulate states).

### States
`idle`, `listening`, `thinking`, `acting`, `speaking`. Each maps to orb size `FORM`, light strength `EDGE` and wisp
speed `SPEED`:

| state | FORM | EDGE | SPEED |
|---|---|---|---|
| idle | 0 (hidden) | 0 | .4 |
| listening | 1 | 1 | 1 |
| thinking | .9 | .75 | 3.2 |
| acting | .78 | .55 | 1.5 |
| speaking | 1 | 1 | 1.4 |

### Full mode (default)
- **Glass orb** at the bottom centre: SVG sphere, radius 62, centre (160, 476) in a 320×560 viewBox anchored to the
  screen bottom. Dark glass body (radial `#06070b` → `#0b0d14` → `#2a2f3c` → rim `#cfd8ea`), white rim gradient,
  bottom inner reflection, top-left specular highlight.
- **Wisps** inside the orb (Siri style), thin tapered ribbons, `mix-blend-mode: screen`, horizontal at rest, swirling
  when thinking, swelling slightly with voice level:
  blue `#0a6cff`, red `#ff2d2d`, orange `#ff8a00`, cyan `#5ad8ff`, green `#2fe07a` (faint), white `#ffffff`.
- **Entrance is a pop**: spring overshoot (`formV += 9`, stiffness 110, damping 12). **No drop animation, no splash
  rings.**
- **Light from the orb** (replaces any border): a soft radial glow rising from the bottom
  (`rgba(150,205,255,.42)` → `rgba(50,120,255,.26)` → faint warm `rgba(255,140,70,.10)`, blur 28px) plus a 1.25px
  hairline rim `rgba(185,222,255,.8)` that fades out towards the top of the screen. Both swell with voice level.
  **No rainbow or conic border, no rotating gradient frame.**
- **Captions**: dark rounded pill above the orb (`bottom: 176px`), user line 14px at 62% white, Monday's line 21px
  semibold white, type-on reveal at 48 characters per second, fades 3.5–5 s after idle.
- **Camera snapshot** card above the captions for 7 s.

### Island mode (Dynamic Island in the notch)
- Notch measured from macOS (`safeAreaInsets`, auxiliary top areas); this MacBook: x 663, width 185, height 32.
- Idle: exactly the notch size (invisible). Active: notch + 140 wide (min 300), mini orb on the left wing, five voice
  bars on the right wing (`#0a6cff #5ad8ff #ffffff #ff8a00 #ff2d2d`). With a caption: at least 500 wide, grows down to
  fit the text, radius 26. Concave top "ears" so it blends with the notch. Spring timing
  `cubic-bezier(.34, 1.4, .5, 1)` .55s. The orb flies between bottom and notch when switching.
- No edge light in island mode; a soft blue shadow under the island instead.

### AI cursor
- While the agent works, the real cursor is hidden and Monday draws its own: arrow with gradient
  `#3de0ff → #2f7bff → #ff7a45`, white 1.7px outline, blue glow, and a tag pill "Monday · working" with gradient
  `#2f7bff → #2bb8ff → #ff7a45`. Click ripple: pale blue ring, .55s. Real mouse moves follow a curved, eased
  "human" path (`tools.glide`).

### Palette rules
- Blue, cyan, white, orange, red, a touch of green. **No purple or violet anywhere.**
- Font: system (`-apple-system`, SF Pro). Dark glass surfaces, never flat grey boxes.

---

## 8. Speed budget (keep it fast)

| Path | Target |
|---|---|
| LOCAL intents (time, timers, volume...) | instant |
| Router patterns (YouTube, open file...) | < 0.3 s + action |
| Gemini decide / answers | ~1–1.5 s (`FAST_MODEL`, thinking `minimal`) |
| Weather | < 1 s |
| Web answer / news | 3–5 s |
| Study notes | 15–30 s |
| Speech recognition | ~0.9 s |
| Voice starts | ~0.4 s (common phrases cached) |

Do not add sleeps before speaking, do not put an LLM call in front of LOCAL or router paths, and keep `open_url`
`wait=0` for anything that is not followed by screen work.

---

## 9. Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | | required |
| `GEMINI_MODEL` | `gemini-3.5-flash` | screen agent, study notes, scraping |
| `FAST_MODEL` | `gemini-3.5-flash-lite` | decisions, answers, vision questions |
| `THINKING` | `minimal` | Gemini thinking level (dropped automatically for models that reject it) |
| `EMBED_MODEL` | `gemini-embedding-001` | file index |
| `STT` | `mlx` on Apple Silicon, else `faster` | speech engine |
| `STT_MODEL` | `mlx-community/whisper-large-v3-turbo` | MLX Whisper model |
| `WHISPER_MODEL` | `base` | faster-whisper model (non-MLX) |
| `WHISPER_LANG` | `en` | empty = auto-detect |
| `WAKE_MODE` | `wake` | `wake` (Hey Monday / clap) or `ptt` (hold `PTT_KEY`) |
| `CLAP` | `1` | double-clap wake |
| `ACK` | `chime` | `chime` or `speak` on wake |
| `CONVERSE_S` | `8` | seconds after a reply with no wake word needed (0 = always need it) |
| `END_MS` | `550` | silence that ends a phrase |
| `FINISH_S` | `1.8` | extra wait for unfinished sentences |
| `TTS` | `kokoro` | `kokoro` or `say` |
| `TTS_VOICE` | `af_bella*0.6+af_sky*0.4` | Kokoro voice or blend |
| `TTS_SPEED` | `1.12` | speaking rate |
| `HUD_MODE` | `full` | `full` or `island` (the last choice is saved in `~/.monday/settings.json`) |
| `OVERLAY` | `1` | `0` disables the HUD |
| `MAX_STEPS` | `12` | screen agent step cap |
| `PTT_KEY`, `KILL_KEY` | `alt_r`, `esc` | keys |
| `CAMERA_INDEX` | `0` | webcam |
| `PORTFOLIO_URL` | `https://abdulrehman-18.vercel.app` | "open my portfolio" |

Never commit `.env`. Never print or log the API key.

---

## 10. Files Monday writes

| Path | Contents |
|---|---|
| `~/.monday/actions.log` | every screen-agent action (JSON lines) |
| `~/.monday/index.json` | file embeddings |
| `~/.monday/settings.json` | saved HUD mode |
| `~/.monday/models/` | Kokoro model files |
| `~/.monday/monday.log` | output when started by `login.sh` |
| `~/Documents/Monday Notes/` | study guides; `Scrapes/` for scraped CSV + MD |

---

## 11. Troubleshooting

- **It talks to itself / loops**: echo. Use headphones, or set `CONVERSE_S=0`. Check the log for
  `(ignored my own voice: ...)` lines.
- **Cuts you off**: raise `END_MS` (e.g. 700). **Waits too long**: lower `FINISH_S`.
- **Gemini 429 / quota**: free-tier limit. Google Search grounding is blocked on the free key, which is why `web.py`
  scrapes DuckDuckGo and Google News instead.
- **Model not found (404)**: Google retires models; pick a current one from `client.models.list()` and set
  `GEMINI_MODEL` / `FAST_MODEL`.
- **Clicks land wrong**: run `selftest.py`, scale should be 2.0 on Retina.
- **Reminders / Calendar / Notes fail**: allow Automation in System Settings → Privacy & Security.
- **Scrape says the page uses JavaScript**: ask "what's on my screen" instead.
- **Audio crackles**: system memory pressure, not Monday; restart `coreaudiod` or the Mac.

---

## 12. Rules for AI agents (mandatory)

### 12.1 Never change without the owner asking explicitly
1. **The look**: everything in section 7. Do not restyle, recolour, resize or re-animate the orb, wisps, light,
   captions, island or cursor. No purple. No rainbow/conic border. No drop animation. No new panels or widgets.
2. **The voice and personality**: section 6. Do not change `TTS_VOICE`, `TTS_SPEED`, the TTS engine, `ACKS`, or the
   tone of `brain.DECIDE`.
3. **Wake and listening behaviour**: section 5 (wake phrases, clap, chime, conversation window, echo filter, loop
   guard, barge-in, Esc).
4. **The model choice**: Gemini through `google-genai`. Swapping providers (OpenCode, OpenAI, local LLMs...) was
   evaluated and rejected by the owner for now.
5. **Timers stay inside Monday** (not the Clock app) — owner's decision.
6. **Defaults in `config.py` and `.env.example`.**

If a request seems to need any of these, ask the owner first and describe the visible change.

### 12.2 Architecture rules
- Keep the routing order: `LOCAL` → `router.fast` → Gemini `DECIDE` → `agent`. Put new instant phrases in `LOCAL`
  (regex, no LLM), deterministic multi-step ones in `router.py`, everything else as a `DECIDE` tool.
- Everything visual goes through `ui.py` (`ui.say`, `ui.state`, ...). Never import `hud` from other modules and never
  draw UI from Python; visuals belong in `hud.html`.
- All speech goes through `voice.speak()` (it handles interruption, captions and echo tracking). Never call `say`,
  `afplay` for speech, or a TTS library directly elsewhere.
- Long work must check `safety.cancelled()` so a new command or Esc can stop it.
- macOS automation uses AppleScript via `osascript` (see `siri.py` `_osa`, `_q` for quoting, `_date_script` for dates,
  never locale-dependent date strings).
- No new heavy dependencies or cloud services without asking. Keep everything that works offline offline
  (speech, voice, timers).
- Match the existing code style: plain functions, short docstrings, comments only for the non-obvious, no classes
  unless needed, f-strings, no type-annotation sprawl.
- Never put secrets, personal data or API keys in code, logs or URLs.

### 12.3 Adding a feature (checklist)
1. Decide the path: instant phrase → `brain.LOCAL`; fixed pattern → `router.fast`; flexible → a tool in
   `brain.DECIDE` (document args in the prompt, 2–3 lines max) plus a branch in `brain._run_tool`.
2. Return a short, cheerful spoken sentence (section 6). Return `""` when you already spoke, `None` from a tool means
   nothing to say.
3. Files you create go under `~/Documents/Monday Notes/` (or a subfolder) and are opened afterwards.
4. Risky actions (send, delete, pay, post) must go through `voice.confirm()` or the existing risky-goal gate.
5. Update this file: features table (section 4), config table (section 9) and anything else that changed.
6. Update `README.md` if users need to know.

### 12.4 Testing protocol (do this before saying "done")
- `.venv/bin/python -m py_compile *.py`
- Routing: call `brain.handle("<phrase>")` with side-effect tools mocked (patch `tools.open_url`, `siri.add_reminder`,
  `voice.speak`, ...) and check the chosen path and the reply.
- Speech: `voice._is_echo`, `voice._strip_echo`, `voice.DANGLING` for listening changes.
- HUD: start the `hud-preview` server and check `hud.html#demo` in a browser in every state and in island mode
  (`H.setup({mode:'island', nx:(innerWidth-185)/2, nw:185, nh:32})`). Visual changes need a screenshot check.
- Typed end-to-end: `printf "what's the time\nquit\n" | .venv/bin/python main.py --text`.
- Do not create real reminders, events, notes, messages or purchases while testing; mock them or syntax-check
  AppleScript with `osacompile`.
- Report honestly what was tested and what was not (for example live microphone behaviour).

### 12.5 Never
- Never remove the kill switches (Esc, corner fail-safe, "stop").
- Never let the screen agent run without the step cap and cycle detection.
- Never make the HUD capturable in screenshots (`setSharingType_(0)` must stay) or clickable (`setIgnoresMouseEvents_`).
- Never send screenshots, files or audio anywhere except the configured Gemini API.
- Never commit or overwrite `.env`, `~/.monday/settings.json` or the user's documents.

---

## 13. Design decisions log (why things are the way they are)

| Decision | Reason |
|---|---|
| Whisper large-v3-turbo on MLX | base model misheard commands; turbo on the M4 GPU is accurate and ~0.9 s |
| Kokoro voice, cute blend | `say` sounded robotic, cloud TTS took 1.4–2 s to start |
| Gemini 3.5 flash / flash-lite, thinking minimal | 2.5 models retired; bigger models with thinking took 3–7 s |
| LOCAL + router before any LLM | "what's the time" used to start the screen agent and loop on Spotlight |
| Chime instead of spoken "I'm listening" | the spoken ack leaked into the user's command |
| Echo filter with number words | "Timer set for 5 minutes" was heard as "five minutes" and looped forever |
| Glass orb with Siri-like wisps | owner's reference image; replaced the purple liquid blob |
| Pop entrance, no drop | owner preference |
| Light rising from the orb, no rainbow border | rainbow border "looked too AI" |
| Dynamic Island mode | uses the MacBook notch; switch by voice or Ctrl+Option+M |
| DuckDuckGo / Google News / wttr.in | Gemini Google Search grounding is blocked on the free key |
| Timers inside Monday | owner chose to keep them for now |
| Gemini over OpenCode | OpenCode free models are temporary, mostly text-only, and the SDK is JS only |
