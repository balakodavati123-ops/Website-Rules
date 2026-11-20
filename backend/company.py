"""Balaji Trading Desk: the company. Teams of agents per market, a strategy lab, an IPO desk, a COO who supervises them all, and the CEO.

Every agent is a set of written rules (and, where a Claude API key is set, a Claude model for reading and writing) running in this program;
what each one is doing is read from live data, never invented. Designations follow the record: every new agent starts as an Associate and is
promoted to Senior Associate once its own work has a profitable record (10+ closed trades, net profit, 45%+ won; team-wide roles such as the
quants are judged on their team's record); Managers are the traders; the COO watches every team, hires an extra Associate when a desk has more
setups than it can handle, asks the CEO before pausing a losing team, and keeps the company's P&L in front of the CEO. Bonus tokens remain the
scoreboard: 500 to the best team of the day, 1,000 to the COO when the company beats the Nifty. Nothing here places an order.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

import quant as Q

CEO = "Balaji"
COO = {"name": "Raghav", "role": "COO"}
TEAMS = [
    {"id": "scalp", "name": "Scalping desk", "bucket": "scalp", "source": "upstox", "sources": ["upstox", "indmoney"], "agents": [("Riya", "Lead analyst"), ("Dev", "Quant analyst"), ("Kabir", "Trading manager")],
     "analysts": ["Universe scanner", "VWAP pullback hunter", "Volatility quant", "Charges quant"], "names": ["Asha", "Riya", "Dev", "Mihir"], "color": "#22d3ee"},
    {"id": "intraday", "name": "Intraday hunters", "bucket": "intraday", "source": "news", "sources": ["upstox", "nse", "news"], "agents": [("Ananya", "Lead analyst"), ("Ishaan", "Quant analyst"), ("Vikram", "Trading manager")],
     "analysts": ["Filings hunter", "Headlines hunter", "Gap scanner", "Momentum scanner", "VWAP pressure scanner", "Risk quant"], "names": ["Ananya", "Farah", "Kunal", "Divya", "Manav", "Ishaan"], "color": "#f97316"},
    {"id": "swing", "name": "Swing & signals", "bucket": "swing", "source": "upstox", "sources": ["upstox", "nse"], "agents": [("Meera", "Lead analyst"), ("Rohan", "Quant analyst"), ("Arjun", "Trading manager")],
     "analysts": ["Breakout analyst", "Trend analyst", "Dip analyst", "Signal desk", "Backtest quant"], "names": ["Meera", "Gautam", "Leela", "Sana", "Rohan"], "color": "#84cc16"},
    {"id": "fno", "name": "F&O desk", "bucket": "FNO", "source": "upstox", "sources": ["upstox", "nse"], "agents": [("Neha", "Lead analyst"), ("Siddharth", "Quant analyst"), ("Karan", "Trading manager")],
     "analysts": ["NIFTY chain reader", "Bank Nifty chain reader", "OI & participants", "IV vs realised quant", "Margin checker"], "names": ["Neha", "Varun", "Anjali", "Siddharth", "Tanvi"], "color": "#a78bfa"},
    {"id": "mcx", "name": "Commodities desk", "bucket": "COMMODITY", "source": "upstox", "sources": ["upstox", "yahoo"], "agents": [("Pooja", "Lead analyst"), ("Aditya", "Quant analyst"), ("Zoya", "Trading manager")],
     "analysts": ["Gold 1 g", "Silver 1 kg", "Crude oil mini", "Natural gas mini", "Margin quant"], "names": ["Pooja", "Irfan", "Rekha", "Vivek", "Aditya"], "color": "#f59e0b"},
    {"id": "crypto", "name": "Crypto desk", "bucket": "CRYPTO", "source": "kraken", "sources": ["kraken"], "agents": [("Tara", "Lead analyst"), ("Nikhil", "Quant analyst"), ("Sam", "Trading manager")],
     "analysts": ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "Volatility quant"], "names": ["Tara", "Kiran", "Ayaan", "Mira", "Zubin", "Esha", "Nikhil"], "color": "#ec4899"},
    {"id": "intel", "name": "Market intelligence", "bucket": None, "source": "news", "sources": ["nse", "yahoo", "news", "upstox", "claude"], "agents": [("Priya", "Lead analyst"), ("Aryan", "Quant analyst"), ("Ira", "Chief forecaster")],
     "analysts": ["World markets", "Smart money", "Option walls", "Headlines desk", "Forecast quant"], "names": ["Priya", "Rahul", "Shreya", "Aman", "Aryan"], "color": "#38bdf8"},
    {"id": "lab", "name": "Strategy lab", "bucket": None, "source": "github", "sources": ["github", "claude"], "agents": [("Priyanka", "Research agent"), ("Lakshmi", "Evaluation agent"), ("Vikas", "Lab manager")],
     "analysts": ["Research agent", "Implementation agent", "Evaluation agent", "Review agent", "Data engineer"], "names": ["Priyanka", "Omar", "Lakshmi", "Joseph", "Rhea"], "color": "#10b981"},
    {"id": "ipo", "name": "IPO desk", "bucket": None, "source": "nse", "sources": ["nse", "news", "claude"], "agents": [("Kavya", "Lead analyst"), ("Harsh", "Valuation quant"), ("Hari", "IPO manager")],
     "analysts": ["DRHP reader", "Subscription tracker", "IPO news reader", "Valuation quant"], "names": ["Kavya", "Yash", "Nisha", "Harsh"], "color": "#ef4444"},
]
SOURCES = [("nse", "NSE"), ("upstox", "Upstox"), ("indmoney", "INDmoney"), ("kraken", "Kraken"), ("yahoo", "Yahoo Finance"), ("news", "News feeds"), ("claude", "Claude AI"), ("github", "CEO inbox (GitHub)")]
TEAM_AWARD, COO_AWARD = 500, 1000
BASE_EFFORT, MAX_EFFORT = 2, 3            # the intraday hunters and scalpers always hunt actively; an extra Associate hired by the COO widens the scan
SENIOR = {"trades": 10, "win_rate": 45.0}


def kind_of(title: str) -> str:
    t = title.lower()
    return ("audit" if "review" in t else "implement" if "implement" in t else "backtest" if "backtest" in t or "evaluation" in t else "data" if any(x in t for x in ("scanner", "engineer", "tracker", "world"))
            else "quant" if "quant" in t or "checker" in t else "research")


def team_of(t: dict) -> str | None:
    d, s = t.get("desk"), str(t.get("strategy") or "")
    if d == "EQUITY":
        return "scalp" if s.startswith("scalp") else "swing" if t.get("opened") in ("swing", "signal") else "intraday"
    return {"FNO": "fno", "COMMODITY": "mcx", "CRYPTO": "crypto"}.get(d)


def new_state() -> dict:
    return {"tokens": {}, "ledger": [], "requests": [], "messages": [], "retired": [], "resumed": [], "paused_teams": [], "variants": {}, "awarded": [], "said": {}, "effort": {}, "hires": [], "designations": {}, "flows": [], "flow_seen": {}, "flow_at": {}}


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
            text = f"Understood. {r['team']} keeps working; I will keep watching its record and report again."
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
    st["messages"] = [m for m in st["messages"] if m.get("kind") != "mood"]           # hunger and moods are retired
    for k_ in ("eco", "mood"):
        st.pop(k_, None)
    _hiring(st, now, ctx, sum(float(t.get("pnl_rs") or 0) for t in trades if t.get("day") == today and team_of(t) == "intraday"))
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
        if tid in ("intraday", "scalp"):
            hired = [h for h in st["hires"] if h["team"] == tid and h["day"] == today]
            st["effort"][tid] = min(MAX_EFFORT, BASE_EFFORT + len(hired))
        paused_t = tid in st["paused_teams"]
        seats = _seats(spec, tid, td, opn, ctx, session, paused_t, trader, pnl_today <= -500)
        staff = _staff(st, now, spec, tid, seats, T, rec, ctx)
        teams.append({"id": tid, "name": spec["name"], "color": spec["color"], "source": spec["source"], "sources": spec["sources"], "status": status, "agents": agents,
                      "tokens": st["tokens"].get("team:" + tid, 0), "effort": st["effort"].get(tid), "staff": staff, "manager": staff[-1]["id"] if staff else None,
                      "today": {"pnl": pnl_today, "pnl_rs": pnl_today, "trades": len(td), "open": len(opn), "closed": sum(t["status"] in ("WIN", "LOSS") for t in td), "wins": sum(t["status"] == "WIN" for t in td)},
                      "record": rec, "verdicts": verdicts, "activity": recent, "variant": st["variants"].get(tid)})
        _flows(st, now, spec, tid, staff, td, session, paused_t)
        # the COO's notes on this team
        if rec.get("n", 0) >= 10 and rec.get("edge_z") is not None and rec["edge_z"] <= -1.5:
            notes.append({"team": tid, "level": "warn", "text": f"{spec['name']}: targets hit {rec['target_hits']} times against {rec['expected_hits']} expected by pure chance (z {rec['edge_z']}): no edge so far."})
        rj = Q.team_numbers([t for t in T if t.get("setup")]) if tid == "intraday" else rec          # the hunters are judged on their own trades, not the desk's older rules
        losing = rj.get("n", 0) >= 20 and (rj.get("net_rs") or 0) < 0 and ((rj.get("edge_z") is not None and rj["edge_z"] <= -1.5) or (rj.get("win_rate") or 0) < 30)
        if losing and not any(r.get("kind") == "team" and r["team"] == tid and r["status"] == "pending" for r in st["requests"]) and tid not in st["paused_teams"]:
            rid = f"R{now:%y%m%d}-{tid}-{len(st['requests']) + 1}"
            st["requests"].append({"id": rid, "team": tid, "strategy": None, "kind": "team", "status": "pending", "created": now.strftime("%d %b %H:%M"),
                                   "text": f"{spec['name']} keeps losing: {rj['n']} closed trades, net {_fmt(rj.get('net_rs') or 0)}, {rj.get('win_rate')}% won. May I pause the team so the strategy lab can rebuild it? It keeps its open trades until they close."})
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
        race = [t for t in teams if t["id"] not in ("intel", "lab", "ipo") and t["today"]["trades"]]
        best = max(race, key=lambda t: t["today"]["pnl"]) if race else None
        if best and best["today"]["pnl"] > 0:
            give(st, now, "team:" + best["id"], TEAM_AWARD, f"best team today ({_fmt(best['today']['pnl'])})")
            say(st, now, f"{COO['name']} (COO)", f"Bonus: {best['name']} was the best team today with {_fmt(best['today']['pnl'])} after charges. 500 tokens to the team.", "award")
        else:
            say(st, now, f"{COO['name']} (COO)", "No team bonus today: no team finished the day in profit.", "award")
        right = [r for r in ((ctx.get("fc") or {}).get("result") or []) if r.get("direction_right")]
        if right:
            give(st, now, "team:intel", 15 * len(right), "forecast direction right: " + ", ".join(r["name"] for r in right))
            say(st, now, "Ira (Market intelligence)", f"Our forecast called the direction right for {', '.join(r['name'] for r in right)} today: {15 * len(right)} tokens earned.", "award")
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
    leader = max([t for t in teams if t["id"] not in ("intel", "lab", "ipo") and t["today"]["trades"]], key=lambda t: t["today"]["pnl"], default=None)
    coo = {**COO, "tokens": st["tokens"].get(COO["name"], 0), "notes": notes[:12], "requests": pending + [r for r in st["requests"] if r["status"] != "pending"][-5:],
           "doing": f"Supervising {len(teams)} teams: {active} traded today, company {_fmt(comp_today)}." + (f" {len(pending)} request{'s' if len(pending) > 1 else ''} waiting for you." if pending else "") +
                    (f" Bonus race leader: {leader['name']} ({_fmt(leader['today']['pnl'])})." if leader and leader["today"]["pnl"] > 0 else "")}
    board = sorted([{"who": k, "tokens": v} for k, v in st["tokens"].items()], key=lambda x: -x["tokens"])
    if now.timestamp() - st["flow_at"].get("ceo", 0) >= 300:
        st["flow_at"]["ceo"] = now.timestamp()
        _flow(st, now, "coo", "ceo", "report", f"Company today {_fmt(comp_today)}" + (f"; {len(pending)} request(s) for you" if pending else ""))
    coo["hires"] = [h for h in st["hires"] if h["day"] == today]
    coo["designation"] = "COO"
    opn_all = [t for t in trades if t["status"] == "OPEN"]
    pnl = {"today_rs": comp_today, "open_rs": round(sum(float(t.get("pnl_rs") or 0) for t in opn_all), 2), "closed_rs": round(sum(float(t.get("pnl_rs") or 0) for t in trades if t["day"] == today and t["status"] in ("WIN", "LOSS")), 2),
           "trades": sum(1 for t in trades if t["day"] == today), "open": len(opn_all), "equity_rs": ctx.get("equity")}
    return {"updated_at": now.isoformat(timespec="seconds"), "ceo": {"name": CEO, "title": "CEO"}, "coo": coo, "pnl": pnl, "flows": st["flows"][-60:], "teams": teams, "sources": [{"id": s_, "name": n_, **((ctx.get("sources") or {}).get(s_) or {"status": "unknown", "detail": ""})} for s_, n_ in SOURCES], "board": board[:20],
            "ledger": st["ledger"][:20], "messages": st["messages"][:30], "company": {"pnl_today": comp_today, "nifty_chg": ctx.get("nifty_chg"), "equity": ctx.get("equity"), "sessions": ctx.get("sessions")},
            "awards": {"team": TEAM_AWARD, "coo": COO_AWARD}, "execution": {"mode": gw.get("mode"), "intents": len(gw.get("intents") or {}), "refused": sum(refused.values())}}


def _seats(spec: dict, tid: str, td: list[dict], opn: list[dict], ctx: dict, session: bool, paused: bool, officer_doing: str, alert: bool) -> list[dict]:
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
                seat(title, "resting", "Off duty: the COO switches it on when the desk needs a wider scan")
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
    elif tid == "lab":
        lab = ctx.get("lab") or {}
        cnt = {x["stage"]: x["n"] for x in lab.get("stages") or []}
        rows = lab.get("strategies") or []
        inv = [r["strategy"] for r in rows if r["stage"] == "INVESTIGATE"]
        seat("Research agent", "active" if cnt.get("PROPOSED") else "idle", f"{cnt.get('PROPOSED', 0)} improved version(s) proposed, waiting for your approval" if cnt.get("PROPOSED") else "Reads every losing streak for an idea worth testing")
        seat("Implementation agent", "active" if (lab.get("experiments") or []) else "idle", f"{len(lab.get('experiments') or [])} new version(s) running on paper" if lab.get("experiments") else "Builds approved versions as new paper strategies")
        seat("Evaluation agent", "active" if rows else "idle", f"Testing {len(rows)} strategies: {cnt.get('BUILT', 0)} built, {cnt.get('TESTED', 0)} tested, {cnt.get('APPROVED', 0)} approved, {cnt.get('INVESTIGATE', 0)} to investigate" if rows else "Waiting for closed trades")
        seat("Review agent", "alert" if inv else "idle", ("Challenging " + ", ".join(x.replace("_", " ") for x in inv[:3]) + ": failed a check") if inv else "Audits every check before a strategy is approved")
        fresh = [k for k, v in (ctx.get("sources") or {}).items() if (v or {}).get("status") in ("warn", "off")]
        seat("Data engineer", "alert" if fresh else "active", ("Data gaps: " + ", ".join(fresh[:4])) if fresh else "Every data feed is fresh")
    elif tid == "ipo":
        ipo = ctx.get("ipo") or {}
        L_ = ipo.get("ipos") or []
        opn_i = [x for x in L_ if x.get("status") == "open"]
        seat("DRHP reader", "active" if ipo.get("drhp_recent") else "idle", f"{len(ipo.get('drhp_recent') or [])} recent draft prospectuses filed with SEBI" if ipo.get("drhp_recent") else "Waiting for SEBI's list of draft prospectuses")
        seat("Subscription tracker", "active" if opn_i else "idle", (f"{len(opn_i)} IPO(s) open: " + ", ".join(x.get("name", "")[:18] for x in opn_i[:3])) if opn_i else f"{len(L_)} upcoming or recent issues on NSE")
        seat("IPO news reader", "active" if any(x.get("news") for x in L_) else "idle", f"Headlines for {sum(1 for x in L_ if x.get('news'))} issue(s)")
        apply_ = [x for x in L_ if str((x.get("analysis") or {}).get("verdict", "")).startswith("Apply")]
        seat("Valuation quant", "active" if apply_ else "idle", (f"{len(apply_)} issue(s) worth one lot: " + ", ".join(x.get("name", "")[:18] for x in apply_[:3])) if apply_ else "Scores each issue on subscription, size and offer-for-sale share")
    else:
        sm, fc, n_head = ctx.get("sm") or {}, ctx.get("fc") or {}, ctx.get("news_n") or 0
        seat("World markets", "active" if ctx.get("world") else "idle", "Overnight US, Asia, dollar, crude and gold, refreshed every half hour before the open")
        seat("Smart money", "active" if sm.get("participants") else "idle", f"NSE participant positions for {sm.get('day')}" if sm.get("day") else "Waiting for NSE's file")
        seat("Option walls", "active" if sm.get("chains") else "idle", "Largest call and put open interest on NIFTY and Bank Nifty")
        nd = ctx.get("news_digest") or {}
        seat("Headlines desk", "active" if n_head or nd else "idle", (f"Claude read the headlines: {nd.get('mood', '')}. {nd.get('brief', '')}"[:160]) if nd.get("brief") else f"{n_head} high-impact headlines in the feed")
        v = (fc.get("views") or {}).get("Nifty 50")
        seat("Forecast quant", "active" if v else "idle", f"Nifty {v['bias'].lower()}, range {v['lo']:,} to {v['hi']:,}" if v else "Builds the 08:45 forecast")
    name = spec["agents"][2][0]
    out.append({"title": spec["agents"][2][1], "name": name, "officer": True, "doing": officer_doing,
                "status": "alert" if alert else "holding" if opn else "active" if td else "idle"})
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
    elif tid == "lab":
        lab = ctx.get("lab") or {}
        r = f"{len(lab.get('strategies') or [])} strategies in the pipeline; {len(lab.get('approved') or [])} passed every check."
        rv = (lab.get("review") or {}).get("text")
        return r, "Seven checks on the paper record: enough trades, profit after charges, double costs, out of sample, beats chance, most days, losing streak.", ("Today's review is written." if rv else "Writes the day's review after the close.")
    elif tid == "ipo":
        ipo = ctx.get("ipo") or {}
        r = f"{len(ipo.get('ipos') or [])} issues tracked; {len(ipo.get('drhp_recent') or [])} recent draft prospectuses."
        return r, "Minimum lot at the top of the price band; listing range from subscription demand.", "Suggests at most one lot; never applies on its own."
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


HIRE_NAMES = ["Farhan", "Leena", "Sahil", "Nora", "Dhruv", "Isha", "Kabir", "Ritu"]


def _hiring(st: dict, now: datetime, ctx: dict, pnl: float) -> None:
    """The COO hires an extra Associate for the intraday hunters when they find more setups than the day's trade limit lets them take
    (the hire widens the scan and lifts the limit; the risk per trade never changes), and lets the hire go if the desk then loses Rs 500 on the day."""
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    d = ctx.get("intraday_diag") or {}
    found = sum(len(v) for v in (d.get("found") or {}).values())
    capped = [k for k, v in (d.get("skipped") or {}).items() if "limit" in str(v) or "already open" in str(v)]
    mine = [h for h in st["hires"] if h["team"] == "intraday" and h["day"] == today]
    if mine and pnl <= -500:
        st["hires"] = [h for h in st["hires"] if h not in mine]
        say(st, now, f"{COO['name']} (COO)", f"Intraday hunters are down {_fmt(pnl)} today: I have stood down {mine[0]['name']} (extra scanner) and the desk is back to its normal limits.", "decision")
        return
    if (ctx.get("sessions") or {}).get("equity") and "09:30" <= hhmm <= "14:30" and found >= 12 and len(capped) >= 3 and not mine and "intraday" not in st["paused_teams"] and pnl > -500:
        name = HIRE_NAMES[len(st["hires"]) % len(HIRE_NAMES)]
        why = f"the desk found {found} setups but its limits left {len(capped)} untaken ({', '.join(capped[:3])})"
        st["hires"] = (st["hires"] + [{"day": today, "t": now.strftime("%H:%M"), "team": "intraday", "name": name, "designation": "Associate", "role": "Overflow scanner", "why": why}])[-30:]
        say(st, now, f"{COO['name']} (COO)", f"Hired {name} as an Associate on the intraday desk: {why}. The desk may take a few more trades today at the same Rs 150 risk each.", "hire")
        _flow(st, now, "coo", "intraday-m", "order", f"Hired {name}: overflow scanner")


def _seat_trades(tid: str, title: str, T: list[dict]) -> list[dict] | None:
    """The trades a seat's own work led to, or None for a team-wide role judged on the team's record."""
    if tid == "intraday":
        m = {"Filings hunter": ("news", "news-led"), "Headlines hunter": ("news", "headline-led"), "Gap scanner": ("gap", None), "Momentum scanner": ("momentum", None), "VWAP pressure scanner": ("vwap", None)}.get(title)
        return [t for t in T if t.get("setup") == m[0] and (m[1] is None or t.get("basis") == m[1])] if m else None
    if tid == "scalp":
        return T if title == "VWAP pullback hunter" else None
    if tid == "swing":
        keys = {"Breakout analyst": ("breakout",), "Trend analyst": ("trend", "ema", "momentum"), "Dip analyst": ("dip", "pullback", "shock", "rsi", "results"), "Signal desk": ("signal",)}.get(title)
        return [t for t in T if any(x in str(t["strategy"]) for x in keys)] if keys else None
    if tid == "fno":
        u = {"NIFTY chain reader": "NIFTY", "Bank Nifty chain reader": "BANKNIFTY"}.get(title)
        return [t for t in T if t.get("underlying", "NIFTY") == u] if u else None
    if tid in ("mcx", "crypto"):
        out = [t for t in T if str(t.get("label", "")).startswith(title) or t.get("symbol") == title]
        return out if "quant" not in title.lower() else None
    return None


def _staff(st: dict, now: datetime, spec: dict, tid: str, seats: list[dict], T: list[dict], rec: dict, ctx: dict) -> list[dict]:
    """Everyone at the team's row, with a designation earned from the record."""
    today, out = now.strftime("%Y-%m-%d"), []
    hires = [h for h in st["hires"] if h["team"] == tid and h["day"] == today]
    rows = seats[:-1] + [{"title": h["role"], "name": h["name"], "status": "active", "doing": f"Hired today by the COO: {h['why']}", "hire": True} for h in hires] + seats[-1:]
    team_ok = rec.get("n", 0) >= 20 and (rec.get("net_rs") or 0) > 0 and (rec.get("edge_z") is None or rec["edge_z"] >= 0)
    for i, x in enumerate(rows):
        officer, title = bool(x.get("officer")), x["title"]
        sid = f"{tid}-m" if officer else f"{tid}-h{i}" if x.get("hire") else f"{tid}-{i}"
        name = x.get("name") or (spec["names"][i] if i < len(spec["names"]) else title)
        mine = None if officer or x.get("hire") else _seat_trades(tid, title, T)
        basis = "team record"
        if mine is not None:
            cl = [t for t in mine if t["status"] in ("WIN", "LOSS")]
            n, w = len(cl), sum(t["status"] == "WIN" for t in cl)
            net = round(sum(float(t.get("pnl_rs") or 0) for t in cl), 2)
            ok, basis = n >= SENIOR["trades"] and net > 0 and w / n * 100 >= SENIOR["win_rate"], "own trades"
        else:
            n, w, net = rec.get("n", 0), round(rec.get("n", 0) * (rec.get("win_rate") or 0) / 100), rec.get("net_rs", 0)
            ok = team_ok
            if tid == "intel":
                rf = ((ctx.get("fc") or {}).get("record") or {}).get("Nifty 50") or {}
                ok, basis = rf.get("days", 0) >= 10 and (rf.get("direction") or 0) >= 55, "forecast record"
            elif tid == "lab":
                ok, basis = bool((ctx.get("lab") or {}).get("approved")), "strategies approved"
            elif tid == "ipo":
                ok, basis = False, "listings called"
        desig = "Manager" if officer else "Associate" if x.get("hire") else "Senior Associate" if ok else "Associate"
        prev = st["designations"].get(sid)
        if not officer and not x.get("hire") and prev and prev != desig:
            say(st, now, f"{COO['name']} (COO)", (f"Promoted {name} ({title}) to Senior Associate: {n} closed trades, {_fmt(net)}." if desig == "Senior Associate" else
                                                  f"{name} ({title}) is back to Associate until the record recovers ({_fmt(net)} over {n} trades)."), "promotion")
        st["designations"][sid] = desig
        status = {"resting": "idle"}.get(x["status"], x["status"])
        out.append({"id": sid, "name": name, "designation": desig, "role": (spec["agents"][2][1] if officer else title), "kind": "trader" if officer else kind_of(title), "status": status,
                    "doing": x["doing"] if not (x["status"] == "resting" and "Off duty" not in x["doing"]) else "Market closed: " + x["doing"][0].lower() + x["doing"][1:],
                    "record": {"trades": n, "wins": w, "pnl_rs": net, "basis": basis}})
    return out


