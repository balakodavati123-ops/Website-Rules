"""Real-time news watcher: polls free RSS feeds and NSE filings, prints only market-moving headlines.

Sources (no key, no account): Economic Times, Moneycontrol, Mint, Business Standard, the RBI press
feed, Google News (Sensex/Nifty/RBI), plus NSE corporate announcements. Polls every 60 seconds.
The first poll only learns what is already out; after that, each NEW headline that matches a
high-impact rule is printed once, as one line:

  [CATEGORY] headline | source | hh:mm IST | LONG-lean or SHORT-lean hint

The hint is a keyword rule about the headline's tone, not a forecast. Nothing is traded here.
Event rules (kept narrow on purpose, to save the CEO's Claude usage): only index-level headlines
(RBI policy, crashes, geopolitics) and NSE filings from watchlist stocks become events; every other
classified headline goes to the dashboard feed only. At most --max-per-day events a day, counted in
/tmp/news_state.json so re-arming the watcher does not reset the cap or replay headlines.
Writes dashboard/data/news_feed.json (the last 60 headlines, with their category).
Usage: python dashboard/news_watch.py [--once] [--max-per-day 6]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (research script)"}
FEEDS = {
    "ET": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "Mint": "https://www.livemint.com/rss/markets",
    "BusinessStandard": "https://www.business-standard.com/rss/markets-106.rss",
    "RBI": "https://rbi.org.in/pressreleases_rss.xml",
    "GoogleNews": "https://news.google.com/rss/search?q=Sensex+OR+Nifty+OR+RBI+OR+SEBI&hl=en-IN&gl=IN&ceid=IN:en",
}
# (category, regex, tone hint). First match wins; order is by importance.
RULES = [
    ("RBI-POLICY", r"\b(repo rate|rate (hike|cut)|mpc|monetary policy|crr|slr|rbi (hikes|cuts|keeps|holds))\b", "bank/rate-sensitive stocks move first; direction depends on the surprise"),
    ("CRASH/SHOCK", r"\b(crash(es|ed)?|plunge[sd]?|tank(s|ed)?|tumble[sd]?|circuit breaker|black swan|meltdown|sell-?off)\b", "SHORT-lean headline"),
    ("GEOPOLITICS", r"\b(war|missile|sanction|tariff|ceasefire|attack)\b", "global risk headline; check crude, gold, rupee"),
    ("LEADER-EXIT", r"\b(resign(s|ed|ation)?|steps? down|quits?|ousted|removed as (ceo|md|chairman))\b", "SHORT-lean headline"),
    ("LEGAL/REGULATORY", r"\b(sebi (order|bans?|probe|notice)|raid|ed (searches|raids)|fraud|default|insolvency|arrest|allegation|probe|investigation)\b", "SHORT-lean headline"),
    ("EARNINGS", r"\b(q[1-4] (results|profit|net profit)|net profit (rises|jumps|falls|declines)|profit (jumps|surges|slumps|plunges)|results)\b", "read the numbers: tone only"),
    ("DEAL/ORDER", r"\b(order win|bags? order|wins? contract|acquires?|acquisition|merger|stake sale|buyback|bonus issue)\b", "LONG-lean headline"),
    ("APPROVAL", r"\b(usfda|approval|nod|licen[cs]e granted)\b", "LONG-lean headline"),
]
MACRO = {"RBI-POLICY", "CRASH/SHOCK", "GEOPOLITICS"}
STATE, FEED = Path("/tmp/news_state.json"), ROOT / "dashboard" / "data" / "news_feed.json"
NSE_LABELS = {"RESULTS", "ORDER/CONTRACT", "ACQUISITION/STAKE", "MANAGEMENT CHANGE", "LEGAL/REGULATORY", "APPROVAL", "BONUS/SPLIT/BUYBACK"}


def fetch(url: str) -> str:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf8", "replace")
    except Exception:
        return ""


def items(body: str):
    for m in re.finditer(r"<item>(.*?)</item>", body, re.S):
        t = re.search(r"<title>(.*?)</title>", m.group(1), re.S)
        if t:
            yield html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1))).strip()


def classify(title: str):
    low = title.lower()
    for cat, rx, hint in RULES:
        if re.search(rx, low):
            return cat, hint
    return None


def watch_symbols() -> set:
    f = ROOT / "watchlists" / "nifty200_plus_etfs.txt"
    return {t.strip().replace(".NS", "") for t in f.read_text().splitlines() if t.strip() and not t.startswith("#")} if f.exists() else set()


def poll(seen: set, learn: bool, feed: list, watch: set):
    """Returns the events (macro headlines and watchlist filings); every classified item goes to feed."""
    events, now = [], datetime.now(IST).strftime("%H:%M")
    for name, url in FEEDS.items():
        for title in items(fetch(url)):
            key = re.sub(r"\W+", "", title.lower())[:90]
            if key in seen:
                continue
            seen.add(key)
            c = None if learn else classify(title)
            if c:
                is_event = c[0] in MACRO
                feed.append({"time": now, "source": name, "category": c[0], "headline": title[:160], "event": "yes" if is_event else "no", "hint": c[1]})
                if is_event:
                    events.append((c[0], title[:150], name, c[1]))
    try:
        from trading_team.spike_watch import fetch_feed, trigger_of
        for a in fetch_feed():
            key = f"nse{a['symbol']}{a['time']:%H%M}{a['desc'][:20]}"
            if key in seen:
                continue
            seen.add(key)
            lab = None if learn else trigger_of({"desc": a["desc"], "text": a["text"]})
            if lab in NSE_LABELS:
                mine = a["symbol"] in watch
                feed.append({"time": now, "source": "NSE", "category": f"NSE-{lab}", "headline": f"{a['symbol']}: {a['desc'][:120]}", "event": "yes" if mine else "no",
                             "hint": "company filing: check the price before reacting"})
                if mine:
                    events.append((f"NSE-{lab}", f"{a['symbol']}: {a['desc'][:110]}", "NSE", "company filing: check the price before reacting"))
    except Exception:
        pass
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-per-day", type=int, default=6)
    a = ap.parse_args()
    today = datetime.now(IST).date().isoformat()
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if st.get("date") != today:
        st = {"date": today, "count": 0, "seen": []}
    seen, watch = set(st["seen"]), watch_symbols()
    feed = json.loads(FEED.read_text()) if FEED.exists() else []
    if not st["seen"]:
        poll(seen, True, feed, watch)
    print(f"watching: {len(seen)} headlines already out, {st['count']} of {a.max_per_day} events used today", flush=True)
    if a.once:
        return
    while True:
        time.sleep(60)
        events = poll(seen, False, feed, watch)
        FEED.parent.mkdir(parents=True, exist_ok=True)
        FEED.write_text(json.dumps(feed[-60:], indent=1))
        st.update(seen=sorted(seen)[-1500:])
        for cat, title, src, hint in events:
            if st["count"] >= a.max_per_day:
                break
            st["count"] += 1
            print(f"[{cat}] {title} | {src} | {datetime.now(IST):%H:%M} IST | {hint} | event {st['count']} of {a.max_per_day}", flush=True)
        STATE.write_text(json.dumps(st))


if __name__ == "__main__":
    main()
