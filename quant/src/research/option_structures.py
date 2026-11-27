"""Option structures on REAL NIFTY option prices (Upstox expired weekly options, 1-minute candles), for the CEO's rule: at most two lots,
bought calls and/or puts, or hedged pairs.

Structures (legs: B = buy, S = sell; offsets in index points from the at-the-money strike, positive = toward in the money):
  buy2      2 lots of the signal's option (call on an up signal, put on a down signal), at the money or in the money by `itm`.
  hedge     1 lot of the signal's option at the money + 1 lot of the opposite option `wing` points out of the money (protection).
  spread    debit spread: buy 1 lot at the money, sell 1 lot `wing` points further out, same side (the sold leg is covered by the bought one).
  straddle  1 call + 1 put at the money (both directions).
  strangle  1 call + 1 put, each `wing` points out of the money.
Expiry: the nearest weekly with at least `min_dte` trading days left; a position still open on the day before expiry is closed at 15:15 and
reopened on the next expiry (a roll, with its own costs). Fills: the option's 1-minute close at the time, plus slippage (0.3%, at least
Rs 0.10) against us on every fill; full charges per leg (brokerage, STT, exchange, SEBI, stamp, GST). Optional stop and target on the
position's value (checked every minute). Nothing here places an order.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..backtest.costs import charges
from ..backtest.straddle_engine import _minute, _price_at, _series

STEP = 50
STRUCTURES = ("buy2", "hedge", "spread", "straddle", "strangle")


class Pricer:
    def __init__(self, bt, log=print):
        self.bt, self.log, self.cache, self.exps, self.fallbacks = bt, log, {}, sorted(bt.expiries), 0

    def series(self, expiry: str, strike: int, kind: str):
        key = (expiry, strike, kind)
        if key not in self.cache:
            meta = next((x for x in self.bt.c.expired_contracts(expiry) if int(x.get("strike_price") or 0) == strike and x.get("instrument_type") == kind), None)
            if not meta:
                self.cache[key] = None
            else:
                E = date.fromisoformat(expiry)
                self.cache[key] = (meta, _series(self.bt.c.expired_candles(meta["instrument_key"], "1minute", E - timedelta(days=13), E)))
        return self.cache[key]

    def px(self, expiry: str, strike: int, kind: str, d: date, t: str, back: int = 20) -> float | None:
        s = self.series(expiry, strike, kind)
        if not s:
            return None
        bars = s[1].get(d) or {}
        if t <= "09:15":                                            # at the open: the first trade of the day (the 09:15 candle's open)
            b = bars.get("09:15")
            return b[1] if b else None
        for k in range(back + 1):                                   # the latest price at or just before t (a thin strike may skip a minute)
            p = _price_at(bars, _minute(t, -k))
            if p is not None:
                return p
        return None

    def spot(self, d: date, t: str) -> float | None:
        bars = self.bt.n1.get(d) or {}
        if t <= "09:15":
            b = bars.get("09:15")
            return b[1] if b else None
        for k in range(16):
            p = _price_at(bars, _minute(t, -k))
            if p is not None:
                return p
        return None

    def expiry_for(self, d: date, min_dte: int) -> str | None:
        tr = self.bt.trading
        for e in self.exps:
            E = date.fromisoformat(e)
            if E >= d and sum(1 for x in tr if d < x <= E) >= min_dte:
                return e
        return None


def legs_for(structure: str, side: int, spot: float, itm: int = 0, wing: int = 200) -> list[tuple]:
    """[(B/S, kind, strike, lots)]; side +1 up, -1 down (ignored by straddle / strangle)."""
    atm = int(round(spot / STEP) * STEP)
    k, ok = ("CE", "PE") if side == 1 else ("PE", "CE")
    toward = lambda kind, pts: atm - pts if kind == "CE" else atm + pts            # in the money by pts (negative pts: out of the money)
    if structure == "buy2":
        return [("B", k, toward(k, itm), 2)]
    if structure == "hedge":
        return [("B", k, atm, 1), ("B", ok, toward(ok, -wing), 1)]
    if structure == "spread":
        return [("B", k, atm, 1), ("S", k, toward(k, -wing), 1)]
    if structure == "straddle":
        return [("B", "CE", atm, 1), ("B", "PE", atm, 1)]
    if structure == "strangle":
        return [("B", "CE", atm + wing, 1), ("B", "PE", atm - wing, 1)]
    raise ValueError(structure)


def _slip(px: float) -> float:
    return max(0.10, 0.003 * px)


def simulate(P: Pricer, trades: list[dict], structure: str, itm: int = 0, wing: int = 200, min_dte: int = 3, stop: float | None = None,
             target: float | None = None) -> list[dict]:
    """trades: [{day, inT, exitDay, outT, side}] from the signal engine. Returns one row per position with real-price P&L."""
    out, tr = [], P.bt.trading
    for s in trades:
        d0, d1 = date.fromisoformat(s["day"]), date.fromisoformat(s["exitDay"])
        t0, t1 = s["inT"], min(s["outT"], "15:25")
        segs, d, t, ok, why = [], d0, t0, True, "signal"
        while ok:
            spot = P.spot(d, t)
            e = P.expiry_for(d, min_dte if d == d0 else 2)
            if not spot or not e:
                ok = False
                break
            L = legs_for(structure, s["side"], spot, itm, wing)
            ent = []
            for side, kind, k, lots in L:
                p = P.px(e, k, kind, d, t)
                meta = P.series(e, k, kind)
                if p is None or p <= 0 or not meta:
                    ok = False
                    break
                ent.append((side, kind, k, lots, p + _slip(p) if side == "B" else p - _slip(p), int(meta[0].get("lot_size") or 75)))
            if not ok:
                break
            E = date.fromisoformat(e)
            roll_day = max((x for x in tr if x < E), default=None)               # the day before expiry: never hold into expiry day
            end_d, end_t, rolled = (d1, t1, False) if (roll_day is None or d1 < roll_day or (d1 == roll_day and t1 <= "15:15")) else (roll_day, "15:15", True)
            # walk minute by minute for the stop / target on the position's value
            base = sum((1 if sd == "B" else -1) * p * lots * lot for sd, kind, k, lots, p, lot in ent)
            x_d, x_t, hit = end_d, end_t, None
            if stop or target:
                days = [x for x in tr if d <= x <= end_d]
                for dd in days:
                    for mi in range(375):
                        tt = _minute("09:16", mi)
                        if (dd == d and tt <= t) or (dd == end_d and tt > end_t):
                            continue
                        vals = [P.px(e, k, kind, dd, tt, back=3) for sd, kind, k, lots, p, lot in ent]
                        if any(v is None for v in vals):
                            continue
                        v = sum((1 if sd == "B" else -1) * vals[j] * lots * lot for j, (sd, kind, k, lots, p, lot) in enumerate(ent))
                        g = (v - base) / abs(base) if base else 0
                        if stop and g <= -stop:
                            x_d, x_t, hit = dd, tt, "stop"
                            break
                        if target and g >= target:
                            x_d, x_t, hit = dd, tt, "target"
                            break
                    if hit:
                        break
            pnl, chg, ex = 0.0, 0.0, []
            for sd, kind, k, lots, p, lot in ent:
                q = P.px(e, k, kind, x_d, x_t)
                if q is None:
                    P.fallbacks += 1
                    q = 0.05 if x_d >= E else p                                      # no print at all: worthless at expiry, else flat (counted)
                q = max(0.05, q - _slip(q) if sd == "B" else q + _slip(q))
                units = lots * lot
                pnl += (q - p) * units if sd == "B" else (p - q) * units
                chg += charges(p * units if sd == "B" else q * units, q * units if sd == "B" else p * units, orders=2)["total"]
                ex.append((kind, k, sd, round(p, 2), round(q, 2), units))
            segs.append({"expiry": e, "from": f"{d} {t}", "to": f"{x_d} {x_t}", "legs": ex, "pnl": round(pnl, 2), "charges": round(chg, 2), "outlay": round(abs(base), 2)})
            if hit:
                why = hit
                break
            if not rolled or (x_d, x_t) >= (d1, t1):
                break
            d, t = roll_day, "15:15"                                             # roll into the next weekly expiry
        if not ok or not segs:
            continue
        net = sum(x["pnl"] - x["charges"] for x in segs)
        out.append({"day": s["day"], "exitDay": segs[-1]["to"][:10], "side": s["side"], "structure": structure, "rolls": len(segs) - 1, "why": why,
                    "outlay": max(x["outlay"] for x in segs), "gross": round(sum(x["pnl"] for x in segs), 2), "charges": round(sum(x["charges"] for x in segs), 2),
                    "net": round(net, 2), "index_pts": s.get("pts"), "segments": segs})
    return out


def stats(rows: list[dict], start_cash: float = 100000.0) -> dict:
    xs = [r["net"] for r in rows]
    if not xs:
        return {"trades": 0}
    w = [x for x in xs if x > 0]
    gp, gl = sum(w), -sum(x for x in xs if x <= 0)
    eq, pk, dd, low = start_cash, start_cash, 0.0, start_cash
    for x in xs:
        eq += x
        pk, low = max(pk, eq), min(low, eq)
        dd = max(dd, pk - eq)
    return {"trades": len(xs), "winRate": round(100 * len(w) / len(xs), 1), "profitFactor": round(gp / gl, 2) if gl else None, "net": round(gp - gl),
            "avg": round((gp - gl) / len(xs)), "worst": round(min(xs)), "best": round(max(xs)), "maxDrawdown": round(dd), "lowestEquity": round(low),
            "endEquity": round(eq), "avgOutlay": round(sum(r["outlay"] for r in rows) / len(rows)), "maxOutlay": round(max(r["outlay"] for r in rows)),
            "charges": round(sum(r["charges"] for r in rows)), "rolls": sum(r["rolls"] for r in rows), **_shape(rows, gp - gl)}


def _shape(rows: list[dict], net: float) -> dict:
    """How the profit is made: the share from the five best trades, the longest losing run, months that made money."""
    xs = [r["net"] for r in rows]
    top5 = sum(sorted(xs, reverse=True)[:5])
    run = cur = 0
    for x in xs:
        cur = cur + 1 if x <= 0 else 0
        run = max(run, cur)
    mon: dict = {}
    for r in rows:
        mon[r["day"][:7]] = mon.get(r["day"][:7], 0) + r["net"]
    return {"top5": round(top5), "top5SharePct": round(100 * top5 / net) if net > 0 else None, "withoutTop5": round(net - top5), "longestLosingRun": run,
            "monthsUp": sum(1 for v in mon.values() if v > 0), "months": len(mon)}
