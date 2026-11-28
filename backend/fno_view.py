"""What the F&O desk thinks about NIFTY today, written for someone who does not trade, plus a snapshot of the NIFTY option chain.

view(): the day's mode (from India VIX), the desk's call (up, down or no clear direction), the range NIFTY is likely to stay inside, and the
reasons in plain words. The call is the desk's own decision rule (desks.straddle_conditions): the direction of the morning's move from the open
(0.15%+), else the move since yesterday's close (0.3%+), else the opening gap (0.3%+); otherwise no direction. Until 10:00 it is an early
read; at 10:00 the desk decides and its trade tilt is frozen for the day. Given today's macro read (backend/macro.py), the headline call
is instead the live all-factor call, updated every minute, and the desk's tilt is kept as its own line. The likely range is one standard deviation of the move India VIX implies
(VIX / sqrt(252) for a full day, scaled by the square root of the time left): about two days in three NIFTY stays inside it.

chain_snapshot(): strikes around the index for one expiry, each side's last price, best bid and ask with quantities, volume, open interest and
its change today, five levels of the order book for the strikes nearest the money, and each strike's EPM (expected premium move, backend/epm.py):
its price if NIFTY moves its expected amount in its favour (target), against it (stop), or not at all, over the rest of today, one session, or
to expiry. trade_epm(): the same for every open option trade, as the position's P/L if NIFTY rises, falls or stays put.
"""
from __future__ import annotations

import math
from datetime import date, datetime

import epm as EPM

MODES = ((13.0, "MODE_1_QUIET", "Quiet", "a calm market with small, slow moves"),
         (18.0, "MODE_2_VOLATILE", "Volatile", "a normal, lively market"),
         (1e9, "MODE_3_HIGH_VOLATILITY", "Highly volatile", "a nervous market with big, fast moves either way"))


def mode(vix: float | None) -> dict:
    if not vix:
        return {"code": None, "name": "Not known yet", "plain": "India VIX is not available yet."}
    for lim, code, name, plain in MODES:
        if vix < lim:
            return {"code": code, "name": name, "plain": plain, "vix": round(vix, 2)}


def minutes_left(now: datetime) -> int:
    t = now.hour * 60 + now.minute
    return max(0, min(375, 15 * 60 + 30 - max(t, 9 * 60 + 15)))


def sigma_pts(level: float, vix: float, minutes: float = 375) -> float:
    return level * vix / 100 / math.sqrt(252) * math.sqrt(max(minutes, 0) / 375)


def _pts(x: float) -> str:
    return f"{abs(x):,.0f} point" + ("" if round(abs(x)) == 1 else "s")


