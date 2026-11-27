"""The CEO's EMA9 / VWAP crossover strategy on NIFTY, backtested on real futures and option prices.

Signals on 3-minute candles of the near-month NIFTY future (real price and volume; the index itself has no volume, so a true VWAP needs the
future, as on most charting platforms):
  EMA(9) of the close, carried across days.  VWAP anchored to each session, source (open + high + low + close) / 4, weighted by volume.
  EMA9 crosses above VWAP at a candle close -> buy the at-the-money call;  crosses below -> buy the at-the-money put
  (nearest weekly expiry, strike nearest the NIFTY index, one lot, real 1-minute option prices).
Exits: a 3-minute candle breaches EMA9 against the trade (close beyond it by default; "touch" variant uses the candle's low or high), or the
option falls by the stop (25% or 30%), or 15:20. One position at a time; an opposite crossover while in a trade closes it and takes the new
signal. Slippage on every fill and full charges, as in the straddle engine. Nothing here places an order.
"""
from __future__ import annotations

import urllib.parse
from datetime import date, timedelta

from ..backtest.costs import charges
from ..reports.report import metrics


def _m(t: str, d: int) -> str:
    h, m = int(t[:2]), int(t[3:]) + d
    return f"{h + m // 60:02d}:{m % 60:02d}"


def futures_minutes(client, expiries: list[str], start: date, end: date, log=print) -> dict:
    """{day: {HH:MM: (o, h, l, c, v)}} from the near-month NIFTY future, rolling to the next contract after each monthly expiry."""
    q = urllib.parse.quote("NSE_INDEX|Nifty 50", safe="")
    months = {}
    for e in expiries:
        months[e[:7]] = max(months.get(e[:7], e), e)                  # the last expiry of a month is the monthly (futures) expiry
    monthly = sorted(months.values())
    out, prev = {}, None
    for m in monthly:
        rows = client.get(f"{client.V2}/expired-instruments/future/contract?instrument_key={q}&expiry_date={m}").get("data") or []
        fut = next((x for x in rows if x.get("instrument_type") == "FUT"), rows[0] if rows else None)
        M = date.fromisoformat(m)
        lo = (date.fromisoformat(prev) + timedelta(days=1)) if prev else start - timedelta(days=5)
        prev = m
        if not fut or M < start - timedelta(days=5):
            continue
        cs = client.expired_candles(fut["instrument_key"], "1minute", max(lo, M - timedelta(days=40)), M)
        for c in cs:
            if lo <= c.ts.date() <= M:
                out.setdefault(c.ts.date(), {})[c.ts.strftime("%H:%M")] = (c.open, c.high, c.low, c.close, c.volume)
    log(f"futures minutes for {len(out)} sessions from {len(monthly)} monthly contracts")
    return out


def three_minute(day_bars: dict) -> list[tuple]:
    """[(start HH:MM, end HH:MM, o, h, l, c, v)] 09:15-15:30."""
    out, t = [], "09:15"
    while t < "15:30":
        mins = [day_bars[x] for x in (t, _m(t, 1), _m(t, 2)) if x in day_bars]
        if mins:
            out.append((t, _m(t, 3), mins[0][0], max(x[1] for x in mins), min(x[2] for x in mins), mins[-1][3], sum(x[4] for x in mins)))
        t = _m(t, 3)
    return out


def indicators(fut: dict, days: list[date]) -> dict:
    """{day: [(start, end, o, h, l, c, ema9, vwap)]}: EMA carried across sessions, VWAP reset each session on (O+H+L+C)/4."""
    k, ema, out = 2 / 10, None, {}
    for d in days:
        bars = three_minute(fut.get(d) or {})
        pv = vv = 0.0
        rows = []
        for s, e, o, h, l, c, v in bars:
            ema = c if ema is None else ema + k * (c - ema)
            src = (o + h + l + c) / 4
            w = v if v > 0 else 1.0
            pv, vv = pv + src * w, vv + w
            rows.append((s, e, o, h, l, c, ema, pv / vv))
        out[d] = rows
    return out


