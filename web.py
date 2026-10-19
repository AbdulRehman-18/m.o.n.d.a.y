"""The web without API keys: search (DuckDuckGo), read pages, answer live questions, weather, and scrape data
from a page into CSV and Markdown."""
import csv, datetime, html, json, re, subprocess, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
import config, llm

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Safari/605.1.15", "Accept-Language": "en-US,en;q=0.9"}
OUT = config.HOME / "Documents" / "Monday Notes" / "Scrapes"
SPOKEN = "Answer for speech: 1 to 3 short sentences, plain words, no markdown, no URLs."


def get(url, timeout=6):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", "ignore")


class _Text(HTMLParser):
    """Visible text of a page, skipping scripts, styles, navigation and footers."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "br", "section", "article", "td", "th"}

    def __init__(self, base="", links=False):
        super().__init__()
        self.out, self.skip, self.title, self._in_title = [], 0, "", False
        self.base, self.links, self._href = base, links, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            ok = self.links and href and not href.startswith(("#", "javascript:"))
            self._href.append(urllib.parse.urljoin(self.base, href) if ok else "")
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            href = self._href.pop()
            if href and not self.skip:
                self.out.append(f" <{href}>")
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def page_text(raw_html, limit=15000, base="", links=False):
    """(title, visible text). links=True keeps each link as <url> after its text, for scraping."""
    p = _Text(base, links)
    try:
        p.feed(raw_html)
    except Exception:
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return p.title.strip(), text[:limit]


def search(query, n=6):
    """DuckDuckGo results as [{title, url, snippet}]."""
    raw = get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query))
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)', raw, re.S):
        href, title, rest = m.groups()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(href)).query)
        url = q.get("uddg", [html.unescape(href)])[0]
        if "duckduckgo.com/y.js" in url:  # ads
            continue
        sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', rest, re.S)
        clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
        out.append({"title": clean(title), "url": url, "snippet": clean(sn.group(1)) if sn else ""})
        if len(out) >= n:
            break
    return out


def news(query, n=8):
    """Latest headlines from Google News RSS: [(title, source, published)]."""
    import xml.etree.ElementTree as ET
    url = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q=" + urllib.parse.quote_plus(query + " when:7d")
    root = ET.fromstring(get(url, timeout=5))
    out = []
    for it in root.iter("item"):
        src = it.find("source")
        out.append((it.findtext("title", ""), src.text if src is not None else "", it.findtext("pubDate", "")[:16]))
        if len(out) >= n:
            break
    return out


NEWSY = re.compile(r"\b(news|headlines?|latest|happening|update|announce\w*|today)\b", re.I)


def _read(url):
    try:
        return page_text(get(url, timeout=3), 6000)[1]
    except Exception:
        return ""


def answer(question):
    """Live answer from the web: search, read the top pages in parallel, answer with the source named."""
    today = datetime.datetime.now().strftime("%A %d %B %Y, %I:%M %p")
    if NEWSY.search(question):
        try:
            topic = re.sub(r"(?i)\b(what(?:'s| is| are)?|the|latest|news|headlines?|about|on|any|today|tell me|give me|me)\b", " ", question)
            items = news(re.sub(r"\s+", " ", topic).strip(" ?.") or question)
        except Exception:
            items = []
        if items:
            heads = "\n".join(f"- {t} ({src}, {d})" for t, src, d in items)
            return llm.text(f"Today is {today}. The user asked: {question}\nSummarize the newest relevant headlines below "
                            f"in 2 to 3 spoken sentences, naming a source once.\n{SPOKEN}\n\n{heads}").strip()
    results = search(question)
    if not results:
        return "I couldn't reach the web right now."
    with ThreadPoolExecutor(3) as ex:
        pages = list(ex.map(_read, [r["url"] for r in results[:3]]))  # 3 s cap per page, all in parallel
    ctx = "\n\n".join(f"[{i + 1}] {r['title']} ({urllib.parse.urlparse(r['url']).netloc})\n{r['snippet']}\n{p[:4000]}"
                      for i, (r, p) in enumerate(zip(results, pages + [""] * 6)))
    return llm.text(f"Today is {today}. Question: {question}\nUse these fresh web results; prefer the newest facts. "
                    f"Mention the source site name briefly. If they do not answer it, say so.\n{SPOKEN}\n\n{ctx}").strip()


WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy", 51: "drizzling",
       53: "drizzling", 55: "drizzling", 61: "light rain", 63: "raining", 65: "heavy rain", 71: "snowing", 73: "snowing",
       75: "heavy snow", 80: "showers", 81: "showers", 82: "heavy showers", 95: "thunderstorms", 96: "thunderstorms", 99: "thunderstorms"}


def _open_meteo(place):
    if place:
        g = json.loads(get("https://geocoding-api.open-meteo.com/v1/search?count=10&name=" + urllib.parse.quote(place)))
        if not g.get("results"):
            return f"I couldn't find a place called {place}."
        best = max(g["results"], key=lambda r: r.get("population") or 0)  # the big city, not a namesake village
        lat, lon, area = best["latitude"], best["longitude"], best["name"]
    else:
        ip = json.loads(get("https://ipapi.co/json/"))
        lat, lon, area = ip["latitude"], ip["longitude"], ip.get("city", "your area")
    w = json.loads(get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,"
                       "apparent_temperature,weather_code&daily=temperature_2m_max,temperature_2m_min,"
                       "precipitation_probability_max&timezone=auto&forecast_days=1"))
    c, d = w["current"], w["daily"]
    rain = d["precipitation_probability_max"][0] or 0
    return (f"In {area} it's {round(c['temperature_2m'])} degrees and {WMO.get(c['weather_code'], 'mixed')}, feels like "
            f"{round(c['apparent_temperature'])}. Today ranges from {round(d['temperature_2m_min'][0])} to "
            f"{round(d['temperature_2m_max'][0])} degrees" + (f", with a {rain} percent chance of rain." if rain >= 30 else "."))


def weather(place=""):
    """Current weather and today's range: wttr.in, or Open-Meteo when it is down (no keys; empty place = here)."""
    try:
        d = json.loads(get(f"https://wttr.in/{urllib.parse.quote(place)}?format=j1", timeout=4))
    except Exception:
        return _open_meteo(place)
    c, day = d["current_condition"][0], d["weather"][0]
    area = place.title() if place else d.get("nearest_area", [{}])[0].get("areaName", [{}])[0].get("value", "your area")
    rain = max(int(h.get("chanceofrain", 0)) for h in day.get("hourly", [{}]))
    return (f"In {area} it's {c['temp_C']} degrees and {c['weatherDesc'][0]['value'].lower()}, feels like "
            f"{c['FeelsLikeC']}. Today ranges from {day['mintempC']} to {day['maxtempC']} degrees"
            + (f", with a {rain} percent chance of rain." if rain >= 30 else "."))