def _epoch(now: datetime, hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return int(now.replace(hour=h, minute=m, second=0, microsecond=0).timestamp())


def view(now: datetime, spot: float, prev: float | None, ohlc: dict, vix: float | None, feats: dict, cond: dict | None, decided: dict | None,
         news: dict | None, trade: dict | None = None, macro: dict | None = None) -> dict:
    """feats: vix (yesterday), vix_chg %, gap %, move_open_pct, range_pct. cond: desks.straddle_conditions now. decided: the desk's straddle sheet
    once booked today ({at, spot, conditions}). news: {strong, net, macro, mood, fc}. trade: today's straddle (id, label, status, legs...).
    macro: today's backend/macro.py read. With it, the headline call is the live all-factor call (world markets, crude, the rupee, NIFTY's own
    move; updated every minute, with its measured hit rate) and the desk's 10:00 trade rule is shown as its own line."""
    news, feats = news or {}, feats or {}
    c = (decided or {}).get("conditions") or cond or {}
    lean = int(c.get("lean") or 0)
    final = bool(decided)
    md = mode(vix)
    op = float(ohlc.get("open") or 0) or None
    base = op or prev or spot                                          # the day's range is centred on today's open (a gap moves the whole day)
    day_sd = sigma_pts(base, vix) if vix else None
    left = minutes_left(now)
    rem_sd = sigma_pts(spot, vix, left) if vix else None
    direction = {1: "UP", -1: "DOWN"}.get(lean, "SIDEWAYS")
    head = {"UP": "NIFTY is more likely to rise than fall today", "DOWN": "NIFTY is more likely to fall than rise today",
            "SIDEWAYS": "No clear direction yet: the desk expects movement but cannot tell which way"}[direction]
    why: list[str] = []
    if prev:
        ch = spot - prev
        why.append(f"NIFTY is at {spot:,.0f}, {'up' if ch >= 0 else 'down'} {_pts(ch)} ({ch / prev * 100:+.2f}%) from yesterday's close of {prev:,.0f}.")
    if op and prev:
        g, mo = op - prev, spot - op
        gap_txt = "opened almost where it closed yesterday" if abs(g) < prev * 0.001 else f"opened {_pts(g)} {'higher' if g > 0 else 'lower'} than yesterday's close"
        mv_txt = "has hardly moved since" if abs(mo) < spot * 0.0005 else f"has {'risen' if mo > 0 else 'fallen'} {_pts(mo)} since"
        why.append(f"This morning it {gap_txt} and {mv_txt}.")
    if vix:
        vc = feats.get("vix_chg")
        trend = "" if vc is None or abs(vc) < 2 else f" ({'up' if vc > 0 else 'down'} {abs(vc):.0f}% since yesterday: traders expect {'bigger' if vc > 0 else 'smaller'} moves than before)"
        why.append(f"India VIX, the market's 'fear gauge', is {vix:.1f}{trend}. That points to {md['plain']}: NIFTY could move about {_pts(day_sd)} up or down over the whole day.")
    if news.get("strong"):
        good, bad = (news["strong"] + (news.get("net") or 0)) // 2, (news["strong"] - (news.get("net") or 0)) // 2
        why.append(f"In the last hour our news readers found {news['strong']} strong headline{'s' if news['strong'] != 1 else ''}: {good} good and {bad} bad for the market.")
    if news.get("macro"):
        why.append("Big news for the whole market today: " + news["macro"][0].rstrip(".") + ".")
    team = []
    if news.get("fc") is not None:
        team.append("our forecast team's view is " + ("positive" if news["fc"] > 0.15 else "negative" if news["fc"] < -0.15 else "neutral"))
    if news.get("mood"):
        team.append(f"the morning news brief reads the mood as {news['mood']}")
    if team:
        why.append("Also: " + " and ".join(team) + ".")
    basis = {"UP": "rising", "DOWN": "falling"}.get(direction)
    if basis:
        src = c.get("basis", "")
        what = "the move since this morning's open" if "open" in src else "the move since yesterday's close" if "close" in src else "the opening gap"
        why.append(f"The desk follows {what}, which is {basis}, so it expects more of the same today." + (" Some of the news points the other way." if c.get("news_against") else ""))
    else:
        why.append("NIFTY has not moved enough this morning (less than about 0.15%) to pick a side.")
    plan = ("At 10:00 the desk buys two contracts on NIFTY for this week: a call, which makes money if NIFTY rises, and a put, which makes money if it "
            "falls. A big enough move either way pays more than the two cost together. " +
            {"UP": "It tilts the pair toward a rise, so a rise pays more than a fall.", "DOWN": "It tilts the pair toward a fall, so a fall pays more than a rise."}.get(
                direction, "It does not tilt the pair either way.") + " It takes profit at +50%, cuts the loss at -35%, and closes everything by 15:15. All trades are on paper.")
    status = (f"Decided at {decided.get('at')} with NIFTY at {float(decided.get('spot') or 0):,.0f}" if final else
              "Early read: the desk watches the first 45 minutes and decides at 10:00" if now.strftime("%H:%M") < "10:00" else "Live read")
    pred = {"direction": direction, "headline": head, "confidence": c.get("confidence"), "spot": round(spot, 2),
            "day_range": [round(base - day_sd), round(base + day_sd)] if day_sd else None,
            "close_range": [round(spot - rem_sd), round(spot + rem_sd)] if rem_sd and left else None}
    mc = (macro or {}).get("call")
    if mc:
        tilt = {"UP": "toward a rise", "DOWN": "toward a fall"}.get(direction, "neither way")
        pred.update(direction=mc["direction"], headline=mc["headline"], confidence=mc.get("confidence"), basis=mc.get("basis"), measured=mc.get("measured"),
                    hit=mc.get("hit"), source="all factors", desk_lean=direction)
        direction = mc["direction"]
        lean = {"UP": 1, "DOWN": -1}.get(direction, 0)
        extra = [r for r in (macro.get("reasons") or [])[1:] if not r.startswith("Today's headlines")][:5]
        why = why[:1] + [f"Live call, all factors: {mc['headline'].lower()}. {mc.get('basis', '')}. {mc.get('measured', '')}"] + extra + why[1:]
        why = [w for w in why if not w.startswith("The desk follows ") and not w.startswith("NIFTY has not moved enough")]
        why.append(f"The desk's 10:00 trade uses its own rule (the morning's move from the open): it tilts {tilt}.")
    out = {"at": now.strftime("%H:%M:%S"), "day": now.strftime("%Y-%m-%d"), "mode": md, "status": status, "final": final,
           "prediction": pred, "why": why, "plan": plan, "trade": trade}
    lv = [{"px": round(prev, 2), "label": "Yesterday's close", "kind": "ref"}] if prev else []
    if op:
        lv.append({"px": round(op, 2), "label": "Today's open", "kind": "ref"})
    if final and decided.get("spot"):
        lv.append({"px": round(float(decided["spot"]), 2), "label": f"Desk decided here ({decided.get('at')})", "kind": "ref"})
    fc = []
    if rem_sd and left >= 5:
        fc = [{"t": _epoch(now, "15:30"), "px": round(spot + rem_sd, 2), "label": "Likely high by close"},
              {"t": _epoch(now, "15:30"), "px": round(spot - rem_sd, 2), "label": "Likely low by close"}]
        if lean:
            fc.append({"t": _epoch(now, "15:15"), "px": round(spot + lean * 0.5 * rem_sd, 2), "label": f"{'Live' if mc else 'Desk' + chr(39) + 's'} call: {direction.lower()}"})
    out["chart"] = {"levels": lv, "forecast": fc}
    return out


def _side(o: dict | None) -> dict:
    o = o or {}
    m, g = o.get("market_data") or {}, o.get("option_greeks") or {}
    oi, poi = m.get("oi"), m.get("prev_oi")
    return {"key": o.get("instrument_key"), "ltp": m.get("ltp"), "cp": m.get("close_price"), "bid": m.get("bid_price"), "bq": m.get("bid_qty"),
            "ask": m.get("ask_price"), "aq": m.get("ask_qty"), "vol": m.get("volume"), "oi": oi, "doi": (oi - poi) if oi is not None and poi is not None else None,
            "iv": g.get("iv")}


def depth_keys(rows: list[dict], spot: float, n: int = 2) -> list[str]:
    ks = sorted({r["strike_price"] for r in rows}, key=lambda k: abs(k - spot))[: 2 * n + 1]
    out = []
    for r in rows:
        if r["strike_price"] in ks:
            out += [x for x in ((r.get("call_options") or {}).get("instrument_key"), (r.get("put_options") or {}).get("instrument_key")) if x]
    return out


def _px(side: dict) -> float | None:
    """The price to value an option at: the middle of the best bid and ask when the quote is sound, else the last trade."""
    b, a, l = side.get("bid") or 0, side.get("ask") or 0, side.get("ltp") or 0
    if b > 0 and a > 0 and a >= b and (a - b) <= max(1.0, 0.05 * (a + b) / 2):
        return round((a + b) / 2, 2)
    return l or None


def add_epm(out: list[dict], spot: float, expiry: str, lot: int, now: datetime) -> dict:
    """EPM (backend/epm.py) for every strike in the snapshot, written into each side as side['epm'] = {horizon: {target, stop, ...}}."""
    try:
        E = date.fromisoformat(expiry)
    except Exception:
        return {"ok": False, "why": "no expiry"}
    res = EPM.chain([{"k": r["k"], "ce": _px(r["ce"]), "pe": _px(r["pe"])} for r in out], spot, E, now, lot)
    for r in out:
        x = res["strikes"].get(r["k"]) or {}
        for s_ in ("ce", "pe"):
            if x.get(s_):
                r[s_]["epm"] = x[s_]
    return res["meta"]


def trade_epm(trades: list[dict], chains: dict, spot: float, now: datetime) -> dict:
    """For each open NIFTY option trade: what each leg should be worth, and the position's P/L, if NIFTY moves its expected amount up,
    down, or not at all over the rest of today (one session when the market is closed). chains: {expiry: Upstox chain rows}."""
    out = {}
    for t in trades:
        if t.get("desk") != "FNO" or t.get("status") != "OPEN" or not t.get("legs") or not chains.get(t.get("expiry")):
            continue
        rows = chains[t["expiry"]]
        snap = [{"k": r["strike_price"], "ce": _px(_side(r.get("call_options"))), "pe": _px(_side(r.get("put_options")))} for r in rows]
        try:
            E = date.fromisoformat(t["expiry"])
        except Exception:
            continue
        T_min = EPM.trading_minutes_to(E, now)
        F = EPM.forward(snap, spot)
        iv0 = EPM.atm_iv(snap, F, T_min)
        left = EPM.minutes_left(now)
        h = left if left >= 15 else EPM.DAY_MIN
        if not iv0 or T_min <= 0:
            continue
        mv = EPM.expected_move(spot, iv0, h)
        units = int(t.get("lot") or 0) * int(t.get("qty") or 1)
        legs, pnl = [], {"up": 0.0, "down": 0.0, "flat": 0.0}
        ok = True
        for l in t["legs"]:
            k, kind = float(l.get("strike") or 0), l.get("kind")
            row = next((x for x in snap if float(x["k"]) == k), None)
            px = row and row[kind.lower()]
            iv = EPM.implied_vol(px, F, k, EPM.years(T_min), kind) if px else None
            e = EPM.epm(F, k, kind, px, T_min, iv, mv, h) if iv else None
            if not e:
                ok = False
                break
            up, dn = (e["target"], e["stop"]) if kind == "CE" else (e["stop"], e["target"])
            sg = 1 if l["side"] == "B" else -1
            for sc, v in (("up", up), ("down", dn), ("flat", e["if_flat"])):
                pnl[sc] += sg * (v - px) * units
            legs.append({"strike": k, "kind": kind, "side": l["side"], "now": px, "if_up": up, "if_down": dn, "if_flat": e["if_flat"],
                         "target": e["target"] if l["side"] == "B" else e["stop"], "stop": e["stop"] if l["side"] == "B" else e["target"]})
        if ok:
            out[t["id"]] = {"move": round(mv), "horizon": "rest of today" if h == left else "one session", "legs": legs,
                            "pnl_if": {k: round(v) for k, v in pnl.items()}}
    return out


def chain_snapshot(rows: list[dict], spot: float, expiry: str, lot: int, now: datetime, quotes: dict | None = None, width: int = 10) -> dict:
    ks = sorted({r["strike_price"] for r in rows})
    if not ks or not spot:
        return {"at": now.strftime("%H:%M:%S"), "expiry": expiry, "rows": []}
    atm = min(ks, key=lambda k: abs(k - spot))
    i = ks.index(atm)
    keep = set(ks[max(0, i - width): i + width + 1])
    out = [{"k": r["strike_price"], "ce": _side(r.get("call_options")), "pe": _side(r.get("put_options"))} for r in sorted(rows, key=lambda r: r["strike_price"]) if r["strike_price"] in keep]
    dep = {}
    for k, q in (quotes or {}).items():
        d = q.get("depth") or {}
        if d:
            dep[k] = {"buy": [[x.get("price"), x.get("quantity"), x.get("orders")] for x in d.get("buy") or []][:5],
                      "sell": [[x.get("price"), x.get("quantity"), x.get("orders")] for x in d.get("sell") or []][:5],
                      "tbq": q.get("total_buy_quantity"), "tsq": q.get("total_sell_quantity")}
    meta = add_epm(out, spot, expiry, lot, now)
    return {"at": now.strftime("%H:%M:%S"), "day": now.strftime("%Y-%m-%d"), "expiry": expiry, "spot": round(spot, 2), "atm": atm, "lot": lot, "rows": out, "depth": dep, "epm": meta}
