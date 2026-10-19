import json, logging, os, threading, time
from pathlib import Path
import numpy as np
import config, llm

EXT = {".txt", ".md", ".pdf", ".csv"}
DIRS = [config.HOME / d for d in ("Desktop", "Documents", "Downloads")]
CACHE = config.HOME / ".monday" / "index.json"
REFRESH = 6 * 3600  # re-index at most every 6 hours, embeddings share the Gemini quota with commands
logging.getLogger("pypdf").setLevel(logging.ERROR)
_idx, _lock = {}, threading.Lock()


def _files(limit=400):
    out = []
    for d in DIRS:
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x != "node_modules"]
            if len(Path(root).relative_to(d).parts) >= 2:
                dirs[:] = []
            for f in files:
                if Path(f).suffix.lower() in EXT and not f.startswith("."):
                    out.append(Path(root, f))
                    if len(out) >= limit:
                        return out
    return out


def read_text(p, pages=3):
    p = Path(p)
    try:
        if p.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            return " ".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages[:pages])
        return p.read_text(errors="ignore")
    except Exception:
        return ""


def build():
    global _idx
    try:
        if CACHE.exists():
            _idx = json.loads(CACHE.read_text())
            if time.time() - CACHE.stat().st_mtime < REFRESH:
                print(f"File index ready: {len(_idx)} files", flush=True)
                return
        todo = [(p, p.stat().st_mtime) for p in _files() if _idx.get(str(p), {}).get("m") != p.stat().st_mtime][:150]
        for i in range(0, len(todo), 25):
            batch = todo[i:i + 25]
            try:
                vecs = llm.embed([f"{p.name}\n{read_text(p)[:1500]}" for p, _ in batch])
            except Exception as e:
                print("File index paused:", str(e)[:80], flush=True)
                break
            with _lock:
                for (p, m), v in zip(batch, vecs):
                    _idx[str(p)] = {"m": m, "v": v}
            time.sleep(2)
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(_idx))
        print(f"File index ready: {len(_idx)} files", flush=True)
    except Exception as e:
        print("File index failed:", e, flush=True)


def search(query, k=3):
    with _lock:
        items = [(p, d["v"]) for p, d in _idx.items() if Path(p).exists()]
    if not items:
        return "no indexed files yet"
    q = np.array(llm.embed([query])[0])
    M = np.array([v for _, v in items])
    sims = M @ q / (np.linalg.norm(M, axis=1) * np.linalg.norm(q) + 1e-9)
    words = [w for w in query.lower().split() if len(w) > 2]
    for i, (p, _) in enumerate(items):
        sims[i] += 0.15 * sum(w in Path(p).name.lower() for w in words)
    return "\n".join(f"{items[i][0]} (score {sims[i]:.2f})" for i in np.argsort(-sims)[:k])