BROWSERS = {"Arc": 'tell application "Arc" to get URL of active tab of front window',
            "Google Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
            "Brave Browser": 'tell application "Brave Browser" to get URL of active tab of front window',
            "Microsoft Edge": 'tell application "Microsoft Edge" to get URL of active tab of front window',
            "Safari": 'tell application "Safari" to get URL of front document'}


def current_url():
    """URL of the tab you are looking at, from the frontmost (or any running) browser."""
    if config.OS != "Darwin":
        return ""
    front = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first application '
                            'process whose frontmost is true'], capture_output=True, text=True).stdout.strip()
    running = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of every application process'],
                             capture_output=True, text=True).stdout
    for name in sorted(BROWSERS, key=lambda b: b != front):
        if name in running:
            url = subprocess.run(["osascript", "-e", BROWSERS[name]], capture_output=True, text=True).stdout.strip()
            if url.startswith("http"):
                return url
    return ""


SCRAPE = """Extract {what} from this web page ({url}).
Return JSON: {{"columns": [column names], "rows": [[values in the same order], ...], "note": "one short line"}}.
Pick sensible columns for what was asked (for example name, price, rating, link). Links appear as <url> after
their text; use those full URLs for link columns. Include every matching item on the
page, up to 200 rows. Use exact values from the page; never invent data. If nothing matches, return no rows.

Page title: {title}
Page text:
{text}"""


def scrape(target="", what="the main data, as a table"):
    """Scrape a URL (or the tab you are on) into CSV + Markdown in ~/Documents/Monday Notes/Scrapes.
    Returns (spoken reply, csv path or None)."""
    url = target if re.match(r"https?://", target or "") else ""
    if not url and target and re.search(r"\.\w{2,}", target) and " " not in target.strip():
        url = "https://" + target.strip()
    url = url or current_url()
    if not url:
        return "Open the page in your browser first, or tell me the website.", None
    title, text = page_text(get(url, timeout=10), 80000, base=url, links=True)
    if len(text) < 200:
        return "That page loads its content with JavaScript, so I can't read it directly. Try read the screen instead.", None
    data = llm.json_out(SCRAPE.format(what=what, url=url, title=title, text=text), temperature=0.1)
    cols, rows = data.get("columns") or [], data.get("rows") or []
    if not rows:
        return f"I read the page but found no {what} on it.", None
    OUT.mkdir(parents=True, exist_ok=True)
    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    name = re.sub(r"[^\w\s.-]", "", f"{host} - {what}")[:80].strip()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")
    csv_path = OUT / f"{name} {stamp}.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
    md = [f"# {what.capitalize()} — {host}", f"> Source: {url} · Scraped by Monday on {stamp}", "",
          "| " + " | ".join(map(cell, cols)) + " |", "|" + " --- |" * len(cols)]
    md += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    csv_path.with_suffix(".md").write_text("\n".join(md) + "\n")
    return f"Done! I scraped {len(rows)} rows from {host} and saved them as a spreadsheet.", csv_path
