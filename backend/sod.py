"""The intraday day plan: what the desks will watch at the start of the day, and how the day went at the end.

SOD (before the open): market tone from the overnight world markets and India VIX, today's results and board meetings, filings that lean one
way, headlines, and for the names in the news the exact price levels at which the desks' rules would act. At 09:12 it adds who is
gapping. EOD (after the close): profit and loss by market, best and worst trade, how planned and news-led trades did, and a few
plain observations. Rule-based screening, not a forecast; nothing here places an order.
"""
from __future__ import annotations


def _row(world: list[dict], *names):
    for n in names:
        for r in world:
            if str(r.get("name", "")).lower() == n.lower():
                return r
    return {}


def tone(world: list[dict], vix) -> dict:
    us = [_row(world, n).get("chg_pct") for n in ("S&P 500", "Nasdaq", "Dow Jones")]
    asia = [_row(world, n).get("chg_pct") for n in ("Nikkei 225", "Hang Seng")]
    us, asia = [x for x in us if x is not None], [x for x in asia if x is not None]
    score = (sum(us) / len(us) * 0.6 if us else 0) + (sum(asia) / len(asia) * 0.4 if asia else 0)
    label = "Positive" if score >= 0.4 else "Weak" if score <= -0.4 else "Mixed"
    notes = []
    if us:
        notes.append(f"US markets averaged {sum(us) / len(us):+.2f}% at the last close.")
    if asia:
        notes.append(f"Asia averaged {sum(asia) / len(asia):+.2f}%.")
    crude, usd = _row(world, "Brent crude"), _row(world, "Dollar in rupees")
    if crude:
        notes.append(f"Brent crude {crude.get('last')} ({crude.get('chg_pct', 0):+.2f}%).")
    if usd:
        notes.append(f"Dollar-rupee {usd.get('last')} ({usd.get('chg_pct', 0):+.2f}%).")
    if vix:
        band = "calm" if vix < 13 else "normal" if vix < 18 else "elevated" if vix < 22 else "stressed"
        notes.append(f"India VIX {vix:.2f}: {band}.")
    return {"label": label, "score": round(score, 2), "notes": notes}


def fno_notes(vix, chg) -> list[dict]:
    v = vix or 15
    return [
        {"strategy": "Iron condor, credit spread (fixed return)", "note": "Favoured on a quiet day" if v < 18 else "Premiums are rich but a big move can hurt; the desk still caps the loss"},
        {"strategy": "Debit spread, long breakout (high return, low loss)", "note": "Needs a 0.25% to 0.5% move from the previous close first; waits for the trend"},
        {"strategy": "Long straddle (high return, high loss)", "note": "Pays only on a big move; the desk skips it when its cost does not fit the F&O limit" if v >= 13 else "Cheap options today: a bigger move than usual would pay"},
    ]


def build_plan(prev: dict | None, day: str, hhmm: str, world: list[dict], events: list[dict], results: list[dict], news_items: list[dict], filings: dict, quotes: dict, vix, nifty: dict) -> dict:
    """quotes: {symbol: (price, net_change)} for the names in the news."""
    plan = dict(prev or {})
    plan.update(day=day, built_at=hhmm, stage=max(1, plan.get("stage", 0)))
    plan["tone"] = tone(world, vix)
    plan["nifty"] = nifty
    plan["world"] = [{"name": r["name"], "last": r.get("last"), "chg_pct": r.get("chg_pct")} for r in world if r.get("last") is not None][:10]
    plan["events"] = [{"symbol": e.get("symbol"), "kind": e.get("kind"), "detail": e.get("detail")} for e in events if str(e.get("date", ""))[:10] == day][:14]
    plan["results"] = [{"symbol": r.get("symbol"), "company": r.get("company"), "time": r.get("time")} for r in results][:14]
    plan["headlines"] = [{"headline": n.get("headline"), "category": n.get("category"), "source": n.get("source"), "time": n.get("time")} for n in news_items[-8:]][::-1]
    names: dict[str, set] = {}
    for s, sent in filings.items():
        names.setdefault(s, set()).add("positive filing" if sent == "positive" else "negative filing")
    for r in results:
        names.setdefault(r.get("symbol"), set()).add("results filed")
    for e in plan["events"]:
        if e.get("symbol"):
            names.setdefault(e["symbol"], set()).add(f"{str(e.get('kind') or 'event').lower()} today")
    watch = []
    for s, why in names.items():
        q = quotes.get(s)
        if not q or q[0] <= 0 or q[0] - q[1] <= 0:
            continue
        prev_close = q[0] - q[1]
        pos, neg = "positive filing" in why, "negative filing" in why
        lo, sh = (0.006, 0.02) if pos else (0.02, 0.006) if neg else (0.02, 0.02)
        watch.append({"symbol": s, "why": sorted(why), "prev_close": round(prev_close, 2), "long_above": round(prev_close * (1 + lo), 2), "short_below": round(prev_close * (1 - sh), 2),
                      "stop_pct": 1.0, "bias": "long" if pos else "short" if neg else "either"})
    watch.sort(key=lambda w: (w["bias"] == "either", w["symbol"]))
    plan["watch"] = watch[:18]
    plan["fno"] = fno_notes(vix, (nifty or {}).get("chg_pct"))
    plan["outlook"] = (f"Tone {plan['tone']['label'].lower()}. {len(plan['watch'])} names in the news to watch; "
                       "the desks act only when price confirms: a 2% move near the day's extreme (0.6% when a filing agrees) on real turnover.")
    return plan


