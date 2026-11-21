"""News pulse: the desk's first look at every market headline and NSE filing, about once a minute, free (no AI).

Each new headline is scored for emotion with a finance word list (order wins, approvals, buybacks and upgrades read positive; probes,
resignations, defaults and downgrades read negative; "denies" or "no impact" soften it), matched to exactly one listed company, and handed
to the intraday desk's Headlines and Filings hunters as a signal. A signal is not a trade: the desk trades it only if the price confirms
(see intraday.setups: a news-led entry needs the stock moving the same way near its day high or low). The hourly Claude analyst then
confirms or doubts the strongest signals; a doubted name is not traded for the rest of the day. Nothing here places an order.
"""
from __future__ import annotations

import email.utils
import html
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (desk news pulse)"}
FEEDS = {
    "ET Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "ET Stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "Mint": "https://www.livemint.com/rss/markets",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "BusinessLine": "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    "NDTV Profit": "https://feeds.feedburner.com/ndtvprofit-latest",
    "CNBC-TV18": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
    "Google News": "https://news.google.com/rss/search?q=shares+OR+stock+NSE+when:1h&hl=en-IN&gl=IN&ceid=IN:en",
}
# phrase -> weight; longer phrases are checked first and their words are not counted again
LEX = {
    "bags order": 3, "bagged order": 3, "wins order": 3, "order win": 3, "secures order": 3, "wins contract": 3, "bags contract": 3, "order worth": 2, "order inflow": 2,
    "buyback": 3, "bonus issue": 3, "stock split": 2, "special dividend": 2, "dividend": 1, "acquisition": 2, "acquires": 2, "to acquire": 2, "merger": 1,
    "usfda approval": 3, "approval": 2, "approves": 1.5, "gets nod": 2, "receives nod": 2, "nod": 1.5, "launches": 1, "expansion": 1, "partnership": 1, "tie-up": 1, "ties up": 1, "signs mou": 1,
    "upgrade": 2.5, "upgraded": 2.5, "raises target": 2, "target raised": 2, "buy rating": 2, "overweight": 1.5, "outperform": 1.5, "beats estimates": 2.5, "beat estimates": 2.5,
    "record profit": 3, "profit jumps": 3, "profit surges": 3, "profit rises": 2, "net profit up": 2, "revenue jumps": 2, "margin expands": 2, "turnaround": 2, "debt-free": 2,
    "raises stake": 2, "stake hike": 2, "promoter buys": 2, "record high": 2, "52-week high": 2, "all-time high": 2, "upper circuit": 3,
    "rally": 1.5, "rallies": 1.5, "surge": 2, "surges": 2, "soars": 2.5, "jumps": 2, "zooms": 2.5, "skyrockets": 3, "rockets": 2.5, "climbs": 1, "gains": 1, "rises": 1,
    "fraud": -4, "scam": -4, "probe": -3, "raid": -3, "searches": -2, "penalty": -2.5, "fined": -2.5, "sebi order": -2.5, "ban": -2.5, "bans": -2.5, "show cause": -2, "tax demand": -2, "gst notice": -2,
    "default": -3.5, "defaults": -3.5, "insolvency": -3.5, "bankruptcy": -4, "resigns": -3, "resignation": -2.5, "steps down": -2.5, "quits": -2.5, "auditor resigns": -4, "arrest": -3.5, "arrested": -3.5,
    "downgrade": -3, "downgraded": -3, "cuts target": -2, "target cut": -2, "sell rating": -2.5, "underweight": -1.5, "underperform": -1.5, "misses estimates": -2.5, "miss estimates": -2.5,
    "profit falls": -3, "profit drops": -3, "profit declines": -2.5, "net loss": -2.5, "loss widens": -3, "revenue falls": -2, "margin contracts": -2, "write-off": -2, "impairment": -2,
    "pledge": -1.5, "pledged": -1.5, "fire at": -2.5, "blaze": -2, "shutdown": -2, "halts": -2, "strike": -1.5, "recall": -2, "warning letter": -3, "import alert": -3, "observations": -1.5,
    "lawsuit": -2, "sued": -2, "allegation": -2, "whistleblower": -2.5, "stake sale": -1, "lower circuit": -3, "52-week low": -2,
    "slump": -2, "slumps": -2, "plunge": -2.5, "plunges": -2.5, "crash": -3, "crashes": -3, "tanks": -2.5, "tumbles": -2.5, "sinks": -2, "slides": -1.5, "falls": -1, "drops": -1, "declines": -1,
}
SOFTEN = ("denies", "denied", "no impact", "clarifies", "clarification", "rejects report", "baseless", "speculation", "rumour", "rumor")
PHRASES = sorted(LEX, key=lambda k: -len(k))
PCT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|per cent)")
WORD = re.compile(r"[a-z0-9&]+")
TAG = lambda tag, s: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", s, re.S) or [None, ""])[1]


