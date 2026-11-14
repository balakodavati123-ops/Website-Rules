"""Pre-market world view for the dashboard: overnight markets, today's company events, headlines.

  Yahoo Finance   last close and change for world indices, the dollar, rupee, crude, gold, US yields
  NSE             board meetings (results) and corporate actions due in the next few days
  Yahoo Finance   news headlines, shown word for word with their publisher. The desk adds no opinion.

Writes dashboard/data/world_markets.json, events_today.json, world_news.json and results_filed.json.
Usage: python dashboard/make_world.py
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "data"
IST = timezone(timedelta(hours=5, minutes=30))
HEADERS = {"User-Agent": "Mozilla/5.0 (research script)", "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
MARKETS = [  # group, name, Yahoo symbol, why it matters to an Indian session
    ("United States", "S&P 500", "^GSPC", "Sets the tone for Asia's open"), ("United States", "Nasdaq", "^IXIC", "Leads Indian IT stocks"),
    ("United States", "Dow Jones", "^DJI", "Broad US risk mood"), ("United States", "US fear index (VIX)", "^VIX", "Rising means global risk-off"),
    ("Asia", "Nikkei 225", "^N225", "Trades before India opens"), ("Asia", "Hang Seng", "^HSI", "Asia and China risk mood"),
    ("Asia", "Shanghai", "000001.SS", "China demand, metals"), ("Europe", "FTSE 100", "^FTSE", "Europe's close, yesterday"),
    ("Europe", "DAX", "^GDAXI", "Europe's close, yesterday"), ("India", "Nifty 50", "^NSEI", "Yesterday's close"),
    ("Money", "US dollar index", "DX-Y.NYB", "A strong dollar pulls money out of India"), ("Money", "Dollar in rupees", "INR=X", "A weak rupee hurts importers, helps IT"),
    ("Money", "US 10-year yield", "^TNX", "Higher yields pressure growth stocks"), ("Commodities", "Brent crude", "BZ=F", "India imports its oil: higher is worse"),
    ("Commodities", "Gold", "GC=F", "Your largest holding follows this"), ("Commodities", "Silver", "SI=F", "Your second-largest holding"),
]


def markets() -> list[dict]:
    import yfinance as yf
    data = yf.download([m[2] for m in MARKETS], period="10d", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    rows = []
    for group, name, sym, why in MARKETS:
        try:
            c = data[sym].Close.dropna()
            last, prev = float(c.iloc[-1]), float(c.iloc[-2])
            rows.append({"group": group, "name": name, "symbol": sym, "last": round(last, 2), "chg_pct": round((last / prev - 1) * 100, 2),
                         "as_of": str(c.index[-1].date()), "why": why, "spark": json.dumps([round(float(x), 2) for x in c.tail(8)])})
        except Exception:
            rows.append({"group": group, "name": name, "symbol": sym, "last": None, "chg_pct": None, "as_of": "", "why": "Data Unverified", "spark": "[]"})
    return rows


def nse(url: str) -> list[dict]:
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=25).read())


def events(today, watch: set[str], days: int = 3, cap: int = 80) -> list[dict]:
    rows, until = [], today + timedelta(days=days)
    day = lambda s: datetime.strptime(s, "%d-%b-%Y").date()
    try:
        for e in nse("https://www.nseindia.com/api/event-calendar"):
            when = day(e["date"])
            if today <= when <= until:
                rows.append({"date": when.isoformat(), "symbol": e["symbol"], "company": e.get("company", ""), "kind": e.get("purpose", "Board meeting"),
                             "detail": (e.get("bm_desc") or "")[:160], "watchlist": "yes" if e["symbol"] in watch else "no"})
    except Exception as err:
        print("event calendar failed:", err)
    try:
        for a in nse("https://www.nseindia.com/api/corporates-corporateActions?index=equities"):
            when = day(a["exDate"])
            if today <= when <= until:
                rows.append({"date": when.isoformat(), "symbol": a["symbol"], "company": a.get("comp", ""), "kind": "Corporate action (ex-date)",
                             "detail": a.get("subject", ""), "watchlist": "yes" if a["symbol"] in watch else "no"})
    except Exception as err:
        print("corporate actions failed:", err)
    rows.sort(key=lambda r: (r["date"], r["watchlist"] != "yes", r["symbol"]))
    return rows[:cap]


def results_filed(now, watch: set[str], cap: int = 60) -> list[dict]:
    """Companies that filed financial results since the previous session's close (15:30 IST).
    The filing is listed as filed; the desk does not read the profit figures out of it."""
    since = now - timedelta(days=1)
    while since.weekday() >= 5:
        since -= timedelta(days=1)
    since = since.replace(hour=15, minute=30, second=0, microsecond=0)
    url = ("https://www.nseindia.com/api/corporate-announcements?index=equities"
           f"&from_date={since.strftime('%d-%m-%Y')}&to_date={now.strftime('%d-%m-%Y')}")
    rows, seen = [], set()
    try:
        for r in nse(url):
            when = datetime.strptime(r["an_dt"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
            desc, text = (r.get("desc") or "").lower(), (r.get("attchmntText") or "").lower()
            is_result = "financial result" in desc or ("financial results" in text and "approved" in text)
            if when < since or not is_result or "transcript" in text or r["symbol"] in seen:
                continue
            seen.add(r["symbol"])
            rows.append({"time": when.strftime("%d %b %H:%M"), "symbol": r["symbol"], "company": r.get("sm_name") or "",
                         "headline": (r.get("attchmntText") or r.get("desc") or "")[:170], "watchlist": "yes" if r["symbol"] in watch else "no"})
    except Exception as err:
        print("results feed failed:", err)
    rows.sort(key=lambda x: (x["watchlist"] != "yes", x["symbol"]))
    return rows[:cap]


def news(cap: int = 14) -> list[dict]:
    import yfinance as yf
    out, seen = [], set()
    for market, sym in (("India", "^NSEI"), ("World", "^GSPC"), ("Tech", "NVDA"), ("Oil", "BZ=F"), ("Gold", "GC=F")):
        try:
            items = yf.Ticker(sym).news or []
        except Exception:
            items = []
        for it in items[:6]:
            c = it.get("content") or it
            title = c.get("title")
            pub = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
            when = c.get("pubDate") or c.get("providerPublishTime") or ""
            if isinstance(when, (int, float)):
                when = datetime.fromtimestamp(when, tz=timezone.utc).isoformat()
            if title and title not in seen:
                seen.add(title)
                out.append({"market": market, "title": title, "publisher": pub or "", "time": str(when)})
    out.sort(key=lambda r: r["time"], reverse=True)
    return out[:cap]


def main():
    now = datetime.now(IST)
    watch = {t.strip().replace(".NS", "") for t in (ROOT / "watchlists" / "nifty200_plus_etfs.txt").read_text().splitlines() if t.strip() and not t.startswith("#")}
    OUT.mkdir(parents=True, exist_ok=True)
    m, e, n, rf = markets(), events(now.date(), watch), news(), results_filed(now, watch)
    (OUT / "results_filed.json").write_text(json.dumps(rf, indent=1))
    (OUT / "world_markets.json").write_text(json.dumps(m, indent=1))
    (OUT / "events_today.json").write_text(json.dumps(e, indent=1))
    (OUT / "world_news.json").write_text(json.dumps(n, indent=1))
    print(f"world: {sum(1 for r in m if r['last'] is not None)}/{len(m)} markets, {len(e)} events ({sum(1 for r in e if r['watchlist'] == 'yes')} on the watchlist), {len(n)} headlines, {len(rf)} results filed since the last close")


if __name__ == "__main__":
    main()
