"""What is moving NIFTY 50 and Sensex right now, rebuilt every minute all day, and the desk's live all-factor call.

What it watches
  World      the rupee (USD/INR), Brent and WTI crude, the US dollar index, S&P 500 and Nasdaq futures, Nikkei, Hang Seng, Shanghai,
             Euro Stoxx, gold, the US 10-year yield and US VIX (Yahoo Finance, 15-minute bars, fetched about every two minutes).
  India      NIFTY, Sensex, Bank Nifty and India VIX (Upstox, real time); breadth of the NIFTY 50 stocks; the heavyweights' share of the
             move; sector baskets that react to crude, the rupee and rates (oil marketers, IT, banks, ...).
  News       today's headlines grouped into themes: crude, the rupee, RBI and rates, the Fed and US markets, war and sanctions, fund flows.

Measured, not guessed (quant/run_macro_research.py and quant/run_macro_intraday.py, results in docs/models/):
  * Each world factor's weight is how much NIFTY moved per 1% move in it on the same day, Jan 2022 - Nov 2026 (888 days, all factors
    fitted together). Together they explain about a fifth of NIFTY's daily moves (R squared 0.20): most of a day's move is India's own
    news and money flows, which is why the page also shows breadth, sectors and headlines.
  * Implied move = the sum of (weight x the factor's move since NIFTY's last close).
  * Live call, 09:15 - 15:30: the implied move and NIFTY's own move so far. When both point the same way the call is that way; tested
    on 481 days it was right about the rest of the day 50% (at 10:15) to 58% (at 12:15) of the time. When they disagree: no call.
  * Before the open: the pre-open model (last night's US close and US VIX, yesterday's crude, rupee, dollar and yields), fitted on
    2022-2024 and tested on 2025-2026: right on the day's close-to-close direction 54.7% of the time, 61.3% when it expected 0.3%+.
These are small edges, and the page prints the measured rate next to every call. Nothing here places an order.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "docs" / "models"

# key, Yahoo symbol, name, the measured weight it carries (None: watched, not weighted), why it matters to India
FACTORS = [
    ("usdinr", "INR=X", "Dollar in rupees", "usdinr", "A weaker rupee drives foreign investors out and makes oil imports dearer"),
    ("brent", "BZ=F", "Brent crude", "brent", "India imports most of its oil: dearer crude widens the trade gap and lifts inflation"),
    ("dxy", "DX-Y.NYB", "US dollar index", "dxy", "A strong dollar pulls money out of emerging markets like India"),
    ("es", "ES=F", "S&P 500 futures", "spx_overnight", "Wall Street's mood, live through the Indian day"),
    ("n225", "^N225", "Nikkei 225", "n225", "Asia's biggest market, open before and during India's morning"),
    ("hsi", "^HSI", "Hang Seng", "hsi", "Asia and China risk mood"),
    ("wti", "CL=F", "WTI crude", None, "US crude: confirms or questions Brent's move"),
    ("gold", "GC=F", "Gold", None, "Rises when investors run for safety"),
    ("us10y", "^TNX", "US 10-year yield", None, "Higher US yields pull money toward US bonds"),
    ("nq", "NQ=F", "Nasdaq futures", None, "Leads Indian IT stocks"),
    ("vix_us", "^VIX", "US fear index (VIX)", None, "Rising means investors worldwide are nervous"),
    ("sse", "000001.SS", "Shanghai", None, "China demand: metals and commodities"),
    ("stoxx", "^STOXX50E", "Euro Stoxx 50", None, "Europe, open from about 13:30 IST"),
]
INDEX = {"nifty": "^NSEI", "sensex": "^BSESN"}                         # Yahoo copies: the session dates, and a fallback for the levels
SHOCK_OF = {"usdinr": "usdinr", "brent": "brent", "dxy": "dxy", "es": "spx_overnight", "n225": "n225", "hsi": "hsi", "gold": "gold",
            "us10y": "us10y", "nq": "ndx_overnight", "vix_us": "vix_overnight"}
PRE = {"spx_lastnight": "^GSPC", "ndx_lastnight": "^IXIC", "vix_lastnight": "^VIX", "brent_yday": "BZ=F", "usdinr_yday": "INR=X",
       "dxy_yday": "DX-Y.NYB", "us10y_yday": "^TNX"}
PRE_NAME = {"spx_lastnight": "S&P 500 last night", "ndx_lastnight": "Nasdaq last night", "vix_lastnight": "US VIX last night",
            "brent_yday": "Brent crude yesterday", "usdinr_yday": "Dollar in rupees yesterday", "dxy_yday": "US dollar index yesterday",
            "us10y_yday": "US 10-year yield yesterday"}
NIFTY50 = ["ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
           "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO", "HINDUNILVR",
           "ICICIBANK", "INDIGO", "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC",
           "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TMPV", "TATAMOTORS", "TATASTEEL",
           "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"]
# approximate NIFTY 50 weights in % (NSE factsheet, late 2025), only to size each heavyweight's share of the move in points
HEAVY = {"HDFCBANK": 13.0, "ICICIBANK": 8.8, "RELIANCE": 8.3, "INFY": 4.9, "BHARTIARTL": 4.7, "LT": 3.9, "ITC": 3.5, "SBIN": 3.2,
         "AXISBANK": 3.0, "TCS": 2.9, "KOTAKBANK": 2.7, "M&M": 2.6, "BAJFINANCE": 2.3, "HINDUNILVR": 1.9, "MARUTI": 1.8, "ETERNAL": 1.7,
         "SUNPHARMA": 1.6, "HCLTECH": 1.4, "NTPC": 1.3, "TITAN": 1.3}
NAMES = {"HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank", "RELIANCE": "Reliance", "INFY": "Infosys", "BHARTIARTL": "Bharti Airtel",
         "LT": "L&T", "ITC": "ITC", "SBIN": "SBI", "AXISBANK": "Axis Bank", "TCS": "TCS", "KOTAKBANK": "Kotak Bank", "M&M": "M&M",
         "BAJFINANCE": "Bajaj Finance", "HINDUNILVR": "HUL", "MARUTI": "Maruti", "ETERNAL": "Eternal", "SUNPHARMA": "Sun Pharma",
         "HCLTECH": "HCL Tech", "NTPC": "NTPC", "TITAN": "Titan"}
SECTORS = [
    ("Oil marketers", ["BPCL", "HINDPETRO", "IOC"], "hurt by dearer crude"),
    ("Oil producers", ["ONGC", "OIL"], "helped by dearer crude"),
    ("Paints and airlines", ["ASIANPAINT", "BERGEPAINT", "INDIGO"], "crude is a big cost for them"),
    ("IT services", ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"], "earn in dollars: a weaker rupee helps"),
    ("Big banks", ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"], "about a third of NIFTY; hurt by rate-hike fears and foreign selling"),
    ("Autos", ["MARUTI", "M&M", "BAJAJ-AUTO", "EICHERMOT", "TMPV", "TATAMOTORS"], "fuel prices and loan rates"),
    ("Metals", ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL"], "China demand and the dollar"),
    ("Consumer staples", ["HINDUNILVR", "ITC", "NESTLEIND", "TATACONSUM"], "defensive: often hold up on bad days"),
    ("Pharma", ["SUNPHARMA", "CIPLA", "DRREDDY"], "defensive, and earn in dollars"),
]
THEMES = [
    ("crude", "crude oil", r"\b(crude|oil prices?|brent|opec\+?|wti|refinery|refineries)\b"),
    ("rupee", "the rupee and the dollar", r"\b(rupee|forex|usd/inr|dollar)s?\b"),
    ("rates", "RBI, rates and inflation", r"\b(rbi|repo rate|rate hikes?|rate cuts?|yields?|bonds?|inflation|cpi|wpi|crr)\b"),
    ("us", "the US markets and the Fed", r"\b(fed|powell|fomc|us treasury|us treasuries|us yields?|us bonds?|wall street|nasdaq|dow jones|s&p 500)\b"),
    ("geo", "war, attacks, sanctions and tariffs", r"\b(wars?|attacks?|attacked|missiles?|houthis?|iran|israel|russia|ukraine|sanctions?|tariffs?|conflict)\b"),
    ("flows", "foreign and domestic fund flows", r"\b(fiis?|fpis?|foreign investors?|foreign funds?|diis?|outflows?|inflows?)\b"),
    ("economy", "India's economy and policy", r"\b(gdp|union budget|gst|fiscal deficit|trade deficit|current account|iip|pmi)\b"),
]
CUTS = ("10:15", "11:15", "12:15", "13:15")
LIVE24 = {"usdinr", "brent", "wti", "dxy", "es", "nq", "gold"}        # trade nearly round the clock: no fresh price for 2 hours means a feed gap
MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def load_models(root: Path = MODELS) -> tuple[dict, dict]:
    out = []
    for f in ("macro_model.json", "macro_intraday.json"):
        try:
            out.append(json.loads((root / f).read_text()))
        except Exception:
            out.append({})
    return out[0], out[1]


def _http(url: str) -> dict:
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read())


def _chart(sym: str, rng: str, interval: str, get=_http) -> dict | None:
    try:
        r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={interval}")["chart"]["result"][0]
    except Exception:
        return None
    q = (r.get("indicators") or {}).get("quote") or [{}]
    bars = [(int(t), float(c)) for t, c in zip(r.get("timestamp") or [], q[0].get("close") or []) if c is not None]
    m = r.get("meta") or {}
    if m.get("regularMarketPrice") and m.get("regularMarketTime") and (not bars or m["regularMarketTime"] > bars[-1][0]):
        bars.append((int(m["regularMarketTime"]), float(m["regularMarketPrice"])))
    return {"bars": bars, "gmtoffset": int(m.get("gmtoffset") or 0)} if bars else None


def fetch_world(get=_http) -> dict:
    """15-minute bars over five days for every factor and the two indexes (about 15 small requests, in parallel)."""
    want = {k: s for k, s, *_ in FACTORS} | INDEX
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(want, ex.map(lambda s: _chart(s, "5d", "15m", get), want.values())))
    return {"at": datetime.now(IST).timestamp(), "series": {k: v for k, v in res.items() if v}}


def fetch_daily(get=_http) -> dict:
    """Daily closes for the pre-open model (a month), and two years of USD/INR for the rupee's record."""
    syms = sorted(set(PRE.values()))
    with ThreadPoolExecutor(7) as ex:
        res = dict(zip(syms, ex.map(lambda s: _chart(s, "2y" if s == "INR=X" else "1mo", "1d", get), syms)))
    out = {}
    for s, v in res.items():
        if v:
            tz = timezone(timedelta(seconds=v["gmtoffset"]))
            out[s] = {datetime.fromtimestamp(t, tz).date().isoformat(): c for t, c in v["bars"]}
    return {"at": datetime.now(IST).timestamp(), "closes": out}


