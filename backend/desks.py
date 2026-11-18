"""Paper-trading desks beyond cash equities: MCX commodities, crypto, and NIFTY F&O.

Every desk keeps trades in one shared shape (see mk) so one page and one scoreboard can show them all:
desk, strategy, label, side, entry, last, exit, qty, pnl_rs, status OPEN/WIN/LOSS, reason (why it was
taken) and why (why it was closed). Nothing here places an order; these are paper books.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import thesis as T

IST = timezone(timedelta(hours=5, minutes=30))
PREFIX = {"EQUITY": "E", "COMMODITY": "M", "CRYPTO": "C", "FNO": "F"}


def mins(hhmm: str) -> int:
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


def new_book() -> dict:
    return {"trades": [], "seen": {}, "seq": 0}


def mk(book: dict, desk: str, strategy: str, label: str, side: str, entry: float, qty: float, now: datetime, **kw) -> dict:
    book["seq"] += 1
    t = {"id": f"{PREFIX[desk]}{now:%y%m%d}-{book['seq']}", "desk": desk, "strategy": strategy, "label": label, "side": side, "entry": round(entry, 4),
         "last": round(entry, 4), "qty": qty, "status": "OPEN", "pnl_rs": 0.0, "exit": "", "why": "", "day": now.strftime("%Y-%m-%d"),
         "opened": now.strftime("%H:%M:%S"), "closed": "", "ts": time.time()}
    t.update(kw)
    book["trades"].append(t)
    return t


def finish(t: dict, px: float, why: str, now: datetime, pnl: float) -> None:
    t.update(exit=round(px, 4), last=round(px, 4), why=why, pnl_rs=round(pnl, 2), status="WIN" if pnl > 0 else "LOSS", closed=now.strftime("%H:%M:%S"))


def _get_json(url: str, timeout: int = 20):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "paper-desk/1.0"}), timeout=timeout).read())


# ---------------------------------------------------------------- commodities (MCX futures)
MCX = [("GOLDPETAL FUT", "Gold 1 g"), ("NATGASMINI FUT", "Natural gas mini"), ("CRUDEOILM FUT", "Crude oil mini"), ("SILVERMIC FUT", "Silver 1 kg")]   # smallest first, so one big contract cannot use the whole limit
MCX_RULES = {"move": 0.8, "near": 0.003, "stop": 0.006, "target": 0.012, "close": "23:15", "open": "09:15", "last_entry": "22:30", "max_open": 4, "notional": 60000}


ROLL_DAYS = 5          # a contract this close to expiry carries tender-period margin and thin trading: the desk uses the next one


def mcx_contracts(ins: list[dict], today) -> list[dict]:
    out = []
    for pre, name in MCX:
        c = [x for x in ins if x.get("instrument_type") == "FUT" and x["trading_symbol"].startswith(pre) and (datetime.fromtimestamp(x["expiry"] / 1000, IST).date() - today).days >= ROLL_DAYS]
        if c:
            x = min(c, key=lambda y: y["expiry"])
            out.append({"key": x["instrument_key"], "label": name, "symbol": x["trading_symbol"], "mult": float(x.get("qty_multiplier") or 1)})
    return out


WORLD_OF = {"Gold 1 g": "Gold", "Silver 1 kg": "Silver", "Crude oil mini": "Brent crude"}


def mcx_step(book: dict, now: datetime, q: dict, contracts: list[dict], paused: set, room=None, ctx: dict | None = None) -> None:
    """ctx (optional): {'margin': Margin, 'env': market context, 'acct': account equity}. With a margin checker a trade opens only if the broker's own margin for it fits the room."""
    R, t = MCX_RULES, mins(now.strftime("%H:%M"))
    ctx = ctx or {}
    by = {c["key"]: c for c in contracts}
    for tr in book["trades"]:
        if tr["desk"] != "COMMODITY" or tr["status"] != "OPEN" or tr["key"] not in q:
            continue
        px = q[tr["key"]]["last_price"]
        d = 1 if tr["side"] == "LONG" else -1
        tr["last"] = px
        pnl = d * (px - tr["entry"]) * tr["mult"] * tr["qty"] - 0.0005 * tr["entry"] * tr["mult"] * tr["qty"]
        tr["pnl_rs"] = round(pnl, 2)
        hit = px <= tr["stop"] if d == 1 else px >= tr["stop"]
        tgt = px >= tr["target_px"] if d == 1 else px <= tr["target_px"]
        if hit or tgt or t >= mins(R["close"]):
            finish(tr, px, "stop" if hit else "target" if tgt else "time", now, pnl)
    if not (mins(R["open"]) <= t < mins(R["last_entry"])):
        return
    day = now.strftime("%Y-%m-%d")
    for c in contracts:
        v = q.get(c["key"])
        if not v or not v.get("last_price") or book["seen"].get(f"{day}|{c['symbol']}") or sum(x["status"] == "OPEN" and x["desk"] == "COMMODITY" for x in book["trades"]) >= R["max_open"]:
            continue
        px, net, oh = v["last_price"], v.get("net_change"), v.get("ohlc") or {}
        if net is None or px - net <= 0:
            continue
        chg, hi, lo = net / (px - net) * 100, oh.get("high") or px, oh.get("low") or px
        strat, stop_p, tgt_p, why = None, R["stop"], R["target"], ""
        if "mcx_momentum" not in paused and (chg >= R["move"] and px >= hi * (1 - R["near"]) or chg <= -R["move"] and px <= lo * (1 + R["near"])):
            up = chg > 0
            strat, why = "mcx_momentum", f"{chg:+.1f}% on the previous close and within 0.3% of the day {'high' if up else 'low'}; stop 0.6%, target 1.2%"
        elif "mcx_pullback" not in paused and ((chg >= 0.5 and hi * 0.988 <= px <= hi * 0.996) or (chg <= -0.5 and lo * 1.004 <= px <= lo * 1.012)):
            up, stop_p, tgt_p = chg > 0, 0.005, 0.009
            strat, why = "mcx_pullback", f"{chg:+.1f}% on the day and pulled back {abs(px / (hi if up else lo) - 1) * 100:.1f}% from its {'high' if up else 'low'}: buying the dip in an up day, selling the bounce in a down day; stop 0.5%, target 0.9%"
        if not strat:
            continue
        side = "LONG" if up else "SHORT"
        qty = max(1, int(R["notional"] // (px * c["mult"])))
        M, tx = ctx.get("margin"), "BUY" if up else "SELL"
        if M:
            while qty >= 1:                              # the broker's own number for this many lots; fewer lots until it fits
                margin = M.final([(c["key"], qty, tx)])
                if margin is None or room is None or margin <= room[0]:
                    break
                qty -= 1
            if margin is None or qty < 1:
                one = M.final([(c["key"], 1, tx)])
                M.skip("COMMODITY", c["label"], one, room[0] if room else 0, "needs more margin than the commodities limit has free" if one else "margin could not be checked", now)
                continue
            src = "Upstox margin calculator"
        else:
            margin, src = round(px * c["mult"] * qty * 0.06), "estimate (6% of contract value)"
            if room is not None and margin > room[0]:
                continue
        if room is not None:
            room[0] -= margin
        book["seen"][f"{day}|{c['symbol']}"] = side
        stop_px, tgt_px = round(px * (1 - stop_p if up else 1 + stop_p), 2), round(px * (1 + tgt_p if up else 1 - tgt_p), 2)
        unit = c["mult"] * qty
        env = ctx.get("env") or {}
        wr = (env.get("world") or {}).get(WORLD_OF.get(c["label"], ""))
        data = [f"{c['label']} ({c['symbol']}) at {px:,.2f}, {chg:+.2f}% on the previous close; day range {lo:,.2f} to {hi:,.2f}, price is {abs(px / (hi if up else lo) - 1) * 100:.2f}% from the day {'high' if up else 'low'}.",
                f"Lot: {c['mult']:g} unit(s) × {qty} lot(s); contract value {T.inr(px * unit)}."]
        if wr and wr.get("last") is not None:
            data.append(f"Global reference: {wr['name']} {wr['last']} ({wr['chg_pct']:+.2f}% at the {str(wr.get('as_of', ''))[5:]} close).")
        news = [n for n in (env.get("news") or [])[:3]] or ["No commodity-specific headline in our feed today; this trade rests on price action alone."]
        th = T.directional("COMMODITY", strat, "intraday", f"{c['label']} {side.lower()}", side, px, stop_px, tgt_px, abs(px - stop_px) * unit, abs(tgt_px - px) * unit, margin, (ctx.get("acct") or 100000.0), data, news,
                           "Out at the stop, the target, or 23:15, whichever comes first.", f"MCX does not allow API orders at the moment, so a real trade would be keyed in by hand in the Upstox app (instrument key {c['key']}).")
        mk(book, "COMMODITY", strat, f"{c['label']} {side.lower()}", side, px, qty, now, key=c["key"], mult=c["mult"], symbol=c["symbol"], stop=stop_px, target_px=tgt_px, horizon="intraday",
           risk_class="Intraday momentum" if strat == "mcx_momentum" else "Intraday pullback", margin_rs=margin, margin_src=src, thesis=th, reason=why)


# ---------------------------------------------------------------- crypto (spot, long only: Indian retail cannot short spot)
PAIRS = {"BTC": "XBT", "ETH": "ETH", "SOL": "SOL", "XRP": "XRP", "DOGE": "XDG", "ADA": "ADA"}
CRYPTO_RULES = {"move": 1.0, "near": 0.006, "dip": 3.0, "stop": 0.015, "target": 0.03, "max_hours": 8, "notional": 2500, "cost": 0.004, "max_open": 2}


def kraken_ticks() -> dict:
    j = _get_json("https://api.kraken.com/0/public/Ticker?pair=" + ",".join(f"{v}USD" for v in PAIRS.values()))
    out = {}
    for sym, code in PAIRS.items():
        for k, v in j.get("result", {}).items():
            if code in k:
                out[sym] = {"last": float(v["c"][0]), "open": float(v["o"]), "high": float(v["h"][1]), "low": float(v["l"][1])}
    return out


def kraken_ohlc(sym: str, interval: int = 5, last: int = 288) -> list[list]:
    """Recent candles for one coin, oldest first: [HH:MM in IST, open, high, low, close, volume] (5-minute) or [date, ...] (daily)."""
    code = PAIRS[sym]
    j = _get_json(f"https://api.kraken.com/0/public/OHLC?pair={code}USD&interval={interval}")
    rows = next(v for k, v in j["result"].items() if k != "last")
    out = []
    for r in rows[-last:]:
        t = datetime.fromtimestamp(int(r[0]), IST)
        out.append([t.strftime("%H:%M") if interval < 1440 else t.strftime("%Y-%m-%d"), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])])
    return out


