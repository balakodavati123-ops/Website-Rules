"""The CEO's EMA9 / VWAP crossover on NIFTY, run live on paper as its own F&O book, separate from the long straddle, so the two records
can be compared before anything is decided. Nothing here sends an order.

Same rules as the backtest (quant/src/research/ema_vwap.py, tests check the two agree):
  Signals on 3-minute candles of the near-month NIFTY future, from 09:15: EMA(9) of the close (seeded from the previous session) and VWAP
  anchored to the session on (open + high + low + close) / 4, weighted by volume.
  EMA9 crosses above VWAP at a candle close -> buy the at-the-money call; crosses below -> buy the at-the-money put (nearest weekly expiry).
  Cleaner signals (tested on Oct 2024 - Oct 2026, quant/results/ema_vwap_filters.json): take a crossover only when VWAP itself has moved
  the same way over the last SLOPE_BARS candles, and skip any crossover within COOLDOWN_MIN minutes of the previous one (whipsaw).
  Exits: a 3-minute candle closes beyond EMA9 against the trade, an opposite crossover, the option down 25% (checked on every loop), 15:20.
  Entries 09:21-15:00, one position at a time, one lot; bought at the ask and sold at the bid from the live option chain, full charges.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta

import desks as D
import thesis as T

STRATEGY = "ema_vwap_cross"
RULES = {"slope_bars": 3, "cooldown_min": 30, "stop": 0.25, "first": "09:21", "last": "15:00", "square_off": "15:20", "breach": "close"}


def _m(t: str, d: int) -> str:
    h, m = int(t[:2]), int(t[3:]) + d
    return f"{h + m // 60:02d}:{m % 60:02d}"


def _mins(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:5])


def charges(buy_value: float, sell_value: float, orders: int = 2) -> float:
    """NSE index options, as in the backtest: Rs 20 an order, STT 0.1% of the sell premium, exchange 0.03503%, SEBI 0.0001%, stamp 0.003% on
    the buy, GST 18% on brokerage + exchange + SEBI."""
    brk, txn, sebi = 20.0 * orders, 0.0003503 * (buy_value + sell_value), 0.000001 * (buy_value + sell_value)
    return round(brk + 0.001 * sell_value + txn + sebi + 0.00003 * buy_value + 0.18 * (brk + txn + sebi), 2)


def three_minute(day_bars: dict, upto: str = "15:30") -> list[tuple]:
    """[(start, end, o, h, l, c, v)] from {HH:MM: (o, h, l, c, v)}; only candles whose end is at or before `upto` (complete)."""
    out, t = [], "09:15"
    while t < "15:30" and _m(t, 3) <= upto:
        mins = [day_bars[x] for x in (t, _m(t, 1), _m(t, 2)) if x in day_bars]
        if mins:
            out.append((t, _m(t, 3), mins[0][0], max(x[1] for x in mins), min(x[2] for x in mins), mins[-1][3], sum(x[4] for x in mins)))
        t = _m(t, 3)
    return out


def indicators(bars3: list[tuple], ema0: float | None) -> list[tuple]:
    """[(start, end, o, h, l, c, ema9, vwap)]: EMA carried from ema0 (the previous session's last value), VWAP reset for the session."""
    k, ema, pv, vv, rows = 0.2, ema0, 0.0, 0.0, []
    for s, e, o, h, l, c, v in bars3:
        ema = c if ema is None else ema + k * (c - ema)
        w = v if v > 0 else 1.0
        pv, vv = pv + (o + h + l + c) / 4 * w, vv + w
        rows.append((s, e, o, h, l, c, ema, pv / vv))
    return rows


def signals(rows: list[tuple], slope_bars: int = 0, cooldown_min: int = 0) -> list[dict]:
    """One entry per candle from the second: {i, end, up, dn, take}. `take` is the filtered entry signal, exactly as the backtest decides it."""
    out, last_cross = [], None
    for i in range(1, len(rows)):
        end, ema, vw = rows[i][1], rows[i][6], rows[i][7]
        pe_, pv_ = rows[i - 1][6], rows[i - 1][7]
        up, dn = pe_ <= pv_ and ema > vw, pe_ >= pv_ and ema < vw
        take, why = up or dn, ""
        if take:
            now_ = _mins(end)
            if cooldown_min and last_cross is not None and now_ - last_cross < cooldown_min:
                take, why = False, f"skipped: only {now_ - last_cross} min after the last crossover (needs {cooldown_min})"
            last_cross = now_
            if take and slope_bars and i >= slope_bars:
                sl_ = vw - rows[i - slope_bars][7]
                take = (sl_ > 0) if up else (sl_ < 0)
                if not take:
                    why = f"skipped: VWAP {'fell' if sl_ < 0 else 'rose' if sl_ > 0 else 'was flat'} over the last {slope_bars} candles, against the crossover"
        out.append({"i": i, "end": end, "up": up, "dn": dn, "take": take, "why": why})
    return out


def seed_ema(get, token: str, key: str, today: str) -> float | None:
    """EMA9 at the close of the previous session of the same futures contract, from its 1-minute candles."""
    q = urllib.parse.quote(key, safe="")
    d0 = datetime.fromisoformat(today)
    url = f"https://api.upstox.com/v3/historical-candle/{q}/minutes/1/{(d0 - timedelta(days=1)):%Y-%m-%d}/{(d0 - timedelta(days=8)):%Y-%m-%d}"
    rows = json.loads(get(url, token)).get("data", {}).get("candles", [])
    rows = [r for r in rows if r[0][:10] < today]
    if not rows:
        return None
    last = max(r[0][:10] for r in rows)
    bars = {r[0][11:16]: (float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)) for r in rows if r[0][:10] == last}
    ind = indicators(three_minute(bars), None)
    return ind[-1][6] if ind else None


