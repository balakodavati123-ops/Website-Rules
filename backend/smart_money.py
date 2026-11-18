"""Who holds what in index derivatives: NSE's participant-wise open interest (FII, DII, proprietary desks, everyone else) and the option-chain
walls for Nifty and Bank Nifty. Public data, published after each close. It describes positions, not intentions: a put held by an
institution may be insurance on a share portfolio or a bet on a fall, and the number alone cannot say which. The readings below say what
each combination usually means and what else would have to be true. Nothing here places an order.
"""
from __future__ import annotations

import csv
import io
import urllib.request
from datetime import date, timedelta

URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{}.csv"
WHO = {"FII": "Foreign institutions (FPIs)", "DII": "Domestic institutions (mutual funds, insurers)", "Pro": "Proprietary traders and market makers", "Client": "Everyone else (retail, HNIs)"}


def _fetch(d: date) -> dict | None:
    try:
        raw = urllib.request.urlopen(urllib.request.Request(URL.format(d.strftime("%d%m%Y")), headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode()
    except Exception:
        return None
    r = list(csv.reader(io.StringIO(raw)))
    if len(r) < 4:
        return None
    hdr = [h.strip() for h in r[1]]
    out = {}
    for x in r[2:]:
        if x and x[0].strip() in WHO:
            out[x[0].strip()] = {h: int(v) for h, v in zip(hdr[1:], x[1:]) if v.strip() != ""}
    return out or None


def history(today: date, have: dict | None = None, sessions: int = 6) -> dict:
    """{date: {participant: {column: contracts}}} for the last sessions that have a file; reuses what is already stored."""
    rows = dict(have or {})
    d, tries = today, 0
    while len([k for k in rows if k <= today.isoformat()]) < sessions and tries < 16:
        tries += 1
        if d.weekday() < 5 and d.isoformat() not in rows:
            got = _fetch(d)
            if got:
                rows[d.isoformat()] = got
        d -= timedelta(days=1)
    return dict(sorted(rows.items())[-sessions:])


def _g(p: dict, k: str) -> int:
    return int(p.get(k, 0))


def stance(p: dict) -> dict:
    """Net positions in index derivatives for one participant on one day (long minus short)."""
    return {"fut": _g(p, "Future Index Long") - _g(p, "Future Index Short"),
            "calls": _g(p, "Option Index Call Long") - _g(p, "Option Index Call Short"),
            "puts": _g(p, "Option Index Put Long") - _g(p, "Option Index Put Short"),
            "put_long": _g(p, "Option Index Put Long"), "put_short": _g(p, "Option Index Put Short"),
            "call_long": _g(p, "Option Index Call Long"), "call_short": _g(p, "Option Index Call Short")}


def reading(who: str, now: dict, then: dict) -> list[str]:
    """Plain-language reading of one participant's net positions and how they changed over the window."""
    out = []
    fut, calls, puts = now["fut"], now["calls"], now["puts"]
    d_fut = fut - then["fut"]
    if who in ("FII", "Pro"):
        move = "little changed" if abs(d_fut) < 5000 else "adding to the position" if (d_fut < 0) == (fut < 0) else "reducing the position"
        out.append(f"Net index futures {fut:+,}: {'net short' if fut < 0 else 'net long'}, {move} over the window ({d_fut:+,}).")
        syn_short, syn_long = puts > 0 and calls < 0, puts < 0 and calls > 0
        if syn_short:
            out.append(f"Net long puts ({puts:+,}) and net short calls ({calls:+,}) together behave like a short index position: a bearish or a hedged stance, not just insurance.")
        elif syn_long:
            out.append(f"Net short puts ({puts:+,}) and net long calls ({calls:+,}) together behave like a long index position: a bullish stance.")
        else:
            out.append(f"Options are mixed (puts {puts:+,}, calls {calls:+,}): no clear one-way bet in options alone.")
    elif who == "DII":
        out.append(f"Net long puts {puts:+,} with futures {fut:+,}: domestic funds buy index puts to insure their large share portfolios. This is cost-of-doing-business hedging, not a forecast of a fall.")
    else:
        out.append(f"Net short puts {puts:+,} and net calls {calls:+,}: this group is the main seller of puts, collecting premium. When it is crowded one way, a sharp move against it forces losses.")
    return out


def digest(parts: dict) -> dict:
    """Latest day, the change over the window, and a plain reading for each participant."""
    days = sorted(parts)
    if not days:
        return {}
    last, first = days[-1], days[0]
    rows = []
    for w in WHO:
        if w not in parts[last] or w not in parts[first]:
            continue
        n, o = stance(parts[last][w]), stance(parts[first][w])
        rows.append({"who": w, "name": WHO[w], **n, "window": len(days) - 1, "d_fut": n["fut"] - o["fut"], "d_puts": n["puts"] - o["puts"], "d_calls": n["calls"] - o["calls"],
                     "series_fut": [stance(parts[d][w])["fut"] for d in days if w in parts[d]], "series_puts": [stance(parts[d][w])["puts"] for d in days if w in parts[d]],
                     "reading": reading(w, n, o)})
    return {"day": last, "from": first, "participants": rows}


def chain_stats(rows: list[dict]) -> dict:
    """Open-interest picture of one option chain: put-to-call ratio, the strikes with most call and put open interest, max pain, and where new open interest was added today."""
    oi = lambda r, s: float((r.get(s) or {}).get("market_data", {}).get("oi") or 0)
    prev = lambda r, s: float((r.get(s) or {}).get("market_data", {}).get("prev_oi") or 0)
    coi, poi = sum(oi(r, "call_options") for r in rows), sum(oi(r, "put_options") for r in rows)
    if not rows or not coi:
        return {}
    ks = [r["strike_price"] for r in rows]
    pain = min(ks, key=lambda k: sum(max(0, k - r["strike_price"]) * oi(r, "put_options") + max(0, r["strike_price"] - k) * oi(r, "call_options") for r in rows))
    top = lambda s, f: sorted(rows, key=lambda r: -f(r, s))[:3]
    return {"pcr": round(poi / coi, 2), "call_oi": int(coi), "put_oi": int(poi), "call_wall": top("call_options", oi)[0]["strike_price"], "put_wall": top("put_options", oi)[0]["strike_price"], "max_pain": pain,
            "call_walls": [[r["strike_price"], int(oi(r, "call_options"))] for r in top("call_options", oi)], "put_walls": [[r["strike_price"], int(oi(r, "put_options"))] for r in top("put_options", oi)],
            "new_calls": [[r["strike_price"], int(oi(r, "call_options") - prev(r, "call_options"))] for r in top("call_options", lambda r, s: oi(r, s) - prev(r, s))],
            "new_puts": [[r["strike_price"], int(oi(r, "put_options") - prev(r, "put_options"))] for r in top("put_options", lambda r, s: oi(r, s) - prev(r, s))]}


EXPLAIN = [
    ["Hedging (insurance)", "A fund with a large share portfolio buys index puts so a market fall is offset by the put's gain. It accepts a small certain cost (the premium) for protection. Domestic mutual funds and insurers are the main example. A put held this way says nothing about where the fund thinks the market goes."],
    ["Directional bet", "A trader buys puts, or sells futures, because they expect a fall. Foreign institutions that hold large net short index futures together with net long puts are doing this or hedging a long cash book; their futures and options positions together tell which."],
    ["Premium collection", "Proprietary desks and the retail crowd often sell puts and calls to collect time decay. Most of the time it works; a fast move against the seller is what costs. Put selling is the opposite view to put buying and is common, not rare."],
    ["Market making and arbitrage", "Large trading firms quote options both ways and hedge each trade with futures or shares. Their put buying is usually one leg of a hedged position (a spread against futures, a volatility trade, a basket against the index), so it is not a one-way market view."],
    ["Event and expiry trading", "Positions around expiry days and big events (budget, results, rate decisions) can be large and short-lived: puts are bought for a jump in volatility, then sold. SEBI has been tightening the rules for expiry-day trading because the size of some of these positions can move the index itself."],
]


def overall(dg: dict, chains: dict) -> list[str]:
    """A few plain sentences on what the latest participant positions and option walls say, and what they cannot say."""
    if not dg:
        return []
    by = {r["who"]: r for r in dg.get("participants", [])}
    out = []
    f, d, p, c = by.get("FII"), by.get("DII"), by.get("Pro"), by.get("Client")
    if f:
        syn = "net long puts and net short calls, which together behave like a short index position" if f["puts"] > 0 > f["calls"] else "no one-way options bet"
        out.append(f"Foreign institutions are net {'short' if f['fut'] < 0 else 'long'} {abs(f['fut']):,} index futures with {syn}. "
                   f"{('That is a bearish or hedged stance' + (', and futures were net short in every one of the last ' + str(len(f['series_fut'])) + ' sessions.' if all(x < 0 for x in f['series_fut']) else '.')) if f['fut'] < 0 and f['puts'] > 0 else 'It is not a clear bearish stance.'}")
    if d:
        out.append(f"Domestic institutions hold {d['puts']:+,} net puts and {d['fut']:+,} futures: the puts are insurance on the funds' share portfolios, so they are not a forecast of a fall.")
    if p:
        out.append(f"Proprietary desks and market makers are close to flat ({p['fut']:+,} futures, {p['puts']:+,} puts, {p['calls']:+,} calls). Their put buying is mostly one leg of a hedged trade.")
    if c:
        out.append(f"Retail and other clients are the largest put sellers ({c['puts']:+,} net puts): the crowd is betting the market will not fall, which is why a sharp fall hurts them most.")
    for u, ch in (chains or {}).items():
        if ch:
            out.append(f"{u} {ch.get('expiry')}: put-to-call ratio {ch['pcr']}; most call open interest at {ch['call_wall']:,.0f} (a ceiling), most put open interest at {ch['put_wall']:,.0f} (a floor); max pain {ch['max_pain']:,.0f}.")
    return out