def px_at(bars: list, ts: float) -> float | None:
    lo, hi = 0, len(bars)
    while lo < hi:
        md = (lo + hi) // 2
        if bars[md][0] <= ts:
            lo = md + 1
        else:
            hi = md
    return bars[lo - 1][1] if lo else None


def ref_close(now: datetime, nifty_bars: list | None) -> tuple[date, float]:
    """NIFTY's last completed session: its date and 15:30 IST as a timestamp (today's after 15:30, else the previous session's)."""
    today = now.date()
    days = sorted({datetime.fromtimestamp(t, IST).date() for t, _ in (nifty_bars or [])})
    done = [d for d in days if d < today or (d == today and now.strftime("%H:%M") >= "15:30")]
    if done:
        d = done[-1]
    else:
        d = today - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d, datetime(d.year, d.month, d.day, 15, 30, tzinfo=IST).timestamp()


def _pct(a, b) -> float | None:
    return (b / a - 1) * 100 if a and b else None


def _session(now: datetime) -> str:
    t = now.strftime("%H:%M")
    if now.weekday() >= 5:
        return "closed"
    return "pre-open" if t < "09:15" else "open" if t < "15:30" else "closed"


def _cut(hhmm: str) -> str:
    c = [x for x in CUTS if x <= hhmm]
    return c[-1] if c else CUTS[0]