def _leg_px(rows: list[dict], strike: float, kind: str) -> tuple[float, float]:
    m = D._px(rows, strike, kind)
    return D._sell(m), D._buy(m)


def step(book: dict, now: datetime, ctx: dict, paused: set) -> dict:
    """ctx: {bars1: [[HH:MM, o, h, l, c, v]] today's 1-minute futures candles, ema0, chains: {expiry: rows}, expiry, lot, spot, room, vix, fut}.
    Manages the open EMA trade, then takes a new signal. Returns the view saved to ema_vwap.json."""
    R, st = RULES, book.setdefault("ema_vwap_state", {})
    day, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    if st.get("day") != day:
        st.clear()
        st["day"] = day
    bars = {b[0]: (float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5] or 0)) for b in ctx.get("bars1") or []}
    rows = indicators(three_minute(bars, upto=hhmm), ctx.get("ema0"))
    sig = signals(rows, R["slope_bars"], R["cooldown_min"])
    new = [s for s in sig if s["end"] > st.get("acted", "09:15")]
    view = {"at": now.strftime("%H:%M:%S"), "fut": ctx.get("fut"), "rules": R, "candles": len(rows), "seeded": ctx.get("ema0") is not None,
            "last": [{"end": r[1], "close": round(r[5], 2), "ema9": round(r[6], 2), "vwap": round(r[7], 2)} for r in rows[-40:]],
            "crosses": [{"end": s["end"], "dir": "up" if s["up"] else "down", "taken": s["take"], "why": s["why"]} for s in sig if s["up"] or s["dn"]][-12:]}
    if rows:
        r = rows[-1]
        view["now"] = {"end": r[1], "close": round(r[5], 2), "ema9": round(r[6], 2), "vwap": round(r[7], 2), "side": "EMA9 above VWAP (calls side)" if r[6] > r[7] else "EMA9 below VWAP (puts side)",
                       "vwap_slope": round(r[7] - rows[-1 - R["slope_bars"]][7], 2) if len(rows) > R["slope_bars"] else None}
    if not ctx.get("ema0"):
        view["note"] = "EMA9 could not be seeded from yesterday's futures candles; the desk waits rather than trade a cold EMA"
    late = _mins(hhmm) >= _mins(R["square_off"])
    # 1) the open position: mark it, stop on every loop, EMA9 breach / opposite cross at a new candle close, square off at 15:20
    for tr in book["trades"]:
        if tr.get("strategy") != STRATEGY or tr["status"] != "OPEN":
            continue
        lg, rows_ = tr["legs"][0], (ctx.get("chains") or {}).get(tr["expiry"])
        if not rows_:
            continue
        bid, _ = _leg_px(rows_, lg["strike"], lg["kind"])
        if bid <= 0:
            continue
        lot, entry = tr["lot"], lg["entry"]
        lg["last"] = round(bid, 2)
        pnl = (bid - entry) * lot - charges(entry * lot, bid * lot)
        tr["pnl_rs"], tr["last"] = round(pnl, 2), round(bid - entry, 2)
        why = None
        if bid <= entry * (1 - R["stop"]):
            why = f"stop: the option fell {R['stop']:.0%} (fakeout)"
        elif late:
            why = "time: square-off at 15:20"
        else:
            for s in new:
                c, ema = rows[s["i"]][5], rows[s["i"]][6]
                against = (c < ema) if lg["kind"] == "CE" else (c > ema)
                flip = s["dn"] if lg["kind"] == "CE" else s["up"]
                if against or flip:
                    why = (f"EMA9 breach: the {s['end']} 3-minute candle closed at {c:,.1f}, {'below' if lg['kind'] == 'CE' else 'above'} EMA9 {ema:,.1f}" if against
                           else f"opposite crossover at {s['end']}")
                    break
        if why:
            D.finish(tr, bid - entry, why, now, pnl)
            tr["exit_premium"], tr["charges_rs"] = round(bid, 2), charges(entry * lot, bid * lot)
    # 2) a new filtered crossover opens a trade at the candle's close (bought at the ask on this loop)
    open_ = any(t.get("strategy") == STRATEGY and t["status"] == "OPEN" for t in book["trades"])
    for s in new:
        if open_ or not s["take"] or STRATEGY in paused or not (R["first"] <= s["end"] <= R["last"]) or not ctx.get("ema0"):
            continue
        if _mins(hhmm) - _mins(s["end"]) > 3:
            continue                                                  # a signal older than one candle is stale (the engine was restarting)
        rows_, spot = (ctx.get("chains") or {}).get(ctx.get("expiry")), ctx.get("spot")
        if not rows_ or not spot:
            continue
        kind = "CE" if s["up"] else "PE"
        k = min((x["strike_price"] for x in rows_), key=lambda x: abs(x - spot))
        bid, ask = _leg_px(rows_, k, kind)
        if ask <= 0 or bid <= 0 or ask - bid > max(1.0, 0.12 * (ask + bid) / 2):
            view["skipped"] = f"{s['end']}: no fair two-sided price on the {k:,.0f} {kind}"
            continue
        lot = ctx["lot"]
        cost = round(ask * lot)
        room = ctx.get("room")
        if room is not None and cost > room[0]:
            view["skipped"] = f"{s['end']}: the premium Rs {cost:,} is more than the F&O limit has free (Rs {room[0]:,.0f})"
            continue
        if room is not None:
            room[0] -= cost
        r = rows[s["i"]]
        exp = ctx["expiry"]
        side_txt = "call" if kind == "CE" else "put"
        th = T.pack("intraday", f"NIFTY {k:,.0f} {kind}: EMA9 crossed {'above' if s['up'] else 'below'} VWAP at {s['end']}", [],
                    [f"Near-month NIFTY future ({ctx.get('fut') or 'NIFTY FUT'}) 3-minute candle {r[0]}-{r[1]}: close {r[5]:,.1f}, EMA9 {r[6]:,.1f}, session VWAP {r[7]:,.1f}.",
                     f"VWAP moved {r[7] - rows[s['i'] - R['slope_bars']][7]:+.1f} over the last {R['slope_bars']} candles, the same way as the crossover; no other crossover in the {R['cooldown_min']} minutes before.",
                     f"Bought the at-the-money {side_txt} ({exp} expiry) at the ask {ask:.2f}; bid {bid:.2f}. NIFTY {spot:,.1f}" + (f", India VIX {ctx['vix']:.2f}." if ctx.get("vix") else "."),
                     "Backtest of these exact rules on real 1-minute option prices, Oct 2024 - Oct 2026 (VERIFIED_HISTORICAL): 861 trades, 30.9% won, "
                     "average Rs -38 a trade after Rs 61 of charges; before charges it made Rs +20,199. It has not made money after costs: this paper book is the test."],
                    "EMA9 / VWAP crossover (the CEO's rules, cleaner signals)",
                    [f"A {side_txt} gains if NIFTY keeps moving {'up' if s['up'] else 'down'} after the crossover; the exits cut it the moment the 3-minute trend breaks."],
                    [["Premium", f"Rs {cost:,}"], ["Stop", f"-{R['stop']:.0%} (Rs {round(ask * lot * R['stop']):,})"], ["Target", "none: held while candles close on the right side of EMA9"],
                     ["Exit", "3-min close beyond EMA9, opposite cross, -25% or 15:20"]],
                    "Most crossovers fail: in the backtest about 7 in 10 lost, a few big moves paid for them. Charges are about Rs 60 a round trip.",
                    "Paper only, run beside the straddle for comparison.")
        D.mk(book, "FNO", STRATEGY, f"NIFTY {k:,.0f} {kind} · EMA9/VWAP · {exp[5:]}", "LONG", -ask, 1, now, expiry=exp, lot=lot, horizon="daily", underlying="NIFTY",
             legs=[{"side": "B", "strike": k, "kind": kind, "entry": round(ask, 2), "last": round(bid, 2), "key": D._key(rows_, k, kind)}],
             unit_base=round(ask, 2), target_u=None, stop_u=round(ask * R["stop"], 2), risk_class="Intraday signal · option buying", max_gain_rs=None, max_loss_rs=cost,
             margin_rs=cost, margin_src="premium paid (an option buyer posts only the premium)", thesis=th, book_name="EMA9/VWAP",
             signal={"candle": s["end"], "close": round(r[5], 2), "ema9": round(r[6], 2), "vwap": round(r[7], 2)},
             reason=f"EMA9 crossed {'above' if s['up'] else 'below'} VWAP on the {s['end']} 3-minute candle (VWAP sloping the same way); bought the {k:,.0f} {kind} at {ask:.2f}. "
                    f"Exit on a 3-minute close beyond EMA9, an opposite cross, -25%, or 15:20.")
        open_ = True
    if rows:
        st["acted"] = rows[-1][1]
    return view


