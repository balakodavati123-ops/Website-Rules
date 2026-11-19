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
    {"id": "scalp", "name": "Scalping desk", "bucket": "scalp", "source": "upstox", "sources": ["upstox", "indmoney"], "agents": [("Riya", "Lead analyst"), ("Dev", "Quant analyst"), ("Kabir", "Trading officer")],
     "analysts": ["Universe scanner", "VWAP pullback hunter", "Volatility quant", "Charges quant"]},
    {"id": "intraday", "name": "Intraday hunters", "bucket": "intraday", "source": "news", "sources": ["upstox", "nse", "news"], "agents": [("Ananya", "Lead analyst"), ("Ishaan", "Quant analyst"), ("Vikram", "Trading officer")],
     "analysts": ["Filings hunter", "Headlines hunter", "Gap scanner", "Momentum scanner", "VWAP pressure scanner", "Risk quant"]},
    {"id": "swing", "name": "Swing & signals", "bucket": "swing", "source": "upstox", "sources": ["upstox", "nse"], "agents": [("Meera", "Lead analyst"), ("Rohan", "Quant analyst"), ("Arjun", "Trading officer")],
     "analysts": ["Breakout analyst", "Trend analyst", "Dip analyst", "Signal desk", "Backtest quant"]},
    {"id": "fno", "name": "F&O desk", "bucket": "FNO", "source": "upstox", "sources": ["upstox", "nse"], "agents": [("Neha", "Lead analyst"), ("Siddharth", "Quant analyst"), ("Karan", "Trading officer")],
     "analysts": ["NIFTY chain reader", "Bank Nifty chain reader", "OI & participants", "IV vs realised quant", "Margin checker"]},
    {"id": "mcx", "name": "Commodities desk", "bucket": "COMMODITY", "source": "upstox", "sources": ["upstox", "yahoo"], "agents": [("Pooja", "Lead analyst"), ("Aditya", "Quant analyst"), ("Zoya", "Trading officer")],
     "analysts": ["Gold 1 g", "Silver 1 kg", "Crude oil mini", "Natural gas mini", "Margin quant"]},
    {"id": "crypto", "name": "Crypto desk", "bucket": "CRYPTO", "source": "kraken", "sources": ["kraken"], "agents": [("Tara", "Lead analyst"), ("Nikhil", "Quant analyst"), ("Sam", "Trading officer")],
     "analysts": ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "Volatility quant"]},
    {"id": "intel", "name": "Market intelligence", "bucket": None, "source": "news", "sources": ["nse", "yahoo", "news", "upstox"], "agents": [("Priya", "Lead analyst"), ("Aryan", "Quant analyst"), ("Ira", "Chief forecaster")],
     "analysts": ["World markets", "Smart money", "Option walls", "Headlines desk", "Forecast quant"]},
]
SOURCES = [("nse", "NSE"), ("upstox", "Upstox"), ("indmoney", "INDmoney"), ("kraken", "Kraken"), ("yahoo", "Yahoo Finance"), ("news", "News feeds"), ("github", "CEO inbox (GitHub)")]
# The token economy: every seat eats a few tokens each trading day; net profit is food (1 token per Rs 10), losses cost food the same way.
# A team that has not yet earned its day's food, or has gone an hour without a trade, hunts harder: its desk switches more setups on and may take
# more trades (the risk per trade never changes). A team that is losing is "injured": it may not hunt harder. A team that runs out of food is
# starving, and the COO asks the CEO whether to pause and rebuild it.
LIVING, EARN, START_TOKENS = 5, 10.0, 500
TEAM_AWARD, COO_AWARD = 500, 1000


def team_of(t: dict) -> str | None:
    d, s = t.get("desk"), str(t.get("strategy") or "")
    if d == "EQUITY":
        return "scalp" if s.startswith("scalp") else "swing" if t.get("opened") in ("swing", "signal") else "intraday"
    return {"FNO": "fno", "COMMODITY": "mcx", "CRYPTO": "crypto"}.get(d)


def new_state() -> dict:
    return {"tokens": {}, "ledger": [], "requests": [], "messages": [], "retired": [], "resumed": [], "paused_teams": [], "variants": {}, "awarded": [], "said": {}, "eco": {}, "effort": {}, "mood": {}}


