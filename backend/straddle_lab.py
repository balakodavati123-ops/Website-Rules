"""Straddle lab: trains the F&O desk's only trade, a bought NIFTY straddle (buy the call and the put at one strike; nothing is sold, so
no margin beyond the premium), on history.

Data: NIFTY 50 and India VIX from Upstox: daily candles since 2016 and 15-minute candles since 2022.
Prices: historical option prices are not available, so every straddle is priced with Black-Scholes from India VIX in market-hours time
(time decay happens while the market is open, not overnight or at weekends), scaled to the desk's live readings (about 0.85x VIX within
four days of expiry, about 1x a week out). Costs: 0.4% slippage each way plus brokerage, STT, exchange fees, GST and stamp duty. One lot of 65.
Training (intraday, 2022-2024): every combination of entry time, expiry (this week's or next week's), strike (at the money, or one strike
with or against the morning's move), target, stop-loss and a market-condition filter (cheap or rich volatility, realised above implied,
news-sized gaps or VIX jumps, days to expiry) is replayed on 15-minute bars, exit by 15:15 at the latest. The rule is chosen on 2022-2024
only (profitable in at least two of the three years, profit factor 1.15+, ranked by average minus one standard error), then tested on
2025-2026, which it never saw. A ten-year open-to-close check (2016-2026, daily candles) shows how the same filter behaved in older markets.
"Days like today": the 40 most similar days (VIX level and percentile, realised against implied volatility, gap, VIX change, days to expiry).
This is a model backtest, not a record of real fills. Nothing here places an order.

  python backend/straddle_lab.py train      -> docs/models/straddle_playbook.json
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "models" / "straddle_playbook.json"
NIFTY, VIX = "NSE_INDEX|Nifty 50", "NSE_INDEX|India VIX"
LOT, RATE, SLIP = 65, 0.065, 0.004
WEEKLY_FROM, TUESDAY_FROM = date(2019, 2, 11), date(2025, 9, 1)
ENTRIES = {"09:30": "09:15", "10:00": "09:45", "11:00": "10:45", "13:00": "12:45"}      # entry time -> the 15-minute bar whose close it is
EXIT_BAR = "15:00"                                                                      # out at 15:15 at the latest
TARGETS, STOPS = (0.25, 0.4, 0.6, None), (0.2, 0.3, 0.45)
TRAIN_TO, TEST_FROM = date(2024, 12, 31), date(2025, 1, 1)


def iv_mult(dte: int) -> float:
    """Weekly at-the-money volatility as a multiple of India VIX in market-hours time (calibrated on the desk's live chain readings:
    about 0.85 within four days of expiry, expiry day included, and about 1.0 a week out)."""
    return 0.85 if dte <= 4 else 0.92 if dte <= 7 else 1.0


SESSION = 375                                                             # minutes from 09:15 to 15:30


def t_years(now: datetime, exp: date, trading: set) -> float:
    """Time to expiry in market hours: what is left of today's session plus one session for every trading day up to expiry, over 252 sessions a
    year. Nights, weekends and holidays carry almost no decay in this convention, which is how option prices actually behave through a week."""
    left = max(0.0, min(SESSION, (datetime(now.year, now.month, now.day, 15, 30) - now).total_seconds() / 60)) if now.date() <= exp else 0.0
    hi = max(trading) if trading else None
    d, n = now.date() + timedelta(days=1), 0
    while d <= exp:
        n += (d in trading) if (trading and d <= hi) else (d.weekday() < 5)
        d += timedelta(days=1)
    return (left + n * SESSION) / (252 * SESSION)


def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def straddle(S: float, K: float, T: float, sig: float) -> float:
    if T <= 1e-7 or sig <= 0:
        return abs(S - K)
    v = sig * math.sqrt(T)
    d1 = (math.log(S / K) + (RATE + 0.5 * sig * sig) * T) / v
    c = S * ncdf(d1) - K * math.exp(-RATE * T) * ncdf(d1 - v)
    return 2 * c - S + K * math.exp(-RATE * T)


def charges(buy: float, sell: float) -> float:
    """Rupees for one lot round trip, both legs: Rs 20 brokerage an order, STT 0.1% on the sale, exchange fees, GST, stamp duty."""
    brok, exch = 80.0, 0.0003503 * (buy + sell)
    return brok + exch + 0.001 * sell + 0.18 * (brok + exch) + 0.00003 * buy


# ------------------------------------------------------------------ data
def fetch(get, token: str, key: str, unit: str, start: date, end: date, chunk_days: int) -> list[list]:
    k, out, d = urllib.parse.quote(key, safe=""), {}, start
    while d <= end:
        e = min(end, d + timedelta(days=chunk_days))
        for attempt in range(3):
            try:
                rows = json.loads(get(f"https://api.upstox.com/v3/historical-candle/{k}/{unit}/{e}/{d}", token)).get("data", {}).get("candles", [])
                for r in rows:
                    out[r[0]] = [r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])]
                break
            except Exception:
                time.sleep(1 + attempt)
        d = e + timedelta(days=1)
        time.sleep(0.25)
    return [out[t] for t in sorted(out)]


def load(get, token: str, today: date) -> dict:
    dn = fetch(get, token, NIFTY, "days/1", date(2015, 6, 1), today, 1500)
    dv = fetch(get, token, VIX, "days/1", date(2015, 6, 1), today, 1500)
    inn = fetch(get, token, NIFTY, "minutes/15", date(2022, 1, 1), today, 27)
    inv = fetch(get, token, VIX, "minutes/15", date(2022, 1, 1), today, 27)
    return {"dn": dn, "dv": dv, "in": inn, "iv": inv}


# ------------------------------------------------------------------ calendar and features
def expiry_on(d: date, trading: set, monthly: bool = False) -> date:
    """The first weekly (or, before weekly options, monthly) NIFTY expiry on or after d, moved to the previous trading day over a holiday."""
    hi = max(trading) if trading else None

    def adj(x: date) -> date:
        if not trading or x > hi:
            return x                                                         # beyond the known calendar: assume a normal trading day
        y = x
        while y not in trading and (x - y).days < 7:
            y -= timedelta(days=1)
        return y if y in trading else x
    if monthly or d < WEEKLY_FROM:
        m = date(d.year, d.month, 28) + timedelta(days=4)
        last = m - timedelta(days=m.day)
        while last.weekday() != 3:
            last -= timedelta(days=1)
        x = adj(last)
        if x < d:
            nm = (date(d.year, d.month, 1) + timedelta(days=32)).replace(day=1)
            return expiry_on(nm, trading, True)
        return x
    wd = 1 if d >= TUESDAY_FROM else 3
    x = d + timedelta(days=(wd - d.weekday()) % 7)
    e = adj(x)
    return e if e >= d else expiry_on(x + timedelta(days=1), trading)


def features(days: list[date], dclose: dict, dopen: dict, vclose: dict) -> dict:
    """Per day, from information known before the open: VIX level and 1-year percentile, 5-day realised against implied volatility, the gap."""
    out, vs = {}, []
    for i, d in enumerate(days):
        if i < 6:
            vs.append(vclose[d])
            continue
        p = days[i - 1]
        hist = vs[-252:]
        vprev = vclose[p]
        rets = [math.log(dclose[days[j]] / dclose[days[j - 1]]) for j in range(i - 5, i)]
        rv5 = statistics.pstdev(rets) * math.sqrt(252) * 100
        out[d] = {"vix": round(vprev, 2), "vix_pct": round(sum(1 for x in hist if x <= vprev) / len(hist) * 100, 1), "rv_iv": round(rv5 / vprev, 2),
                  "gap": round((dopen[d] / dclose[p] - 1) * 100, 2), "prev_close": dclose[p]}
        vs.append(vclose[d])
    return out


# ------------------------------------------------------------------ the replay
def path(bars_n: dict, bars_v: dict, d: date, entry: str, exp: date, strike_rule: str, f: dict, trading: set = frozenset()) -> dict | None:
    """Straddle value at the entry bar and every later 15-minute close until 15:15."""
    times = sorted(t for t in bars_n if t >= ENTRIES[entry] and t <= EXIT_BAR)
    if not times or times[0] != ENTRIES[entry] or EXIT_BAR not in bars_n:
        return None
    S0 = bars_n[times[0]]
    move = S0 / f["prev_close"] - 1
    K = round(S0 / 50) * 50
    if strike_rule != "atm" and abs(move) >= 0.003:
        K += (-50 if move > 0 else 50) * (1 if strike_rule == "with" else -1)      # "with": the call side in the money, so the straddle leans with the move
    dte = (exp - d).days
    vals = []
    for t in times:
        hh, mm = int(t[:2]), int(t[3:]) + 15
        now = datetime(d.year, d.month, d.day, hh + mm // 60, mm % 60)
        T = t_years(now, exp, trading)
        sig = iv_mult(dte) * (bars_v.get(t) or f["vix"]) / 100
        vals.append(straddle(bars_n[t], K, T, sig))
    vchg = ((bars_v.get(times[0]) or f["vix"]) / f["vix"] - 1) * 100
    return {"K": K, "vals": vals, "dte": dte, "vix_chg": round(vchg, 2), "move": round(move * 100, 2)}


def outcome(vals: list[float], tgt, stp) -> tuple[float, str]:
    e = vals[0] * (1 + SLIP)
    for v in vals[1:]:
        x = v * (1 - SLIP)
        if tgt is not None and x >= e * (1 + tgt):
            return x, "target"
        if x <= e * (1 - stp):
            return x, "stop"
    return vals[-1] * (1 - SLIP), "time"


def pnl_rs(vals, tgt, stp) -> tuple[float, str]:
    x, why = outcome(vals, tgt, stp)
    e = vals[0] * (1 + SLIP)
    return round((x - e) * LOT - charges(e * LOT, x * LOT), 2), why


FILTERS = {
    "all": lambda f: True,
    "cheap volatility (VIX in its lowest third of the year)": lambda f: f["vix_pct"] <= 33,
    "rich volatility (VIX in its top third of the year)": lambda f: f["vix_pct"] >= 67,
    "realised above implied (5-day moves at least 0.9x VIX)": lambda f: f["rv_iv"] >= 0.9,
    "news-sized open (gap 0.6%+ or VIX up 5%+ at entry)": lambda f: abs(f["gap"]) >= 0.6 or f["vix_chg"] >= 5,
    "VIX rising at entry (3%+)": lambda f: f["vix_chg"] >= 3,
    "calm open (gap under 0.3%)": lambda f: abs(f["gap"]) < 0.3,
    "near expiry (0-1 days)": lambda f: f["dte"] <= 1,
    "away from expiry (2+ days)": lambda f: f["dte"] >= 2,
}


def stats(xs: list[float]) -> dict:
    n = len(xs)
    if not n:
        return {"n": 0}
    m = sum(xs) / n
    sd = statistics.pstdev(xs) if n > 1 else 0.0
    w, l = [x for x in xs if x > 0], [x for x in xs if x <= 0]
    eq = dd = peak = 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"n": n, "avg_rs": round(m, 1), "total_rs": round(sum(xs)), "win_rate": round(len(w) / n * 100, 1), "pf": round(sum(w) / -sum(l), 2) if l and sum(l) < 0 else None,
            "lcb_rs": round(m - sd / math.sqrt(n), 1), "max_dd_rs": round(dd)}


def train(data: dict, today: date) -> dict:
    dn = {date.fromisoformat(r[0][:10]): r for r in data["dn"]}
    dv = {date.fromisoformat(r[0][:10]): r for r in data["dv"]}
    days = sorted(set(dn) & set(dv))
    trading = set(days)
    F = features(days, {d: dn[d][4] for d in days}, {d: dn[d][1] for d in days}, {d: dv[d][4] for d in days})
    bn, bv = {}, {}
    for r in data["in"]:
        bn.setdefault(date.fromisoformat(r[0][:10]), {})[r[0][11:16]] = r[4]
    for r in data["iv"]:
        bv.setdefault(date.fromisoformat(r[0][:10]), {})[r[0][11:16]] = r[4]
    idays = [d for d in sorted(bn) if d in F]
    # every path once; exits are cheap to replay
    rows = []
    for d in idays:
        e_near = expiry_on(d, trading)
        e_next = expiry_on(e_near + timedelta(days=1), trading)
        for entry in ENTRIES:
            for xsel, exp in (("this week", e_near), ("next week", e_next)):
                for srule in ("atm", "with", "against"):
                    p = path(bn[d], bv.get(d, {}), d, entry, exp, srule, F[d], trading)
                    if p:
                        rows.append((d, entry, xsel, srule, p))
    results = {}
    for d, entry, xsel, srule, p in rows:
        f = {**F[d], "dte": p["dte"], "vix_chg": p["vix_chg"]}
        for tgt in TARGETS:
            for stp in STOPS:
                key = (entry, xsel, srule, tgt, stp)
                r, why = pnl_rs(p["vals"], tgt, stp)
                results.setdefault(key, []).append((d, r, why, f))
    cands = []
    for key, lst in results.items():
        for fname, fn in FILTERS.items():
            tr = [x for x in lst if x[0] <= TRAIN_TO and fn(x[3])]
            if len(tr) < 40:
                continue
            s = stats([x[1] for x in tr])
            years = {}
            for x in tr:
                years[x[0].year] = years.get(x[0].year, 0.0) + x[1]
            good_years = sum(1 for v in years.values() if v > 0)
            if (s["pf"] or 0) >= 1.15 and good_years >= 2 and s["avg_rs"] > 0:
                cands.append((s["lcb_rs"], key, fname, s))
    cands.sort(key=lambda c: -c[0])
    tried = len(results) * len(FILTERS)
    pick = cands[0] if cands else None
    if pick is None:                                                            # nothing passed: keep the plainest rule and say so
        key = ("10:00", "this week", "atm", 0.4, 0.3)
        lst = results.get(key, [])
        s = stats([x[1] for x in lst if x[0] <= TRAIN_TO])
        pick = (s.get("lcb_rs", 0), key, "all", s)
    _, key, fname, s_tr = pick
    fn = FILTERS[fname]
    lst = results[key]
    test = [x for x in lst if x[0] >= TEST_FROM and fn(x[3])]
    s_te = stats([x[1] for x in test])
    allx = [x for x in lst if fn(x[3])]
    by_year = {}
    for x in allx:
        by_year.setdefault(str(x[0].year), []).append(x[1])
    exits = {}
    for x in allx:
        exits[x[2]] = exits.get(x[2], 0) + 1
    # ten-year open-to-close check with daily candles (no intraday path: bought at the open, sold at the close)
    ten = {}
    for d in days:
        if d not in F or d >= date(2022, 1, 1) and False:
            continue
        exp = expiry_on(d, trading)
        dte = (exp - d).days
        o, c = dn[d][1], dn[d][4]
        vo, vc = dv[d][1] or F[d]["vix"], dv[d][4]
        K = round(o / 50) * 50
        T0 = t_years(datetime(d.year, d.month, d.day, 9, 15), exp, trading)
        T1 = t_years(datetime(d.year, d.month, d.day, 15, 15), exp, trading)
        v0, v1 = straddle(o, K, T0, iv_mult(dte) * vo / 100), straddle(c, K, max(T1, 0.0), iv_mult(dte) * vc / 100)
        f = {**F[d], "dte": dte, "vix_chg": round((vo / F[d]["vix"] - 1) * 100, 2)}
        if fn(f):
            e, x = v0 * (1 + SLIP), v1 * (1 - SLIP)
            ten.setdefault(str(d.year), []).append(round((x - e) * LOT - charges(e * LOT, x * LOT), 2))
    # days like today: the chosen trade on every day (no filter), with the features to find neighbours
    table = [[x[0].isoformat(), x[3]["vix"], x[3]["vix_pct"], x[3]["rv_iv"], x[3]["gap"], x[3]["vix_chg"], x[3]["dte"], x[1]] for x in lst]
    closes = [[d.isoformat(), dn[d][4], dv[d][4]] for d in days[-300:]]
    entry, xsel, srule, tgt, stp = key
    return {"trained_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "data": {"daily_from": days[0].isoformat(), "daily_to": days[-1].isoformat(), "intraday_from": idays[0].isoformat() if idays else None,
            "intraday_days": len(idays)}, "rule": {"entry": entry, "expiry": xsel, "strike": {"atm": "at the money", "with": "one strike with the morning's move", "against": "one strike against the morning's move"}[srule],
            "strike_code": srule, "target": tgt, "stop": stp, "exit_by": "15:15", "filter": fname}, "train": {**s_tr, "from": "2022-01-01", "to": TRAIN_TO.isoformat()},
            "test": {**s_te, "from": TEST_FROM.isoformat(), "to": days[-1].isoformat()}, "by_year": {y: stats(v) for y, v in sorted(by_year.items())}, "exits": exits,
            "ten_year_open_to_close": {y: stats(v) for y, v in sorted(ten.items())}, "rules_tried": tried, "rules_passing_train": len(cands),
            "runners_up": [{"lcb_rs": c[0], "entry": c[1][0], "expiry": c[1][1], "strike": c[1][2], "target": c[1][3], "stop": c[1][4], "filter": c[2], "train_avg_rs": c[3]["avg_rs"],
                            "test_avg_rs": stats([x[1] for x in results[c[1]] if x[0] >= TEST_FROM and FILTERS[c[2]](x[3])]).get("avg_rs")} for c in cands[1:6]],
            "iv_mult": {"0": iv_mult(0), "1": iv_mult(1), "2-4": iv_mult(3), "5-7": iv_mult(6), "8+": iv_mult(9)}, "lot": LOT, "slippage": SLIP,
            "table": table, "closes": closes,
            "honesty": "Model backtest: option prices rebuilt from India VIX with Black-Scholes, scaled to the desk's live readings; real bid and ask, skew and expiry-day pricing differ. "
                       "Chosen on 2022-2024 only; 2025-2026 is out of sample. Paper results decide anything further."}


# ------------------------------------------------------------------ live use
def today_view(pb: dict, f: dict, k: int = 40) -> dict:
    """Does the trained rule's filter hold today, and how did the trade do on the 40 most similar days?"""
    if not pb or not pb.get("table"):
        return {"ok": False, "why": "no trained playbook yet"}
    fn = FILTERS.get(pb["rule"]["filter"], FILTERS["all"])
    hit = fn(f)
    cols = list(zip(*[r[1:7] for r in pb["table"]]))
    sd = [statistics.pstdev(c) or 1.0 for c in cols]
    q = [f["vix"], f["vix_pct"], f["rv_iv"], f["gap"], f["vix_chg"], f["dte"]]
    near = sorted(pb["table"], key=lambda r: sum(((r[1 + i] - q[i]) / sd[i]) ** 2 for i in range(6)))[:k]
    pn = [r[7] for r in near]
    knn = {"k": len(pn), "avg_rs": round(sum(pn) / len(pn), 1) if pn else None, "win_rate": round(sum(1 for x in pn if x > 0) / len(pn) * 100, 1) if pn else None,
           "dates": [r[0] for r in near[:5]]}
    if not pb.get("rules_passing_train"):
        return {"ok": False, "why": f"no straddle rule beat time decay and costs in training ({pb.get('rules_tried', 0)} rules tested); "
                                     f"on the {knn['k']} days most like today the trade averaged Rs {knn['avg_rs']:,.0f}", "match": hit, "knn": knn, "features": f}
    ok = bool(hit and (knn["avg_rs"] or 0) >= 0)
    why = (f"today matches the trained condition ({pb['rule']['filter']}) and the {knn['k']} most similar days averaged Rs {knn['avg_rs']:,.0f}" if ok else
           f"today does not match the trained condition ({pb['rule']['filter']})" if not hit else f"the {knn['k']} most similar days averaged Rs {knn['avg_rs']:,.0f}: no edge on days like today")
    return {"ok": ok, "why": why, "match": hit, "knn": knn, "features": f}


