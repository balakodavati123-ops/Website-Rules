"""Intraday paper desk for the always-on backend (GitHub Actions). No Claude, no browser.

Every run (about every 5 minutes in market hours) it reads 5-minute bars for the watchlist from Yahoo
Finance (NSE data is delayed by up to about 15 minutes), applies the live-session rules, and saves the
book to docs/data/live_book.json. The page in docs/ shows that file.

Rules (same as the dashboard's live session, minus options, which need a data source this backend
does not have): long a stock up 2%+ within 1% of its day high, short one down 2%+ within 1% of its day
low; Rs 10 crore traded, price Rs 20+, not up/down more than 9.5% (likely circuit-locked); a filing today
that points the other way cancels the trade ("price + news"); at most 4 trades; entries 09:20-15:10 IST;
stop 1%; all closed at 15:10. Paper only.

Usage: python backend/intraday.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "data"
IST = timezone(timedelta(hours=5, minutes=30))
C = dict(notional=8000.0, max_trades=4, move=2.0, stop=0.01, start=9 * 60 + 20, end=15 * 60 + 10, stock_cost=0.001, circuit=9.5)
NEG = {"MANAGEMENT CHANGE", "LEGAL/REGULATORY"}
POS = {"ORDER/CONTRACT", "APPROVAL", "ACQUISITION/STAKE", "BONUS/SPLIT/BUYBACK"}


def mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def close_trade(tr: dict, px: float, why: str):
    d = 1 if tr["side"] == "LONG" else -1
    pnl = d * (px - tr["entry"]) * tr["qty"] - C["stock_cost"] * tr["entry"] * tr["qty"]
    tr.update(exit=px, last=px, pnl_rs=round(pnl, 2), status="WIN" if pnl > 0 else "LOSS", why=why)


def step(book: dict, day: str, hhmm: str, rows: list[dict], news: dict) -> dict:
    """rows: [{symbol, price, chg_pct, day_high, day_low, volume}]; news: {symbol: 'positive'|'negative'}."""
    if book.get("day") != day:
        book.update(day=day, trades=[], seen={}, seq=0)
    t = mins(hhmm)
    by = {r["symbol"]: r for r in rows}
    for tr in book["trades"]:
        if tr["status"] != "OPEN":
            continue
        if tr["symbol"] in by:
            tr["last"] = by[tr["symbol"]]["price"]
        hit = tr["last"] <= tr["stop"] if tr["side"] == "LONG" else tr["last"] >= tr["stop"]
        if hit or t >= C["end"]:
            close_trade(tr, tr["last"], "stop" if hit else "time")
    if t < C["start"] or t >= C["end"]:
        return book
    for r in sorted(rows, key=lambda x: -abs(x["chg_pct"])):
        if len(book["trades"]) >= C["max_trades"]:
            break
        if book["seen"].get(r["symbol"]) or r["price"] < 20 or r["price"] * r["volume"] < 1e8 or abs(r["chg_pct"]) > C["circuit"]:
            continue
        up = r["chg_pct"] >= C["move"] and r["price"] >= 0.99 * r["day_high"]
        dn = r["chg_pct"] <= -C["move"] and r["price"] <= 1.01 * r["day_low"]
        if not (up or dn):
            continue
        n = news.get(r["symbol"], "")
        if (up and n == "negative") or (dn and n == "positive"):
            book["seen"][r["symbol"]] = "conflict"
            continue
        side = "LONG" if up else "SHORT"
        book["seen"][r["symbol"]] = side
        book["seq"] += 1
        p = r["price"]
        book["trades"].append({"id": book["seq"], "day": day, "time": hhmm, "kind": "stock", "symbol": r["symbol"], "side": side, "entry": p, "last": p,
                               "qty": int(C["notional"] // p), "stop": round(p * (1 - C["stop"] if up else 1 + C["stop"]), 2),
                               "basis": "price + news" if n else "price only", "label": f"{r['symbol']} {side.lower()}", "status": "OPEN", "pnl_rs": 0, "exit": "", "why": ""})
    return book


def watch_symbols() -> list[str]:
    f = ROOT / "watchlists" / "nifty200_plus_etfs.txt"
    return [t.strip() for t in f.read_text().splitlines() if t.strip() and not t.startswith("#")]


def bars_to_rows(data, ticks: list[str], now: datetime):
    """Latest-bar snapshot per stock from 5-minute bars. Returns (rows, day) or ([], None) when today has no bars yet."""
    rows, day = [], None
    for t in ticks:
        try:
            d = data[t].dropna(subset=["Close"])
        except KeyError:
            continue
        if len(d) < 3:
            continue
        idx = d.index.tz_convert(IST) if d.index.tz is not None else d.index.tz_localize(IST)
        d = d.set_axis(idx)
        last_day = idx[-1].date()
        if last_day != now.date() or (now - idx[-1].to_pydatetime()).total_seconds() > 40 * 60:
            continue                                       # not today, or the feed has gone stale
        today, prev = d[d.index.date == last_day], d[d.index.date < last_day]
        if prev.empty:
            continue
        price = float(today.Close.iloc[-1])
        rows.append({"symbol": t.replace(".NS", ""), "price": price, "chg_pct": (price / float(prev.Close.iloc[-1]) - 1) * 100,
                     "day_high": float(today.High.max()), "day_low": float(today.Low.min()), "volume": float(today.Volume.sum())})
        day = str(last_day)
    return rows, day


def filings_news() -> dict:
    """Today's NSE filings that lean one way, per symbol. An empty dict if NSE refuses the request."""
    try:
        sys.path.insert(0, str(ROOT))
        from trading_team.spike_watch import fetch_feed, trigger_of
        out = {}
        for a in fetch_feed(whole_day=True):
            lab = trigger_of({"desc": a["desc"], "text": a["text"]})
            if lab in NEG:
                out[a["symbol"]] = "negative"
            elif lab in POS:
                out.setdefault(a["symbol"], "positive")
        return out
    except Exception:
        return {}


