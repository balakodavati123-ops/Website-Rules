"""The paper desk, running with no page open: equities, NIFTY F&O, MCX commodities and crypto, as one team.

Each GitHub run loops for LOOP_SECONDS, re-reading real-time Upstox prices every 15 seconds (all ~2,760 NSE
equities, index options, MCX futures) and Kraken for crypto, and lets every desk open, mark and close its own paper
trades by fixed rules. Every trade lands in one shared list (docs/data/all_trades.json) with the reason it was
taken, so the page, the scoreboard and the learning loop all read the same trades. No order is ever placed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desks as D        # noqa: E402
import intraday as I     # noqa: E402
import upstox as U       # noqa: E402
import open_fill as OF   # noqa: E402
import ledger as L       # noqa: E402
import account as A      # noqa: E402
import executor as X     # noqa: E402
import sod as SOD        # noqa: E402
import notify as N       # noqa: E402
import daily as DLY      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = Path(os.environ.get("DESK_DOCS") or ROOT / "docs" / "data")
IST = D.IST
PUBLISH_EVERY = 15
IDX = {"nifty": "NSE_INDEX|Nifty 50", "banknifty": "NSE_INDEX|Nifty Bank", "vix": "NSE_INDEX|India VIX", "sensex": "BSE_INDEX|SENSEX"}
DAILY_FILES = ["world_markets", "world_news", "events_today", "results_filed", "crypto_quotes", "crypto_candles", "alerts_log", "desk_signals", "signal_ledger", "signal_lessons", "fo_ledger",
               "macro_signals", "strategies_macro", "paper_equity", "approved_strategies"]
NIFTY = IDX["nifty"]


def load(name: str, default):
    f = DOCS / name
    try:
        return json.loads(f.read_text()) if f.exists() else default
    except Exception:
        return default


def save(name: str, obj) -> None:
    (DOCS / name).write_text(json.dumps(obj, indent=1))


def unify_equity(book: dict) -> list[dict]:
    out = []
    for t in book.get("trades", []):
        d = 1 if t["side"] == "LONG" else -1
        pnl = t["pnl_rs"] if t["status"] != "OPEN" else round(d * (t["last"] - t["entry"]) * t["qty"], 2)
        out.append({"id": f"E{str(t['day']).replace('-', '')[2:]}-{t['id']}", "desk": "EQUITY", "strategy": t.get("basis", "price only").replace(" ", "_"), "label": t["label"], "symbol": t.get("symbol"), "side": t["side"],
                    "entry": t["entry"], "last": t["last"], "exit": t.get("exit", ""), "qty": t["qty"], "stop": t.get("stop"), "status": t["status"], "pnl_rs": pnl, "reason": t.get("reason", ""),
                    "why": t.get("why", ""), "day": t["day"], "opened": t["time"], "closed": "", "risk_class": "Intraday momentum", "margin_rs": round(t["entry"] * t["qty"] * 0.2)})
    return out


def OF_opens(token: str, led: list[dict]) -> dict:
    want = {r["symbol"] for r in led if r["status"] == "PENDING" and r["market"] == "NSE"}
    keys = {x["trading_symbol"]: x["instrument_key"] for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ" and x["trading_symbol"] in want}
    q = U.quotes(list(keys.values()), token)
    return {s: float((q.get(k, {}).get("ohlc") or {}).get("open") or 0) or None for s, k in keys.items()}


def sessions(now: datetime) -> dict:
    t, wk = D.mins(now.strftime("%H:%M")), now.weekday() < 5
    return {"equity": wk and D.mins("09:10") <= t <= D.mins("15:40"), "fno": wk and D.mins("09:15") <= t <= D.mins("15:30"),
            "mcx": wk and D.mins("09:00") <= t <= D.mins("23:30"), "crypto": True}


def close_stale(eq: dict, xb: dict, today: str) -> None:
    """A trade left open from an earlier day (a run was missed) is closed now at its last known price."""
    now = datetime.now(IST)
    for t in eq.get("trades", []):
        if t["status"] == "OPEN" and t["day"] != today:
            I.close_trade(t, t["last"], "carried over: closed late at the last price")
    for t in xb["trades"]:
        if t["status"] == "OPEN" and t["day"] != today and t["desk"] in ("FNO", "COMMODITY"):
            D.finish(t, t["last"], "carried over: closed late at the last price", now, t["pnl_rs"])


def _git(*a, check=True):
    import subprocess
    return subprocess.run(["git", "-c", "user.name=desk-bot", "-c", "user.email=desk-bot@users.noreply.github.com", *a], cwd=ROOT, check=check, capture_output=True, text=True)


def sync_daily() -> None:
    """Bring in what the daily job committed (new signals, world data, results) so a long live run never works from stale files."""
    br = os.environ.get("GITHUB_REF_NAME")
    if not br or not os.environ.get("GITHUB_TOKEN"):
        return
    try:
        _git("fetch", "-q", "--depth=1", "origin", br)
        for f in DAILY_FILES:
            _git("checkout", "FETCH_HEAD", "--", f"docs/data/{f}.json", check=False)
        # the paper ledger has two writers: the daily job adds new orders, this engine fills them at the open. Keep ours, add theirs.
        theirs = _git("show", "FETCH_HEAD:docs/data/paper_ledger.json", check=False)
        lf = DOCS / "paper_ledger.json"
        if theirs.returncode == 0 and lf.exists():
            mine = json.loads(lf.read_text())
            have = {r["id"] for r in mine}
            add = [r for r in json.loads(theirs.stdout) if r["id"] not in have]
            if add:
                lf.write_text(json.dumps(mine + add, indent=1))
    except Exception as e:
        print("sync failed:", str(e)[:150])


def commit_main(paths: list[str], msg: str) -> None:
    if not os.environ.get("GITHUB_REF_NAME") or not os.environ.get("GITHUB_TOKEN"):
        return
    try:
        _git("add", *paths)
        if _git("diff", "--cached", "--quiet", check=False).returncode:
            _git("commit", "-q", "-m", msg)
            for _ in range(3):
                if _git("pull", "-q", "--rebase", "-X", "theirs", check=False).returncode == 0 and _git("push", "-q", check=False).returncode == 0:
                    break
    except Exception as e:
        print("commit failed:", str(e)[:150])


def publish() -> None:
    """Push a snapshot of docs/data to the `data` branch (one fresh commit, force-pushed, so history never grows).
    The live page reads it from raw.githubusercontent.com, so it stays current while a long run is still going."""
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (tok and repo):
        return
    import shutil
    import subprocess
    import tempfile
    d = Path(tempfile.mkdtemp())
    try:
        for f in DOCS.glob("*.json"):
            shutil.copy(f, d / f.name)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=desk-bot", "-c", "user.email=desk-bot@users.noreply.github.com", *a], cwd=d, check=True, capture_output=True, text=True)
        git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "live data")
        git("push", "-q", "-f", f"https://x-access-token:{tok}@github.com/{repo}.git", "HEAD:refs/heads/data")
    except Exception as e:
        print("publish failed:", str(e)[:200].replace(tok, "***"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def migrate() -> None:
    """One time: trades opened before the Rs 1,00,000 account existed were sized for other pools. Shrink the open ones
    so the swing and signal books fit their slices; closed trades and their results are untouched."""
    for name, bucket, budget in (("paper_ledger.json", "swing", A.START * A.BUDGET["swing"]), ("signal_ledger.json", "signal", A.START * A.BUDGET["signal"])):
        f = DOCS / name
        if not f.exists():
            continue
        rows = json.loads(f.read_text())
        todo = [r for r in rows if r["status"] == "OPEN" and not r.get("rebased")]
        if not todo:
            continue
        val = lambda r: float(r.get("entry") or 0) * float(r.get("qty") or 0)
        total = sum(val(r) for r in rows if r["status"] == "OPEN")
        k = min(1.0, budget / total) if total else 1.0
        for r in todo:
            q0 = float(r["qty"] or 0)
            q1 = max(1, int(q0 * k)) if q0 else q0
            f_ = q1 / q0 if q0 else 1
            r["qty"] = q1
            for key in ("risk_rs", "unrealized_rs", "unreal_rs"):
                if r.get(key) not in (None, ""):
                    r[key] = round(float(r[key]) * f_, 2)
            if r.get("deploy_rs") not in (None, ""):
                r["deploy_rs"] = round(float(r["deploy_rs"]) * f_, 2)
            r["rebased"] = True
            r["note"] = (r.get("note") or "") + " Resized to fit the Rs 1,00,000 account."
        f.write_text(json.dumps(rows, indent=1))


def run() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    migrate()
    token = os.environ.get("UPSTOX_TOKEN", "").strip()
    end = time.time() + int(os.environ.get("LOOP_SECONDS", "0"))
    eq = load("live_book.json", {"day": "", "trades": [], "seen": {}, "seq": 0})
    xb = load("desk_book.json", D.new_book())
    if not xb.get("rebased"):                  # one time: positions opened before the Rs 1,00,000 account are closed at their last price, and today's desks may trade again within their limits
        nowr, todayr = datetime.now(IST), datetime.now(IST).strftime("%Y-%m-%d")
        for t in xb["trades"]:
            if t["status"] == "OPEN":
                D.finish(t, t["last"], "closed: the account was reset to Rs 1,00,000 and this position was larger than its limit", nowr, t["pnl_rs"])
        xb["seen"] = {k: v for k, v in xb["seen"].items() if not k.startswith(todayr)}
        xb["rebased"] = True
    archive = {t["id"]: t for t in load("trade_archive.json", [])}
    paused = {s["strategy"] for s in load("strategy_stats.json", []) if s["verdict"] == "PAUSED"}
    news, status, i = I.filings_news(), {"desks": {}}, 0
    mcx_c: list = []
    filled, snap, series, last_slow = False, {}, load("pnl_series.json", {}), 0.0
    qs: dict = {}
    plan, eod_hist, told = load("intraday_plan.json", {}), load("eod_history.json", []), load("notified.json", {"open": [], "closed": [], "plan": "", "eod": ""})
    intra: dict = load("intraday.json", {"day": "", "s": {}})
    last_intra, key_of = 0.0, {}
    if token:
        try:
            key_of = {x["trading_symbol"]: x["instrument_key"] for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"}
        except Exception:
            pass
    def compose():
        live_open = [t for t in unify_equity(eq) + xb["trades"] if t["status"] == "OPEN"]
        books = L.swing(load("paper_ledger.json", [])) + L.weekly_fno(load("fo_ledger.json", [])) + L.signals(load("signal_ledger.json", []))
        allt = list(archive.values()) + live_open + books
        allt.sort(key=lambda t: (t["day"], t["opened"]), reverse=True)
        if key_of:
            for t in allt:
                if t["desk"] == "EQUITY" and t.get("symbol") and not t.get("instrument_key"):
                    t["instrument_key"] = key_of.get(t["symbol"])
        return allt, books

    def persist() -> None:
        save("live_book.json", eq)
        xb["trades"] = [t for t in xb["trades"] if t["status"] == "OPEN" or t["id"] not in archive]
        save("desk_book.json", xb)
        allt, books = compose()
        save("trade_archive.json", sorted((t for t in archive.values()), key=lambda t: (t["day"], t["opened"]))[-4000:])
        save("all_trades.json", allt[:4000])
        stats = D.learn(list(archive.values()) + [t for t in books if t["status"] in ("WIN", "LOSS")])
        save("strategy_stats.json", stats)
        try:                                           # the bridge to the broker: off unless EXEC_MODE is set
            X.run(allt, stats, DOCS / "executions.json")
        except Exception as e:
            status["desks"]["execution"] = f"error: {str(e)[:100]}"
        status["open"] = sum(t["status"] == "OPEN" for t in allt)
        save("live_status.json", status)
        nf = (snap.get("indices") or {}).get("Nifty 50", {}).get("last")
        series.update(L.day_series(series, datetime.now(IST).strftime("%Y-%m-%d"), datetime.now(IST).strftime("%H:%M:%S"), allt, nf))
        save("pnl_series.json", series)
        save("prices.json", {"updated_at": status.get("updated_at"), **snap})
        if qs:
            save("quotes.json", {"updated_at": status.get("updated_at"), "q": qs})
        nonlocal_state["tick"] = allt
        save("account.json", {"updated_at": status.get("updated_at"), **A.summary(allt)})

    nonlocal_state: dict = {}
    last_pub = 0.0
    while True:
        now = datetime.now(IST)
        today, hhmm, ses = now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), sessions(now)
        close_stale(eq, xb, today)
        rm = A.rooms(nonlocal_state.get("tick") or compose()[0])
        for t in unify_equity(eq) + xb["trades"]:       # keep every closed trade before the day's book resets
            if t["status"] != "OPEN":
                archive[t["id"]] = t
        info = status["desks"]
        q_idx, ctx, rows_now = {}, {}, []
        if token and (ses["fno"] or ses["mcx"] or ses["equity"]):
            try:
                q_idx = U.quotes(list(IDX.values()), token)
            except Exception as e:
                info["indices"] = f"error: {e}"
        if token and ses["equity"]:
            try:
                rows = rows_now = U.equity_rows(token)
                qs.clear()
                qs.update({r["symbol"]: [round(r["price"], 2), round(r["chg_pct"], 2), r["day_high"], r["day_low"], int(r["volume"])] for r in rows})
                if rows:
                    I.step(eq, today, hhmm, rows, news, rm["intraday"])
                info["equity"] = f"{len(rows)} stocks, real time"
            except Exception as e:
                info["equity"] = f"error: {e}"
        elif ses["equity"]:
            info["equity"] = "no token: Yahoo fallback runs in intraday.py"
        if token and ses["equity"] and hhmm >= "09:16" and not filled:
            try:                                   # pending paper orders fill at today's real open, not a day late
                lf = DOCS / "paper_ledger.json"
                if lf.exists():
                    led = json.loads(lf.read_text())
                    n = OF.fill_pending(led, DLY.RULES, OF_opens(token, led), now.date(), (q_idx.get("NSE_INDEX|India VIX") or {}).get("last_price"))
                    if n:
                        lf.write_text(json.dumps(led, indent=1))
                    info["paper_orders"] = f"{n} pending orders filled or expired at today's open"
                filled = True
            except Exception as e:
                info["paper_orders"] = f"error: {e}"
        if token and ses["mcx"]:
            try:
                mcx_c = mcx_c or D.mcx_contracts(U.instruments("MCX"), now.date())
                D.mcx_step(xb, now, U.quotes([c["key"] for c in mcx_c], token), mcx_c, paused, rm["COMMODITY"])
                info["commodities"] = f"{len(mcx_c)} MCX futures, real time"
            except Exception as e:
                info["commodities"] = f"error: {e}"
        if token and ses["fno"]:
            try:
                n = q_idx.get(NIFTY, {})
                spot = n.get("last_price")
                exps = [e for e in U.expiries(token, NIFTY) if e >= today]
                open_exp = {t["expiry"] for t in xb["trades"] if t["desk"] == "FNO" and t["status"] == "OPEN"}
                chains = {e: U.option_chain(token, NIFTY, e) for e in sorted(open_exp | {exps[0]}) if e >= today or e in open_exp}
                ctx = {"spot": spot, "prev": (spot - n["net_change"]) if spot and n.get("net_change") is not None else None, "chains": chains, "expiry": exps[0], "lot": U.lot_size(NIFTY, exps[0]), "room": rm["FNO"]}
                D.fno_step(xb, now, ctx, paused)
                rows_ = chains.get(exps[0]) or []
                if rows_ and spot:
                    atm = min((r["strike_price"] for r in rows_), key=lambda k: abs(k - spot))
                    st_ = D._buy(D._px(rows_, atm, "CE")) + D._buy(D._px(rows_, atm, "PE"))
                    snap["fno"] = {"spot": spot, "expiry": exps[0], "lot": ctx["lot"], "atm": atm, "straddle": round(st_, 1), "vix": (q_idx.get(IDX["vix"]) or {}).get("last_price")}
                info["fno"] = f"NIFTY {spot} , expiry {exps[0]}, {len(chains)} chain(s), real time"
            except Exception as e:
                info["fno"] = f"error: {e}"
        try:
            ticks = D.kraken_ticks()
            D.crypto_step(xb, now, ticks, paused, rm["CRYPTO"])
            snap["crypto"] = [{"name": k, "last": v["last"], "chg_pct": (v["last"] / v["open"] - 1) * 100, "high": v["high"], "low": v["low"], "unit": "$"} for k, v in ticks.items()]
            info["crypto"] = "6 coins from Kraken, real time"
        except Exception as e:
            info["crypto"] = f"error: {e}"
        if q_idx:
            names = {IDX["nifty"]: "Nifty 50", IDX["banknifty"]: "Bank Nifty", IDX["vix"]: "India VIX", IDX["sensex"]: "Sensex"}
            snap["indices"] = {names[k]: {"name": names[k], "last": v.get("last_price"), "chg_pct": (v["net_change"] / (v["last_price"] - v["net_change"]) * 100) if v.get("net_change") is not None and v.get("last_price") else None,
                                          "high": (v.get("ohlc") or {}).get("high"), "low": (v.get("ohlc") or {}).get("low")} for k, v in q_idx.items() if k in names}
        if ses["mcx"] and mcx_c:
            try:
                qm = U.quotes([c["key"] for c in mcx_c], token)
                snap["mcx"] = [{"key": c["key"], "name": c["label"], "last": qm[c["key"]]["last_price"], "chg_pct": qm[c["key"]]["net_change"] / (qm[c["key"]]["last_price"] - qm[c["key"]]["net_change"]) * 100, "high": (qm[c["key"]].get("ohlc") or {}).get("high"), "low": (qm[c["key"]].get("ohlc") or {}).get("low"), "unit": "₹"} for c in mcx_c if c["key"] in qm and qm[c["key"]].get("last_price")]
            except Exception:
                pass
        if ses["equity"] and rows_now:
            liq = [r for r in rows_now if r["price"] * r["volume"] >= 1e8 and r["price"] >= 20]
            top = lambda lst: [{"symbol": r["symbol"], "price": r["price"], "chg_pct": round(r["chg_pct"], 2), "turnover_cr": round(r["price"] * r["volume"] / 1e7, 1)} for r in lst[:8]]
            snap["movers"] = {"gainers": top(sorted(liq, key=lambda r: -r["chg_pct"])), "losers": top(sorted(liq, key=lambda r: r["chg_pct"])), "active": top(sorted(liq, key=lambda r: -r["price"] * r["volume"])), "count": len(rows_now)}
        if token and now.weekday() < 5:
            try:
                if hhmm >= "08:45" and plan.get("day") != today:                      # start of day: tone, news, the names to watch and their trigger levels
                    qi = q_idx or U.quotes(list(IDX.values()), token)
                    nf, vx = qi.get(NIFTY) or {}, qi.get(IDX["vix"]) or {}
                    results, events = load("results_filed.json", []), load("events_today.json", [])
                    syms = set(news) | {r.get("symbol") for r in results} | {e.get("symbol") for e in events if str(e.get("date", ""))[:10] == today}
                    keys = {sy: key_of[sy] for sy in syms if sy in key_of}
                    qq = U.quotes(list(keys.values()), token) if keys else {}
                    quotes = {sy: (qq[k]["last_price"], qq[k].get("net_change") or 0) for sy, k in keys.items() if k in qq and qq[k].get("last_price")}
                    prev_n = (nf.get("last_price") or 0) - (nf.get("net_change") or 0)
                    plan = SOD.build_plan(None, today, hhmm, load("world_markets.json", []), events, results, load("news_feed.json", []), news, quotes, vx.get("last_price"),
                                          {"last": nf.get("last_price"), "chg_pct": round(nf["net_change"] / prev_n * 100, 2) if nf.get("net_change") is not None and prev_n else None})
                    save("intraday_plan.json", plan)
                    if told.get("plan") != today:
                        N.push("Day plan", f"Tone {plan['tone']['label']}. {len(plan['watch'])} names to watch. " + " ".join(plan["tone"]["notes"][:2]), 3, "sunrise")
                        told["plan"] = today
                if plan.get("day") == today and plan.get("stage", 0) < 2 and hhmm >= "09:12" and rows_now:    # at the open: who is gapping
                    plan = SOD.add_gaps(plan, rows_now, hhmm)
                    save("intraday_plan.json", plan)
                if hhmm >= "15:45" and (not eod_hist or eod_hist[-1]["day"] != today):                          # end of day report
                    allt_, _b = compose()
                    e = SOD.build_eod(allt_, today, plan if plan.get("day") == today else None, A.summary(allt_)["equity"])
                    save("eod.json", e)
                    eod_hist = [x for x in eod_hist if x["day"] != today] + [{k: e[k] for k in ("day", "trades", "closed", "wins", "win_rate", "pnl", "equity")}]
                    save("eod_history.json", eod_hist[-60:])
                    N.push("End of day", e["notes"][0] if e["notes"] else "No trades today.", 3, "chart_with_upwards_trend")
                # alerts: each trade the desks open or close today, as a ticket you can key into the Upstox app
                for t in unify_equity(eq) + xb["trades"]:
                    if t["desk"] in ("EQUITY", "FNO") and t["day"] == today:
                        if t["status"] == "OPEN" and t["id"] not in told["open"]:
                            ti, bo = N.ticket(t)
                            if N.push(ti, bo, 4, "arrow_up" if t["side"] == "LONG" else "arrow_down"):
                                told["open"].append(t["id"])
                        elif t["status"] in ("WIN", "LOSS") and t["id"] in told["open"] and t["id"] not in told["closed"]:
                            if N.push(f"EXIT: {t['label']}", f"Closed at {t.get('exit')} ({t.get('why')}). Result {t['pnl_rs']:+,.0f} rupees. Close your position if you took the trade.", 4, "stop_sign"):
                                told["closed"].append(t["id"])
                save("notified.json", {**told, "open": told["open"][-300:], "closed": told["closed"][-300:]})
            except Exception as e:
                info["plan"] = f"error: {str(e)[:100]}"
        # one shared list of trades
        trades = unify_equity(eq) + xb["trades"]
        for t in trades:
            if t["status"] != "OPEN":
                archive[t["id"]] = t
        status.update(updated_at=now.isoformat(timespec="seconds"), updated_hm=now.strftime("%d %b %H:%M:%S"), loops=i + 1, sessions=ses,
                      note="Real-time Upstox prices for equities, NIFTY options and MCX; Kraken for crypto. Paper trades only." if token else "No Upstox token: delayed fallback prices.")
        if time.time() - last_slow >= 300:
            last_slow = time.time()
            sync_daily()
            migrate()
            n2 = I.filings_news()
            if n2:
                news = n2
            try:
                I.update_news_feed(now)
            except Exception as e:
                info["news"] = f"error: {str(e)[:80]}"
        if token and time.time() - last_intra >= 60 and nonlocal_state.get("tick"):
            last_intra = time.time()
            try:                                   # today's 5-minute candles for every stock we hold or traded today, for the page's charts
                if intra.get("day") != today:
                    intra = {"day": today, "s": {}}
                key_of = key_of or {x["trading_symbol"]: x["instrument_key"] for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"}
                want = sorted({t["symbol"] for t in nonlocal_state["tick"] if t["desk"] == "EQUITY" and t.get("symbol") and (t["status"] == "OPEN" or t["day"] == today)})[:45]
                for sy in want:
                    if sy in key_of:
                        intra["s"][sy] = U.intraday(token, key_of[sy], 5)
                extra = {"Nifty 50": IDX["nifty"], "Bank Nifty": IDX["banknifty"], "India VIX": IDX["vix"], "Sensex": IDX["sensex"], **{c["label"]: c["key"] for c in mcx_c}}     # the instruments in the strip at the top get charts too
                for nm, k in extra.items():
                    try:
                        intra["s"][nm] = U.intraday(token, k, 5)
                    except Exception:
                        pass
                for coin in D.PAIRS:
                    try:
                        intra["s"][coin] = D.kraken_ohlc(coin, 5, 288)
                    except Exception:
                        pass
                save("intraday.json", intra)
            except Exception as e:
                info["intraday"] = f"error: {str(e)[:80]}"
        i += 1
        persist()
        if time.time() - last_pub >= PUBLISH_EVERY:
            publish()
            last_pub = time.time()
        if time.time() + 5 >= end:
            break
        time.sleep(5)
    persist()
    publish()
    print(status["updated_hm"], status["desks"], "open", status["open"], "closed", len(archive))


if __name__ == "__main__":
    run()