def clean(t: str) -> str:
    return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", t or "")).strip()


def score(title: str) -> tuple[float, list[str]]:
    """Emotion score of one headline (positive = optimism, negative = fear) and the phrases that drove it."""
    low = title.lower()
    found = [p for p in PHRASES if re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", low)]
    hits = [p for p in found if not any(p != q and p in q for q in found)]  # "jumps" inside "profit jumps" is counted once
    total = sum(LEX[p] for p in hits)
    if hits:
        m = PCT.search(title)
        if m and float(m.group(1)) >= 5:
            total *= 1.3                                                     # "jumps 12%": a big number is a strong signal
        if any(x in low for x in SOFTEN):
            total *= 0.3
    return round(total, 2), hits


def emotion(s: float) -> str:
    return "Euphoria" if s >= 4 else "Optimism" if s >= 1.5 else "Panic" if s <= -4 else "Fear" if s <= -1.5 else "Neutral"


BROKERS = ("anand rathi", "motilal oswal", "icici securities", "kotak securities", "jm financial", "nuvama", "axis securities", "hdfc securities", "sharekhan", "angel one",
           "iifl", "geojit", "prabhudas lilladher", "emkay", "elara", "antique", "choice broking", "religare", "5paisa", "nomura", "jefferies", "morgan stanley", "goldman sachs", "clsa", "citi")
GENERIC = ("nifty", "sensex", "largecap", "midcap", "smallcap", "stocks to buy", "stocks to watch", "markets", "market today", "stock market", "stocks:", "top gainers", "top losers")


def match(title: str, idx: dict) -> str | None:
    """The one listed company a headline names, or None when it names none or several, or only a brokerage giving a view."""
    if not idx:
        return None
    low = title.lower()
    for b in BROKERS:
        low = low.replace(b, " ")                                            # "Anand Rathi sees ..." is about the stock, not the broker
    w = WORD.findall(low)
    pair = {idx["pair"][f"{a} {b}"] for a, b in zip(w, w[1:]) if f"{a} {b}" in idx["pair"]}
    single = {idx["one"][x] for x in w if x in idx["one"]} | {idx["sym"][x] for x in w if x in idx["sym"]}
    found = pair | single
    if len(found) != 1:
        return None
    if not pair and any(g in low for g in GENERIC):
        return None                                                          # a market-wide story with one stray word that looks like a company
    return found.pop()


def fetch(url: str, state: dict) -> str:
    """One conditional GET: unchanged feeds cost almost nothing."""
    h = dict(UA)
    c = state.setdefault("cache", {}).get(url) or {}
    if c.get("etag"):
        h["If-None-Match"] = c["etag"]
    if c.get("mod"):
        h["If-Modified-Since"] = c["mod"]
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=12)
        state["cache"][url] = {"etag": r.headers.get("ETag"), "mod": r.headers.get("Last-Modified")}
        return r.read().decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        return "" if e.code == 304 else None                                 # "" = unchanged since the last read, None = the feed failed
    except Exception:
        return None


def items(body: str) -> list[dict]:
    out = []
    for m in re.finditer(r"<item>(.*?)</item>", body, re.S):
        it = m.group(1)
        title, link, pub = clean(TAG("title", it)), clean(TAG("link", it)), clean(TAG("pubDate", it))
        try:
            ts = email.utils.parsedate_to_datetime(pub).timestamp() if pub else None
        except Exception:
            ts = None
        if title:
            out.append({"title": title, "link": link, "ts": ts})
    return out


def new_state() -> dict:
    return {"day": "", "seen": {}, "signals": [], "cache": {}, "feeds": {}, "scans": 0}