def live_features(pb: dict, closes: list[list], vix_now: float, spot_open: float, dte: int, vix_prev: float | None = None) -> dict:
    """Today's features from recent daily closes [[date, nifty, vix], ...] (yesterday last) and the live VIX."""
    c = [r[1] for r in closes][-6:]
    v = [r[2] for r in closes][-252:]
    vprev = vix_prev or v[-1]
    rets = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    rv5 = statistics.pstdev(rets) * math.sqrt(252) * 100 if len(rets) >= 2 else vprev
    return {"vix": round(vprev, 2), "vix_pct": round(sum(1 for x in v if x <= vprev) / len(v) * 100, 1) if v else 50.0, "rv_iv": round(rv5 / vprev, 2),
            "gap": round((spot_open / c[-1] - 1) * 100, 2), "vix_chg": round((vix_now / vprev - 1) * 100, 2), "dte": dte, "prev_close": c[-1]}


if __name__ == "__main__":
    if sys.argv[1:2] == ["train"]:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import upstox as U
        tok = os.environ.get("UPSTOX_TOKEN") or "proxy-injected"
        t0 = time.time()
        cache = os.environ.get("STRADDLE_CACHE")
        if cache and Path(cache).exists():
            data = json.loads(Path(cache).read_text())
        else:
            data = load(U._get, tok, datetime.now(IST).date())
            if cache:
                Path(cache).write_text(json.dumps(data))
        print(f"data: {len(data['dn'])} daily NIFTY, {len(data['dv'])} daily VIX, {len(data['in'])} 15-minute NIFTY, {len(data['iv'])} 15-minute VIX ({time.time() - t0:.0f}s)")
        pb = train(data, datetime.now(IST).date())
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(pb, separators=(",", ":")))
        show = {k: v for k, v in pb.items() if k not in ("table", "closes")}
        print(json.dumps(show, indent=1)[:6000])
        print(f"done in {time.time() - t0:.0f}s -> {OUT}")
    else:
        print(__doc__)