def simulate(bt, ind: dict, stop: float = 0.25, breach: str = "close", first_entry: str = "09:21", last_entry: str = "15:00", square_off: str = "15:20", label: str = "",
             slope_bars: int = 0, cooldown_min: int = 0) -> list[dict]:
    """bt: a loaded straddle_engine.Backtester (index minutes, expiries, contracts cache, client).
    Cleaner signals: slope_bars > 0 takes a crossover only when VWAP has risen (calls) or fallen (puts) over the last slope_bars 3-minute candles;
    cooldown_min > 0 skips any crossover that comes within that many minutes of the previous crossover (whipsaw filter)."""
    from ..backtest.straddle_engine import _price_at, _series
    trades, cache = [], {}

    def leg(expiry: str, strike: int, kind: str):
        key = (expiry, strike, kind)
        if key in bt.legs:
            return bt.legs[key]
        if key not in cache:
            meta = next((x for x in bt.c.expired_contracts(expiry) if x.get("strike_price") == strike and x.get("instrument_type") == kind), None)
            if not meta:
                cache[key] = None
            else:
                E = date.fromisoformat(expiry)
                cache[key] = (meta, _series(bt.c.expired_candles(meta["instrument_key"], "1minute", E - timedelta(days=9), E)))
        return cache[key]

    exps = sorted(bt.expiries)
    for d, rows in sorted(ind.items()):
        if d < bt.cfg.start or d not in bt.n1 or len(rows) < 3:
            continue
        expiry = next((e for e in exps if e >= d.isoformat()), None)
        if not expiry:
            continue
        dte = sum(1 for x in bt.trading if d < x <= date.fromisoformat(expiry))
        pos, last_cross = None, None
        for i in range(1, len(rows)):
            s, end, o, h, l, c, ema, vw = rows[i]
            pe_, pv_ = rows[i - 1][6], rows[i - 1][7]
            up, dn = pe_ <= pv_ and ema > vw, pe_ >= pv_ and ema < vw
            take = up or dn
            if take:
                mins_now = int(end[:2]) * 60 + int(end[3:])
                if cooldown_min and last_cross is not None and mins_now - last_cross < cooldown_min:
                    take = False                                  # a second crossover within the cooldown: whipsaw, skip it
                last_cross = mins_now
                if take and slope_bars and i >= slope_bars:
                    sl_ = vw - rows[i - slope_bars][7]
                    take = (sl_ > 0) if up else (sl_ < 0)         # VWAP must slope the way of the trade
            # 1) manage an open position: minute-by-minute stop inside this candle, then the EMA9 breach at the candle close
            if pos:
                bars = pos["bars"]
                hit = None
                t = s
                while t <= end and t <= square_off:
                    px = _price_at(bars, t)
                    if px is not None and px - bt._slip(px) <= pos["entry"] * (1 - stop) and t > pos["t"]:
                        hit = (t, px - bt._slip(px), f"STOP_{int(stop * 100)}PCT")
                        break
                    t = _m(t, 1)
                if not hit:
                    against = (c < ema if pos["kind"] == "CE" else c > ema) if breach == "close" else (l < ema if pos["kind"] == "CE" else h > ema)
                    flip = (dn if pos["kind"] == "CE" else up)
                    if end >= square_off:
                        px = _price_at(bars, square_off) or _price_at(bars, end)
                        hit = (square_off, (px or pos["entry"]) - bt._slip(px or pos["entry"]), "SQUARE_OFF_1520")
                    elif against or flip:
                        px = _price_at(bars, end)
                        if px is not None:
                            hit = (end, px - bt._slip(px), "EMA9_BREACH_3MIN" if against else "OPPOSITE_CROSS")
                if hit:
                    x = max(hit[1], 0.05)
                    lot = pos["lot"]
                    ch = charges(pos["entry"] * lot, x * lot, orders=2)["total"]
                    net = (x - pos["entry"]) * lot - ch
                    trades.append({"variant": label, "day": d.isoformat(), "expiry": expiry, "dte": dte, "mode": pos["mode"], "side": "CALL" if pos["kind"] == "CE" else "PUT",
                                   "strike": pos["strike"], "symbol": pos["sym"], "entry_time": pos["t"], "entry_price": round(pos["entry"], 2), "spot_at_entry": pos["spot"],
                                   "exit_time": hit[0], "exit_price": round(x, 2), "exit_reason": hit[2], "lot_size": lot, "capital_deployed": round(pos["entry"] * lot, 2),
                                   "gross_pnl_inr": round((x - pos["entry"]) * lot, 2), "est_charges_inr": round(ch, 2), "net_pnl_inr": round(net, 2),
                                   "return_pct": round(net / (pos["entry"] * lot) * 100, 2), "hold_min": (int(hit[0][:2]) * 60 + int(hit[0][3:])) - (int(pos["t"][:2]) * 60 + int(pos["t"][3:])),
                                   "entry_timestamp_ist": f"{d}T{pos['t']}:00+05:30", "slippage_inr": 0.0, "mae_pct": 0.0, "mfe_pct": 0.0, "data_source_status": "VERIFIED_HISTORICAL"})
                    pos = None
            # 2) a new crossover opens a trade at the candle close
            if not pos and take and first_entry <= end <= last_entry:
                spot = _price_at(bt.n1[d], end)
                if not spot:
                    continue
                kind, k = ("CE" if up else "PE"), int(round(spot / 50) * 50)
                lg = leg(expiry, k, kind)
                if not lg:
                    continue
                bars = lg[1].get(d) or {}
                px = _price_at(bars, end)
                if px is None or px <= 0:
                    continue
                vix = _price_at(bt.v1.get(d) or {}, end) or 15.0
                mode = "MODE_1_QUIET" if vix < 13 else "MODE_2_VOLATILE" if vix < 18 else "MODE_3_HIGH_VOLATILITY"
                pos = {"kind": kind, "strike": k, "t": end, "entry": px + bt._slip(px), "bars": bars, "lot": int(lg[0].get("lot_size") or 65), "mode": mode,
                       "sym": lg[0].get("trading_symbol", ""), "spot": round(spot, 2)}
    return trades


