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
