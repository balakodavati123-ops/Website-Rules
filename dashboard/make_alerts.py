"""Filing alerts for the most recent trading day, with the price reaction around each filing.

Reads NSE's public announcements for the day, keeps price-sensitive filings made during the
session in stocks that trade at least Rs 2 crore a day, and measures the price from Yahoo
one-minute bars (available for about the last 7 days). Writes dashboard/inputs/alerts.json
and dashboard/inputs/events.json for build_seed.py.

Usage: python dashboard/make_alerts.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trading_team.spike_watch import HEADERS, IST, trigger_of  # noqa: E402

MIN_TURNOVER_CR = 2.0


def reaction(minutes: pd.DataFrame, prev_close: float, filed_at: datetime) -> dict | None:
    """Price move at the filing and after it, from one-minute bars of one session."""
    if minutes.empty or not prev_close:
        return None
    before = minutes[minutes.index <= filed_at]
    px = float(before.Close.iloc[-1]) if len(before) else float(minutes.Open.iloc[0])
    last = float(minutes.Close.iloc[-1])
    return {"at_filing": round((px / prev_close - 1) * 100, 1), "since_filing": round((last / px - 1) * 100, 1),
            "day_pct": round((last / prev_close - 1) * 100, 1),
            "day_high": round((float(minutes.High.max()) / prev_close - 1) * 100, 1)}


def read_of(r: dict) -> str:
    if abs(r["at_filing"]) >= 5:
        return "Moved before the filing"
    if r["since_filing"] >= 3:
        return "Rose after the filing"
    if r["since_filing"] <= -3:
        return "Sold after the filing"
    return "No clear reaction"


def feed_for(day: date) -> list[dict]:
    s = day.strftime("%d-%m-%Y")
    url = f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={s}&to_date={s}"
    rows = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30).read())
    out = []
    for r in rows:
        t = datetime.strptime(r["an_dt"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
        out.append({"symbol": r["symbol"], "desc": r.get("desc") or "", "text": r.get("attchmntText") or "", "time": t})
    return out


def measure(item: dict, day: date) -> dict | None:
    import yfinance as yf
    t = yf.Ticker(f"{item['symbol']}.NS")
    try:
        daily = t.history(period="2mo", interval="1d", auto_adjust=False)
        m = t.history(period="8d", interval="1m", auto_adjust=False)
    except Exception:
        return None
    if daily.empty or m.empty:
        return None
    turnover = float((daily.Close * daily.Volume).tail(20).mean() / 1e7)
    prev = daily[daily.index.date < day]
    m = m[m.index.date == day]
    if turnover < MIN_TURNOVER_CR or prev.empty or m.empty:
        return None
    return reaction(m, float(prev.Close.iloc[-1]), item["time"])


def main():
    import yfinance as yf
    if len(sys.argv) > 1:
        day = date.fromisoformat(sys.argv[1])
    else:
        idx = yf.Ticker("^NSEI").history(period="10d", interval="1d").index
        day = idx[-1].date()
    items = []
    for it in feed_for(day):
        mins = it["time"].hour * 60 + it["time"].minute
        trig = trigger_of(it)
        if trig and 9 * 60 + 15 <= mins <= 15 * 60 + 30:
            items.append((it, trig))
    seen, uniq = set(), []
    for it, trig in sorted(items, key=lambda x: x[0]["time"]):
        if it["symbol"] not in seen:
            seen.add(it["symbol"])
            uniq.append((it, trig))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda x: measure(x[0], day), uniq[:60]))
    alerts = []
    for (it, trig), r in zip(uniq, results):
        if not r:
            continue
        head = "Quarterly results filed" if trig == "RESULTS" else (re.sub(r"^.*?has informed the Exchange (?:about|regarding)?\s*", "", it["text"]).strip() or it["desc"])
        alerts.append({"time": it["time"].strftime("%H:%M"), "symbol": it["symbol"], "type": "Results" if trig == "RESULTS" else "Order" if trig.startswith("ORDER") else CD_TITLE.get(trig, trig.title()),
                       "headline": head[:150], **r, "read": read_of(r)})
    inputs = ROOT / "dashboard" / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "alerts.json").write_text(json.dumps(alerts, indent=1))
    top = sorted(alerts, key=lambda a: abs(a["day_high"]), reverse=True)[:4]
    events = [{"symbol": a["symbol"], "kind": "Earnings" if a["type"] == "Results" else "Event",
               "headline": f"{a['type']} on {day:%d %b}: {a['day_pct']:+.1f}% on the day, high {a['day_high']:+.1f}%",
               "why": f"{a['headline']}. The price was {a['at_filing']:+.1f}% when it appeared and {a['since_filing']:+.1f}% after. {a['read']}.",
               "source": f"NSE filing {a['time']} and Yahoo prices, {day:%d %b}"} for a in top]
    (inputs / "events.json").write_text(json.dumps(events, indent=1))
    print(f"{day}: {len(alerts)} filing alerts, {len(events)} events")


CD_TITLE = {"ACQUISITION/STAKE": "Deal", "FUND RAISE": "Fund raise", "APPROVAL": "Approval", "BONUS/SPLIT/BUYBACK": "Corporate action"}

if __name__ == "__main__":
    main()
