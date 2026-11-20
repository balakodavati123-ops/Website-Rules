"""Live candle charts for the dashboard: one focus instrument per desk (F&O, commodities, equities, crypto), its 1-minute (crypto 5-minute)
candles, the order book, the lines each strategy watches (VWAP, opening range, day high/low, open), the chosen strategy and the trade's
entry, stop, target, exit and forecast exits. Published as candles.json about once a minute. Nothing here trades.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def epoch(day: str, hhmm: str) -> int:
    return int(datetime.strptime(f"{day} {hhmm[:5]}", "%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp())


def upstox_candles(get, token: str, key: str, now: datetime) -> list[list]:
    """Today's 1-minute candles, or the last session's when today has none: [[epoch, o, h, l, c, v]] oldest first."""
    k = urllib.parse.quote(key, safe="")
    rows = []
    try:
        rows = json.loads(get(f"https://api.upstox.com/v3/historical-candle/intraday/{k}/minutes/1", token)).get("data", {}).get("candles", [])
    except Exception:
        rows = []
    if not rows:
        to, fr = (now + timedelta(days=1)).strftime("%Y-%m-%d"), (now - timedelta(days=6)).strftime("%Y-%m-%d")
        try:
            rows = json.loads(get(f"https://api.upstox.com/v3/historical-candle/{k}/minutes/1/{to}/{fr}", token)).get("data", {}).get("candles", [])
        except Exception:
            rows = []
        if rows:
            last = max(r[0][:10] for r in rows)
            rows = [r for r in rows if r[0][:10] == last]
    out = []
    for r in reversed(rows):
        t = datetime.fromisoformat(r[0]).timestamp()
        out.append([int(t), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)])
    return out


def from_hhmm(bars: list[list], day: str) -> list[list]:
    return [[epoch(day, b[0])] + [float(x) for x in b[1:6]] for b in bars]


def depth_upstox(q: dict | None) -> dict | None:
    if not q:
        return None
    d = q.get("depth") or {}
    bids = [[float(x["price"]), float(x["quantity"])] for x in d.get("buy") or [] if x.get("price")]
    asks = [[float(x["price"]), float(x["quantity"])] for x in d.get("sell") or [] if x.get("price")]
    if not bids and not asks:
        return None
    return {"bids": bids[:5], "asks": asks[:5], "buy_qty": float(q.get("total_buy_quantity") or 0), "sell_qty": float(q.get("total_sell_quantity") or 0)}


def lines(c: list[list], prev_close: float | None = None) -> dict:
    """The paths each strategy family watches, one point per candle."""
    pv = vv = 0.0
    vw, hi, lo = [], [], []
    h = l = None
    for b in c:
        pv += (b[2] + b[3] + b[4]) / 3 * (b[5] or 1)
        vv += b[5] or 1
        vw.append([b[0], round(pv / vv, 2)])
        h, l = max(h or b[2], b[2]), min(l or b[3], b[3])
        hi.append([b[0], round(h, 2)])
        lo.append([b[0], round(l, 2)])
    out = {"vwap": ("VWAP", vw), "day_high": ("Day high (momentum long)", hi), "day_low": ("Day low (momentum short)", lo)}
    if len(c) > 15:
        orh, orl = max(b[2] for b in c[:15]), min(b[3] for b in c[:15])
        out["or_high"] = ("Opening range high", [[b[0], round(orh, 2)] for b in c[15:]])
        out["or_low"] = ("Opening range low", [[b[0], round(orl, 2)] for b in c[15:]])
    if c:
        out["open"] = ("Day open (gap)", [[b[0], round(c[0][1], 2)] for b in c])
    return out


CHOSEN = {"scalp_vwap_pullback": "vwap", "vwap": "vwap", "news": "vwap", "gap": "open", "momentum_LONG": "day_high", "momentum_SHORT": "day_low"}


def strategies(c: list[list], trade: dict | None) -> list[dict]:
    ls = lines(c)
    pick = None
    if trade:
        s = str(trade.get("setup") or trade.get("strategy") or "")
        pick = CHOSEN.get(f"{s}_{trade.get('side')}") or CHOSEN.get(s) or ("vwap" if s.startswith("scalp") else None)
    return [{"id": k, "name": n, "chosen": k == pick, "line": v[::2] + v[-1:] if len(v) > 200 else v} for k, (n, v) in ls.items()]


def _t(day: str, hms: str | None) -> int | None:
    return epoch(day, hms) if hms and re.match(r"\d\d:\d\d", str(hms)) else None


def trade_marks(t: dict | None, c: list[list], now: datetime, out_by: str | None = "15:10") -> dict | None:
    if not t or not c:
        return None
    day = str(t.get("day") or now.strftime("%Y-%m-%d"))
    te = _t(day, t.get("opened")) or c[0][0]
    tx = _t(day, t.get("closed")) if t.get("status") in ("WIN", "LOSS") else None
    last = c[-1][4]
    end = epoch(day, out_by) if out_by else c[-1][0] + 3600
    fc = []
    if t.get("target_px"):
        fc.append({"label": "Target", "t": min(end, c[-1][0] + 20 * 60), "px": float(t["target_px"])})
    if t.get("stop"):
        fc.append({"label": "Stop-loss", "t": min(end, c[-1][0] + 12 * 60), "px": float(t["stop"])})
    if t.get("status") == "OPEN" and out_by:
        fc.append({"label": f"Time exit {out_by}", "t": end, "px": round(last, 2)})
    return {"id": t.get("id"), "side": t.get("side"), "label": t.get("label"), "strategy": t.get("strategy"), "entry": [te, float(t.get("entry") or last)],
            "stop": float(t["stop"]) if t.get("stop") else None, "target": float(t["target_px"]) if t.get("target_px") else None,
            "exit": [tx, float(t.get("exit") or last)] if tx else None, "status": t.get("status"), "pnl_rs": float(t.get("pnl_rs") or 0), "forecast": fc if t.get("status") == "OPEN" else []}


def fno_marks(t: dict | None, c: list[list], now: datetime) -> tuple[dict | None, list[dict], list[dict]]:
    """An option structure drawn on the index: the strikes as the chosen line, break-evens as levels, entry where the index was when it was booked."""
    if not t or not c:
        return None, [], []
    day = str(t.get("day") or now.strftime("%Y-%m-%d"))
    te = _t(day, t.get("opened")) or c[0][0]
    spot = next((b[4] for b in c if b[0] >= te), c[-1][4])
    be = []
    for row in ((t.get("thesis") or {}).get("numbers") or []):
        if str(row[0]).lower().startswith("break-even"):
            be = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", str(row[1])) if float(x.replace(",", "")) > 1000]
    strikes = sorted({float(lg["strike"]) for lg in t.get("legs") or []})
    levels = [{"label": f"Break-even {x:,.0f}", "px": x, "kind": "breakeven"} for x in be]
    chosen = [{"id": "structure", "name": f"{str(t.get('strategy', '')).replace('_', ' ')} {'/'.join(f'{s:,.0f}' for s in strikes)}", "chosen": True,
               "line": [[b[0], strikes[len(strikes) // 2]] for b in c if b[0] >= te]}] if strikes else []
    end = epoch(day, "15:15")
    fc = [{"label": f"Profit beyond {x:,.0f}", "t": end, "px": x} for x in be] + ([{"label": "Out by 15:15", "t": end, "px": round(c[-1][4], 2)}] if t.get("status") == "OPEN" else [])
    tx = _t(day, t.get("closed")) if t.get("status") in ("WIN", "LOSS") else None
    mk = {"id": t.get("id"), "side": t.get("side"), "label": t.get("label"), "strategy": "structure", "entry": [te, round(spot, 2)], "stop": None, "target": None,
          "exit": [tx, next((b[4] for b in c if b[0] >= tx), c[-1][4])] if tx else None, "status": t.get("status"), "pnl_rs": float(t.get("pnl_rs") or 0),
          "forecast": fc if t.get("status") == "OPEN" else []}
    return mk, chosen, levels


def focus(trades: list[dict], desk: str, today: str, pred=None) -> dict | None:
    """The trade a desk's chart follows: an open one first, else today's latest."""
    T = [t for t in trades if t.get("desk") == desk and (pred is None or pred(t))]
    opn = [t for t in T if t.get("status") == "OPEN"]
    if opn:
        return max(opn, key=lambda t: (str(t.get("day")), str(t.get("opened"))))
    td = [t for t in T if t.get("day") == today]
    return max(td, key=lambda t: str(t.get("closed") or t.get("opened"))) if td else None


def chart(cid: str, desk: str, symbol: str, label: str, tf: str, c: list[list], depth: dict | None, strats: list[dict], trade: dict | None, levels: list[dict]) -> dict:
    return {"id": cid, "desk": desk, "symbol": symbol, "label": label, "tf": tf, "candles": c[-400:], "last": c[-1][4] if c else None, "depth": depth,
            "strategies": strats, "trade": trade, "levels": levels}
