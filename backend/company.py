"""Balaji Trading Desk: the company. Teams of agents (research, quant, trader) per market, a COO who supervises them, and the CEO.

Every agent is a set of written rules running in this program; what each one is doing is read from live data, never invented.
Bonus tokens are the company's scoreboard: at the end of each trading day the team with the best net result (after charges) earns 500
tokens, split among its agents, and the COO earns 1,000 when the whole company beat the Nifty that day. The COO reads every team's
record each minute, writes notes when something needs correcting, and when a strategy has lost over enough trades to be paused, asks
the CEO for permission to retire it and, where it knows how, proposes an improved replacement team. The CEO answers from the dashboard
(a pre-filled GitHub issue that only the repository owner can use). Nothing here places an order.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

import quant as Q

CEO = "Balaji"
COO = {"name": "Raghav", "role": "COO"}
TEAMS = [
    {"id": "scalp", "name": "Scalping desk", "bucket": "scalp", "source": "nse", "agents": [("Riya", "Research"), ("Dev", "Quant"), ("Kabir", "Trader")]},
    {"id": "intraday", "name": "Intraday equities", "bucket": "intraday", "source": "news", "agents": [("Ananya", "Research"), ("Ishaan", "Quant"), ("Vikram", "Trader")]},
    {"id": "swing", "name": "Swing & signals", "bucket": "swing", "source": "nse", "agents": [("Meera", "Research"), ("Rohan", "Quant"), ("Arjun", "Trader")]},
    {"id": "fno", "name": "F&O desk", "bucket": "FNO", "source": "chain", "agents": [("Neha", "Research"), ("Siddharth", "Quant"), ("Karan", "Trader")]},
    {"id": "mcx", "name": "Commodities desk", "bucket": "COMMODITY", "source": "mcx", "agents": [("Pooja", "Research"), ("Aditya", "Quant"), ("Zoya", "Trader")]},
    {"id": "crypto", "name": "Crypto desk", "bucket": "CRYPTO", "source": "crypto", "agents": [("Tara", "Research"), ("Nikhil", "Quant"), ("Sam", "Trader")]},
    {"id": "intel", "name": "Market intelligence", "bucket": None, "source": "news", "agents": [("Priya", "Research"), ("Aryan", "Quant"), ("Ira", "Forecaster")]},
]
SOURCES = [("nse", "NSE stocks"), ("chain", "Option chains"), ("mcx", "MCX futures"), ("crypto", "Crypto (Kraken)"), ("news", "News & world")]
TEAM_AWARD, COO_AWARD = 500, 1000


def team_of(t: dict) -> str | None:
    d, s = t.get("desk"), str(t.get("strategy") or "")
    if d == "EQUITY":
        return "scalp" if s.startswith("scalp") else "swing" if t.get("opened") in ("swing", "signal") else "intraday"
    return {"FNO": "fno", "COMMODITY": "mcx", "CRYPTO": "crypto"}.get(d)


def new_state() -> dict:
    return {"tokens": {}, "ledger": [], "requests": [], "messages": [], "retired": [], "resumed": [], "paused_teams": [], "variants": {}, "awarded": [], "said": {}}


def say(st: dict, now: datetime, who: str, text: str, kind: str = "info") -> None:
    st["messages"] = ([{"t": now.strftime("%d %b %H:%M"), "from": who, "text": text, "kind": kind}] + st["messages"])[:60]


def give(st: dict, now: datetime, who: str, amount: int, why: str) -> None:
    st["tokens"][who] = st["tokens"].get(who, 0) + amount
    st["ledger"] = ([{"day": now.strftime("%Y-%m-%d"), "to": who, "tokens": amount, "why": why}] + st["ledger"])[:200]


def paused_strategies(st: dict, learned_paused: set, all_strategies: dict) -> set:
    """What may not open new trades: strategies the record paused, strategies the CEO retired, and every strategy of a team the CEO paused,
    minus strategies the CEO chose to keep running."""
    out = set(learned_paused) | set(st["retired"])
    for team in st["paused_teams"]:
        out |= {s for s, tm in all_strategies.items() if tm == team}
    return out - set(st["resumed"])


def scalp_variant(trades: list[dict], params: dict) -> dict:
    """The COO's improved scalping team: changes drawn from how the old one lost."""
    closed = [t for t in trades if t.get("status") in ("WIN", "LOSS")]
    why = Counter(str(t.get("why") or "") for t in closed)
    n = max(1, len(closed))
    if why["time"] / n >= 0.5:
        ch, reason = {"vol_x": round(params.get("vol_x", 1.2) + 0.3, 2), "rr": 1.2}, f"{why['time']} of {n} trades ran out of time: demand a stronger bar and set a closer target"
    elif why["stop"] / n >= 0.5:
        ch, reason = {"stop_min": round(params.get("stop_min", 0.15) + 0.05, 2), "ext_max": round(params.get("ext_max", 0.8) - 0.2, 2)}, f"{why['stop']} of {n} trades were stopped: a wider minimum stop, and no entries far from VWAP"
    else:
        ch, reason = {"min_rc": params.get("min_rc", 3.0) + 1.0}, "results were too thin after charges: demand more target per rupee of charges"
    return {"params": ch, "why": reason}