def crypto_step(book: dict, now: datetime, ticks: dict, paused: set, room=None, ctx: dict | None = None) -> None:
    R = CRYPTO_RULES
    for tr in book["trades"]:
        if tr["desk"] != "CRYPTO" or tr["status"] != "OPEN" or tr["symbol"] not in ticks:
            continue
        px = ticks[tr["symbol"]]["last"]
        tr["last"] = px
        pnl = (px / tr["entry"] - 1) * R["notional"] - R["cost"] * R["notional"]
        tr["pnl_rs"] = round(pnl, 2)
        stop, tgt, old = px <= tr["stop"], px >= tr["target_px"], time.time() - tr["ts"] > R["max_hours"] * 3600
        if stop or tgt or old:
            finish(tr, px, "stop" if stop else "target" if tgt else "time", now, pnl)
    day = now.strftime("%Y-%m-%d")
    for sym, k in ticks.items():
        if sum(x["status"] == "OPEN" and x["desk"] == "CRYPTO" for x in book["trades"]) >= R["max_open"] or book["seen"].get(f"{day}|{sym}"):
            continue
        chg, px = (k["last"] / k["open"] - 1) * 100, k["last"]
        strat = why = None
        if "crypto_breakout" not in paused and chg >= R["move"] and px >= k["high"] * (1 - R["near"]):
            strat, why = "crypto_breakout", f"{chg:+.1f}% on the day and within 0.6% of the 24-hour high"
        elif "crypto_dip_bounce" not in paused and px <= k["high"] * (1 - R["dip"] / 100) and px >= k["low"] * 1.005 and chg > -6:
            strat, why = "crypto_dip_bounce", f"{(px / k['high'] - 1) * 100:.1f}% below the 24-hour high and already 0.5% off its low"
        if not strat:
            continue
        if room is not None and room[0] < R["notional"]:
            break
        if room is not None:
            room[0] -= R["notional"]
        book["seen"][f"{day}|{sym}"] = strat
        stop_px, tgt_px = round(px * (1 - R["stop"]), 6), round(px * (1 + R["target"]), 6)
        env = ctx.get("env") if ctx else None
        th = T.directional("CRYPTO", strat, "intraday", f"{sym} long", "LONG", px, stop_px, tgt_px, R["notional"] * R["stop"], R["notional"] * R["target"], R["notional"], (ctx or {}).get("acct") or 100000.0,
                           [f"{sym} at ${px:,.2f}, {chg:+.2f}% over the last 24 hours; 24-hour range ${k['low']:,.2f} to ${k['high']:,.2f}.", f"Spot only: ₹{R['notional']:,} of coin, no leverage. Round-trip cost assumed {R['cost'] * 100:.1f}% (exchange fee and spread)."],
                           [n for n in ((env or {}).get("news") or [])[:2]] or ["No crypto headline in our feed; this trade rests on price action alone."], "Out at the stop, the target, or after 8 hours.",
                           "Crypto here is spot only (shorting spot is not possible for Indian retail), trades around the clock on Kraken prices, and is not available through Upstox: a real trade would be on an Indian crypto exchange.")
        mk(book, "CRYPTO", strat, f"{sym} long", "LONG", px, R["notional"], now, symbol=sym, stop=stop_px, target_px=tgt_px, horizon="intraday",
           risk_class="Intraday spot", margin_rs=R["notional"], thesis=th, reason=why + "; stop 1.5%, target 3%, out after 8 hours")