def _move_text(key: str, name: str, chg: float, last: float) -> str:
    if key == "usdinr":
        return f"The rupee is {abs(chg):.2f}% {'weaker' if chg > 0 else 'stronger'} ({last:.2f} per dollar)"
    if key == "us10y":
        return f"The US 10-year yield is {'up' if chg > 0 else 'down'} {abs(chg):.1f}% (now {last:.2f}%)"
    return f"{name} is {'up' if chg > 0 else 'down'} {abs(chg):.1f}%" + (f" (${last:,.2f} a barrel)" if key in ("brent", "wti") else "")


def _today_news(news: list, now: datetime) -> list[dict]:
    out = []
    for n in news or []:
        m = re.match(r"\s*(\d{1,2})\s+([A-Za-z]{3})", str(n.get("time") or ""))
        if m and int(m.group(1)) == now.day and MON.get(m.group(2).lower()) == now.month:
            out.append(n)
    return out


def themes(news: list, now: datetime) -> list[dict]:
    rows = _today_news(news, now)
    out = []
    for key, label, rx in THEMES:
        hit = [n for n in rows if re.search(rx, str(n.get("headline") or ""), re.I)]
        if not hit:
            continue
        neg = sum(1 for n in hit if re.search(r"CRASH|SHOCK", str(n.get("category") or ""), re.I) or "SHORT" in str(n.get("hint") or "").upper())
        pos = sum(1 for n in hit if "LONG" in str(n.get("hint") or "").upper())
        last = hit[-1]
        out.append({"key": key, "label": label, "count": len(hit), "neg": neg, "pos": pos,
                    "latest": {"headline": str(last.get("headline") or "")[:200], "source": last.get("source"), "time": last.get("time")}})
    return sorted(out, key=lambda x: -x["count"])


