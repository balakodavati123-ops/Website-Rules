"""Real-time news watcher: polls free RSS feeds and NSE filings, prints only market-moving headlines.

Sources (no key, no account): Economic Times, Moneycontrol, Mint, Business Standard, the RBI press
feed, Google News (Sensex/Nifty/RBI), plus NSE corporate announcements. Polls every 60 seconds.
The first poll only learns what is already out; after that, each NEW headline that matches a
high-impact rule is printed once, as one line:

  [CATEGORY] headline | source | hh:mm IST | LONG-lean or SHORT-lean hint

The hint is a keyword rule about the headline's tone, not a forecast. Nothing is traded here.
Usage: python dashboard/news_watch.py [--once] [--max-per-hour 12]
"""
from __future__ import annotations

import argparse
import html
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


def poll(seen: set, learn: bool):
    hits = []
    for name, url in FEEDS.items():
        for title in items(fetch(url)):
            key = re.sub(r"\W+", "", title.lower())[:90]
            if key in seen:
                continue
            seen.add(key)
            c = None if learn else classify(title)
            if c:
                hits.append((c[0], title[:150], name, c[1]))
    try:
        from trading_team.spike_watch import fetch_feed, trigger_of
        for a in fetch_feed():
            key = f"nse{a['symbol']}{a['time']:%H%M}{a['desc'][:20]}"
            if key in seen:
                continue
            seen.add(key)
            lab = None if learn else trigger_of({"desc": a["desc"], "text": a["text"]})
            if lab in NSE_LABELS:
                hits.append((f"NSE-{lab}", f"{a['symbol']}: {a['desc'][:110]}", "NSE", "company filing: check the price before reacting"))
    except Exception:
        pass
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-per-hour", type=int, default=12)
    a = ap.parse_args()
    seen: set = set()
    poll(seen, learn=True)
    print(f"watching: {len(seen)} headlines already out; alerts only for new high-impact items", flush=True)
    if a.once:
        return
    sent = []
    while True:
        time.sleep(60)
        now = time.time()
        sent = [t for t in sent if now - t < 3600]
        for cat, title, src, hint in poll(seen, learn=False):
            if len(sent) >= a.max_per_hour:
                break
            sent.append(now)
            print(f"[{cat}] {title} | {src} | {datetime.now(IST):%H:%M} IST | {hint}", flush=True)


if __name__ == "__main__":
    main()