def say(st: dict, now: datetime, who: str, text: str, kind: str = "info") -> None:
    st["messages"] = ([{"t": now.strftime("%d %b %H:%M"), "from": who, "text": text, "kind": kind}] + st["messages"])[:60]


def give(st: dict, now: datetime, who: str, amount: int, why: str) -> None:
    st["tokens"][who] = st["tokens"].get(who, 0) + amount
    st["ledger"] = ([{"day": now.strftime("%Y-%m-%d"), "to": who, "tokens": amount, "why": why}] + st["ledger"])[:200]


def economy(st: dict, tid: str, now: datetime, seats: int, realized_today: float, idle_min: float, injured: bool, session: bool) -> dict:
    """One team's wallet for today: yesterday's balance minus today's food, plus what today's closed trades earned."""
    today = now.strftime("%Y-%m-%d")
    e = st["eco"].setdefault(tid, {"balance": START_TOKENS, "carried": START_TOKENS, "day": ""})
    need = LIVING * seats
    if e["day"] != today and (now.weekday() < 5 or tid == "crypto"):
        e.update(day=today, carried=e["balance"] - need)             # breakfast: the day's food is eaten at the start of the day
    earned = int(realized_today / EARN)
    e["balance"] = e["carried"] + earned
    e["earned"], e["need"] = earned, need
    hunger = max(0.0, min(1.0, (need - earned) / need)) if session else 0.0
    effort = min(3, round(2 * hunger) + (1 if session and idle_min >= 60 else 0))
    if injured:
        effort = min(effort, 1)
    if e["balance"] <= 0 and injured:
        effort = 0
    mood = ("Starving" if e["balance"] <= 0 else "Injured" if injured else ("Thriving" if e["balance"] >= 2 * START_TOKENS else "Fed") if earned >= need else
            "Hungry" if effort >= 2 else "Hunting" if effort == 1 else "Resting")
    st["effort"][tid] = effort if session else 1
    return {"balance": e["balance"], "earned": earned, "need": need, "hunger": round(hunger, 2), "effort": effort, "mood": mood, "idle_min": round(idle_min) if session else None, "injured": injured}


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
        if k == "approve" and r.get("kind") == "team":
            if r["team"] not in st["paused_teams"]:
                st["paused_teams"].append(r["team"])
            text = f"Done. {r['team']} is paused: no new trades. Its open trades run to their exits. Resume it when you want it back."
            say(st, now, f"{COO['name']} (COO)", text, "decision")
            return text
        if k == "approve":
            if r["strategy"] not in st["retired"]:
                st["retired"].append(r["strategy"])
            if r.get("variant"):
                v = r["variant"]
                st["variants"][r["team"]] = {"name": v["name"], "params": v["params"], "why": v["why"], "since": now.strftime("%Y-%m-%d"), "replaces": r["strategy"]}
            text = f"Done. {r['strategy'].replace('_', ' ')} is retired" + (f"; the new team {r['variant']['name'].replace('_', ' ')} starts on paper now ({r['variant']['why']})." if r.get("variant") else ".")
        elif r.get("kind") == "team":
            text = f"Understood. {r['team']} keeps working; I will feed it from the company's reserve and report again."
            st["eco"].setdefault(r["team"], {"balance": 0, "carried": 0, "day": ""})["carried"] += 100
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