def record(trades: list[dict], strategy: str) -> dict:
    """Closed-trade record of one book."""
    c = [t for t in trades if t.get("desk") == "FNO" and t.get("strategy") == strategy and t.get("status") in ("WIN", "LOSS")]
    o = [t for t in trades if t.get("desk") == "FNO" and t.get("strategy") == strategy and t.get("status") == "OPEN"]
    pn = [float(t.get("pnl_rs") or 0) for t in c]
    days = sorted({t["day"] for t in c})
    return {"closed": len(c), "wins": sum(x > 0 for x in pn), "win_rate": round(sum(x > 0 for x in pn) / len(pn) * 100, 1) if pn else None, "total_rs": round(sum(pn)),
            "avg_rs": round(sum(pn) / len(pn)) if pn else None, "best_rs": round(max(pn)) if pn else None, "worst_rs": round(min(pn)) if pn else None,
            "sessions": len(days), "since": days[0] if days else None, "open": len(o), "open_rs": round(sum(float(t.get("pnl_rs") or 0) for t in o)),
            "trades": [{k: t.get(k) for k in ("id", "day", "opened", "closed", "label", "status", "pnl_rs", "why", "entry", "exit_premium", "legs")} for t in sorted(c + o, key=lambda t: (t["day"], t["opened"]))[-25:]]}