# ---------------------------------------------------------------- NIFTY F&O
RISK = {"fixed": "Fixed return · controlled loss", "hrhl": "High return · high loss", "hrll": "High return · low loss"}
FNO_RULES = {"first": "09:45", "last": "13:30", "close": "15:15", "leg_cost": 40, "trend": 0.25, "breakout": 0.5}


def days_to(expiry: str, now: datetime) -> float:
    try:
        return max(0.25, float((datetime.fromisoformat(expiry).date() - now.date()).days))
    except ValueError:
        return 1.0


def atm_iv(rows: list[dict], spot: float) -> float | None:
    """Implied volatility (percent a year) at the strike nearest the index, averaged over its call and put."""
    if not rows or not spot:
        return None
    r = min(rows, key=lambda x: abs(x["strike_price"] - spot))
    v = [((r.get(s) or {}).get("option_greeks") or {}).get("iv") for s in ("call_options", "put_options")]
    v = [float(x) for x in v if x]
    return sum(v) / len(v) if v else None


def _px(rows: list[dict], strike: float, kind: str) -> dict:
    for r in rows:
        if r["strike_price"] == strike:
            return ((r.get("call_options") if kind == "CE" else r.get("put_options")) or {}).get("market_data") or {}
    return {}


def _key(rows: list[dict], strike: float, kind: str):
    for r in rows:
        if r["strike_price"] == strike:
            return ((r.get("call_options") if kind == "CE" else r.get("put_options")) or {}).get("instrument_key")
    return None