def _mood_line(eco: dict, spec: dict) -> str:
    m, e, need = eco["mood"], eco["earned"], eco["need"]
    if m == "Hungry":
        return f"We have earned {e} of today's {need} tokens" + (f" and had no trade for {eco['idle_min']} minutes" if (eco.get("idle_min") or 0) >= 60 else "") + f": hunting harder now ({eco.get('hunt') or 'every setup on'})."
    if m == "Hunting":
        return f"Today's food is not earned yet ({e} of {need} tokens): out hunting" + (f" ({eco['hunt']})." if eco.get("hunt") else ".")
    if m == "Fed":
        return f"Today's food is earned ({e} of {need} tokens). Back to our core setups."
    if m == "Thriving":
        return f"Wallet at {eco['balance']} tokens: the team is thriving."
    if m == "Injured":
        return "We are losing more than we win lately, so we are not allowed to hunt harder until the record improves."
    if m == "Starving":
        return f"We are out of food ({eco['balance']} tokens). Asking the COO for help."
    return "Market closed: resting."


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
        ses = ctx.get("sessions") or {}
        session = bool(ses.get("crypto") if tid == "crypto" else ses.get("mcx") if tid == "mcx" else ses.get("fno") if tid == "fno" else ses.get("equity"))
        closed_today = [t for t in td if t["status"] in ("WIN", "LOSS")]
        entries = [mins_ago(t.get("opened")) for t in td if str(t.get("opened") or "")[2:3] == ":"]
        idle = min(entries) if entries else (now.hour * 60 + now.minute) - (0 if tid == "crypto" else 9 * 60 + 15)
        if tid in ("swing", "intel"):
            idle = 0                                                    # daily-bar and forecasting teams are not meant to trade every hour
        mine = [t for t in T if t.get("setup")] if tid == "intraday" else T          # the hunters are a new team: they are judged on their own trades
        last10 = sorted([t for t in mine if t["status"] in ("WIN", "LOSS")], key=lambda t: (t["day"], str(t.get("closed"))))[-10:]
        rec_m = Q.team_numbers(mine) if tid == "intraday" else rec
        injured = (len(last10) >= 6 and sum(float(t["pnl_rs"] or 0) for t in last10) < 0 and sum(t["status"] == "WIN" for t in last10) / len(last10) < 0.35) or \
                  (rec_m.get("n", 0) >= 10 and rec_m.get("edge_z") is not None and rec_m["edge_z"] <= -1.5)
        eco = economy(st, tid, now, len(spec["analysts"]) + 1, sum(float(t["pnl_rs"] or 0) for t in closed_today), idle, injured, session and tid != "intel")
        if tid == "intel" and ((ctx.get("fc") or {}).get("views") or {}):
            eco["mood"] = "Forecasting"
        eco["hunt"] = (HUNT.get(tid) or {}).get(eco["effort"])
        key = f"{tid}|{today}|{eco['mood']}"
        if session and st["mood"].get(tid) != eco["mood"] and key not in st["said"]:
            st["said"][key] = 1
            st["said"] = dict(list(st["said"].items())[-300:])
            st["mood"][tid] = eco["mood"]
            say(st, now, f"{spec['agents'][2][0]} ({spec['name']})", _mood_line(eco, spec), "mood")
        teams.append({"id": tid, "name": spec["name"], "source": spec["source"], "sources": spec["sources"], "status": status, "agents": agents, "tokens": st["tokens"].get("team:" + tid, 0), "eco": eco,
                      "seats": _seats(spec, tid, td, opn, ctx, session, tid in st["paused_teams"], trader, eco["mood"]),
                      "today": {"pnl": pnl_today, "trades": len(td), "open": len(opn), "closed": sum(t["status"] in ("WIN", "LOSS") for t in td), "wins": sum(t["status"] == "WIN" for t in td)},
                      "record": rec, "verdicts": verdicts, "activity": recent, "variant": st["variants"].get(tid)})
        # the COO's notes on this team
        if rec.get("n", 0) >= 10 and rec.get("edge_z") is not None and rec["edge_z"] <= -1.5:
            notes.append({"team": tid, "level": "warn", "text": f"{spec['name']}: targets hit {rec['target_hits']} times against {rec['expected_hits']} expected by pure chance (z {rec['edge_z']}): no edge so far."})
        if eco["mood"] == "Starving" and not any(r.get("kind") == "team" and r["team"] == tid and r["status"] == "pending" for r in st["requests"]) and tid not in st["paused_teams"]:
            rid = f"R{now:%y%m%d}-{tid}-{len(st['requests']) + 1}"
            st["requests"].append({"id": rid, "team": tid, "strategy": None, "kind": "team", "status": "pending", "created": now.strftime("%d %b %H:%M"),
                                   "text": f"{spec['name']} has run out of food ({eco['balance']} tokens) and is losing. May I pause the team so I can rebuild it? It keeps its open trades until they close."})
            say(st, now, f"{COO['name']} (COO)", st["requests"][-1]["text"] + f" (request {rid})", "request")
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
            st["eco"].setdefault(best["id"], {"balance": START_TOKENS, "carried": START_TOKENS, "day": today})["carried"] += TEAM_AWARD     # the bonus is food: the team can hunt longer
            say(st, now, f"{COO['name']} (COO)", f"Bonus: {best['name']} was the best team today with {_fmt(best['today']['pnl'])} after charges. 500 tokens of food for the whole team.", "award")
        else:
            say(st, now, f"{COO['name']} (COO)", "No team bonus today: no team finished the day in profit.", "award")
        right = [r for r in ((ctx.get("fc") or {}).get("result") or []) if r.get("direction_right")]
        if right:
            st["eco"].setdefault("intel", {"balance": START_TOKENS, "carried": START_TOKENS, "day": today})["carried"] += 15 * len(right)
            say(st, now, "Ira (Market intelligence)", f"Our forecast called the direction right for {', '.join(r['name'] for r in right)} today: {15 * len(right)} tokens of food earned.", "award")
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
    return {"updated_at": now.isoformat(timespec="seconds"), "ceo": CEO, "coo": coo, "teams": teams, "sources": [{"id": s_, "name": n_, **((ctx.get("sources") or {}).get(s_) or {"status": "unknown", "detail": ""})} for s_, n_ in SOURCES], "board": board[:20],
            "ledger": st["ledger"][:20], "messages": st["messages"][:30], "company": {"pnl_today": comp_today, "nifty_chg": ctx.get("nifty_chg"), "equity": ctx.get("equity"), "sessions": ctx.get("sessions")},
            "awards": {"team": TEAM_AWARD, "coo": COO_AWARD}, "execution": {"mode": gw.get("mode"), "intents": len(gw.get("intents") or {}), "refused": sum(refused.values())}}