def news_tone(news: list, now: datetime) -> dict:
    """Today's headlines on the market-moving themes, each counted once: how many read as bad and how many as good for the market."""
    seen, neg, pos, hits = set(), 0, 0, []
    for n in _today_news(news, now):
        h = str(n.get("headline") or "")
        k = h[:60].lower()
        if k in seen or not any(re.search(rx, h, re.I) for _, _, rx in THEMES):
            continue
        seen.add(k)
        bad = bool(re.search(r"CRASH|SHOCK", str(n.get("category") or ""), re.I) or "SHORT" in str(n.get("hint") or "").upper())
        good = "LONG" in str(n.get("hint") or "").upper()
        neg, pos = neg + bad, pos + good
        hits.append(h)
    return {"headlines": len(seen), "bad": neg, "good": pos}


def india_view(qs: dict, nifty_prev: float | None) -> dict:
    """qs: {symbol: [price, change %, ...]} for every NSE stock (the engine's real-time snapshot)."""
    seen = [s for s in NIFTY50 if s in qs]
    up = sum(1 for s in seen if qs[s][1] > 0.05)
    dn = sum(1 for s in seen if qs[s][1] < -0.05)
    heavy = []
    for s, w in HEAVY.items():
        if s in qs:
            c = float(qs[s][1])
            heavy.append({"symbol": s, "name": NAMES.get(s, s), "chg_pct": round(c, 2), "weight": w,
                          "pts": round(w / 100 * c / 100 * nifty_prev, 1) if nifty_prev else None})
    sec = []
    for name, syms, why in SECTORS:
        xs = [float(qs[s][1]) for s in syms if s in qs]
        if xs:
            sec.append({"name": name, "chg_pct": round(sum(xs) / len(xs), 2), "n": len(xs), "of": [s for s in syms if s in qs], "why": why})
    return {"breadth": {"up": up, "down": dn, "flat": len(seen) - up - dn, "seen": len(seen)},
            "heavy": sorted(heavy, key=lambda x: -abs(x["pts"] or 0)), "sectors": sec}


def pre_open(daily: dict, model: dict, today: date) -> dict | None:
    """The pre-open model's read for today from last night's US close and yesterday's crude, rupee, dollar and yields."""
    po = (model or {}).get("pre_open") or {}
    b = po.get("factors") or {}
    cl = (daily or {}).get("closes") or {}
    if not b:
        return None
    x, rows = {}, []
    for k, sym in PRE.items():
        s = cl.get(sym) or {}
        ks = sorted(d for d in s if d < today.isoformat())
        if len(ks) < 2:
            return None
        x[k] = _pct(s[ks[-2]], s[ks[-1]])
        if x[k] is None:
            return None
        rows.append({"key": k, "name": PRE_NAME[k], "chg_pct": round(x[k], 2), "day": ks[-1], "effect_pct": round(b.get(k, 0) * x[k], 3)})
    pred = float(po.get("intercept") or 0) + sum(b.get(k, 0) * v for k, v in x.items())
    te = po.get("test") or {}
    strong = abs(pred) >= 0.3
    return {"pct": round(pred, 2), "direction": "UP" if pred > 0 else "DOWN" if pred < 0 else "SIDEWAYS", "strong": strong,
            "hit": te.get("strong_close_to_close_hit") if strong else te.get("close_to_close_hit"), "tested_days": te.get("strong_days") if strong else te.get("days"),
            "open_to_close_hit": te.get("open_to_close_hit"), "inputs": sorted(rows, key=lambda r: -abs(r["effect_pct"]))}


def live_call(hhmm: str, implied: float | None, sofar: float | None, intr: dict) -> dict:
    """Rest-of-day call from the implied move and NIFTY's own move, with the measured hit rate at the nearest tested time."""
    cut = _cut(hhmm)
    r = (intr or {}).get(cut) or {}
    mk = implied is not None and abs(implied) >= 0.2
    nk = sofar is not None and abs(sofar) >= 0.3
    sgn = lambda v: 1 if v > 0 else -1
    if mk and nk and sgn(implied) == sgn(sofar):
        d, hit, n = sgn(implied), r.get("agree_hit"), r.get("agree_days")
        basis = "World markets and NIFTY's own move point the same way"
    elif mk and nk:
        d, hit, n = 0, r.get("disagree_macro_hit"), r.get("disagree_days")
        basis = "World markets point one way and NIFTY is moving the other: no edge either way in the tests"
    elif implied is not None and abs(implied) >= 0.3:
        d, hit, n = sgn(implied), r.get("macro_strong_hit"), r.get("macro_strong_days")
        basis = "World markets point this way; NIFTY has not moved much yet"
    elif nk:
        d, hit, n = sgn(sofar), r.get("momentum_hit"), r.get("days")
        basis = "NIFTY's own move so far; world markets are roughly neutral"
    else:
        d, hit, n = 0, None, None
        basis = "Neither world markets nor NIFTY's own move are strong enough to call"
    dirn = {1: "UP", -1: "DOWN", 0: "SIDEWAYS"}[d]
    head = {"UP": "More likely to rise than fall for the rest of today", "DOWN": "More likely to fall than rise for the rest of today",
            "SIDEWAYS": "No clear direction for the rest of today"}[dirn]
    meas = (f"In tests on {n} similar days (at {cut}), this was right {hit:.0f} times in 100." if hit is not None and n and d else
            f"In tests on {n} days like this (at {cut}), siding with world markets was right {hit:.0f} times in 100"
            + (": too few days to rely on." if n < 50 else ": no better than a coin toss.") if hit is not None and n else
            "No tested edge right now.")
    return {"direction": dirn, "headline": head, "basis": basis, "hit": hit, "tested_days": n, "cut": cut, "measured": meas, "horizon": "rest of today",
            "confidence": None if not d or hit is None else "fair" if hit >= 60 else "moderate" if hit >= 57 else "low"}