def apply(st: dict, cmd: dict, now: datetime) -> str:
    """Carry out one instruction from the CEO; returns the COO's reply."""
    k, arg = cmd["kind"], cmd.get("arg", "")
    if k in ("approve", "reject"):
        r = next((x for x in st["requests"] if x["id"].lower() == arg.lower()), None)
        if not r:
            return f"I could not find a request called {arg}."
        if r["status"] != "pending":
            return f"Request {r['id']} was already {r['status']}."
        r.update(status="approved" if k == "approve" else "rejected", decided=now.strftime("%d %b %H:%M"))
        if k == "approve":
            if r["strategy"] not in st["retired"]:
                st["retired"].append(r["strategy"])
            if r.get("variant"):
                v = r["variant"]
                st["variants"][r["team"]] = {"name": v["name"], "params": v["params"], "why": v["why"], "since": now.strftime("%Y-%m-%d"), "replaces": r["strategy"]}
            text = f"Done. {r['strategy'].replace('_', ' ')} is retired" + (f"; the new team {r['variant']['name'].replace('_', ' ')} starts on paper now ({r['variant']['why']})." if r.get("variant") else ".")
        else:
            if r["strategy"] not in st["resumed"]:
                st["resumed"].append(r["strategy"])
            text = f"Understood. {r['strategy'].replace('_', ' ')} keeps trading on paper; I will report again if it keeps losing."
        say(st, now, f"{COO['name']} (COO)", text, "decision")
        return text
    team = next((t for t in TEAMS if t["id"] == arg.lower() or t["name"].lower() == arg.lower()), None)
    if k in ("pause", "resume"):
        if not team:
            return "Which team? Use one of: " + ", ".join(t["id"] for t in TEAMS)
        if k == "pause" and team["id"] not in st["paused_teams"]:
            st["paused_teams"].append(team["id"])
        if k == "resume":
            st["paused_teams"] = [x for x in st["paused_teams"] if x != team["id"]]
        text = f"{team['name']} is {'paused: no new trades until you resume it' if k == 'pause' else 'back at work'}."
        say(st, now, f"{COO['name']} (COO)", text, "decision")
        return text
    say(st, now, f"{CEO} (CEO)", cmd.get("text") or arg, "ceo")
    text = "Noted, I have shared it with the teams. I act on: APPROVE or REJECT a request id, PAUSE or RESUME a team."
    say(st, now, f"{COO['name']} (COO)", text, "info")
    return text


def _fmt(x: float) -> str:
    return f"{'+' if x > 0 else '−' if x < 0 else ''}₹{abs(x):,.0f}"