def scan(st: dict, idx: dict, now: datetime, get=None, filings: list[dict] | None = None, max_age_h: float = 3.0) -> list[dict]:
    """Read every feed once; return the new signals (headlines and filings that name one company and lean one way)."""
    day = now.strftime("%Y-%m-%d")
    if st.get("day") != day:
        st.update(day=day, seen={}, signals=[])
    get = get or (lambda u: fetch(u, st))
    fresh, t_now = [], now.timestamp()
    rows = []
    for src, url in FEEDS.items():
        body = get(url)
        its = items(body) if body else []
        st["feeds"][src] = {"ok": body is not None, "items": len(its) if body else (st["feeds"].get(src) or {}).get("items", 0), "at": now.strftime("%H:%M:%S")}
        rows += [(src, x) for x in its]
    for f in filings or []:
        rows.append(("NSE filing", {"title": f"{f['symbol']}: {f['desc']}", "link": f.get("link", ""), "ts": f.get("ts"), "symbol": f["symbol"], "tone": f.get("tone")}))
    for src, x in rows:
        key = re.sub(r"\W+", "", x["title"].lower())[:90]
        if not key or key in st["seen"]:
            continue
        st["seen"][key] = 1
        if x.get("ts") and t_now - x["ts"] > max_age_h * 3600:
            continue                                                         # old news: the market has already priced it
        s, hits = score(x["title"])
        if x.get("tone") and not hits:
            s, hits = (2.5 if x["tone"] == "positive" else -2.5), [f"filing: {x['tone']}"]
        sym = x.get("symbol") or match(x["title"], idx)
        if not sym or abs(s) < 1.5:
            continue
        sig = {"id": f"N{now:%H%M%S}-{len(st['signals']) + len(fresh) + 1}", "t": now.strftime("%H:%M:%S"), "ts": t_now, "pub": datetime.fromtimestamp(x["ts"], IST).strftime("%H:%M") if x.get("ts") else None,
               "lag_s": round(t_now - x["ts"]) if x.get("ts") else None, "symbol": sym, "tone": "positive" if s > 0 else "negative", "score": s, "emotion": emotion(s),
               "why": hits[:4], "headline": x["title"][:180], "source": src, "link": x.get("link", ""), "kind": "filing" if src == "NSE filing" else "headline", "status": "new"}
        fresh.append(sig)
    if len(st["seen"]) > 6000:
        st["seen"] = dict(list(st["seen"].items())[-4000:])
    st["signals"] = (st["signals"] + fresh)[-300:]
    st["scans"] = st.get("scans", 0) + 1
    return fresh


def for_hunters(st: dict, now: datetime, doubted: set, hours: float = 3.0) -> dict:
    """{symbol: {tone, headline, time, source}}: the latest strong signal per company in the last few hours, minus names the AI analyst doubted."""
    out = {}
    for s in st.get("signals") or []:
        if now.timestamp() - s["ts"] <= hours * 3600 and s["symbol"] not in doubted:
            out[s["symbol"]] = {"tone": s["tone"], "headline": s["headline"], "time": s["t"][:5], "source": s["source"], "emotion": s["emotion"], "score": s["score"]}
    return out


def track(st: dict, prices: dict, traded: set, skipped: dict, checks: dict) -> None:
    """Price since each signal, and what the desk did with it."""
    for s in st.get("signals") or []:
        p = prices.get(s["symbol"])
        if p:
            s.setdefault("px0", p)
            s["px"] = p
            s["move_pct"] = round((p / s["px0"] - 1) * 100, 2) if s["px0"] else None
        c = checks.get(s["symbol"])
        if c:
            s["ai"] = c
        if s["symbol"] in traded:
            s["status"] = "traded"
        elif c and c.get("verdict") == "doubt":
            s["status"] = "skipped: the AI analyst doubted it"
        elif s["symbol"] in skipped:
            s["status"] = "not taken: " + str(skipped[s["symbol"]])[:60]
        elif s.get("move_pct") is not None:
            agree = s["move_pct"] > 0 if s["tone"] == "positive" else s["move_pct"] < 0
            s["status"] = "price agrees: hunters checking the entry rule" if agree and abs(s["move_pct"]) >= 0.3 else "watching: price has not confirmed yet"
