"""Live spike watcher for NSE stocks.

What it does, every poll during market hours:
  1. reads NSE's public corporate-announcements feed (each item has the exchange's
     own dissemination time) and picks out new filings of types that move prices;
  2. looks at that stock's one-minute prices (Yahoo, about 30 seconds behind);
  3. prints an alert saying what was filed, how long ago, and how far the price
     has already moved.

What it cannot do: it cannot know about a filing before NSE publishes it, and it
does not try to. It reacts to public information, as fast as the public feed allows.
Alerts are research prompts, not orders; the move may already be over.

Usage: python -m trading_team.spike_watch [--once] [--interval 20] [--min-turnover-cr 2]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
HEADERS = {"User-Agent": "Mozilla/5.0 (research script)", "Accept": "application/json",
           "Referer": "https://www.nseindia.com/"}
FEED = "https://www.nseindia.com/api/corporate-announcements?index=equities"

# (label, keywords) in priority order. Matched against the filing type and its text.
TRIGGERS = [
    ("RESULTS", ["financial result", "results for the"]),
    ("ORDER/CONTRACT", ["letter of award", "work order", "bagged", "secured an order",
                        "received an order", "order worth", "contract"]),
    ("ACQUISITION/STAKE", ["acquisition", "acquire", "merger", "amalgamation", "stake",
                           "joint venture"]),
    ("FUND RAISE", ["preferential", "warrant", "qip", "rights issue", "fund raising"]),
    ("APPROVAL", ["usfda", "approval", "patent", "licen"]),
    ("BONUS/SPLIT/BUYBACK", ["bonus", "split", "buyback", "buy back"]),
]
IGNORE = ("copy of newspaper", "analysts/institutional", "trading window", "shareholders meeting")


def fetch_feed() -> list[dict]:
    req = urllib.request.Request(FEED, headers=HEADERS)
    rows = json.loads(urllib.request.urlopen(req, timeout=20).read())
    out = []
    for r in rows:
        out.append({"symbol": r["symbol"], "desc": r.get("desc") or "",
                    "text": r.get("attchmntText") or "", "file": r.get("attchmntFile") or "",
                    "time": datetime.strptime(r["an_dt"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)})
    return out


def trigger_of(item: dict) -> str | None:
    if any(n in item["desc"].lower() for n in IGNORE):
        return None
    blob = f"{item['desc']} {item['text']}".lower()
    for label, keys in TRIGGERS:
        if any(k in blob for k in keys):
            return label
    return None


def price_snapshot(symbol: str, since: datetime) -> dict | None:
    """Move so far today, volume against normal, and the move since the filing."""
    import yfinance as yf
    t = yf.Ticker(f"{symbol}.NS")
    d = t.history(period="5d", interval="1m", auto_adjust=False)
    daily = t.history(period="2mo", interval="1d", auto_adjust=False)
    if d.empty or len(daily) < 25:
        return None
    today = datetime.now(IST).date()
    d = d[d.index.date == today]
    prev_close = daily[daily.index.date < today].Close.iloc[-1]
    if d.empty:
        return None
    turnover_cr = float((daily.Close * daily.Volume).tail(20).mean() / 1e7)
    at = d[d.index <= since]
    px_at_filing = float(at.Close.iloc[-1]) if len(at) else float(d.Open.iloc[0])
    last = float(d.Close.iloc[-1])
    mins = max((datetime.now(IST) - since).total_seconds() / 60, 1)
    exp_vol = float(daily.Volume.tail(20).mean()) / 375 * mins   # volume expected in that span
    since_vol = float(d[d.index >= since].Volume.sum())
    return {"last": last, "prev_close": float(prev_close),
            "day_pct": 100 * (last / prev_close - 1),
            "since_filing_pct": 100 * (last / px_at_filing - 1),
            "at_filing_pct": 100 * (px_at_filing / prev_close - 1),
            "day_high_pct": 100 * (float(d.High.max()) / prev_close - 1),
            "volume_vs_normal": since_vol / exp_vol if exp_vol else None,
            "turnover_cr": turnover_cr, "bar_time": d.index[-1].strftime("%H:%M")}


def verdict(trigger: str, snap: dict) -> str:
    before, moved = snap["at_filing_pct"], snap["since_filing_pct"]
    if before >= 5:
        return (f"MOVED BEFORE THE FILING: already {before:+.1f}% when it was published. "
                f"Either the news was anticipated or this filing is not the cause. "
                f"Not an early signal.")
    if snap["day_pct"] >= 15:
        return "LATE: already up 15%+ today. Chasing is the riskiest entry."
    if moved >= 5:
        return f"MOVING: {moved:+.1f}% since the filing. Much of a typical move may be done."
    if moved >= 1.5:
        return f"EARLY: {moved:+.1f}% since the filing, still building."
    return "NOT MOVING YET: filing is fresh and price has not reacted. Read it now."


def alert(item: dict, trig: str, snap: dict) -> str:
    age = (datetime.now(IST) - item["time"]).total_seconds() / 60
    vol = snap["volume_vs_normal"]
    lines = [f"[{datetime.now(IST):%H:%M:%S}] {item['symbol']}  {trig}  filed {item['time']:%H:%M:%S} "
             f"({age:.0f} min ago)",
             f"    {item['text'][:160]}",
             f"    price {snap['last']:.2f} ({snap['day_pct']:+.1f}% today, day high "
             f"{snap['day_high_pct']:+.1f}%), {snap['since_filing_pct']:+.1f}% since filing, "
             f"volume {'%.1fx normal' % vol if vol else 'n/a'}, bar {snap['bar_time']}",
             f"    {verdict(trig, snap)}"]
    if item["file"]:
        lines.append(f"    filing: {item['file']}")
    return "\n".join(lines)


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) < (15, 30)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="check the latest filings once and exit")
    ap.add_argument("--interval", type=int, default=20, help="seconds between polls")
    ap.add_argument("--min-turnover-cr", type=float, default=2.0,
                    help="ignore stocks whose 20-day average daily turnover is below this (Rs crore)")
    ap.add_argument("--lookback-min", type=int, default=15,
                    help="with --once, include filings from the last N minutes")
    args = ap.parse_args(argv)

    seen: set[tuple] = set()
    first = True
    while True:
        now = datetime.now(IST)
        if not args.once and not market_open(now):
            print(f"[{now:%H:%M}] market closed; waiting", flush=True)
            time.sleep(60)
            continue
        try:
            feed = fetch_feed()
        except Exception as exc:
            print(f"feed error: {exc}", file=sys.stderr, flush=True)
            time.sleep(args.interval)
            continue
        cutoff = now - timedelta(minutes=args.lookback_min if (args.once or first) else 5)
        for item in sorted(feed, key=lambda x: x["time"]):
            key = (item["symbol"], item["time"], item["desc"])
            if key in seen:
                continue
            seen.add(key)
            if item["time"] < cutoff:
                continue
            trig = trigger_of(item)
            if not trig:
                continue
            try:
                snap = price_snapshot(item["symbol"], item["time"])
            except Exception as exc:
                print(f"{item['symbol']}: price error {exc}", file=sys.stderr, flush=True)
                continue
            if snap is None or snap["turnover_cr"] < args.min_turnover_cr:
                continue
            print(alert(item, trig, snap), flush=True)
        first = False
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