def _buy(m): return float(m.get("ask_price") or 0)
def _sell(m): return float(m.get("bid_price") or 0)


def _build(name: str, spot: float, prev: float, rows: list[dict]):
    """Return (legs, risk class, params) or None. legs: (side 'S'/'B', strike, kind)."""
    ks = sorted({r["strike_price"] for r in rows})
    near = lambda x: min(ks, key=lambda k: abs(k - x))
    chg = (spot / prev - 1) * 100 if prev else 0
    up = chg >= 0
    atm = near(spot)
    if name == "iron_condor":
        sc, sp = near(spot * 1.008), near(spot * 0.992)
        bc, bp = near(sc + 200), near(sp - 200)
        if len({sc, bc}) < 2 or len({sp, bp}) < 2:
            return None
        return [("S", sc, "CE"), ("B", bc, "CE"), ("S", sp, "PE"), ("B", bp, "PE")], "fixed", {"width": max(bc - sc, sp - bp), "target": 0.5, "stop": 1.0}
    if name == "credit_spread":
        if up:
            s = near(spot * 0.994); b = near(s - 150); legs = [("S", s, "PE"), ("B", b, "PE")]
        else:
            s = near(spot * 1.006); b = near(s + 150); legs = [("S", s, "CE"), ("B", b, "CE")]
        return (legs, "fixed", {"width": abs(s - b), "target": 0.5, "stop": 1.0}) if s != b else None
    if name == "long_straddle":
        return [("B", atm, "CE"), ("B", atm, "PE")], "hrhl", {"width": None, "target": 0.5, "stop": 0.35}
    if name == "debit_spread":
        if abs(chg) < FNO_RULES["trend"]:
            return None
        o = near(atm + 150) if up else near(atm - 150)
        return ([("B", atm, "CE"), ("S", o, "CE")] if up else [("B", atm, "PE"), ("S", o, "PE")]), "hrll", {"width": abs(o - atm), "target": 0.6, "stop": 0.4}
    if name == "long_breakout":
        if abs(chg) < FNO_RULES["breakout"]:
            return None
        return [("B", atm, "CE" if up else "PE")], "hrll", {"width": None, "target": 0.5, "stop": 0.3}
    return None