HUNT = {"intraday": {0: "news and momentum only", 1: "news, gap and momentum", 2: "news, gap, momentum and VWAP pressure", 3: "all four setups across a wider list of stocks"},
        "scalp": {0: "25 names, 10 trades a day", 1: "35 names, 12 trades a day", 2: "45 names, 14 trades a day", 3: "55 names, 16 trades a day"}}


def _seats(spec: dict, tid: str, td: list[dict], opn: list[dict], ctx: dict, session: bool, paused: bool, officer_doing: str, mood: str) -> list[dict]:
    """Every seat in the team's row: its analysts (each a real scanner, reader or quant check) and the trading officer."""
    out = []
    seat = lambda title, status, doing: out.append({"title": title, "status": status, "doing": doing})
    if tid == "intraday":
        d, heads = ctx.get("intraday_diag") or {}, ctx.get("headlines") or {}
        found, on = d.get("found") or {}, d.get("setups_on") or []
        seat("Filings hunter", "active" if d.get("news_names") else "idle", f"{d.get('news_names', 0)} companies filed news today that leans one way")
        seat("Headlines hunter", "active" if heads else "idle", (f"{len(heads)} recent headlines name a listed company: " + ", ".join(list(heads)[:4])) if heads else "No headline in the last 3 hours names a listed company")
        for k, title in (("gap", "Gap scanner"), ("momentum", "Momentum scanner"), ("vwap", "VWAP pressure scanner")):
            f = found.get(k) or []
            if k not in on:
                seat(title, "resting", "Off duty: switched on when the desk is hungry")
            else:
                seat(title, "active" if f else "idle", f"{len(f)} candidate(s) now: {', '.join(f[:4])}" if f else f"Scanning {d.get('scanned', 0)} liquid stocks: nothing meets the rule right now")
        seat("Risk quant", "holding" if opn else "idle", "Sizes each trade to Rs 150 of risk: stop just beyond VWAP, target 2R, stop moved to entry after a 1R gain")
    elif tid == "scalp":
        n = ctx.get("scalp_n") or 0
        seat("Universe scanner", "active" if n else "idle", f"{n} liquid names on 1-minute bars" if n else "Waiting for the session")
        seat("VWAP pullback hunter", "holding" if opn else "active" if td else "idle", f"{len(td)} setup(s) traded today" if td else "No pullback has met the rule yet today")
        seat("Volatility quant", "active" if n else "idle", "Keeps every stop at least one standard deviation of 10-minute noise away")
        seat("Charges quant", "idle", "Skips any setup whose charges would eat more than a third of the target")
    elif tid == "swing":
        groups = {"Breakout analyst": ("breakout",), "Trend analyst": ("trend", "ema", "momentum"), "Dip analyst": ("dip", "pullback", "shock", "rsi", "results"), "Signal desk": ("signal",)}
        for title, keys in groups.items():
            k = [t for t in opn if any(x in str(t["strategy"]) for x in keys)]
            seat(title, "holding" if k else "idle", f"{len(k)} open position(s): " + ", ".join(sorted({str(t.get('symbol')) for t in k})[:4]) if k else "No open position; the daily scan runs after the close")
        seat("Backtest quant", "idle", "Five-year tests decide which daily rules may trade")
    elif tid == "fno":
        ch, sm, fs = (ctx.get("sm") or {}).get("chains") or {}, ctx.get("sm") or {}, ctx.get("fno_snap") or {}
        for u, title in (("NIFTY", "NIFTY chain reader"), ("BANKNIFTY", "Bank Nifty chain reader")):
            c = ch.get(u)
            seat(title, "active" if c else "idle", f"{c['expiry']}: put-to-call {c['pcr']}, call wall {c['call_wall']:,.0f}, put wall {c['put_wall']:,.0f}" if c else "Waiting for the chain")
        fii = next((x for x in sm.get("participants") or [] if x.get("who") == "FII"), None)
        seat("OI & participants", "active" if fii else "idle", f"FIIs net {fii['fut']:+,} index futures, {fii['puts']:+,} puts" if fii else "Waiting for NSE's participant file")
        seat("IV vs realised quant", "active" if fs else "idle", f"ATM straddle {fs.get('straddle')} points: the market prices about ±{fs['straddle'] / fs['spot'] * 100:.2f}% to {fs['expiry']}" if fs.get("straddle") and fs.get("spot") else "Compares implied with realised volatility to pick buying or selling")
        sk = [x for x in ((ctx.get("via") or {}).get("skipped") or []) if x.get("desk") == "FNO"]
        seat("Margin checker", "alert" if sk else "idle", f"{len(sk)} structure(s) skipped today: the broker's margin did not fit" if sk else "Every structure is checked with the broker's margin calculator")
    elif tid in ("mcx", "crypto"):
        live = {x["name"]: x for x in (ctx.get("mcx") if tid == "mcx" else ctx.get("crypto")) or []}
        for title in spec["analysts"][:-1]:
            x, hold = live.get(title), [t for t in opn if str(t.get("label", "")).startswith(title) or t.get("symbol") == title]
            mv = x and abs(x.get("chg_pct") or 0) >= (0.8 if tid == "mcx" else 1.0)
            seat(title, "holding" if hold else "active" if mv else "idle", (f"{x['chg_pct']:+.2f}% today" + (", in a trade" if hold else ", moving: watching for an entry" if mv else "")) if x else "No price yet")
        seat(spec["analysts"][-1], "idle", "Checks margin and noise before every trade" if tid == "mcx" else "Sets stop and target from each coin's own volatility")
    else:
        sm, fc, n_head = ctx.get("sm") or {}, ctx.get("fc") or {}, ctx.get("news_n") or 0
        seat("World markets", "active" if ctx.get("world") else "idle", "Overnight US, Asia, dollar, crude and gold, refreshed every half hour before the open")
        seat("Smart money", "active" if sm.get("participants") else "idle", f"NSE participant positions for {sm.get('day')}" if sm.get("day") else "Waiting for NSE's file")
        seat("Option walls", "active" if sm.get("chains") else "idle", "Largest call and put open interest on NIFTY and Bank Nifty")
        seat("Headlines desk", "active" if n_head else "idle", f"{n_head} high-impact headlines in the feed")
        v = (fc.get("views") or {}).get("Nifty 50")
        seat("Forecast quant", "active" if v else "idle", f"Nifty {v['bias'].lower()}, range {v['lo']:,} to {v['hi']:,}" if v else "Builds the 08:45 forecast")
    name = spec["agents"][2][0]
    out.append({"title": spec["agents"][2][1], "name": name, "officer": True, "doing": officer_doing,
                "status": "alert" if mood in ("Starving", "Injured") else "holding" if opn else "active" if td else "idle"})
    for x in out:
        if paused:
            x["status"] = "vacant"
        elif not session and x["status"] in ("active", "idle"):
            x["status"] = "resting"
    return out


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
