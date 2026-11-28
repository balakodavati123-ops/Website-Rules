"""EPM, the expected premium move: where an option's price should be if NIFTY makes its expected move, for each strike.

How it is worked out:
 1. Expected NIFTY move (one standard deviation) over a horizon is NIFTY x IV x sqrt(time). IV is the at-the-money implied volatility of the
    expiry, backed out of the at-the-money call and put prices. The horizon is the rest of today, one session, or the time to expiry.
    About two times in three, NIFTY ends the horizon inside that move.
 2. Each strike is repriced with Black-Scholes at NIFTY plus and minus that move, with the time decay of the horizon. Each strike uses its
    own implied volatility, backed out of its own price, so the volatility smile is kept. Prices are taken off the forward NIFTY implied by
    the at-the-money call and put (put-call parity), as the market prices them, not off spot.
 3. Target is the premium if NIFTY moves the expected amount in the option's favour (up for a call, down for a put). Stop is the premium if
    it moves the same amount against. If-flat is the premium if NIFTY does not move (time decay only). Each is the price now plus the
    model's change, so a gap between the model and the market price cancels out.

Time is counted in trading minutes (375 a session, 252 sessions a year), so an option loses its time value during market hours, as NIFTY
weeklies do; weekends and holidays count as no time. Volatility is assumed unchanged over the horizon. A jump in IV (before events) or a
crush (after them) moves premiums beyond this. Nothing here places an order.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

DAY_MIN, YEAR_DAYS = 375, 252
HORIZONS = (("today", "Rest of today"), ("session", "One session"), ("expiry", "To expiry"))


def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S: float, K: float, T: float, sig: float, kind: str) -> float:
    """Black-Scholes price, interest rate zero (NIFTY weeklies are priced off the near future; the difference is a few paise)."""
    if T <= 0 or sig <= 0:
        return max(0.0, S - K) if kind == "CE" else max(0.0, K - S)
    v = sig * math.sqrt(T)
    d1 = (math.log(S / K) + v * v / 2) / v
    d2 = d1 - v
    return S * ncdf(d1) - K * ncdf(d2) if kind == "CE" else K * ncdf(-d2) - S * ncdf(-d1)


def implied_vol(price: float, S: float, K: float, T: float, kind: str) -> float | None:
    """The volatility at which Black-Scholes gives this price (bisection), or None when the price is below its intrinsic value or too thin."""
    if not price or price <= 0 or T <= 0:
        return None
    intrinsic = max(0.0, S - K) if kind == "CE" else max(0.0, K - S)
    if price <= intrinsic + 0.05:
        return None
    lo, hi = 0.005, 3.0
    if bs(S, K, T, hi, kind) < price:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs(S, K, T, mid, kind) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def minutes_left(now: datetime) -> int:
    """Trading minutes left in today's session (09:15-15:30); 0 outside it or at the weekend."""
    if now.weekday() >= 5:
        return 0
    t = now.hour * 60 + now.minute
    return max(0, min(DAY_MIN, 15 * 60 + 30 - max(t, 9 * 60 + 15)))


def trading_minutes_to(expiry: date, now: datetime, holidays: set | None = None) -> int:
    """Trading minutes from now to 15:30 on expiry day (weekdays, minus known holidays)."""
    hol = holidays or set()
    n, d = minutes_left(now) if now.date() <= expiry else 0, now.date() + timedelta(days=1)
    while d <= expiry:
        if d.weekday() < 5 and d.isoformat() not in hol:
            n += DAY_MIN
        d += timedelta(days=1)
    return n


def years(minutes: float) -> float:
    return max(minutes, 1) / DAY_MIN / YEAR_DAYS


def expected_move(S: float, iv: float, minutes: float) -> float:
    """One standard deviation of NIFTY over `minutes` of trading."""
    return S * iv * math.sqrt(years(minutes))