def summarise(trades: list[dict]) -> dict:
    from collections import Counter, defaultdict
    g = lambda key: {k: metrics(v) for k, v in sorted(_group(trades, key).items())}
    days = {t["day"] for t in trades}
    per_day = Counter(t["day"] for t in trades)
    return {"overall": metrics(trades), "sessions_with_trades": len(days), "avg_trades_per_session": round(len(trades) / len(days), 2) if days else 0,
            "max_trades_in_a_session": max(per_day.values()) if per_day else 0, "exit_reasons": dict(Counter(t["exit_reason"] for t in trades)),
            "avg_hold_min": round(sum(t["hold_min"] for t in trades) / len(trades), 1) if trades else None,
            "by_side": g("side"), "by_mode": g("mode"), "by_dte": g("dte"), "by_year": g(lambda t: t["day"][:4]), "by_hour": g(lambda t: t["entry_time"][:2])}


def _group(trades, key):
    from collections import defaultdict
    out = defaultdict(list)
    for t in trades:
        out[key(t) if callable(key) else t[key]].append(t)
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# Entry rules from the "EMA VWAP" reel (3-minute candles), tested on real option prices. Each rule reads candle i at its close and returns
# "CE" (buy calls), "PE" (buy puts) or None. rows[i] = (start, end, open, high, low, close, ema9, vwap) of the near-month NIFTY future.
def rule_wick_vwap(rows, i):
    """The images: trade WITH the trend after a wick into VWAP is rejected. Down trend (EMA9 below VWAP): the candle's high reaches VWAP but
    it closes back below VWAP and EMA9, red -> puts. Up trend (EMA9 above VWAP): the low reaches VWAP, closes back above both, green -> calls."""
    s, e, o, h, l, c, ema, vw = rows[i]
    if ema < vw and h >= vw and c < vw and c < ema and c < o:
        return "PE"
    if ema > vw and l <= vw and c > vw and c > ema and c > o:
        return "CE"
    return None


def rule_wick_any(rows, i):
    """As rule_wick_vwap, but a wick into EITHER line counts (EMA9 sits between price and VWAP on most pullbacks)."""
    s, e, o, h, l, c, ema, vw = rows[i]
    if ema < vw and h >= min(ema, vw) and c < ema and c < o:
        return "PE"
    if ema > vw and l <= max(ema, vw) and c > ema and c > o:
        return "CE"
    return None


def rule_as_written(rows, i):
    """The CEO's words: a candle that wicks through VWAP and closes back below it -> puts; a candle that breaks (closes) through EMA9 upward
    -> calls. No trend filter."""
    s, e, o, h, l, c, ema, vw = rows[i]
    pc, pe = rows[i - 1][5], rows[i - 1][6]
    if h >= vw and c < vw and o < vw:
        return "PE"
    if pc <= pe and c > ema:
        return "CE"
    return None


def rule_cross(rows, i):
    """Baseline tested earlier: EMA9 crosses VWAP."""
    pe_, pv_, ema, vw = rows[i - 1][6], rows[i - 1][7], rows[i][6], rows[i][7]
    return "CE" if pe_ <= pv_ and ema > vw else "PE" if pe_ >= pv_ and ema < vw else None