def build(st: dict, now: datetime, trades: list[dict], stats: list[dict], ctx: dict) -> dict:
    """ctx: plan, fc, sm, gw, via, desks (status strings), world {name: row}, nifty_chg, equity, scalp_n, scalp_params, sessions, quant_notes {trade id: numbers}."""
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    by_team: dict = {t["id"]: [] for t in TEAMS}
    for t in trades:
        tm = team_of(t)
        if tm:
            by_team[tm].append(t)
    vstat = {(s["strategy"]): s for s in stats}
    strat_team = {t["strategy"]: team_of(t) for t in trades if team_of(t)}
    teams, notes = [], []
    mins_ago = lambda hms: (now.hour * 60 + now.minute) - (int(str(hms)[:2]) * 60 + int(str(hms)[3:5])) if str(hms)[:2].isdigit() and str(hms)[2:3] == ":" else 9999
    for spec in TEAMS:
        tid, T = spec["id"], by_team[spec["id"]]
        td = [t for t in T if t["day"] == today]
        opn = [t for t in T if t["status"] == "OPEN"]
        pnl_today = round(sum(float(t.get("pnl_rs") or 0) for t in td), 2)
        rec = Q.team_numbers(T)
        strats = sorted({t["strategy"] for t in T})
        verdicts = [{"strategy": s, **{k: vstat[s][k] for k in ("closed", "win_rate", "pnl_rs", "verdict")}} for s in strats if s in vstat]
        recent = sum(1 for t in td if mins_ago(t.get("opened")) <= 30 or mins_ago(t.get("closed")) <= 30)
        status = "Paused by you" if tid in st["paused_teams"] else "New team" if st["variants"].get(tid) else "Paused (losing record)" if any(v["verdict"] == "PAUSED" and v["strategy"] not in st["resumed"] for v in verdicts) else \
                 "On watch" if any(v["verdict"] == "WEAK" and v["closed"] >= 20 for v in verdicts) else "Active"
        research, quant, trader = _doing(tid, spec, td, opn, T, rec, ctx, now)
        agents = [{"name": n, "role": r, "doing": d, "tokens": st["tokens"].get(n, 0)} for (n, r), d in zip(spec["agents"], (research, quant, trader))]
        teams.append({"id": tid, "name": spec["name"], "source": spec["source"], "status": status, "agents": agents, "tokens": st["tokens"].get("team:" + tid, 0),
                      "today": {"pnl": pnl_today, "trades": len(td), "open": len(opn), "closed": sum(t["status"] in ("WIN", "LOSS") for t in td), "wins": sum(t["status"] == "WIN" for t in td)},
                      "record": rec, "verdicts": verdicts, "activity": recent, "variant": st["variants"].get(tid)})
        # the COO's notes on this team
        if rec.get("n", 0) >= 10 and rec.get("edge_z") is not None and rec["edge_z"] <= -1.5:
            notes.append({"team": tid, "level": "warn", "text": f"{spec['name']}: targets hit {rec['target_hits']} times against {rec['expected_hits']} expected by pure chance (z {rec['edge_z']}): no edge so far."})
        if pnl_today <= -500:
            notes.append({"team": tid, "level": "warn", "text": f"{spec['name']} is down {_fmt(pnl_today)} today. Watching the next trades closely."})
        for v in verdicts:
            if v["verdict"] == "PAUSED" and v["strategy"] not in st["retired"] and v["strategy"] not in st["resumed"] and not any(r["strategy"] == v["strategy"] and r["status"] == "pending" for r in st["requests"]):
                rid = f"R{now:%y%m%d}-{tid}-{len(st['requests']) + 1}"
                req = {"id": rid, "team": tid, "strategy": v["strategy"], "status": "pending", "created": now.strftime("%d %b %H:%M"),
                       "text": f"{v['strategy'].replace('_', ' ')} has lost over {v['closed']} closed trades (net {_fmt(v['pnl_rs'])}, {v['win_rate']}% won). The record paused it automatically. May I retire it?"}
                if tid == "scalp":
                    var = scalp_variant([t for t in T if t["strategy"] == v["strategy"]], ctx.get("scalp_params") or {})
                    req["variant"] = {"name": f"scalp_vwap_pullback_v{len(st['variants']) + 2}", **var}
                    req["text"] += f" I propose a new scalping team: {var['why']}."
                st["requests"].append(req)
                say(st, now, f"{COO['name']} (COO)", req["text"] + f" (request {rid})", "request")
    gw = ctx.get("gw") or {}
    refused = Counter((x.get("reasons") or [""])[0].split(":")[0] for x in (gw.get("intents") or {}).values() if x.get("status") == "REJECTED")
    for why, n in refused.most_common(2):
        notes.append({"team": "scalp", "level": "info", "text": f"The gateway refused {n} scalping order{'s' if n > 1 else ''} today: {why}. Dev (Quant) is reviewing the stop and size rules."})
    for k, v in (ctx.get("desks") or {}).items():
        if "error" in str(v):
            notes.append({"team": None, "level": "warn", "text": f"Data problem at the {k} desk: {str(v)[:90]}. Trades there wait until it clears."})
    skips = (ctx.get("via") or {}).get("skipped") or []
    if skips:
        notes.append({"team": "fno", "level": "info", "text": f"{len(skips)} trades were skipped today because the broker's margin did not fit the account: the desks only trade what is viable."})
    rec_f = ((ctx.get("fc") or {}).get("record") or {}).get("Nifty 50") or {}
    if rec_f.get("days", 0) >= 10 and (rec_f.get("direction") or 0) < 45:
        notes.append({"team": "intel", "level": "warn", "text": f"The Nifty forecast was right on direction only {rec_f['direction']}% of {rec_f['days']} days: Aryan (Quant) should review the weights."})
    # end of day: bonuses
    if now.weekday() < 5 and hhmm >= "15:45" and today not in st["awarded"]:
        st["awarded"] = (st["awarded"] + [today])[-30:]
        race = [t for t in teams if t["id"] != "intel" and t["today"]["trades"]]
        best = max(race, key=lambda t: t["today"]["pnl"]) if race else None
        if best and best["today"]["pnl"] > 0:
            give(st, now, "team:" + best["id"], TEAM_AWARD, f"best team today ({_fmt(best['today']['pnl'])})")
            names = [a["name"] for a in best["agents"]]
            for i, nm in enumerate(names):
                give(st, now, nm, TEAM_AWARD // len(names) + (1 if i < TEAM_AWARD % len(names) else 0), f"{best['name']} won the day")
            say(st, now, f"{COO['name']} (COO)", f"Bonus: {best['name']} was the best team today with {_fmt(best['today']['pnl'])} after charges. 500 tokens to {', '.join(names)}.", "award")
        else:
            say(st, now, f"{COO['name']} (COO)", "No team bonus today: no team finished the day in profit.", "award")
        comp = sum(t["today"]["pnl"] for t in teams)
        pct, nf = comp / (ctx.get("equity") or 100000) * 100, ctx.get("nifty_chg")
        if nf is not None and comp > 0 and pct > nf:
            give(st, now, COO["name"], COO_AWARD, f"company {pct:+.2f}% beat the Nifty {nf:+.2f}%")
            say(st, now, f"{COO['name']} (COO)", f"The company made {pct:+.2f}% today against the Nifty's {nf:+.2f}%. 1,000 tokens to the COO.", "award")
        elif nf is not None:
            say(st, now, f"{COO['name']} (COO)", f"Company today {_fmt(comp)} ({pct:+.2f}%) against the Nifty's {nf:+.2f}%: no COO bonus.", "award")
    pending = [r for r in st["requests"] if r["status"] == "pending"]
    active = sum(1 for t in teams if t["today"]["trades"])
    comp_today = round(sum(t["today"]["pnl"] for t in teams), 2)
    leader = max([t for t in teams if t["id"] != "intel" and t["today"]["trades"]], key=lambda t: t["today"]["pnl"], default=None)
    coo = {**COO, "tokens": st["tokens"].get(COO["name"], 0), "notes": notes[:12], "requests": pending + [r for r in st["requests"] if r["status"] != "pending"][-5:],
           "doing": f"Supervising {len(teams)} teams: {active} traded today, company {_fmt(comp_today)}." + (f" {len(pending)} request{'s' if len(pending) > 1 else ''} waiting for you." if pending else "") +
                    (f" Bonus race leader: {leader['name']} ({_fmt(leader['today']['pnl'])})." if leader and leader["today"]["pnl"] > 0 else "")}
    board = sorted([{"who": k, "tokens": v} for k, v in st["tokens"].items()], key=lambda x: -x["tokens"])
    return {"updated_at": now.isoformat(timespec="seconds"), "ceo": CEO, "coo": coo, "teams": teams, "sources": [{"id": s, "name": n} for s, n in SOURCES], "board": board[:20],
            "ledger": st["ledger"][:20], "messages": st["messages"][:30], "company": {"pnl_today": comp_today, "nifty_chg": ctx.get("nifty_chg"), "equity": ctx.get("equity"), "sessions": ctx.get("sessions")},
            "awards": {"team": TEAM_AWARD, "coo": COO_AWARD}, "execution": {"mode": gw.get("mode"), "intents": len(gw.get("intents") or {}), "refused": sum(refused.values())}}


def _doing(tid: str, spec: dict, td: list[dict], opn: list[dict], T: list[dict], rec: dict, ctx: dict, now: datetime) -> tuple[str, str, str]:
    """What each of the three agents on a team is doing right now, read from the live data."""
    plan, fc, sm, world = ctx.get("plan") or {}, ctx.get("fc") or {}, ctx.get("sm") or {}, ctx.get("world") or {}
    ses = ctx.get("sessions") or {}
    last = max(T, key=lambda t: (t["day"], str(t.get("closed") or t.get("opened"))), default=None)
    qn = (ctx.get("quant_notes") or {})
    if tid == "scalp":
        r = f"Scanning the {ctx.get('scalp_n') or 25} most liquid stocks on 1-minute bars for VWAP pullbacks." if ses.get("equity") else "Market closed: the scan restarts at 09:30."
    elif tid == "intraday":
        r = f"Watching {len(plan.get('watch') or [])} name(s) in the news and today's filings; {len(plan.get('results') or [])} results to read." if plan.get("day") == now.strftime("%Y-%m-%d") else "Preparing the morning plan at 08:45."
    elif tid == "swing":
        r = f"Daily chart scan after the close; holding {len(opn)} swing positions with stops."
    elif tid == "fno":
        ch = (sm.get("chains") or {}).get("NIFTY") or {}
        r = f"NIFTY {ch.get('expiry', '')}: put-to-call {ch.get('pcr')}, call wall {ch.get('call_wall', 0):,.0f}, put wall {ch.get('put_wall', 0):,.0f}." if ch else "Reading the NIFTY and Bank Nifty option chains."
    elif tid == "mcx":
        b, g = world.get("Brent crude") or {}, world.get("Gold") or {}
        r = f"Brent {b.get('chg_pct', 0):+.2f}%, gold {g.get('chg_pct', 0):+.2f}% overnight; tracking 4 MCX contracts the account can carry." if b else "Tracking gold, silver, crude and natural gas futures."
    elif tid == "crypto":
        r = "Reading 6 coins on Kraken around the clock; long only (spot)."
    else:
        v = (fc.get("views") or {}).get("Nifty 50") or {}
        fii = next((p for p in (sm.get("participants") or []) if p.get("who") == "FII"), None)
        r = (f"Nifty forecast {v.get('bias', '').lower()} (score {v.get('score', 0):+.2f}), range {v.get('lo', 0):,} to {v.get('hi', 0):,}." if v else "Building the 08:45 forecast.") + (f" FIIs net {fii['fut']:+,} index futures." if fii else "")
    # quant
    if tid == "intel":
        rf = (fc.get("record") or {}).get("Nifty 50") or {}
        q = f"Scoring the forecast against the close every evening: {rf.get('direction')}% right on direction over {rf.get('days')} days." if rf.get("days") else "Weights the six inputs, sets the one-standard-deviation range from India VIX, scores it every evening."
        f = "Sends the day's bias and levels to the F&O and equity desks."
        return r, q, f
    lt = opn[-1] if opn else (td[-1] if td else None)
    n = qn.get(lt["id"]) if lt else None
    if n and n.get("base_p") is not None:
        q = (f"{lt['label']}: reward {n['rr']}× the risk; a random walk reaches the target first {n['base_p'] * 100:.0f}% of the time; break-even needs {n['breakeven_p'] * 100:.0f}% wins after charges"
             + (f"; stop is {n['stop_sigma']}σ of noise" if n.get("stop_sigma") else "") + ".")
    elif rec.get("n"):
        q = f"Record: {rec['n']} closed, {rec['win_rate']}% won, average {_fmt(rec['avg_rs'])}" + (f", target hits {rec['target_hits']} vs {rec['expected_hits']} by chance (z {rec['edge_z']})" if rec.get("edge_z") is not None else "") + "."
    else:
        q = "Sizing every trade from the stop distance, charges and margin; no closed trades yet to test for an edge."
    if opn:
        t = opn[-1]
        tr = f"Holding {len(opn)}: {t['label']} at {float(t['entry']):,.2f}" + (f", stop {float(t['stop']):,.2f}" if t.get("stop") else "") + f", now {_fmt(float(t.get('pnl_rs') or 0))}."
    elif last and last["day"] == now.strftime("%Y-%m-%d"):
        tr = f"Closed {last['label']} ({str(last.get('why') or '').split(':')[0] or 'exit'}): {_fmt(float(last.get('pnl_rs') or 0))}."
    else:
        tr = "Waiting: no setup has met the rules yet today."
    return r, q, tr
