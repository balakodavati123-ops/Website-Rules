"""Today's forecast for the indexes (Nifty 50, Bank Nifty), with the reasons, and a daily scorecard so the method is judged by results.

The view is a weighted score from six things that are public and checkable: the overnight world tone, the index's own trend,
where it closed in yesterday's range, the option-chain picture (put-to-call ratio and max pain), what foreign institutions hold in
index futures, and the change in India VIX. At 09:16 the opening gap is added. The expected range comes from India VIX: a
one-standard-deviation day. The weights are our own and unproven; each evening the forecast is compared with what happened and the
running hit-rate is shown beside it. It is a way to organise evidence, not a prediction service. Nothing here places an order.
"""
from __future__ import annotations

import json
import math
import urllib.parse
from datetime import date, timedelta

import upstox as U

WEIGHTS = {"world": 0.25, "trend": 0.20, "range": 0.10, "gap": 0.15, "options": 0.15, "fii": 0.10, "vix": 0.05}
clip = lambda x, a=-1.0, b=1.0: max(a, min(b, x))


def daily(token: str, key: str, today: date, n: int = 400) -> list[list]:
    """Daily candles, oldest first: [date, open, high, low, close]. The last one is today's if the session has started."""
    url = f"https://api.upstox.com/v2/historical-candle/{urllib.parse.quote(key, safe='')}/day/{today}/{today - timedelta(days=n)}"
    c = json.loads(U._get(url, token)).get("data", {}).get("candles", [])
    return [[k[0][:10], k[1], k[2], k[3], k[4]] for k in reversed(c)]


def realised_vol(closes: list[float], n: int = 10) -> float | None:
    r = [math.log(closes[i] / closes[i - 1]) for i in range(max(1, len(closes) - n), len(closes))]
    if len(r) < 3:
        return None
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252) * 100


def pivots(h: float, l: float, c: float) -> dict:
    p = (h + l + c) / 3
    return {"P": round(p), "R1": round(2 * p - l), "S1": round(2 * p - h), "R2": round(p + h - l), "S2": round(p - (h - l))}


def view(name: str, hist: list[list], today: str, tone: dict, vix: float | None, vix_chg: float | None, chain: dict, fii: dict | None, open_px: float | None,
         sigma_pct: float | None = None, headlines: list[str] | None = None) -> dict:
    """hist: daily candles up to and including the last completed session (today's candle, if present, is ignored)."""
    h = [x for x in hist if x[0] < today]
    if len(h) < 25:
        return {}
    last = h[-1]
    closes = [x[4] for x in h]
    prev = closes[-1]
    ma20, ret5 = sum(closes[-20:]) / 20, closes[-1] / closes[-6] - 1
    parts: dict[str, tuple[float, str]] = {}
    ts, stale = (tone or {}).get("score"), None
    ao = str((tone or {}).get("as_of") or "")
    if ao:
        age = (date.fromisoformat(today) - date.fromisoformat(ao)).days
        if age > 4:
            stale, ts = age, None
    if stale:
        parts_note = f"World-market data is {stale} days old (last close {ao}), so it is left out of today's score until it refreshes."
    if ts is not None:
        parts["world"] = (clip(ts / 0.8), f"World tone is {tone.get('label', '').lower()}: US and Asia weighted average {ts:+.2f}% at the {(ao[8:10] + "/" + ao[5:7]) if ao else "last"} close" + (f"; {tone['notes'][2].rstrip('.')}" if len(tone.get("notes", [])) > 2 else "") + ".")
    trend = clip((prev / ma20 - 1) / 0.03) * 0.5 + clip(ret5 / 0.03) * 0.5
    parts["trend"] = (trend, f"{name} closed at {prev:,.0f}, {(prev / ma20 - 1) * 100:+.1f}% from its 20-day average ({ma20:,.0f}) and {ret5 * 100:+.1f}% over five sessions: the trend is {'up' if trend > 0.15 else 'down' if trend < -0.15 else 'flat'}.")
    pos = (last[4] - last[3]) / (last[2] - last[3]) if last[2] > last[3] else 0.5
    parts["range"] = (clip((pos - 0.5) * 2), f"Yesterday it closed in the {'upper' if pos > 0.66 else 'lower' if pos < 0.34 else 'middle'} third of its {last[3]:,.0f} to {last[2]:,.0f} range, so buyers or sellers {'held the close' if pos > 0.66 or pos < 0.34 else 'did not win the day'}.")
    if open_px:
        gap = (open_px / prev - 1) * 100
        parts["gap"] = (clip(gap / 0.6), f"It opened at {open_px:,.0f}, {gap:+.2f}% from the previous close.")
    if chain:
        pcr, pain, spot = chain.get("pcr"), chain.get("max_pain"), (open_px or prev)
        c = clip((pcr - 1.0) / 0.4) * 0.5 + clip((pain - spot) / (spot * 0.01)) * 0.5
        parts["options"] = (c, f"Options: put-to-call ratio {pcr} ({'put writers are confident' if pcr > 1.1 else 'call writers dominate' if pcr < 0.8 else 'balanced'}), most call open interest at {chain['call_wall']:,.0f} (ceiling), most put open interest at {chain['put_wall']:,.0f} (floor), max pain {pain:,.0f}.")
    if fii:
        d = fii.get("d_fut", 0)
        f = clip(fii["fut"] / 100000) * 0.5 + clip(d / 25000) * 0.5
        parts["fii"] = (f, f"Foreign institutions are net {'short' if fii['fut'] < 0 else 'long'} {abs(fii['fut']):,} index futures, {'adding' if abs(d) >= 5000 and (d < 0) == (fii['fut'] < 0) else 'cutting' if abs(d) >= 5000 else 'little changed'} "
                          f"({d:+,} over {fii.get('window', 'the last few')} sessions): {'a persistent bearish tilt' if f < -0.15 else 'a bullish tilt' if f > 0.15 else 'no strong tilt'}.")
    if vix_chg is not None and vix:
        parts["vix"] = (clip(-vix_chg / 5), f"India VIX {vix:.1f} ({vix_chg:+.1f}%): {'fear is rising' if vix_chg > 1.5 else 'fear is easing' if vix_chg < -1.5 else 'steady'}.")
    wsum = sum(WEIGHTS[k] for k in parts)
    score = sum(parts[k][0] * WEIGHTS[k] for k in parts) / wsum if wsum else 0.0
    bias = "Bullish" if score >= 0.2 else "Bearish" if score <= -0.2 else "Sideways"
    sig = (sigma_pct or ((vix or 15) / math.sqrt(252))) / 100 * prev
    centre = prev + score * 0.30 * sig
    reasons = [parts[k][1] for k in sorted(parts, key=lambda k: -abs(parts[k][0] * WEIGHTS[k]))] + ([parts_note] if stale else [])
    lv = pivots(last[2], last[3], last[4])
    lo, hi = centre - sig, centre + sig
    res = [lv["R1"], chain.get("call_wall")] if chain else [lv["R1"]]
    sup = [lv["S1"], chain.get("put_wall")] if chain else [lv["S1"]]
    play = (f"Above {lv['R1']:,} the day favours buyers (next stop {lv['R2']:,}); below {lv['S1']:,} sellers take over (next {lv['S2']:,}). "
            f"Between them expect a range day: the edges {lo:,.0f} and {hi:,.0f} are where moves have usually run out of fuel.")
    return {"name": name, "bias": bias, "score": round(score, 2), "confidence": "Higher" if abs(score) >= 0.45 else "Moderate" if abs(score) >= 0.2 else "Low", "prev_close": round(prev), "centre": round(centre),
            "lo": round(lo), "hi": round(hi), "lo2": round(centre - 2 * sig), "hi2": round(centre + 2 * sig), "sigma_pts": round(sig), "sigma_pct": round(sig / prev * 100, 2),
            "pivots": lv, "resistance": sorted({round(x) for x in res if x}), "support": sorted({round(x) for x in sup if x}),
            "parts": {k: round(v[0], 2) for k, v in parts.items()}, "reasons": reasons, "playbook": play, "headlines": (headlines or [])[:3], "rv": round(realised_vol(closes) or 0, 1), "stage": 2 if open_px else 1}