RULES = {"wick into VWAP, with the trend (the images)": rule_wick_vwap, "wick into EMA9 or VWAP, with the trend": rule_wick_any,
         "as written: VWAP wick -> puts, EMA9 break -> calls": rule_as_written, "EMA9 x VWAP crossover (tested earlier)": rule_cross}


def simulate_rule(bt, ind: dict, rule, lots: int = 2, stop: float | None = 0.25, first_entry: str = "09:21", last_entry: str = "15:00",
                  square_off: str = "15:20", max_trades: int = 99, min_dte: int = 0) -> list[dict]:
    """One position at a time: buy `lots` lots of the at-the-money option of the nearest weekly expiry with at least `min_dte` trading days
    left, at the signal candle's close (real 1-minute option price + slippage). Exit at the first 3-minute candle that CLOSES back across EMA9
    against the trade (image 2), or when the option falls by `stop` (checked every minute), or at `square_off`. Full charges."""
    from ..backtest.straddle_engine import _price_at, _series
    trades, cache, exps = [], {}, sorted(bt.expiries)

    def leg(expiry, strike, kind):
        key = (expiry, strike, kind)
        if key not in cache:
            try:
                meta = next((x for x in bt.c.expired_contracts(expiry) if int(x.get("strike_price") or 0) == strike and x.get("instrument_type") == kind), None)
                E = date.fromisoformat(expiry)
                cache[key] = (meta, _series(bt.c.expired_candles(meta["instrument_key"], "1minute", E - timedelta(days=9), E))) if meta else None
            except RuntimeError:
                cache[key] = None
        return cache[key]

    for d, rows in sorted(ind.items()):
        if d < bt.cfg.start or d not in bt.n1 or len(rows) < 3:
            continue
        cand = [e for e in exps if e >= d.isoformat() and sum(1 for x in bt.trading if d < x <= date.fromisoformat(e)) >= min_dte]
        if not cand:
            continue
        expiry = cand[0]
        dte = sum(1 for x in bt.trading if d < x <= date.fromisoformat(expiry))
        pos, n = None, 0
        for i in range(1, len(rows)):
            s, end, o, h, l, c, ema, vw = rows[i]
            if pos:
                bars, hit, t = pos["bars"], None, s
                while t <= end and t <= square_off:                     # the premium stop, minute by minute inside this candle
                    px = _price_at(bars, t)
                    if stop and px is not None and t > pos["t"] and px - _slip(px) <= pos["entry"] * (1 - stop):
                        hit = (t, px - _slip(px), f"stop -{int(stop * 100)}%")
                        break
                    t = _m(t, 1)
                if not hit:
                    if end >= square_off:
                        px = _price_at(bars, square_off) or _price_at(bars, end)
                        hit = (square_off, (px or pos["entry"]) - _slip(px or pos["entry"]), "15:20 square-off")
                    elif (c < ema) if pos["kind"] == "CE" else (c > ema):   # a 3-minute close back across EMA9: exit (image 2)
                        px = _price_at(bars, end)
                        if px is not None:
                            hit = (end, px - _slip(px), "3-min close across EMA9")
                if hit:
                    x = max(hit[1], 0.05)
                    units = pos["units"]
                    ch = charges(pos["entry"] * units, x * units, orders=2)["total"]
                    net = (x - pos["entry"]) * units - ch
                    trades.append({"day": d.isoformat(), "expiry": expiry, "dte": dte, "side": "CALL" if pos["kind"] == "CE" else "PUT", "strike": pos["strike"],
                                   "in": pos["t"], "out": hit[0], "entry": round(pos["entry"], 2), "exit": round(x, 2), "why": hit[2], "units": units,
                                   "outlay": round(pos["entry"] * units), "charges": round(ch, 2), "net": round(net, 2), "fut_move": round((c - pos["fut"]) * (1 if pos["kind"] == "CE" else -1), 1)})
                    pos = None
                continue
            if n >= max_trades or not (first_entry <= end <= last_entry):
                continue
            kind = rule(rows, i)
            if not kind:
                continue
            spot = _price_at(bt.n1[d], end)
            if not spot:
                continue
            k = int(round(spot / 50) * 50)
            lg = leg(expiry, k, kind)
            if not lg:
                continue
            px = _price_at(lg[1].get(d) or {}, end)
            if px is None or px <= 0:
                continue
            pos = {"kind": kind, "strike": k, "t": end, "entry": px + _slip(px), "bars": lg[1].get(d) or {}, "units": lots * int(lg[0].get("lot_size") or 75), "fut": c}
            n += 1
    return trades


def _slip(px: float) -> float:
    return max(0.10, 0.003 * px)