def _flow(st: dict, now: datetime, a: str, b: str, kind: str, text: str) -> None:
    st["flows"] = (st["flows"] + [{"t": now.strftime("%H:%M:%S"), "from": a, "to": b, "kind": kind, "text": text[:90]}])[-80:]


def _flows(st: dict, now: datetime, spec: dict, tid: str, staff: list[dict], td: list[dict], session: bool, paused: bool) -> None:
    """What moves across the floor: data from the sources to the analysts, setups to the manager, orders and reports to the COO."""
    if not staff:
        return
    today, mgr, seen = now.strftime("%Y-%m-%d"), staff[-1]["id"], st["flow_seen"]
    for k in [k for k, v in seen.items() if v != today]:
        del seen[k]
    for t in td:
        k = f"{t['id']}:{t['status']}"
        if k in seen:
            continue
        seen[k] = today
        if t["status"] == "OPEN":
            an = next((x for x in staff[:-1] if (_seat_trades(tid, x["role"], [t]) or [])), staff[0])
            _flow(st, now, an["id"], mgr, "idea", f"{t['label']}: setup found")
            _flow(st, now, mgr, "coo", "order", f"Opened {t['label']} at {float(t.get('entry') or 0):,.2f}")
        else:
            _flow(st, now, mgr, "coo", "report", f"Closed {t['label']}: {_fmt(float(t.get('pnl_rs') or 0))}")
    live = [x for x in staff[:-1] if x["status"] in ("active", "holding", "alert")]
    if (session or tid in ("intel", "lab", "ipo")) and not paused and live and now.timestamp() - st["flow_at"].get(tid, 0) >= 45:
        st["flow_at"][tid] = now.timestamp()
        i = (now.minute * 3 + now.second // 20) % len(live)
        src = spec["sources"][i % len(spec["sources"])]
        _flow(st, now, "src:" + src, live[i]["id"], "data", live[i]["doing"][:80])