def add_gaps(plan: dict, rows: list[dict], hhmm: str) -> dict:
    liq = [r for r in rows if r["price"] >= 20 and r["price"] * r["volume"] >= 2e7]
    top = lambda lst: [{"symbol": r["symbol"], "price": round(r["price"], 2), "chg_pct": round(r["chg_pct"], 2)} for r in lst[:10]]
    plan["gaps"] = {"up": top(sorted(liq, key=lambda r: -r["chg_pct"])), "down": top(sorted(liq, key=lambda r: r["chg_pct"])), "at": hhmm}
    plan["stage"] = 2
    return plan


def build_eod(trades: list[dict], day: str, plan: dict | None, equity: float | None) -> dict:
    today = [t for t in trades if t["day"] == day and t.get("opened") not in ("swing", "weekly", "signal")]
    closed = [t for t in today if t["status"] in ("WIN", "LOSS")]
    pnl = lambda ts: round(sum(float(t["pnl_rs"] or 0) for t in ts), 2)
    wins = sum(t["status"] == "WIN" for t in closed)
    by_desk = {d: {"trades": sum(t["desk"] == d for t in today), "pnl": pnl([t for t in today if t["desk"] == d])} for d in ("EQUITY", "FNO", "COMMODITY", "CRYPTO")}
    strat: dict = {}
    for t in today:
        s = strat.setdefault(t["strategy"], {"strategy": t["strategy"], "n": 0, "pnl": 0.0})
        s["n"] += 1
        s["pnl"] = round(s["pnl"] + float(t["pnl_rs"] or 0), 2)
    ordered = sorted(today, key=lambda t: float(t["pnl_rs"] or 0))
    planned = {w["symbol"] for w in (plan or {}).get("watch", [])}
    news = [t for t in today if t["strategy"] == "news-led" or "positive filing" in (t.get("reason") or "") or "negative filing" in (t.get("reason") or "")]
    pl = [t for t in today if t.get("symbol") in planned]
    out = {"day": day, "trades": len(today), "closed": len(closed), "open": len(today) - len(closed), "wins": wins, "win_rate": round(wins / len(closed) * 100) if closed else None, "pnl": pnl(today),
           "by_desk": by_desk, "by_strategy": sorted(strat.values(), key=lambda s: -s["pnl"]), "equity": equity,
           "best": {"label": ordered[-1]["label"], "pnl": float(ordered[-1]["pnl_rs"])} if ordered else None, "worst": {"label": ordered[0]["label"], "pnl": float(ordered[0]["pnl_rs"])} if ordered else None,
           "news": {"n": len(news), "pnl": pnl(news)}, "planned": {"n": len(pl), "pnl": pnl(pl)}}
    notes = []
    if today:
        notes.append(f"{len(today)} trades: {wins} won and {len(closed) - wins} lost of {len(closed)} closed; net {out['pnl']:+,.0f} rupees.")
        best_d = max(by_desk.items(), key=lambda kv: kv[1]["pnl"])
        worst_d = min(by_desk.items(), key=lambda kv: kv[1]["pnl"])
        if best_d[1]["trades"]:
            notes.append(f"Best market: {best_d[0]} ({best_d[1]['pnl']:+,.0f}). Weakest: {worst_d[0]} ({worst_d[1]['pnl']:+,.0f}).")
        if news:
            notes.append(f"News-led trades: {len(news)}, net {pnl(news):+,.0f}.")
        if pl:
            notes.append(f"Names on the morning plan that traded: {len(pl)}, net {pnl(pl):+,.0f}.")
        if closed and wins / len(closed) < 0.4:
            notes.append("Win rate under 40% today: the strategies below the line on the scoreboard are the ones to watch for a pause.")
    else:
        notes.append("No intraday trade was taken today: nothing met the rules.")
    out["notes"] = notes
    return out
