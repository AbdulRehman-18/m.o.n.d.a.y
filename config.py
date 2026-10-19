import os, platform
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
OS = platform.system()  # Darwin, Windows, Linux
HOME = Path.home()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_LANG = os.getenv("WHISPER_LANG", "en") or None
PTT_KEY = os.getenv("PTT_KEY", "alt_r")  # hold to talk (right Option on Mac)
KILL_KEY = os.getenv("KILL_KEY", "esc")
PORTFOLIO_URL = os.getenv("PORTFOLIO_URL", "https://abdulrehman-18.vercel.app")
HUD_MODE = os.getenv("HUD_MODE", "full")  # full or island (Dynamic Island in the notch), ctrl+option+M toggles
MAX_STEPS = int(os.getenv("MAX_STEPS", "12"))
SHOT_W = 1280
WAKE_MODE = os.getenv("WAKE_MODE", "wake")  # wake: say "hey Monday" or double clap. ptt: hold PTT_KEY
CLAP = os.getenv("CLAP", "1") == "1"
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
_APPLE_GPU = OS == "Darwin" and platform.machine() == "arm64"
STT = os.getenv("STT", "mlx" if _APPLE_GPU else "faster")  # mlx: Whisper on the Apple GPU
STT_MODEL = os.getenv("STT_MODEL", "mlx-community/whisper-large-v3-turbo")
CONVERSE_S = float(os.getenv("CONVERSE_S", "8"))  # after a reply, talk again without the wake word
END_FRAMES = int(os.getenv("END_MS", "550")) // 30  # silence that ends a phrase
FINISH_S = float(os.getenv("FINISH_S", "1.8"))  # extra wait when a sentence sounds unfinished ("I want you to...")
ACK = os.getenv("ACK", "chime")  # what Monday does on wake: chime (instant) or speak
TTS = os.getenv("TTS", "kokoro")  # kokoro (natural, on device) or say
TTS_VOICE = os.getenv("TTS_VOICE", "af_bella*0.6+af_sky*0.4")  # one voice or a blend, see voice_samples/
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.12"))
FAST_MODEL = os.getenv("FAST_MODEL", "gemini-3.5-flash-lite")  # quick decisions and answers
THINKING = os.getenv("THINKING", "minimal")  # Gemini thinking level: minimal is fastest, low/high think more