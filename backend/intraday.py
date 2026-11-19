"""Intraday paper desk for the always-on backend (GitHub Actions). No Claude, no browser.

Every run (about every 5 minutes in market hours) it reads 5-minute bars for the watchlist from Yahoo
Finance (NSE data is delayed by up to about 15 minutes), applies the live-session rules, and saves the
book to docs/data/live_book.json. The page in docs/ shows that file.

The desk is a hunter: every few seconds it scans every liquid NSE stock for four setups (news-led, from today's
filings or from a headline that names the company; gap and go; momentum near the day's extreme; VWAP with order-book
pressure). How widely it hunts is set by the company's token economy (a hungry desk switches more setups on and may
take more trades); the stop-loss (just beyond VWAP, 0.6%-1.2%), the Rs 150 risk per trade, the 2R target, the stop
moved to entry after a 1R gain, and the 15:10 close never change. A filing or headline pointing the other way
cancels a trade. Intraday margin is counted at one fifth of the stock's value. Paper only.

Usage: python backend/intraday.py
"""
from __future__ import annotations

import json
import os
import time
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "data"
IST = timezone(timedelta(hours=5, minutes=30))
C = dict(start=9 * 60 + 20, end=15 * 60 + 10, last_entry=14 * 60 + 50, circuit=9.5, min_price=20.0, risk_rs=150.0, max_value=25000.0, leverage=5.0, max_open=4, rr=2.0,
         stop_min=0.6, stop_max=1.2, gap=1.5, pressure=1.5, stock_cost=0.001, notional=5000.0, move=2.0, news_move=0.6, max_trades=4)
# How hard the desk hunts, set each minute by the company's token economy (0 = fed and calm ... 3 = hungry and searching everywhere).
# Only the search widens: the stop-loss, the risk per trade and the closing time never change with hunger.
EFFORT = {0: dict(move=2.0, news_move=0.8, turnover=1e8, max_trades=5, setups=("news", "momentum")),
          1: dict(move=1.8, news_move=0.6, turnover=1e8, max_trades=7, setups=("news", "gap", "momentum")),
          2: dict(move=1.5, news_move=0.5, turnover=1e8, max_trades=9, setups=("news", "gap", "momentum", "vwap")),
          3: dict(move=1.5, news_move=0.5, turnover=5e7, max_trades=10, setups=("news", "gap", "momentum", "vwap"))}
NEG = {"MANAGEMENT CHANGE", "LEGAL/REGULATORY"}
POS = {"ORDER/CONTRACT", "APPROVAL", "ACQUISITION/STAKE", "BONUS/SPLIT/BUYBACK"}
SETUP_NAME = {"news": "News-led", "gap": "Gap and go", "momentum": "Momentum", "vwap": "VWAP pressure"}


def mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _cost(tr: dict, px: float) -> float:
    try:
        import gateway as G
        buy, sell = (tr["entry"], px) if tr["side"] == "LONG" else (px, tr["entry"])
        return G.charges(buy * tr["qty"], sell * tr["qty"])
    except Exception:
        return C["stock_cost"] * tr["entry"] * tr["qty"]


def close_trade(tr: dict, px: float, why: str):
    d = 1 if tr["side"] == "LONG" else -1
    pnl = d * (px - tr["entry"]) * tr["qty"] - _cost(tr, px)
    tr.update(exit=px, last=px, pnl_rs=round(pnl, 2), status="WIN" if pnl > 0 else "LOSS", why=why)


# ---------------------------------------------------------------- headlines -> stocks
WORD = re.compile(r"[a-z0-9&]+")
COMMON = {"india", "indian", "bank", "power", "energy", "finance", "financial", "industries", "the", "and", "of", "company", "corporation", "services", "technologies", "tech", "international",
          "global", "holdings", "enterprises", "infra", "capital", "life", "insurance", "steel", "motors", "pharma", "chemicals", "solar", "foods", "cement", "textiles", "systems", "ventures",
          "group", "new", "national", "state", "first", "gold", "silver", "oil", "gas", "market", "markets", "share", "shares", "stock", "stocks", "nifty", "sensex", "today", "price", "rate", "this",
          "fund", "funds", "auto", "metal", "metals", "realty", "media", "money", "best", "top", "high", "low", "news", "live", "deal", "order", "orders", "union", "central", "general", "united",
          "dollar", "rupee", "crude", "copper", "brent", "silver", "rally", "trade", "trading", "results", "profit", "sales", "budget", "policy", "global", "world", "data", "growth", "bonus", "buy",
          "sell", "target", "watch", "stake", "rating", "check", "bull", "bear", "inox", "wave", "royal", "prime", "star", "super", "smart", "ideal", "zenith", "titan", "jyoti"}