FNO_STRATEGIES = ["iron_condor", "credit_spread", "long_straddle", "debit_spread", "long_breakout"]


def _unit_pnl(legs: list[dict], rows: list[dict]):
    """Per-unit profit if every leg were closed now: buy back shorts at the ask, sell longs at the bid. None if a price is missing."""
    tot = 0.0
    for lg in legs:
        m = _px(rows, lg["strike"], lg["kind"])
        px = _buy(m) if lg["side"] == "S" else _sell(m)
        if lg["side"] == "S" and px <= 0:
            return None
        lg["last"] = round(px, 2)
        tot += (lg["entry"] - px) if lg["side"] == "S" else (px - lg["entry"])
    return tot


def fno_step(book: dict, now: datetime, ctx: dict, paused: set) -> None:
    """ctx: {spot, prev, chains: {expiry: rows}, expiry, lot}"""
    R, t = FNO_RULES, mins(now.strftime("%H:%M"))
    for tr in book["trades"]:
        if tr["desk"] != "FNO" or tr["status"] != "OPEN" or tr.get("horizon", "daily") != "daily":
            continue
        rows = ctx["chains"].get(tr["expiry"])
        if rows is None:
            continue
        u = _unit_pnl(tr["legs"], rows)
        if u is None:
            continue
        pnl = u * tr["lot"] * tr["qty"] - R["leg_cost"] * len(tr["legs"])
        tr["pnl_rs"], tr["last"] = round(pnl, 2), round(u, 2)
        tgt, stp, late = u >= tr["target_u"], u <= -tr["stop_u"], t >= mins(R["close"])
        if tgt or stp or late:
            finish(tr, u, "target" if tgt else "stop" if stp else "time", now, pnl)
    spot, prev, rows, day = ctx.get("spot"), ctx.get("prev"), ctx["chains"].get(ctx["expiry"]), now.strftime("%Y-%m-%d")
    if not (spot and prev and rows) or not (mins(R["first"]) <= t <= mins(R["last"])):
        return
    for name in FNO_STRATEGIES:
        if name in paused or book["seen"].get(f"{day}|{name}"):
            continue
        b = _build(name, spot, prev, rows)
        if not b:
            continue
        legs_def, risk, p = b
        legs, ok = [], True
        for side, strike, kind in legs_def:
            m = _px(rows, strike, kind)
            e = _sell(m) if side == "S" else _buy(m)
            bid, ask = _sell(m), _buy(m)
            if e <= 0 or bid <= 0 or ask - bid > max(1.0, 0.12 * (ask + bid) / 2) or (m.get("volume") is not None and not m.get("volume")):
                ok = False                      # no two-sided market, a wide spread or no trades today: not a price worth trading
                break
            legs.append({"side": side, "strike": strike, "kind": kind, "entry": round(e, 2), "last": round(e, 2), "key": _key(rows, strike, kind)})
        if not ok:
            continue
        net = sum(l["entry"] if l["side"] == "S" else -l["entry"] for l in legs)        # + credit, - debit (points per unit)
        base = abs(net)
        if base < 3 or (risk == "fixed" and (net <= 0 or net < 0.12 * (p["width"] or 1))):
            continue                          # a fixed-return structure must pay at least 12% of its width, or the odds are bad
        lot = ctx["lot"]
        gain = (net if net > 0 else (p["width"] - base if p["width"] else None))
        loss = ((p["width"] - net) if (risk == "fixed") else base if net < 0 else None)
        margin = round(loss * lot) if loss else round(base * lot)
        src, M = "estimate (largest possible loss)", ctx.get("margin")
        if M:
            real = M.final([(l["key"], lot, "BUY" if l["side"] == "B" else "SELL") for l in legs])
            if real is None or (ctx.get("room") is not None and real > ctx["room"][0]):
                M.skip("FNO", f"NIFTY {name.replace('_', ' ')} (daily)", real, ctx["room"][0] if ctx.get("room") is not None else 0,
                       "needs more margin than the F&O limit has free" if real else "margin could not be checked", now)
                continue                              # not viable on this account today: the broker would ask for more than we can post
            margin, src = real, "Upstox margin calculator"
        elif ctx.get("room") is not None and margin > ctx["room"][0]:
            continue                                  # the account cannot carry this structure's margin today
        if ctx.get("room") is not None:
            ctx["room"][0] -= margin
        book["seen"][f"{day}|{name}"] = "booked"
        days = days_to(ctx["expiry"], now)
        th = T.fno(name, "daily", legs, net, spot, prev, ctx.get("iv"), ctx.get("vix"), days, lot, margin, ctx.get("acct") or 100000.0, ctx["expiry"], ctx.get("env") or {},
                   exit_rule=f"Take profit at {p['target']:.0%} of the {'credit' if net > 0 else 'debit'}, cut at {p['stop']:.0%}, and be flat by 15:15 whatever happens.", unit_target=base * p["target"], unit_stop=base * p["stop"])
        mk(book, "FNO", name, f"NIFTY {name.replace('_', ' ')} · {ctx['expiry'][5:]}", "SHORT" if net > 0 else "LONG", net, 1, now, expiry=ctx["expiry"], lot=lot, legs=legs, horizon="daily", underlying="NIFTY",
           unit_base=base, target_u=round(base * p["target"], 2), stop_u=round(base * p["stop"], 2), risk_class=RISK[risk],
           max_gain_rs=round(gain * lot) if gain else None, max_loss_rs=round(loss * lot) if loss else None,
           margin_rs=margin, margin_src=src, thesis=th,
           reason=f"NIFTY {spot:,.0f} ({(spot / prev - 1) * 100:+.2f}% on the close). {'Credit' if net > 0 else 'Debit'} {base:.1f} points; target {p['target']:.0%} of it, stop {p['stop']:.0%} of it; out by 15:15")