def epm(S: float, K: float, kind: str, premium: float, T_min: float, iv: float, move: float, horizon_min: float) -> dict | None:
    """Target, stop and if-flat premiums for one option. T_min: trading minutes to expiry; horizon_min: trading minutes the move takes."""
    if not premium or premium <= 0 or not iv or T_min <= 0:
        return None
    h = min(horizon_min, T_min)
    T0, T1 = years(T_min), years(T_min - h) if T_min - h > 0 else 0.0
    p0, up, dn, flat = bs(S, K, T0, iv, kind), bs(S + move, K, T1, iv, kind), bs(S - move, K, T1, iv, kind), bs(S, K, T1, iv, kind)
    fav, adv = (up, dn) if kind == "CE" else (dn, up)
    tgt, stp, fl = premium + fav - p0, max(0.05, premium + adv - p0), max(0.05, premium + flat - p0)
    return {"target": round(tgt, 2), "stop": round(stp, 2), "if_flat": round(fl, 2), "gain": round(tgt - premium, 2), "loss": round(premium - stp, 2),
            "rr": round((tgt - premium) / (premium - stp), 2) if premium - stp > 0.01 else None}


def forward(rows: list[dict], S: float) -> float:
    """The forward NIFTY the options are priced off (put-call parity at the strike nearest the money: F = K + call - put). It carries the
    interest and dividend effect that spot misses; without it calls look cheaper and puts dearer than they are. Falls back to spot."""
    if not rows or not S:
        return S
    r = min(rows, key=lambda x: abs(x["k"] - S))
    c, p = r.get("ce"), r.get("pe")
    if not c or not p:
        return S
    f = r["k"] + c - p
    return f if abs(f - S) <= 0.02 * S else S


def atm_iv(rows: list[dict], S: float, T_min: float) -> float | None:
    """ATM implied volatility of an expiry from the call and put nearest the money: rows [{k, ce: price, pe: price}]."""
    if not rows or not S:
        return None
    r = min(rows, key=lambda x: abs(x["k"] - S))
    ivs = [v for v in (implied_vol(r.get("ce"), S, r["k"], years(T_min), "CE"), implied_vol(r.get("pe"), S, r["k"], years(T_min), "PE")) if v]
    return sum(ivs) / len(ivs) if ivs else None


def chain(rows: list[dict], S: float, expiry: date, now: datetime, lot: int, holidays: set | None = None) -> dict:
    """EPM for every strike of one expiry. rows: [{k, ce: price, pe: price}] (mid of bid and ask when both are sound, else last).
    Returns {meta, strikes: {k: {ce: {horizon: epm}, pe: {...}}}}; rupees per lot are the price change times the lot size."""
    T_min = trading_minutes_to(expiry, now, holidays)
    left = minutes_left(now)
    spot, S = S, forward(rows, S)                                  # price off the forward; the expected move is the same in points
    iv0 = atm_iv(rows, S, T_min)
    if not iv0 or T_min <= 0:
        return {"meta": {"ok": False, "why": "no at-the-money price to read the market's volatility from"}, "strikes": {}}
    hz = {"today": left if left >= 15 else 0, "session": DAY_MIN, "expiry": T_min}
    moves = {k: round(expected_move(S, iv0, m), 1) for k, m in hz.items() if m}
    out = {}
    for r in rows:
        k = r["k"]
        for kind in ("CE", "PE"):
            px = r.get(kind.lower())
            iv = implied_vol(px, S, k, years(T_min), kind) if px else None
            if not iv:
                continue
            e = {h: epm(S, k, kind, px, T_min, iv, moves[h], m) for h, m in hz.items() if m}
            for v in e.values():
                if v:
                    v["gain_rs"], v["loss_rs"] = round(v["gain"] * lot), round(v["loss"] * lot)
            out.setdefault(k, {})[kind.lower()] = {"px": px, "iv": round(iv * 100, 1), **e}
    return {"meta": {"ok": True, "atm_iv": round(iv0 * 100, 1), "spot": round(spot, 2), "forward": round(S, 2), "minutes_left": left, "minutes_to_expiry": T_min, "moves": moves,
                     "ranges": {h: [round(spot - m), round(spot + m)] for h, m in moves.items()}, "lot": lot,
                     "horizons": [{"id": h, "name": n} for h, n in HORIZONS if h in moves]}, "strikes": out}