def update_news_feed(now: datetime):
    """Headlines from the free RSS feeds that match a high-impact rule, newest 60, de-duplicated."""
    sys.path.insert(0, str(ROOT / "dashboard"))
    import news_watch as nw
    f = DOCS / "news_feed.json"
    feed = json.loads(f.read_text()) if f.exists() else []
    have = {re.sub(r"\W+", "", x["headline"].lower())[:90] for x in feed}
    for name, url in nw.FEEDS.items():
        for title in nw.items(nw.fetch(url)):
            key = re.sub(r"\W+", "", title.lower())[:90]
            c = nw.classify(title)
            if c and key not in have:
                have.add(key)
                feed.append({"time": now.strftime("%d %b %H:%M"), "source": name, "category": c[0], "headline": title[:160], "event": "yes" if c[0] in nw.MACRO else "no", "hint": c[1]})
    f.write_text(json.dumps(feed[-60:], indent=1))


def main():
    import yfinance as yf
    DOCS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(IST)
    status = {"updated_at": now.isoformat(timespec="seconds"), "updated_hm": now.strftime("%d %b %H:%M"), "state": "idle", "names": 0,
              "note": "NSE prices from Yahoo Finance, delayed by up to about 15 minutes."}
    try:
        update_news_feed(now)
    except Exception as e:
        print("news feed failed:", e)
    wd = now.weekday() < 5 and mins("09:10") <= mins(now.strftime("%H:%M")) <= mins("15:40")
    bf = DOCS / "live_book.json"
    book = json.loads(bf.read_text()) if bf.exists() else {"day": "", "trades": [], "seen": {}, "seq": 0}
    if wd:
        ticks = watch_symbols()
        data = yf.download(ticks, period="5d", interval="5m", group_by="ticker", auto_adjust=False, threads=True, progress=False)
        rows, day = bars_to_rows(data, ticks, now)
        status.update(names=len(rows), state="running" if rows else "no fresh prices")
        if rows:
            news = filings_news()
            step(book, day, now.strftime("%H:%M"), rows, news)
            status["filings_checked"] = "yes" if news is not None else "no"
    else:
        status["state"] = "market closed"
    bf.write_text(json.dumps(book, indent=1))
    (DOCS / "live_status.json").write_text(json.dumps(status, indent=1))
    print(status["state"], status["names"], "names;", len(book["trades"]), "trades today")


if __name__ == "__main__":
    main()