# ---------------------------------------------------------------- learning: which strategies earn their place
def learn(trades: list[dict]) -> list[dict]:
    """Per desk and strategy: closed trades, win rate, average rupees per trade, t-statistic, and a verdict the desks obey."""
    g: dict = {}
    for t in trades:
        if t["status"] in ("WIN", "LOSS"):
            g.setdefault((t["desk"], t["strategy"]), []).append(t["pnl_rs"])
    out = []
    for (desk, strat), v in sorted(g.items()):
        n, mean = len(v), sum(v) / len(v)
        sd = math.sqrt(sum((x - mean) ** 2 for x in v) / (n - 1)) if n > 1 else 0
        tstat = mean / (sd / math.sqrt(n)) if sd > 0 else 0
        conf = 0.5 * (1 + math.erf(tstat / math.sqrt(2)))
        verdict = ("PAUSED" if n >= 30 and tstat <= -1.0 else "COLLECTING" if n < 20 else
                   "READY FOR REVIEW" if n >= 100 and conf >= 0.98 and mean > 0 else "WORKING" if mean > 0 else "WEAK")
        out.append({"desk": desk, "strategy": strat, "closed": n, "wins": sum(x > 0 for x in v), "win_rate": round(sum(x > 0 for x in v) / n * 100, 1), "pnl_rs": round(sum(v), 2),
                    "avg_rs": round(mean, 2), "t_stat": round(tstat, 2), "confidence": round(conf * 100, 1), "verdict": verdict})
    return out