BASE = {"news": 40, "gap": 30, "momentum": 20, "vwap": 10}             # which setup a hunter trusts first: news, then a held gap, then momentum, then order-book pressure
UP = ("jump", "surge", "rall", "soar", "gain", "rise", "rose", "rocket", "win", "bag", "upgrade", "record high", "buyback", "acquisition", "acquire", "approval", "bonus", "zoom", "climb", "spurt")
DOWN = ("slip", "fall", "fell", "plunge", "crash", "slump", "drop", "tank", "downgrade", "loss", "probe", "raid", "penalty", "fraud", "resign", "sink", "skid", "decline", "cut", "weak")


def name_index(instruments: list[dict]) -> dict:
    """Ways a headline can name a listed company: its symbol, the first two words of its name, or a first word no other company shares."""
    rows = [(x["trading_symbol"], [w for w in WORD.findall(str(x.get("name") or "").lower()) if w not in ("limited", "ltd")]) for x in instruments
            if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"]
    first = {}
    for _, w in rows:
        if w:
            first[w[0]] = first.get(w[0], 0) + 1
    idx = {"pair": {}, "one": {}, "sym": {}}
    for sym, w in rows:
        if len(w) >= 2:
            idx["pair"].setdefault(" ".join(w[:2]), sym)
        if w and first[w[0]] == 1 and len(w[0]) >= 5 and w[0] not in COMMON:
            idx["one"][w[0]] = sym
        if len(sym) >= 4 and sym.lower() not in COMMON and sym.isalpha():
            idx["sym"][sym.lower()] = sym
    return idx


def tone(item: dict) -> str | None:
    hint, h = str(item.get("hint") or ""), str(item.get("headline") or "").lower()
    if hint.startswith("LONG"):
        return "positive"
    if hint.startswith("SHORT"):
        return "negative"
    up, dn = sum(w in h for w in UP), sum(w in h for w in DOWN)
    return "positive" if up > dn else "negative" if dn > up else None


def headline_names(feed: list[dict], idx: dict, now: datetime, hours: float = 3.0) -> dict:
    """{symbol: {tone, headline, time, source}} for today's headlines (last few hours) that name one listed company and lean one way."""
    out = {}
    for it in feed:
        try:
            t = datetime.strptime(f"{now.year} {it['time']}", "%Y %d %b %H:%M").replace(tzinfo=IST)
        except Exception:
            continue
        if t.date() != now.date() or (now - t).total_seconds() > hours * 3600:
            continue
        words = WORD.findall(str(it.get("headline") or "").lower())
        found = {idx["pair"][f"{a} {b}"] for a, b in zip(words, words[1:]) if f"{a} {b}" in idx["pair"]} | {idx["one"][w] for w in words if w in idx["one"]} | {idx["sym"][w] for w in words if w in idx["sym"]}
        tn = tone(it)
        if len(found) == 1 and tn:
            out[found.pop()] = {"tone": tn, "headline": it["headline"], "time": it["time"], "source": it.get("source")}
    return out


# ---------------------------------------------------------------- the hunt
def setups(r: dict, P: dict, filing: str, head: dict | None) -> list[tuple]:
    """Every setup this stock shows right now: (setup, side, strength, basis, reason)."""
    out, p, chg, hi, lo = [], r["price"], r["chg_pct"], r["day_high"], r["day_low"]
    vw, op, pc = r.get("vwap") or 0, r.get("open") or 0, r.get("prev_close") or 0
    news = filing or (head or {}).get("tone")
    src = "filing" if filing else "headline" if head else ""
    if "news" in P["setups"] and news:
        if news == "positive" and chg >= P["news_move"] and p >= 0.985 * hi:
            out.append(("news", "LONG", 3 + chg, "news-led" if filing else "headline-led", f"{'a positive filing today' if filing else 'headline: ' + head['headline'][:90]}; price {chg:+.1f}% near the day high"))
        if news == "negative" and chg <= -P["news_move"] and p <= 1.015 * lo:
            out.append(("news", "SHORT", 3 - chg, "news-led" if filing else "headline-led", f"{'a negative filing today' if filing else 'headline: ' + head['headline'][:90]}; price {chg:+.1f}% near the day low"))
    if "gap" in P["setups"] and op and pc and vw:
        g = (op / pc - 1) * 100
        if g >= C["gap"] and p >= op and p >= vw and p >= 0.99 * hi:
            out.append(("gap", "LONG", 2 + g, "gap-and-go", f"opened {g:+.1f}% higher and is holding above the open and VWAP, near the day high"))
        if g <= -C["gap"] and p <= op and p <= vw and p <= 1.01 * lo:
            out.append(("gap", "SHORT", 2 - g, "gap-and-go", f"opened {g:+.1f}% lower and is holding below the open and VWAP, near the day low"))
    if "momentum" in P["setups"]:
        if chg >= P["move"] and p >= 0.99 * hi:
            out.append(("momentum", "LONG", 1 + chg, "price + news" if news == "positive" else "price only", f"{chg:+.1f}% move near the day high" + (f", {src} agrees" if news == "positive" else "")))
        if chg <= -P["move"] and p <= 1.01 * lo:
            out.append(("momentum", "SHORT", 1 - chg, "price + news" if news == "negative" else "price only", f"{chg:+.1f}% move near the day low" + (f", {src} agrees" if news == "negative" else "")))
    if "vwap" in P["setups"] and vw and r.get("buy_qty") and r.get("sell_qty"):
        bs = r["buy_qty"] / r["sell_qty"]
        if p >= vw * 1.003 and chg >= 1.0 and bs >= C["pressure"] and p >= 0.99 * hi:
            out.append(("vwap", "LONG", bs + chg, "vwap-pressure", f"above VWAP ({vw:,.2f}), {chg:+.1f}% on the day, buyers queue {bs:.1f} times the sellers"))
        if p <= vw * 0.997 and chg <= -1.0 and 1 / bs >= C["pressure"] and p <= 1.01 * lo:
            out.append(("vwap", "SHORT", 1 / bs - chg, "vwap-pressure", f"below VWAP ({vw:,.2f}), {chg:+.1f}% on the day, sellers queue {1 / bs:.1f} times the buyers"))
    return [(k, sd, BASE[k] + min(9.9, st_), b, w) for k, sd, st_, b, w in out]


def agrees(side: str, news: str) -> bool:
    return not ((side == "LONG" and news == "negative") or (side == "SHORT" and news == "positive"))


def step(book: dict, day: str, hhmm: str, rows: list[dict], news: dict, room=None, effort: int = 1, headlines: dict | None = None) -> dict:
    """rows: [{symbol, price, chg_pct, day_high, day_low, volume, open, prev_close, vwap, buy_qty, sell_qty}]; news: {symbol: 'positive'|'negative'} from filings;
    headlines: {symbol: {tone, headline, ...}}. Manages open trades (stop, a stop moved to entry after a 1R gain, a 2R target, 15:10), then hunts."""
    if book.get("day") != day:
        book.update(day=day, trades=[], seen={}, seq=0)
    t = mins(hhmm)
    P = EFFORT[max(0, min(3, int(effort)))]
    by = {r["symbol"]: r for r in rows}
    for tr in book["trades"]:
        if tr["status"] != "OPEN":
            continue
        if tr["symbol"] in by:
            tr["last"] = by[tr["symbol"]]["price"]
        d = 1 if tr["side"] == "LONG" else -1
        if tr.get("target") and not tr.get("protected") and d * (tr["last"] - tr["entry"]) >= abs(tr["entry"] - tr["stop"]):
            tr.update(stop=tr["entry"], protected=True)              # one risk-unit in profit: the stop moves to the entry, the trade can no longer lose
        hit = tr["last"] <= tr["stop"] if d == 1 else tr["last"] >= tr["stop"]
        tgt = tr.get("target") and (tr["last"] >= tr["target"] if d == 1 else tr["last"] <= tr["target"])
        if hit or tgt or t >= C["end"]:
            close_trade(tr, tr["last"], ("breakeven stop" if tr.get("protected") else "stop") if hit else "target" if tgt else "time")
            tr["closed"] = hhmm
    found = {k: [] for k in EFFORT[3]["setups"]}
    diag = {"at": hhmm, "effort": int(effort), "setups_on": list(P["setups"]), "scanned": 0, "found": found, "taken": [], "skipped": {}, "news_names": len(news), "headline_names": len(headlines or {})}
    book["diag"] = diag
    if t < C["start"] or t > C["last_entry"]:
        return book
    cands = []
    for r in rows:
        if r["price"] < C["min_price"] or r["price"] * r["volume"] < P["turnover"] or abs(r["chg_pct"]) > C["circuit"]:
            continue
        diag["scanned"] += 1
        nw = news.get(r["symbol"], "") or ((headlines or {}).get(r["symbol"]) or {}).get("tone", "")
        raw = setups(r, P, news.get(r["symbol"], ""), (headlines or {}).get(r["symbol"]))
        ok = [x for x in raw if agrees(x[1], nw)]
        if raw and not ok:
            book["seen"][r["symbol"]] = "conflict"                 # the news points the other way: no trade
        for s in ok:
            found[s[0]].append(r["symbol"])
            cands.append((s, r))
    for k in found:
        found[k] = found[k][:8]
    opn = sum(x["status"] == "OPEN" for x in book["trades"])
    for (setup, side, strength, basis, why), r in sorted(cands, key=lambda c: -c[0][2]):
        sym = r["symbol"]
        if book["seen"].get(sym):
            continue
        if len(book["trades"]) >= P["max_trades"] or opn >= C["max_open"]:
            diag["skipped"][sym] = "the day's trade limit is reached" if len(book["trades"]) >= P["max_trades"] else f"{C['max_open']} positions already open"
            break
        p, vw, long_ = r["price"], r.get("vwap") or 0, side == "LONG"
        sp = ((p - vw) / p * 100 + 0.15) if (vw and long_ and vw < p) else ((vw - p) / p * 100 + 0.15) if (vw and not long_ and vw > p) else 1.0
        sp = min(C["stop_max"], max(C["stop_min"], sp))                # stop just beyond VWAP, between 0.6% and 1.2%
        dist = p * sp / 100
        qty = min(int(C["risk_rs"] // dist), int(C["max_value"] // p))
        margin = qty * p / C["leverage"]
        if qty < 1:
            continue
        if room is not None and margin > room[0]:
            diag["skipped"][sym] = "no intraday margin left"
            break
        if room is not None:
            room[0] -= margin
        book["seen"][sym] = side
        book["seq"] += 1
        opn += 1
        stop = round(p - dist if long_ else p + dist, 2)
        target = round(p + C["rr"] * dist if long_ else p - C["rr"] * dist, 2)
        book["trades"].append({"id": book["seq"], "day": day, "time": hhmm, "kind": "stock", "symbol": sym, "side": side, "entry": p, "last": p, "qty": qty, "stop": stop, "target": target,
                               "leverage": C["leverage"], "margin": round(margin), "setup": setup, "basis": basis, "effort": int(effort),
                               "reason": f"{SETUP_NAME[setup]}: {why}. Stop {stop:,.2f} ({sp:.2f}%), target {target:,.2f} (2R), stop moves to entry after a 1R gain, out by 15:10.",
                               "label": f"{sym} {side.lower()}", "status": "OPEN", "pnl_rs": 0, "exit": "", "why": ""})
        diag["taken"].append(sym)
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


def upstox_rows(token: str) -> list[dict]:
    """Real-time snapshot of every NSE equity from Upstox's read-only market-data API (500 names per call)."""
    import gzip, urllib.parse, urllib.request
    hdr = {"Accept": "application/json", "User-Agent": "paper-desk/1.0"}
    if token != "proxy-injected":      # in this sandbox the network proxy adds the real header itself
        hdr["Authorization"] = f"Bearer {token}"
    raw = urllib.request.urlopen("https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz", timeout=60).read()
    keys = [x["instrument_key"] for x in json.loads(gzip.decompress(raw)) if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"]
    rows = []
    for i in range(0, len(keys), 500):
        q = urllib.parse.quote(",".join(keys[i:i + 500]), safe=",")
        req = urllib.request.Request("https://api.upstox.com/v2/market-quote/quotes?instrument_key=" + q, headers=hdr)
        data = json.loads(urllib.request.urlopen(req, timeout=60).read()).get("data", {})
        for v in data.values():
            last, net, oh = v.get("last_price"), v.get("net_change"), v.get("ohlc") or {}
            if not last or net is None or not v.get("volume"):
                continue
            prev = last - net
            if prev <= 0:
                continue
            rows.append({"symbol": v["symbol"], "price": float(last), "chg_pct": net / prev * 100, "day_high": float(oh.get("high") or last),
                         "day_low": float(oh.get("low") or last), "volume": float(v["volume"])})
    return rows


def main():
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
        token = os.environ.get("UPSTOX_TOKEN", "").strip()
        end = time.time() + (int(os.environ.get("LOOP_SECONDS", "0")) if token else 0)
        news = filings_news()
        while True:
            now = datetime.now(IST)
            if token:
                rows, day = upstox_rows(token), now.strftime("%Y-%m-%d")
                status["note"] = "All NSE equities from the Upstox market-data API, real time, polled every 30 seconds."
            else:
                import yfinance as yf
                ticks = watch_symbols()
                data = yf.download(ticks, period="5d", interval="5m", group_by="ticker", auto_adjust=False, threads=True, progress=False)
                rows, day = bars_to_rows(data, ticks, now)
            status.update(names=len(rows), state="running" if rows else "no fresh prices", updated_at=now.isoformat(timespec="seconds"), updated_hm=now.strftime("%d %b %H:%M:%S"))
            if rows:
                step(book, day, now.strftime("%H:%M"), rows, news)
                status["filings_checked"] = "yes" if news is not None else "no"
                bf.write_text(json.dumps(book, indent=1))
            if time.time() + 30 >= end or mins(now.strftime("%H:%M")) > mins("15:40"):
                break
            time.sleep(30)
    else:
        status["state"] = "market closed"
    bf.write_text(json.dumps(book, indent=1))
    (DOCS / "live_status.json").write_text(json.dumps(status, indent=1))
    print(status["state"], status["names"], "names;", len(book["trades"]), "trades today")


if __name__ == "__main__":
    main()