def window_implied(ser: dict, fb: dict, t0: float, t1: float) -> float | None:
    """The implied NIFTY move (%) from the weighted factors' moves between two times."""
    tot, ok = 0.0, False
    for key, _, _, beta_key, _ in FACTORS:
        s, beta = ser.get(key), (fb.get(beta_key) or {}).get("beta") if beta_key else None
        if not s or beta is None:
            continue
        c = _pct(px_at(s["bars"], t0), px_at(s["bars"], t1))
        if c is not None:
            tot, ok = tot + beta * c, True
    return round(tot, 3) if ok else None


def build(now: datetime, world: dict, daily: dict | None, india: dict | None, news: list | None, model: dict, intr: dict,
          state: dict | None = None) -> dict:
    """world: fetch_world(). daily: fetch_daily(). india: {nifty|sensex|banknifty|vix: {last, prev, open}, qs: {symbol: [price, chg%...]}}.
    news: the engine's news_feed.json rows. state: {usdinr_max, alerts: {key: at}} kept between calls (alerts are added to it)."""
    india, state = india or {}, state if state is not None else {}
    ser = (world or {}).get("series") or {}
    rday, rts = ref_close(now, (ser.get("nifty") or {}).get("bars"))
    if india.get("day") and india["day"] < (now.date().isoformat() if _session(now) == "open" else rday.isoformat()):
        india = {k: v for k, v in india.items() if k == "mcx_crude" and _session(now) != "open"}     # an old session's snapshot is not today's
    sess = _session(now)
    sd = (model or {}).get("same_day") or {}
    fb, sb = sd.get("factors") or {}, sd.get("sensex_betas") or {}
    shocks = (model or {}).get("shocks") or {}

    def idx(name: str) -> dict:
        u = india.get(name) or {}
        y = (ser.get(name) or {}).get("bars") or []
        last, prev = u.get("last"), u.get("prev")
        src = "Upstox, real time" if last and prev else None
        if not (last and prev) and y:
            daily_: dict = {}
            for t, c in y:
                daily_[datetime.fromtimestamp(t, IST).date()] = c       # the last 15-minute close of each session
            ds = sorted(daily_)
            cur = [d for d in ds if d <= (now.date() if sess == "open" else rday)]
            if len(cur) >= 2:
                last, prev, src = daily_[cur[-1]], daily_[cur[-2]], "Yahoo Finance (delayed)"
        c = _pct(prev, last)
        return {"last": round(last, 2) if last else None, "prev": round(prev, 2) if prev else None, "chg_pct": round(c, 2) if c is not None else None,
                "chg_pts": round(last - prev, 1) if last and prev else None, "source": src}
    nifty, sensex = idx("nifty"), idx("sensex")
    nprev, sprev = nifty.get("prev") or nifty.get("last"), sensex.get("prev") or sensex.get("last")

    rows, imp, simp, missing = [], 0.0, 0.0, []
    for key, sym, name, beta_key, why in FACTORS:
        s = ser.get(key)
        if not s:
            rows.append({"key": key, "name": name, "symbol": sym, "last": None, "chg_pct": None, "weighted": bool(beta_key), "why": why})
            if beta_key:
                missing.append(name)
            continue
        bars = s["bars"]
        last, last_t = bars[-1][1], bars[-1][0]
        ref = px_at(bars, rts) or bars[0][1]
        chg = _pct(ref, last) if last_t > rts else 0.0
        note = "no trade since NIFTY's close" if last_t <= rts else None
        stale = key in LIVE24 and sess == "open" and now.timestamp() - last_t > 2 * 3600
        via = None
        if stale:
            note = f"no fresh price since {datetime.fromtimestamp(last_t, IST).strftime('%d %b %H:%M')}"
            mc, ui = india.get("mcx_crude") or {}, ser.get("usdinr")
            if key == "brent" and mc.get("last") and mc.get("prev") and ui:              # crude in rupees on MCX, converted to dollars
                u_chg = _pct(px_at(ui["bars"], rts) or ui["bars"][0][1], ui["bars"][-1][1]) or 0.0
                chg = ((1 + _pct(mc["prev"], mc["last"]) / 100) / (1 + u_chg / 100) - 1) * 100
                via, note = "MCX", "live from MCX crude (Upstox), converted to dollars; Yahoo's Brent is not updating"
        beta = (fb.get(beta_key) or {}).get("beta") if beta_key else None
        eff = beta * chg if beta is not None and chg is not None else None
        if eff is not None:
            imp += eff
            simp += (sb.get(beta_key) or 0) * chg
        rows.append({"key": key, "name": name, "symbol": sym, "last": round(last, 4 if key == "usdinr" else 2), "chg_pct": round(chg, 2) if chg is not None else None,
                     "as_of": datetime.fromtimestamp(last_t, IST).strftime("%d %b %H:%M"), "weighted": bool(beta_key), "beta": beta,
                     "effect_pct": round(eff, 3) if eff is not None else None, "effect_pts": round(eff / 100 * nprev, 1) if eff is not None and nprev else None,
                     "why": why, "note": note, "stale": stale and not via, "via": via})
        if stale and not via and beta_key:
            missing.append(name + " (not updating)")
    mc = india.get("mcx_crude") or {}
    if mc.get("last") and mc.get("prev"):
        c_ = _pct(mc["prev"], mc["last"])
        rows.append({"key": "mcx_crude", "name": "MCX crude (rupees)", "symbol": mc.get("symbol"), "last": round(mc["last"], 1), "chg_pct": round(c_, 2) if c_ is not None else None,
                     "as_of": now.strftime("%d %b %H:%M"), "weighted": False, "why": "Crude traded in India, live all day (Upstox); includes the rupee's move",
                     "note": "change since MCX's previous close (23:30)", "stale": False})
    have_w = any(r["weighted"] and r.get("chg_pct") is not None for r in rows)
    implied = round(imp, 3) if have_w else None
    by_key = {r["key"]: r for r in rows}

    big = []
    for r in rows:
        sk = SHOCK_OF.get(r["key"])
        sh = shocks.get(sk) if sk else None
        if not sh or r.get("chg_pct") is None or abs(r["chg_pct"]) < sh["threshold_pct"]:
            continue
        side = sh["up" if r["chg_pct"] > 0 else "down"]
        if side.get("days"):
            big.append({"key": r["key"], "text": f"{_move_text(r['key'], r['name'], r['chg_pct'], r['last'])} since NIFTY's last close. On the {side['days']} days since 2022 "
                        f"when it {'rose' if r['chg_pct'] > 0 else 'fell'} {sh['threshold_pct']:g}% or more, NIFTY fell on {side['nifty_fell_pct']:.0f}% of them "
                        f"(average move {side['nifty_avg_pct']:+.2f}%).", "nifty_fell_pct": side["nifty_fell_pct"], "days": side["days"]})
    rec = None
    u = by_key.get("usdinr") or {}
    if u.get("last"):
        hist = ((daily or {}).get("closes") or {}).get("INR=X") or {}
        prior = [v for d, v in hist.items() if d < now.date().isoformat()]
        mx = max(prior) if prior else ((model or {}).get("usdinr_record") or {}).get("value")
        if mx and u["last"] > mx:
            rec = {"value": u["last"], "previous": round(mx, 3)}
            state["usdinr_max"] = max(state.get("usdinr_max") or 0, u["last"])

    ind = india_view(india.get("qs") or {}, nprev) if india.get("qs") else None
    th = themes(news or [], now)
    sofar = nifty.get("chg_pct") if sess == "open" or (sess == "closed" and rday == now.date()) else None
    call = live_call(now.strftime("%H:%M"), implied, sofar, intr) if sess == "open" else None
    po = pre_open(daily, model, now.date()) if sess == "pre-open" or (sess == "closed" and rday < now.date() and now.weekday() < 5) else None
    if sess == "pre-open" and po:
        call = {"direction": po["direction"] if po["strong"] or abs(po["pct"]) >= 0.1 else "SIDEWAYS", "horizon": "today, close to close",
                "headline": {"UP": "More likely up than down today (before the open)", "DOWN": "More likely down than up today (before the open)"}.get(po["direction"], "No clear direction before the open"),
                "basis": "Last night's US close and yesterday's crude, rupee, dollar and yields (the pre-open model)", "hit": po["hit"],
                "tested_days": po["tested_days"], "cut": "pre-open", "confidence": "fair" if po["strong"] and (po["hit"] or 0) >= 60 else "low",
                "measured": f"Tested on {po['tested_days']} days in 2025-26: right on the day's direction {po['hit']:.0f} times in 100. It says little about the move after the open "
                            f"({po['open_to_close_hit']:.0f} in 100)."}
        if call["direction"] == "SIDEWAYS":
            call.update(headline="No clear direction before the open", confidence=None,
                        measured=f"The pre-open model expects only {po['pct']:+.2f}% for today: too small to call either way.")

    reasons = []
    if nifty.get("chg_pct") is not None and nifty.get("last"):
        when = "so far today" if sess == "open" else "at the close" if rday == now.date() else f"at its last close ({rday.strftime('%d %b')})"
        reasons.append(f"NIFTY is {'up' if nifty['chg_pct'] >= 0 else 'down'} {abs(nifty['chg_pts'] or 0):,.0f} points ({nifty['chg_pct']:+.2f}%) at {nifty['last']:,.0f} {when}"
                       + (f"; Sensex {sensex['chg_pct']:+.2f}%." if sensex.get("chg_pct") is not None else "."))
    top = sorted((r for r in rows if r.get("effect_pts") is not None and abs(r["effect_pts"]) >= 3), key=lambda r: -abs(r["effect_pts"]))[:4]
    bigk = {b["key"]: b for b in big}
    for r in top:
        b = bigk.pop(r["key"], None)
        tail = f" On the {b['days']} days since 2022 with a move this big, NIFTY fell on {b['nifty_fell_pct']:.0f}% of them." if b else ""
        reasons.append(f"{_move_text(r['key'], r['name'], r['chg_pct'], r['last'])} since NIFTY's last close" + (" (from MCX)" if r.get("via") else "")
                       + f": on past days that has meant about {r['effect_pts']:+,.0f} NIFTY points." + tail)
    if rec:
        reasons.append(f"The rupee is at a record low: {rec['value']:.2f} per dollar (its weakest close before today was {rec['previous']:.2f}).")
    for b in sorted(bigk.values(), key=lambda b: -b["days"])[:3]:
        reasons.append(b["text"])
    gone = [r["name"] for r in rows if r.get("stale")]
    if gone:
        reasons.append("Not updating right now (no fresh price from Yahoo): " + ", ".join(gone) + ". Their last known moves are used.")
    if ind:
        br = ind["breadth"]
        if br["seen"]:
            reasons.append(f"Inside NIFTY: {br['up']} of the {br['seen']} stocks we can see are up and {br['down']} are down.")
        hv = [h for h in ind["heavy"][:3] if h["pts"] and abs(h["pts"]) >= 4]
        if hv:
            reasons.append("Biggest movers by weight: " + ", ".join(f"{h['name']} {h['chg_pct']:+.1f}% (about {h['pts']:+.0f} points)" for h in hv) + ".")
        sx = sorted(ind["sectors"], key=lambda s: -abs(s["chg_pct"]))[:3]
        if sx and abs(sx[0]["chg_pct"]) >= 0.5:
            reasons.append("Sectors: " + "; ".join(f"{s['name']} {s['chg_pct']:+.1f}% ({s['why']})" for s in sx) + ".")
    vx = india.get("vix") or {}
    if vx.get("last") and vx.get("prev"):
        vc = _pct(vx["prev"], vx["last"])
        if vc is not None and abs(vc) >= 3:
            reasons.append(f"India VIX, the fear gauge, is {'up' if vc > 0 else 'down'} {abs(vc):.0f}% at {vx['last']:.1f}: traders expect {'bigger' if vc > 0 else 'smaller'} moves.")
    tone = news_tone(news or [], now)
    if tone["bad"] >= 3 and tone["bad"] >= 2 * tone["good"]:
        reasons.append(f"India's own news today is mostly bad for the market: {tone['bad']} bad and {tone['good']} good among {tone['headlines']} headlines on these themes "
                       "(shown for context: headlines are not part of the tested call).")
    elif tone["good"] >= 3 and tone["good"] >= 2 * tone["bad"]:
        reasons.append(f"India's own news today is mostly good for the market: {tone['good']} good and {tone['bad']} bad among {tone['headlines']} headlines on these themes "
                       "(shown for context: headlines are not part of the tested call).")
    if th:
        reasons.append("Today's headlines: " + ", ".join(f"{t['count']} on {t['label']}" for t in th[:4]) + f". Latest on {th[0]['label']}: \"{th[0]['latest']['headline']}\".")
    expl = implied if sess == "open" else None
    if sess != "open" and rday == now.date():                         # after the close: what world markets did during today's session itself
        nd = sorted({datetime.fromtimestamp(t, IST).date() for t, _ in ((ser.get("nifty") or {}).get("bars") or [])})
        before = [d for d in nd if d < rday]
        if before:
            p = before[-1]
            expl = window_implied(ser, fb, datetime(p.year, p.month, p.day, 15, 30, tzinfo=IST).timestamp(), rts)
    if expl is not None and nifty.get("chg_pct") is not None and sofar is not None and nprev:
        gap = nifty["chg_pct"] - expl
        reasons.append(f"World markets account for about {expl * nprev / 100:+,.0f} of NIFTY's {nifty['chg_pts']:+,.0f} points"
                       + (" today. " if sess == "open" else " in today's session. ")
                       + ("The rest is India's own news and money flows (on a typical day world markets explain about a fifth of the move)." if abs(gap) >= 0.25 else
                          "That is most of the move."))

    out = {"at": now.strftime("%H:%M:%S"), "day": now.strftime("%Y-%m-%d"), "session": sess,
           "ref": {"day": rday.isoformat(), "label": f"since NIFTY's close on {rday.strftime('%d %b')} (15:30)"},
           "nifty": nifty, "sensex": sensex, "banknifty": india.get("banknifty"), "vix": india.get("vix"),
           "implied": {"nifty_pct": implied, "nifty_pts": round(implied * nprev / 100, 1) if implied is not None and nprev else None,
                       "sensex_pct": round(simp, 3) if have_w else None, "sensex_pts": round(simp * sprev / 100, 1) if have_w and sprev else None,
                       "missing": missing, "session_pct": expl if sess != "open" else None,
                       "session_pts": round(expl * nprev / 100, 1) if sess != "open" and expl is not None and nprev else None},
           "call": call, "pre_open": po, "factors": rows, "news_tone": tone, "big_moves": big, "rupee_record": rec, "india": ind, "themes": th, "reasons": reasons,
           "model": {"r2": sd.get("r2"), "days": (model or {}).get("days"), "from": (model or {}).get("from"), "to": (model or {}).get("to")},
           "world_at": datetime.fromtimestamp((world or {}).get("at") or 0, IST).strftime("%H:%M:%S") if (world or {}).get("at") else None}
    out["alerts"] = alerts(out, state, now)
    return out