def score_day(v: dict, o: float | None, h: float, l: float, c: float) -> dict:
    """Compare one forecast with what the index actually did."""
    chg = (c / v["prev_close"] - 1) * 100
    right = (chg > 0.1 and v["bias"] == "Bullish") or (chg < -0.1 and v["bias"] == "Bearish") or (abs(chg) < 0.35 and v["bias"] == "Sideways")
    return {"name": v["name"], "day": v.get("day"), "bias": v["bias"], "score": v["score"], "prev_close": v["prev_close"], "lo": v["lo"], "hi": v["hi"], "open": o, "high": h, "low": l, "close": c,
            "chg_pct": round(chg, 2), "direction_right": bool(right), "close_in_range": bool(v["lo"] <= c <= v["hi"]), "high_in_range": bool(h <= v["hi2"]), "low_in_range": bool(l >= v["lo2"])}


def record(hist: list[dict], rows: list[dict], day: str) -> list[dict]:
    return [x for x in hist if x["day"] != day or x["name"] not in {r["name"] for r in rows}] + rows


def hit_rate(hist: list[dict], name: str) -> dict:
    rows = [x for x in hist if x["name"] == name]
    n = len(rows)
    return {"days": n, "direction": round(sum(x["direction_right"] for x in rows) / n * 100) if n else None, "range": round(sum(x["close_in_range"] for x in rows) / n * 100) if n else None}


def build(token: str, today: date, hists: dict, names: dict, tone: dict, vix: float | None, vix_chg: float | None, chains: dict, fii: dict | None, opens: dict, headlines: list[str]) -> dict:
    """Both indexes at once. hists/chains/opens are keyed by index name; Bank Nifty's one-day range is scaled from VIX by how much more it has been moving."""
    out, rv = {}, {k: realised_vol([x[4] for x in h if x[0] < today.isoformat()]) for k, h in hists.items()}
    for nm in names:
        h = hists.get(nm) or []
        base = (vix or 15) / math.sqrt(252)
        k = clip((rv[nm] / rv["Nifty 50"]) if rv.get(nm) and rv.get("Nifty 50") else 1.0, 1.0, 1.6) if nm != "Nifty 50" else 1.0
        v = view(nm, h, today.isoformat(), tone, vix, vix_chg, chains.get(nm) or {}, fii, opens.get(nm), base * k, headlines)
        if v:
            v["day"] = today.isoformat()
            out[nm] = v
    return out
