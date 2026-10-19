"""Study notes: find a PDF (by name or topic), let Gemini read all of it, and write a Markdown study guide
with a summary, key concepts, questions and an answer key."""
import datetime, re, subprocess
from pathlib import Path
from google.genai import types
import config, llm, tools

OUT = config.HOME / "Documents" / "Monday Notes"
DOCS = {".pdf", ".txt", ".md"}
INLINE_LIMIT = 18 * 1024 * 1024  # Gemini reads PDFs up to about 20 MB directly, images and scans included
STOP = set("""a an the my me of on in at to for from with and or about that this these those pdf pdfs file files document
document's doc notes note study studies make create generate write give questions question quiz summary summarize summarise
please can could you want i some all it its from my latest recent new md markdown guide revision chapter""".split())

PROMPT = """You are an expert teacher. Make a study guide from the attached document "{name}".{focus}
Write GitHub Markdown only, nothing before or after it, in this structure:

# {title} — Study Notes
> Source: {name} · Made by Monday on {date}

## Summary
6 to 10 clear sentences covering the whole document.

## Key concepts
Bullets: **term** — one-line explanation.

## Important facts, formulas and definitions
Only if the document has them. Use a table when it helps.

## Questions
### Multiple choice
{mcq} questions, options a) to d), one correct.
### Short answer
{short} questions.
### Long answer (exam style)
{long} questions.
### Think deeper
3 application or analysis questions.

## Answer key
Multiple choice: answer letter plus a one-line reason. Short answer: 1 to 2 lines each. Long answer: a bullet outline
of the points to cover.

## Quick revision checklist
5 to 8 "- [ ]" items.

Use only what the document says. Number every question. Write for a student revising for an exam."""


def find_document(query):
    """Best matching PDF or text document for a file name or a topic, newest first when it is a tie."""
    q = query.strip().strip("'\"")
    if re.search(r"\.(pdf|txt|md)$", q, re.I):
        try:
            return tools._resolve(q)
        except FileNotFoundError:
            pass
    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 1 and w not in STOP]
    if config.OS == "Darwin":
        cond = " && ".join(f'(kMDItemFSName == "*{w}*"cd || kMDItemTextContent == "{w}*"cdw)' for w in words[:6])
        kinds = '(kMDItemContentTypeTree == "com.adobe.pdf" || kMDItemFSName == "*.md"c || kMDItemFSName == "*.txt"c)'
        out = subprocess.run(["mdfind", "-onlyin", str(config.HOME), f"{kinds} && {cond}" if cond else kinds],
                             capture_output=True, text=True, timeout=8).stdout.splitlines()
        hits = [Path(h) for h in out if Path(h).suffix.lower() in DOCS and not tools._SKIP.search(h) and Path(h).exists()]
        if hits:
            # file name matches beat text matches; rare words ("geothermal") count more than common ones ("energy")
            weight = {w: 1 / (1 + sum(w in h.name.lower() for h in hits)) for w in words}
            return max(hits, key=lambda p: (round(sum(weight[w] for w in words if w in p.name.lower()), 3), p.stat().st_mtime))
    raise FileNotFoundError(f"I couldn't find a document about {query}")


def _counts(size):
    return {"mcq": 15, "short": 10, "long": 6} if size == "big" else {"mcq": 10, "short": 8, "long": 5}


def make_notes(query, focus="", size="normal"):
    """Writes the study guide and returns (markdown path, two-sentence spoken summary, source path)."""
    src = find_document(query)
    title = re.sub(r"[_\-]+", " ", src.stem).strip()
    prompt = PROMPT.format(name=src.name, title=title, date=datetime.date.today().strftime("%d %B %Y"),
                           focus=f"\nFocus especially on: {focus}." if focus else "", **_counts(size))
    if src.suffix.lower() == ".pdf" and src.stat().st_size <= INLINE_LIMIT:
        doc = types.Part.from_bytes(data=src.read_bytes(), mime_type="application/pdf")
    else:
        from rag import read_text
        doc = f"Document text:\n{read_text(src, pages=120)[:400000]}"
    md = (llm._gen(config.MODEL, [doc, prompt], temperature=0.4).text or "").strip()
    md = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", md)
    if not md:
        raise RuntimeError("Gemini returned an empty study guide")
    OUT.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\s,.()-]", "", title)[:80].strip() or "Notes"
    out = OUT / f"{safe} - Study Notes.md"
    n = 2
    while out.exists():
        out = OUT / f"{safe} - Study Notes ({n}).md"
        n += 1
    out.write_text(md + "\n")
    m = re.search(r"## Summary\s*\n+(.+?)(?:\n#|\Z)", md, re.S)
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", m.group(1)).strip()) if m else []
    return out, " ".join(sentences[:2]), src