def alerts(out: dict, state: dict, now: datetime) -> list[dict]:
    """New alerts for big moves (each once a day per level) plus today's earlier ones. state['alerts']: {key: {at, title, body}}."""
    sent = state.setdefault("alerts", {})
    day = now.strftime("%Y-%m-%d")
    for k in [k for k in sent if not k.startswith(day)]:
        del sent[k]
    new = []

    def add(key: str, title: str, body: str) -> None:
        k = f"{day}:{key}"
        if k not in sent:
            sent[k] = {"at": now.strftime("%H:%M"), "title": title, "body": body, "new": True}
            new.append(k)
    lv = {"brent": 2.0, "wti": 2.0, "usdinr": 0.35, "dxy": 0.6, "es": 1.0, "n225": 2.0, "hsi": 2.0, "vix_us": 10.0, "us10y": 3.0}
    for r in out.get("factors") or []:
        th, c = lv.get(r["key"]), r.get("chg_pct")
        if th and c is not None and abs(c) >= th:
            n = int(abs(c) // th)
            add(f"{r['key']}:{'+' if c > 0 else '-'}{n}", f"{r['name']} {c:+.1f}%", _move_text(r["key"], r["name"], c, r["last"]) + " since NIFTY's last close. " + r["why"] + ".")
    rec = out.get("rupee_record")
    if rec:
        add(f"rupee_record:{round(rec['value'] * 4) / 4}", "Rupee at a record low", f"{rec['value']:.2f} per dollar (previous weakest close {rec['previous']:.2f}).")
    imp = (out.get("implied") or {}).get("nifty_pct")
    if imp is not None and abs(imp) >= 0.5:
        add(f"implied:{'+' if imp > 0 else '-'}{int(abs(imp) // 0.5)}", "World markets point " + ("up" if imp > 0 else "down") + " for NIFTY",
            f"Crude, the rupee, the dollar and world markets together point to about {imp:+.2f}% ({(out['implied'].get('nifty_pts') or 0):+,.0f} points) for NIFTY.")
    c = out.get("call") or {}
    if c.get("direction") in ("UP", "DOWN") and out.get("session") == "open":
        add(f"call:{c['direction']}", f"Live call: NIFTY {c['direction'].lower()}", f"{c['headline']}. {c['basis']}. {c['measured']}")
    rows = [{"key": k, **{x: v for x, v in a.items() if x != "new"}} for k, a in sent.items()]
    return sorted(rows, key=lambda a: a["at"], reverse=True)


def pop_new(state: dict) -> list[dict]:
    """Alerts not yet pushed to the phone; marks them pushed."""
    out = []
    for k, a in (state.get("alerts") or {}).items():
        if a.get("new"):
            a["new"] = False
            out.append(a)
    return out
