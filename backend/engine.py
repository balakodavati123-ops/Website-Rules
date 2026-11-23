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
import threading
import time
from datetime import date, datetime, timedelta
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
import margin as MG         # noqa: E402
import forecast as FC       # noqa: E402
import smart_money as SM    # noqa: E402
import horizons as HZ       # noqa: E402
import thesis as TH         # noqa: E402
import scalp as SC          # noqa: E402
import gateway as GW        # noqa: E402
import indstocks as IND     # noqa: E402
import company as CO        # noqa: E402
import quant as QN          # noqa: E402
import ceo_inbox as CI      # noqa: E402
import llm as LLM           # noqa: E402
import lab as LB            # noqa: E402
import ipo as IPO           # noqa: E402
import charts_feed as CF    # noqa: E402
import news_pulse as NP     # noqa: E402
import straddle_lab as SL   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = Path(os.environ.get("DESK_DOCS") or ROOT / "docs" / "data")
IST = D.IST
PUBLISH_EVERY = 15
IDX = {"nifty": "NSE_INDEX|Nifty 50", "banknifty": "NSE_INDEX|Nifty Bank", "vix": "NSE_INDEX|India VIX", "sensex": "BSE_INDEX|SENSEX"}
DAILY_FILES = ["world_markets", "world_news", "events_today", "results_filed", "crypto_quotes", "crypto_candles", "alerts_log", "desk_signals", "signal_ledger", "signal_lessons", "fo_ledger",
               "macro_signals", "strategies_macro", "paper_equity", "approved_strategies"]
NIFTY = IDX["nifty"]
UNDER = {"NIFTY": NIFTY, "BANKNIFTY": IDX["banknifty"]}              # the two indexes with options we trade
VIEW_NAME = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty"}
FC_NAMES = {"Nifty 50": IDX["nifty"], "Bank Nifty": IDX["banknifty"], "Sensex": IDX["sensex"]}       # the indexes we forecast


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
                    "why": t.get("why", ""), "day": t["day"], "opened": t["time"], "closed": t.get("closed", ""), "risk_class": "Intraday hunter", "margin_rs": t.get("margin") or round(t["entry"] * t["qty"] * 0.2),
                    "target_px": t.get("target"), "leverage": t.get("leverage"), "setup": t.get("setup")})
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
        if t["status"] == "OPEN" and t["day"] != today and (t["desk"] in ("FNO", "COMMODITY") and t.get("horizon", "daily") in ("daily", "intraday") or t.get("strategy") == SC.STRATEGY):
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
    cst = load("company.json", {}).get("state") or CO.new_state()            # the company: tokens, the COO's requests, the CEO's decisions
    for k_, v_ in CO.new_state().items():
        cst.setdefault(k_, v_)
    clock = threading.Lock()
    paused = CO.paused_strategies(cst, {s["strategy"] for s in load("strategy_stats.json", []) if s["verdict"] == "PAUSED"}, {})
    news, status, i = {}, {"desks": {}}, 0
    news_thread = None
    mcx_c: list = []
    filled, snap, series, last_slow = False, {}, load("pnl_series.json", {}), 0.0
    qs: dict = {}
    plan, eod_hist, told = load("intraday_plan.json", {}), load("eod_history.json", []), load("notified.json", {"open": [], "closed": [], "plan": "", "eod": ""})
    intra: dict = load("intraday.json", {"day": "", "s": {}})
    last_intra, key_of = 0.0, {}
    M = MG.Margin(token) if token else None
    ind_token = os.environ.get("INDSTOCKS_TOKEN", "").strip()
    ind = IND.Client(ind_token) if ind_token else None                 # INDstocks: reads only unless the gateway is switched to live on a whitelisted host
    master = IND.Master()
    scalp_bars: dict = {}
    headlines: dict = {}
    names_idx: dict = {}
    hl_at = [0.0]
    bars_at, bars_thread = [0.0], [None]
    gw = GW.Gateway(DOCS / "gateway.json", ind, master)
    fc_try = [0.0]
    fc, fc_hist = load("forecast.json", {}), load("forecast_history.json", [])
    sm, parts = load("smart_money.json", {}), load("participants.json", {})
    hist_cache: dict = {}                                            # (index name, day) -> daily candles
    chain_cache: dict = {}                                           # (underlying, expiry) -> (time, rows)
    acct = [A.START]                                                 # account equity, for "per cent of the account" in the written thesis
    world_at = [0.0]                                                 # when world markets were last refreshed from the web
    llm_u = load("llm_usage.json", LLM.new_usage())                  # the Claude analysts and their spending, capped per 5 hours and per day
    ai, ai_lock = LLM.Desk(llm_u), threading.Lock()
    digest, review = [load("news_digest.json", {})], [load("day_review.json", {})]
    ipo_v, ipo_st, lab_v = [load("ipo.json", {})], load("ipo_state.json", {}), [load("lab.json", {})]
    charts_at, charts_thread, fut_key = [0.0], [None], [None]
    pulse = load("news_pulse_state.json", NP.new_state())               # the first look at every headline and filing, about once a minute
    for k_, v_ in NP.new_state().items():
        pulse.setdefault(k_, v_)
    pulse_at, pulse_thread, px_now = [0.0], [None], {}
    inbox_at, inbox_thread = [0.0], [None]
    try:                                                              # the straddle desk's trained playbook (backend/straddle_lab.py, retrained weekly)
        playbook = json.loads((ROOT / "docs" / "models" / "straddle_playbook.json").read_text())
    except Exception:
        playbook = {}
    sdl = {"day": "", "closes": list(playbook.get("closes") or []), "view": {}}
    if playbook:
        save("straddle.json", {"updated_at": datetime.now(IST).isoformat(timespec="seconds"), "today": {}, "playbook": {k: v for k, v in playbook.items() if k not in ("table", "closes")}})

    def get_chain(under: str, expiry: str, ttl: float = 10.0):
        hit = chain_cache.get((under, expiry))
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        rows = U.option_chain(token, UNDER[under], expiry)
        chain_cache[(under, expiry)] = (time.time(), rows)
        return rows

    def lot_of(under: str, expiry: str) -> int:
        U.expiries(token, UNDER[under])
        return U.lot_size(UNDER[under], expiry)

    def world_rows() -> list[dict]:
        live, base = load("world_live.json", {"rows": []})["rows"], load("world_markets.json", [])
        asof = lambda rows: max((r.get("as_of") or "" for r in rows), default="")
        return live if live and asof(live) >= asof(base) else base

    def make_env() -> dict:
        """What every trade's written thesis may quote: today's views, option walls, institutional positions, world tone and headlines."""
        pl = plan if plan.get("day") else {}
        fii = next((p for p in (sm.get("participants") or []) if p["who"] == "FII"), None)
        news_, seen_ = list((pl.get("tone") or {}).get("notes", [])[:3]), set()
        for h in (pl.get("headlines") or []):
            k_ = str(h.get("headline", ""))[:40].lower()
            if h.get("headline") and k_ not in seen_ and len(seen_) < 3:
                seen_.add(k_)
                news_.append(f"{h['headline']} ({h.get('source', '')})")
        if pl.get("results"):
            news_.append(f"{len(pl['results'])} companies filed results or hold board meetings today.")
        views_ = fc.get("views") if fc.get("day") == datetime.now(IST).strftime("%Y-%m-%d") else {}
        return {"view": {u: (views_ or {}).get(n) for u, n in VIEW_NAME.items()}, "chain": {u: (sm.get("chains") or {}).get(u) for u in UNDER}, "tone": pl.get("tone"), "news": news_,
                "world": {r["name"]: r for r in world_rows()},
                "participants": (f"Foreign institutions hold net {fii['fut']:+,} index futures, net {fii['puts']:+,} puts and {fii['calls']:+,} calls (NSE participant data, {sm.get('day')})." if fii else None)}

    def build_forecast(now, qi: dict, opens: bool) -> None:
        """Today's view of Nifty and Bank Nifty with the reasons; rebuilt at the open once the gap is known."""
        nonlocal fc
        today_ = now.date()
        names = FC_NAMES
        for nm, k in names.items():
            if (nm, today_.isoformat()) not in hist_cache:
                hist_cache[(nm, today_.isoformat())] = FC.daily(token, k, today_)
        chains_ = {}
        for u, nm in VIEW_NAME.items():
            exps_ = [e for e in U.expiries(token, UNDER[u]) if e >= today_.isoformat()]
            chains_[nm] = {**SM.chain_stats(get_chain(u, exps_[0], 60)), "expiry": exps_[0]} if exps_ else {}
        vx = qi.get(IDX["vix"]) or {}
        vix_chg = (vx["net_change"] / (vx["last_price"] - vx["net_change"]) * 100) if vx.get("net_change") is not None and vx.get("last_price") else None
        fii = next((p for p in (sm.get("participants") or []) if p["who"] == "FII"), None)
        op = {nm: ((qi.get(k) or {}).get("ohlc") or {}).get("open") for nm, k in names.items()} if opens else {}
        views = FC.build(token, today_, {nm: hist_cache[(nm, today_.isoformat())] for nm in names}, names, plan.get("tone") or {}, vx.get("last_price"), vix_chg, chains_, fii, op,
                         [h["headline"] for h in (plan.get("headlines") or []) if h.get("headline")])
        pre = fc.get("pre") if fc.get("day") == today_.isoformat() else None
        if opens and fc.get("day") == today_.isoformat() and fc.get("stage") == 1:
            pre = {nm: {k: v[k] for k in ("bias", "score", "lo", "hi", "centre")} for nm, v in (fc.get("views") or {}).items()}
        fc = {"day": today_.isoformat(), "built_at": now.strftime("%H:%M"), "stage": 2 if opens else 1, "views": views, "pre": pre, "scored": False,
              "record": {nm: FC.hit_rate(fc_hist, nm) for nm in names}, "world_as_of": (plan.get("tone") or {}).get("as_of")}
        save("forecast.json", fc)
    if token:
        try:
            key_of = {x["trading_symbol"]: x["instrument_key"] for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"}
        except Exception:
            pass
    via_ref = {"rows": load("viability.json", {}).get("reference", []), "day": load("viability.json", {}).get("ref_day", "")}
    world_at[0] = load("world_live.json", {"at": 0}).get("at", 0)

    def refresh_world(at) -> None:
        live = load("world_live.json", {"at": 0, "rows": []})
        every = 1800 if "05:30" <= at.strftime("%H:%M") <= "09:30" else 4 * 3600
        if at.weekday() >= 5 and live.get("rows") or time.time() - live.get("at", 0) < every:
            return
        import importlib.util as iu
        spec = iu.spec_from_file_location("make_world", ROOT / "dashboard" / "make_world.py")
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows = mod.markets()
        if sum(r.get("last") is not None for r in rows) >= 8:      # a half-empty download must never replace a good one
            save("world_live.json", {"at": time.time(), "rows": rows})
            world_at[0] = time.time()

    def refresh_smart(at) -> None:
        nonlocal sm, parts
        parts = SM.history(at.date(), parts)
        save("participants.json", parts)
        dg, ch = SM.digest(parts), {}
        for u in UNDER:
            exps_ = [e for e in U.expiries(token, UNDER[u]) if e >= at.strftime("%Y-%m-%d")]
            if exps_:
                rows = get_chain(u, exps_[0], 120)
                ch[u] = {**SM.chain_stats(rows), "expiry": exps_[0], "spot": rows[0].get("underlying_spot_price") if rows else None}
        sm = {"updated_at": at.isoformat(timespec="seconds"), **dg, "chains": ch, "explain": SM.EXPLAIN, "who": SM.WHO, "summary": SM.overall(dg, ch)}
        save("smart_money.json", sm)

    REF = [("CRUDEOIL", "Crude oil (100 barrels)"), ("CRUDEOILM", "Crude oil mini (10 barrels)"), ("NATURALGAS", "Natural gas (1,250 mmBtu)"), ("NATGASMINI", "Natural gas mini (250 mmBtu)"),
           ("GOLD", "Gold (1 kg)"), ("GOLDM", "Gold mini (100 g)"), ("GOLDPETAL", "Gold petal (1 g)"), ("SILVER", "Silver (30 kg)"), ("SILVERM", "Silver mini (5 kg)"), ("SILVERMIC", "Silver micro (1 kg)")]

    def margin_reference(at) -> None:
        """Once a day: the broker's margin for one lot of each MCX contract, against what this account's commodities limit and cash can carry."""
        if not M or via_ref["day"] == at.strftime("%Y-%m-%d"):
            return
        ins, rows = U.instruments("MCX"), []
        for pre, name in REF:
            c = sorted((x for x in ins if x.get("instrument_type") == "FUT" and x["trading_symbol"].startswith(pre + " FUT")
                        and (datetime.fromtimestamp(x["expiry"] / 1000, IST).date() - at.date()).days >= D.ROLL_DAYS), key=lambda x: x["expiry"])
            if not c:
                continue
            m = M.final([(c[0]["instrument_key"], 1, "SELL")])
            if m:
                rows.append({"name": name, "contract": c[0]["trading_symbol"], "margin": m})
        if rows:
            via_ref.update(rows=rows, day=at.strftime("%Y-%m-%d"))

    def ceo_close(tid: str, at) -> str:
        """The CEO's manual override: close one open trade now at its latest marked price (after charges)."""
        tid = str(tid).strip().split()[0] if str(tid).strip() else ""
        t = next((x for x in xb["trades"] + eq["trades"] if str(x.get("id", "")).lower() == tid.lower()), None)
        if not t:
            return f"I could not find a trade called {tid or '(none given)'} on the desks I run (intraday, scalping, F&O, commodities, crypto)."
        if t["status"] != "OPEN":
            return f"{t['label']} is already closed ({t['status']}: {t.get('why', '')})."
        why, today_ = "closed by the CEO from the dashboard", at.strftime("%Y-%m-%d")
        with clock:
            if any(x is t for x in eq["trades"]):
                I.close_trade(t, float(t.get("last") or t["entry"]), why)
                t["closed"] = at.strftime("%H:%M:%S")
            else:
                D.finish(t, float(t["last"] if t.get("last") is not None else t["entry"]), why, at, float(t.get("pnl_rs") or 0))
            cst.setdefault("ceo_blocks", {})[t["strategy"]] = today_          # no instant re-entry of the same strategy today
            paused.add(t["strategy"])
            pnl_ = float(t.get("pnl_rs") or 0)
            text = (f"Done. {t['label']} is closed at the latest marked price: {'+' if pnl_ > 0 else '−' if pnl_ < 0 else ''}Rs {abs(pnl_):,.0f} after charges"
                    + (f", and its Rs {float(t['margin_rs']):,.0f} of margin is free again" if t.get("margin_rs") else "") + f". The desk will not open another {str(t['strategy']).replace('_', ' ')} today.")
            CO.say(cst, at, f"{CO.COO['name']} (COO)", text, "decision")
        return text

    def ceo_commands(at) -> None:
        """Instructions saved on the branch (docs/ceo/commands.json) by the CEO's own Claude sessions: same commands as the inbox."""
        br = os.environ.get("GITHUB_REF_NAME") or _git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
        if not br or _git("fetch", "-q", "--depth=1", "origin", br, check=False).returncode != 0:
            return
        r = _git("show", "FETCH_HEAD:docs/ceo/commands.json", check=False)
        try:
            cmds = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
        except ValueError:
            cmds = []
        done = cst.setdefault("done_cmds", [])
        for c in cmds:
            if not isinstance(c, dict) or not c.get("id") or c["id"] in done:
                continue
            done.append(c["id"])
            cst["done_cmds"] = done[-200:]
            if c.get("kind") == "close":
                ceo_close(c.get("arg", ""), at)
            else:
                with clock:
                    CO.apply(cst, {"kind": c.get("kind", "note"), "arg": c.get("arg", ""), "text": c.get("text", "")}, at)

    def ceo_inbox(at) -> None:
        """Instructions from the CEO (GitHub issues titled CEO ..., owner only): apply them and answer."""
        gt, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
        if not (gt and repo):
            return
        for cmd in CI.poll(gt, repo):
            if not cmd["owner"]:
                CI.reply(gt, repo, cmd["issue"], "Only the CEO (the owner of this repository) can give the company instructions.")
                continue
            if cmd["kind"] == "close":
                text = ceo_close(cmd["arg"], at)
            else:
                with clock:
                    text = CO.apply(cst, cmd, at)
            CI.reply(gt, repo, cmd["issue"], text)

    def ai_ask(kind, system, prompt, tier="read", max_tokens=None):
        with ai_lock:
            out = ai.ask(kind, system, prompt, tier, max_tokens)
            save("llm_usage.json", llm_u)
        return out

    def news_ai(at) -> None:
        """Every half hour: Claude Haiku reads the latest Indian and international headlines for the CEO and the desks."""
        gap = 9000 if ai.mode == "plan" else 1800                       # on the Claude plan: about every 2.5 hours, market days only
        if not ai.on or (digest[0].get("at") and time.time() - digest[0]["at"] < gap) or (at.weekday() >= 5 and (ai.mode == "plan" or digest[0].get("day") == at.strftime("%Y-%m-%d"))) \
                or (ai.mode == "plan" and not ("09:00" <= at.strftime("%H:%M") <= "15:30")):
            return
        wire = load("news_wire.json", [])
        heads = list(reversed(wire))[:60]
        with ai_lock:
            d = LLM.news_digest(ai, heads)
            save("llm_usage.json", llm_u)
        if d:
            digest[0] = {**d, "at": time.time(), "day": at.strftime("%Y-%m-%d"), "time": at.strftime("%d %b %H:%M"), "n": len(heads), "model": LLM.MODELS["read"]}
            save("news_digest.json", digest[0])

    def ipo_desk(at) -> None:
        """Every half hour: the IPO desk reads NSE's issues, SEBI's draft prospectuses and the news."""
        if ipo_v[0].get("at") and time.time() - ipo_v[0]["at"] < 1800:
            return
        out = IPO.build(at, ipo_st, llm=None)
        notes = ipo_st.setdefault("notes", {})
        day = at.strftime("%Y-%m-%d")
        if notes.get("day") != day:
            notes.clear()
            notes.update(day=day, n={}, tried=False)
        want = [x for x in out.get("ipos") or [] if x.get("status") in ("open", "upcoming") and x.get("name") not in notes["n"]][:6]
        if want and ai.on and not notes["tried"] and at.weekday() < 5 and at.strftime("%H:%M") >= "10:00":
            notes["tried"] = True                                       # one call a day writes the notes for every open or upcoming issue
            facts = [{k: x.get(k) for k in ("name", "board", "status", "open_date", "close_date", "price_band", "lot_size", "min_invest_rs", "issue_size_cr", "fresh_cr", "ofs_cr", "subscription")}
                     | {"verdict": (x.get("analysis") or {}).get("verdict"), "reasons": (x.get("analysis") or {}).get("reasons"), "risks": (x.get("analysis") or {}).get("risks"),
                        "headlines": [n_.get("title") for n_ in x.get("news") or []][:3]} for x in want]
            res = LLM.parse_json(ai_ask("ipo", IPO_SYSTEM, json.dumps(facts, default=str), "write"))
            if isinstance(res, dict):
                notes["n"].update({k: str(v)[:900] for k, v in (res.get("notes") or res).items() if isinstance(v, str)})
        notes["n"].update({k: v for k, v in ((ai_files[0].get("ipo_notes") or {}).get("notes") or {}).items() if k not in notes["n"]})
        for x in out.get("ipos") or []:
            if x.get("name") in notes["n"]:
                x["thesis"] = notes["n"][x["name"]]
                (x.get("analysis") or {})["method"] = "rules+claude"
        ipo_v[0] = {**out, "at": time.time()}
        save("ipo.json", ipo_v[0])
        save("ipo_state.json", ipo_st)

    ai_files = [{}]                                                  # the scheduled Claude analyst's latest round (docs/ai on the branch)

    def ai_sync(at) -> None:
        """Pick up what the scheduled Claude analyst (running in the CEO's own Claude account) saved on the branch: brief, IPO notes, review."""
        br = os.environ.get("GITHUB_REF_NAME") or _git("rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
        if not br or _git("fetch", "-q", "--depth=1", "origin", br, check=False).returncode != 0:
            return
        got = {}
        for f in ("brief", "ipo_notes", "review", "signal_checks"):
            r = _git("show", f"FETCH_HEAD:docs/ai/{f}.json", check=False)
            if r.returncode == 0 and r.stdout.strip():
                try:
                    got[f] = json.loads(r.stdout)
                except ValueError:
                    pass
        ai_files[0] = got
        b = got.get("brief") or {}
        if b.get("brief") and b.get("at", 0) > digest[0].get("at", 0):
            digest[0] = b
            save("news_digest.json", b)
        rv = got.get("review") or {}
        if rv.get("text") and rv.get("day") != review[0].get("day"):
            review[0] = {"day": rv["day"], "time": rv.get("time"), "text": rv["text"], "model": rv.get("model")}
            save("day_review.json", review[0])
        notes = (got.get("ipo_notes") or {})
        if notes.get("notes") and ipo_v[0].get("ipos"):
            for x in ipo_v[0]["ipos"]:
                if x.get("name") in notes["notes"] and not x.get("thesis"):
                    x["thesis"] = notes["notes"][x["name"]]
                    (x.get("analysis") or {})["method"] = "rules+claude"
            save("ipo.json", ipo_v[0])

    def ai_state() -> dict:
        b = (ai_files[0].get("brief") or {})
        if ai.on:
            return ai.status()
        if b.get("at"):
            return {"on": True, "mode": "scheduled", "last": b.get("time"), "next": "every hour from 09:20 to 16:20 IST on weekdays", "models": {"analyst": "Claude (your plan, scheduled)"}}
        return ai.status()

    IPO_SYSTEM = ("You are the IPO analyst of an Indian paper-trading desk. For each issue given, write a plain-English note of at most 110 words from the facts given only: "
                  "what the company raises money for if stated, what the demand so far says, the main risk, and whether one minimum lot is worth a small bet. Never invent numbers or promise returns. "
                  "Reply with one JSON object: {\"notes\": {\"<exact issue name>\": \"note\"}}.")

    def review_day(at) -> None:
        """After the close: Claude Opus writes the COO's review of the day from the real numbers."""
        today = at.strftime("%Y-%m-%d")
        if not ai.on or at.weekday() >= 5 or at.strftime("%H:%M") < "15:50" or review[0].get("day") == today:
            return
        allt = nonlocal_state.get("tick") or []
        td = [t for t in allt if t["day"] == today]
        teams_ = {}
        for t in td:
            k = CO.team_of(t) or "other"
            r = teams_.setdefault(k, {"trades": 0, "pnl_rs": 0.0, "wins": 0})
            r["trades"] += 1
            r["pnl_rs"] = round(r["pnl_rs"] + float(t.get("pnl_rs") or 0), 2)
            r["wins"] += t["status"] == "WIN"
        facts = {"day": today, "nifty_chg_pct": ((snap.get("indices") or {}).get("Nifty 50") or {}).get("chg_pct"), "teams": teams_,
                 "trades": [{k: t.get(k) for k in ("label", "strategy", "status", "pnl_rs", "why")} for t in td[:60]],
                 "lab": [{k: r.get(k) for k in ("strategy", "stage", "closed", "net_rs", "win_rate")} | {"failed": [c["name"] for c in r.get("checks", []) if c.get("ok") is False]} for r in (lab_v[0].get("strategies") or [])[:25]],
                 "forecast": (fc or {}).get("result"), "coo_notes": [n_["text"] for n_ in (load("company.json", {}).get("coo") or {}).get("notes", [])][:8]}
        with ai_lock:
            text = LLM.day_review(ai, facts)
            save("llm_usage.json", llm_u)
        if text:
            review[0] = {"day": today, "time": at.strftime("%d %b %H:%M"), "text": text, "model": LLM.MODELS["review"]}
            save("day_review.json", review[0])
            with clock:
                CO.say(cst, at, f"{CO.COO['name']} (COO)", "Today's review is written: see the Strategy lab page.", "review")

    def ai_checks(today: str) -> dict:
        c = ai_files[0].get("signal_checks") or {}
        return c.get("checks") or {} if c.get("day") == today else {}

    def pulse_scan(now) -> None:
        """Every headline and NSE filing, scored for emotion and matched to one company; handed to the intraday hunters."""
        try:
            today = now.strftime("%Y-%m-%d")
            if not names_idx and U._cache.get("NSE"):
                names_idx.update(I.name_index(U.instruments("NSE")))
            fil = []
            try:
                sys.path.insert(0, str(ROOT))
                from trading_team.spike_watch import fetch_feed, trigger_of
                for a in fetch_feed():
                    lab = trigger_of({"desc": a["desc"], "text": a["text"]})
                    tn = "negative" if lab in I.NEG else "positive" if lab in I.POS else None
                    if tn:
                        fil.append({"symbol": a["symbol"], "desc": a["desc"][:140], "ts": a["time"].timestamp(), "tone": tn, "link": a.get("file", "")})
            except Exception:
                pass
            new = NP.scan(pulse, names_idx, now, filings=fil)                # network reads: never inside the clock lock
            tr_ = {t["symbol"] for t in list(eq.get("trades") or []) if t.get("setup") == "news"}
            NP.track(pulse, dict(px_now), tr_, dict((eq.get("diag") or {}).get("skipped") or {}), ai_checks(today))
            sig = list(reversed(pulse["signals"]))
            hour = [x for x in sig if now.timestamp() - x["ts"] <= 3600]
            lags = sorted(x["lag_s"] for x in sig[:40] if x.get("lag_s") is not None and x["lag_s"] >= 0)
            save("news_pulse.json", {"updated_at": now.isoformat(timespec="seconds"), "scans": pulse["scans"], "feeds": pulse["feeds"], "signals": sig[:80],
                                     "stats": {"last_hour": len(hour), "positive": sum(x["tone"] == "positive" for x in hour), "negative": sum(x["tone"] == "negative" for x in hour),
                                               "today": len(sig), "median_lag_min": round(lags[len(lags) // 2] / 60, 1) if lags else None, "new_this_scan": len(new)}})
            save("news_pulse_state.json", {**pulse, "seen": dict(list(pulse["seen"].items())[-4000:])})
            status["desks"]["news_pulse"] = f"{len(new)} new signal(s); {len(hour)} in the last hour from {sum(1 for f_ in pulse['feeds'].values() if f_.get('ok'))} feeds"
        except Exception as e:
            status["desks"]["news_pulse"] = f"error: {str(e)[:100]}"

    def build_charts(now) -> None:
        """candles.json: one live chart per desk with the strategies' lines, the trade's marks and the order book."""
        try:
            today, allt, out = now.strftime("%Y-%m-%d"), nonlocal_state.get("tick") or [], []
            if token:
                if not fut_key[0]:
                    futs = [x for x in U.instruments("NSE") if x.get("segment") == "NSE_FO" and x.get("instrument_type") == "FUT" and x.get("name") == "NIFTY" and x.get("expiry", 0) / 1000 > time.time()]
                    fut_key[0] = min(futs, key=lambda x: x["expiry"])["instrument_key"] if futs else None
                t = CF.focus(allt, "FNO", today, lambda x: x.get("horizon", "daily") == "daily") or CF.focus(allt, "FNO", today)
                c = CF.upstox_candles(U._get, token, IDX["nifty"], now)
                q = U.quotes([fut_key[0]], token) if fut_key[0] else {}
                mk, chosen, lv = CF.fno_marks(t, c, now)
                out.append(CF.chart("fno", "F&O", "NIFTY", "NIFTY 50" + (f" · {t['label']}" if t else ""), "1m", c, CF.depth_upstox(q.get(fut_key[0])),
                                    [x for x in CF.strategies(c, None) if x["id"] in ("vwap", "or_high", "or_low")] + chosen, mk, lv))
                t = CF.focus(allt, "COMMODITY", today)
                cc = next((x for x in mcx_c if t and x["key"] == t.get("key")), None) or next((x for x in mcx_c if "rude" in x["label"]), mcx_c[0] if mcx_c else None)
                if cc:
                    c = CF.upstox_candles(U._get, token, cc["key"], now)
                    q = U.quotes([cc["key"]], token)
                    out.append(CF.chart("comm", "Commodities", cc["symbol"], cc["label"] + (f" · {t['label']}" if t else ""), "1m", c, CF.depth_upstox(q.get(cc["key"])), CF.strategies(c, t), CF.trade_marks(t, c, now, None), []))
                t = CF.focus(allt, "EQUITY", today, lambda x: x.get("opened") not in ("swing", "signal") and (x.get("setup") or str(x.get("strategy")).startswith("scalp")))
                found = (eq.get("diag") or {}).get("found") or {}
                sym = t["symbol"] if t else next((v[0] for k_ in ("news", "gap", "momentum", "vwap") for v in [found.get(k_) or []] if v), "RELIANCE")
                kmap = key_of or {x["trading_symbol"]: x["instrument_key"] for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"}
                if kmap.get(sym):
                    c = CF.from_hhmm(scalp_bars[sym], today) if len(scalp_bars.get(sym) or []) > 30 and t and t.get("day") == today else CF.upstox_candles(U._get, token, kmap[sym], now)
                    q = U.quotes([kmap[sym]], token)
                    out.append(CF.chart("eq", "Equities", sym, (t["label"] if t else f"{sym} · top candidate now"), "1m", c, CF.depth_upstox(q.get(kmap[sym])), CF.strategies(c, t), CF.trade_marks(t, c, now), []))
            t = CF.focus(allt, "CRYPTO", today)
            coin = t["symbol"] if t and t.get("symbol") in D.PAIRS else "BTC"
            j = D._get_json(f"https://api.kraken.com/0/public/OHLC?pair={D.PAIRS[coin]}USD&interval=5")
            rows = next(v for k_, v in j["result"].items() if k_ != "last")[-150:]
            c = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6])] for r in rows]
            dj = next(iter(D._get_json(f"https://api.kraken.com/0/public/Depth?pair={D.PAIRS[coin]}USD&count=5")["result"].values()))
            dep = {"bids": [[float(b[0]), float(b[1])] for b in dj["bids"]], "asks": [[float(a[0]), float(a[1])] for a in dj["asks"]]}
            dep.update(buy_qty=sum(b[1] for b in dep["bids"]), sell_qty=sum(a[1] for a in dep["asks"]))
            out.append(CF.chart("crypto", "Crypto", coin, f"{coin} / USD (Kraken)" + (f" · {t['label']}" if t else ""), "5m", c, dep, CF.strategies(c, t), CF.trade_marks(t, c, now, None), []))
            save("candles.json", {"updated_at": now.isoformat(timespec="seconds"), "charts": out})
            status["desks"]["charts"] = f"{len(out)} live charts"
        except Exception as e:
            status["desks"]["charts"] = f"error: {str(e)[:100]}"

    def sources_status(now) -> dict:
        """Where the company's data comes from, and whether each pipe is flowing right now."""
        d, ok = status["desks"], lambda good, detail, bad=False: {"status": "error" if bad else "ok" if good else "idle", "detail": detail}
        feed = load("news_feed.json", [])
        b = gw.st.get("broker") or {}
        age = (time.time() - world_at[0]) / 60 if world_at[0] else None
        return {"upstox": ok("real time" in str(d.get("equity", "")) or "real time" in str(d.get("commodities", "")), str(d.get("equity") or d.get("commodities") or "market closed: quotes resume at 09:00")[:70], "error" in str(d.get("equity", ""))),
                "nse": ok(bool(sm.get("day")) or bool(news), f"{len(news)} filings lean one way today; participant positions for {sm.get('day', '—')}"),
                "indmoney": {"status": "ok" if b.get("ok") else "off", "detail": f"connected: intraday funds Rs {b.get('funds') or 0:,.0f}" if b.get("ok") else "not connected here: the gateway reads it only where INDSTOCKS_TOKEN is set"},
                "kraken": ok("Kraken" in str(d.get("crypto", "")), str(d.get("crypto", ""))[:70], "error" in str(d.get("crypto", ""))),
                "yahoo": ok(age is not None and age < 6 * 60, f"world markets refreshed {age:.0f} min ago" if age is not None else "world markets not refreshed yet"),
                "news": ok(bool(feed) or bool(pulse.get("signals")), f"news pulse: {sum(1 for f_ in pulse['feeds'].values() if f_.get('ok'))} feeds read every minute in market hours, {len(pulse.get('signals') or [])} signals today; {len(headlines)} with the hunters now"),
                "claude": (({"status": "warn" if ai.status().get("resting_until") else "ok", "detail": f"your Claude plan: {ai.status()['calls_5h']} of {ai.status()['cap_calls_5h']} calls in the last 5 hours, {ai.status()['calls_day']} of {ai.status()['cap_calls_day']} today"
                             + ("; resting after the plan's limit" if ai.status().get("resting_until") else "")} if ai.mode == "plan" else
                            {"status": "ok", "detail": f"API: ${ai.status()['usd_5h']:.3f} of ${ai.status()['cap_5h']:.2f} in 5 hours"}) if ai.on else
                           {"status": "ok", "detail": f"scheduled Claude analyst (your plan): last round {ai_state().get('last')}, next on the hour's :20 from 09:20 to 16:20 IST on weekdays"} if ai_state().get("mode") == "scheduled" else
                           {"status": "off", "detail": "not connected yet: the desks run on their written rules"}),
                "github": {"status": "ok" if os.environ.get("GITHUB_TOKEN") else "off", "detail": "listening for your instructions every 5 minutes" if os.environ.get("GITHUB_TOKEN") else "not available on this machine"}}

    def company_view(now, allt, stats) -> None:
        """The god's-eye view of the company: every team's three agents and what they are doing, the COO's notes and requests, the bonus board."""
        qn, rec_ = {}, {}
        for t in allt:
            if t["status"] == "OPEN" or t["day"] == now.strftime("%Y-%m-%d"):
                if t["desk"] in ("EQUITY", "COMMODITY", "CRYPTO") and t.get("stop") and t.get("entry"):
                    tm = CO.team_of(t)
                    if tm not in rec_:
                        rec_[tm] = QN.team_numbers([x for x in allt if CO.team_of(x) == tm])
                    hit = rec_[tm].get("hit_rate") if rec_[tm].get("n", 0) >= 20 else None
                    q_ = float(t.get("qty") or 0) if t["desk"] != "CRYPTO" else 1.0
                    mult = float(t.get("mult") or 1)
                    cost = GW.round_trip_cost(float(t["entry"]), float(t.get("target_px") or t["entry"]), int(q_ * mult), "BUY") if t["desk"] == "EQUITY" else 0.0
                    sig = QN.sigma_bars([b[4] for b in scalp_bars.get(t.get("symbol"), [])[-60:]], SC.R["hold_min"]) if str(t["strategy"]).startswith("scalp") else None
                    qn[t["id"]] = QN.trade_numbers(float(t["entry"]), float(t["stop"]), float(t.get("target_px") or 0) or None, q_ * mult if t["desk"] != "CRYPTO" else float(t["qty"]) / float(t["entry"]), cost, sig, hit)
        nf = ((snap.get("indices") or {}).get("Nifty 50") or {}).get("chg_pct")
        lab = LB.build(allt, stats, cst, CO.team_of, gw.st)
        lab["review"], lab["ai"] = review[0], ai_state()
        lab_v[0] = lab
        save("lab.json", lab)
        with clock:
            view = CO.build(cst, now, allt, stats, {"plan": plan, "fc": fc, "sm": sm, "gw": gw.st, "via": load("viability.json", {}), "desks": status["desks"], "world": make_env()["world"],
                                                   "nifty_chg": nf, "equity": acct[0], "scalp_n": len(scalp_bars), "scalp_params": {**SC.R, **((cst["variants"].get("scalp") or {}).get("params") or {})},
                                                   "sessions": status.get("sessions"), "quant_notes": qn, "headlines": headlines, "intraday_diag": eq.get("diag"), "mcx": snap.get("mcx"),
                                                   "crypto": snap.get("crypto"), "fno_snap": snap.get("fno"), "news_n": len(load("news_feed.json", [])), "sources": sources_status(now),
                                                   "lab": lab, "ipo": ipo_v[0], "news_digest": digest[0], "pulse": pulse.get("signals") or []})
            for r in view["coo"]["requests"]:
                if r["status"] == "pending" and r["id"] not in cst["said"].get("pushed", []):
                    cst["said"]["pushed"] = (cst["said"].get("pushed", []) + [r["id"]])[-50:]
                    N.push("COO needs your decision", r["text"] + " Open the Company page to approve or reject.", 4, "briefcase")
            save("company.json", {**view, "quant": qn, "state": cst})

    def load_master() -> None:
        if ind and not len(master):
            txt = ind.instruments("equity")
            if txt:
                master.by.update(IND.Master(txt).by)

    def compose():
        live_open = [t for t in unify_equity(eq) + xb["trades"] if t["status"] == "OPEN"]
        books = L.swing(load("paper_ledger.json", [])) + L.weekly_fno(load("fo_ledger.json", [])) + L.signals(load("signal_ledger.json", []))
        allt = list(archive.values()) + live_open + books
        allt.sort(key=lambda t: (t["day"], t["opened"]), reverse=True)
        env_ = make_env()
        for i_, t in enumerate(allt):
            if not t.get("thesis") and t["desk"] == "EQUITY" and (t["status"] == "OPEN" or t["day"] == datetime.now(IST).strftime("%Y-%m-%d") or t.get("opened") in ("swing", "signal")):
                allt[i_] = {**t, "thesis": TH.for_trade(t, env_, acct[0])}
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
        th_ = {t["id"]: t["thesis"] for t in allt[:600] if t.get("thesis")}
        save("theses.json", th_)
        save("all_trades.json", [{k: v for k, v in t.items() if k != "thesis"} | ({"has_thesis": True} if t.get("thesis") else {}) for t in allt[:4000]])
        stats = D.learn(list(archive.values()) + [t for t in books if t["status"] in ("WIN", "LOSS")])
        save("strategy_stats.json", stats)
        try:                                           # the gateway to the broker: dry-run unless EXEC_MODE=live and every live condition holds
            ok_ = set(lab_v[0].get("approved") or [])           # only strategies the lab approved may reach the broker
            stage_ = {r["strategy"]: r["stage"] for r in lab_v[0].get("strategies") or []}
            gws = gw.process(allt, [s_ if s_["strategy"] in ok_ else {**s_, "verdict": f"LAB {stage_.get(s_['strategy'], 'BUILT')}"} for s_ in stats], datetime.now(IST), {k: v[0] for k, v in qs.items()})
            status["desks"]["gateway"] = f"{gws.get('mode')} · {sum(1 for x in gws['intents'].values() if x['status'] != 'REJECTED')} intents, {sum(1 for x in gws['intents'].values() if x['status'] == 'REJECTED')} refused"
        except Exception as e:
            status["desks"]["gateway"] = f"error: {str(e)[:100]}"
        status["open"] = sum(t["status"] == "OPEN" for t in allt)
        save("live_status.json", status)
        nf = (snap.get("indices") or {}).get("Nifty 50", {}).get("last")
        series.update(L.day_series(series, datetime.now(IST).strftime("%Y-%m-%d"), datetime.now(IST).strftime("%H:%M:%S"), allt, nf))
        save("pnl_series.json", series)
        save("prices.json", {"updated_at": status.get("updated_at"), **snap})
        if qs:
            save("quotes.json", {"updated_at": status.get("updated_at"), "q": qs})
        nonlocal_state["tick"] = allt
        with clock:                                    # the strategies that may open trades now: the record's pauses, the CEO's decisions
            fresh = CO.paused_strategies(cst, {s["strategy"] for s in stats if s["verdict"] == "PAUSED"}, {})
            fresh |= {k_ for k_, d_ in (cst.get("ceo_blocks") or {}).items() if d_ == datetime.now(IST).strftime("%Y-%m-%d")}
            paused.clear()
            paused.update(fresh)
        summ = A.summary(allt)
        acct[0] = summ["equity"]
        save("account.json", {"updated_at": status.get("updated_at"), **summ})
        try:
            company_view(datetime.now(IST), allt, stats)
        except Exception as e:
            import traceback
            traceback.print_exc()
            status["desks"]["company"] = f"error: {str(e)[:100]}"
        if M:
            today_s = datetime.now(IST).strftime("%Y-%m-%d")
            save("viability.json", {"updated_at": status.get("updated_at"), "skipped": sorted((v for v in M.log.values() if v["day"] == today_s), key=lambda v: v["at"], reverse=True)[:30],
                                    "reference": via_ref["rows"], "ref_day": via_ref["day"],
                                    "limits": {k: v["budget"] for k, v in summ["buckets"].items()}})

    nonlocal_state: dict = {}
    last_pub = 0.0
    while True:
        now = datetime.now(IST)
        today, hhmm, ses = now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), sessions(now)
        it0, T = time.time(), {}
        close_stale(eq, xb, today)
        rm = A.rooms(nonlocal_state.get("tick") or compose()[0])
        for tm_ in cst["paused_teams"]:                 # a team the CEO paused gets no money for new trades
            b_ = next((t["bucket"] for t in CO.TEAMS if t["id"] == tm_), None)
            if b_ in rm:
                rm[b_] = [0.0]
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
                    if time.time() - hl_at[0] >= 60:                     # headlines that name a listed company, refreshed each minute
                        hl_at[0] = time.time()
                        if not names_idx and U._cache.get("NSE"):
                            names_idx.update(I.name_index(U.instruments("NSE")))
                        headlines.clear()
                        headlines.update(I.headline_names(load("news_feed.json", []), names_idx, now) if names_idx else {})
                        doubted_ = {k_ for k_, v_ in ai_checks(today).items() if v_.get("verdict") == "doubt"}
                        for k_ in doubted_:
                            headlines.pop(k_, None)
                        headlines.update(NP.for_hunters(pulse, now, doubted_))
                    px_now.update({r_["symbol"]: r_["price"] for r_ in rows})
                    I.step(eq, today, hhmm, rows, news, rm["intraday"], cst["effort"].get("intraday", 1), headlines)
                info["equity"] = f"{len(rows)} stocks, real time"
            except Exception as e:
                info["equity"] = f"error: {e}"
        elif ses["equity"]:
            info["equity"] = "no token: Yahoo fallback runs in intraday.py"
        T["equity"] = round(time.time() - it0, 1)
        if token and ses["equity"] and rows_now:                         # the scalping desk: 1-minute bars for the most liquid names, fetched once a minute off the price loop
            try:
                if not (bars_thread[0] and bars_thread[0].is_alive()) and time.time() - bars_at[0] >= 60:
                    bars_at[0] = time.time()

                    def _bars(syms=SC.universe(rows_now, 25 + 10 * cst["effort"].get("scalp", 1)) + [t["symbol"] for t in xb["trades"] if t.get("strategy") == SC.STRATEGY and t["status"] == "OPEN"]):
                        for sy in dict.fromkeys(syms):
                            if sy in key_of:
                                try:
                                    scalp_bars[sy] = U.intraday(token, key_of[sy], 1)[:-1]       # drop the minute still forming
                                except Exception:
                                    pass
                    bars_thread[0] = threading.Thread(target=_bars, daemon=True)
                    bars_thread[0].start()
                rowd = {r["symbol"]: r for r in rows_now}
                var_ = cst["variants"].get("scalp") or {}
                SC.step(xb, now, {"effort": cst["effort"].get("scalp", 1), "rows": rowd, "bars": {k: v for k, v in scalp_bars.items() if k in rowd}, "room": rm["scalp"], "acct": acct[0], "paused": (var_.get("name") or SC.STRATEGY) in paused,
                                  "name": var_.get("name"), "params": var_.get("params"), "sigma": lambda s_: QN.sigma_bars([b[4] for b in scalp_bars.get(s_, [])[-60:]], SC.R["hold_min"]),
                                  "tick": lambda s_: (master.get(s_) or {}).get("tick", 0.05), "leverage": lambda s_: (master.get(s_) or {}).get("leverage", 5.0), "news": make_env()["news"]})
                info["scalp"] = f"{len(scalp_bars)} names scanned, bars refreshed {int(time.time() - bars_at[0])} s ago"
            except Exception as e:
                import traceback
                traceback.print_exc()
                info["scalp"] = f"error: {str(e)[:100]}"
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
        T["fill"] = round(time.time() - it0, 1)
        if token and ses["mcx"]:
            try:
                mcx_c = mcx_c or D.mcx_contracts(U.instruments("MCX"), now.date())
                D.mcx_step(xb, now, U.quotes([c["key"] for c in mcx_c], token), mcx_c, paused, rm["COMMODITY"], {"margin": M, "env": make_env(), "acct": acct[0]})
                info["commodities"] = f"{len(mcx_c)} MCX futures, real time"
            except Exception as e:
                info["commodities"] = f"error: {e}"
        T["mcx"] = round(time.time() - it0, 1)
        if token and ses["fno"]:
            try:
                n = q_idx.get(NIFTY, {})
                spot = n.get("last_price")
                exps = [e for e in U.expiries(token, NIFTY) if e >= today]
                open_exp = {t["expiry"] for t in xb["trades"] if t["desk"] == "FNO" and t["status"] == "OPEN" and t.get("underlying", "NIFTY") == "NIFTY" and t.get("horizon", "daily") == "daily"}
                rule_ = playbook.get("rule") or {}
                sx_ = exps[1] if rule_.get("expiry") == "next week" and len(exps) > 1 else exps[0]
                chains = {e: get_chain("NIFTY", e, 5) for e in sorted(open_exp | {exps[0], sx_}) if e >= today or e in open_exp}
                prev_n = (spot - n["net_change"]) if spot and n.get("net_change") is not None else None
                env = make_env()
                vixq = (q_idx.get(IDX["vix"]) or {}).get("last_price")
                ctx = {"spot": spot, "prev": prev_n, "chains": chains, "expiry": exps[0], "lot": U.lot_size(NIFTY, exps[0]), "room": rm["FNO"], "margin": M, "env": env, "vix": vixq,
                       "iv": D.atm_iv(chains.get(exps[0]) or [], spot), "acct": acct[0]}
                ctx["straddle"] = {"ok": False, "why": "no trained playbook yet"}
                if playbook and spot and vixq:
                    if sdl["day"] != today:                           # once a day: the closes since training, so today's features are current
                        try:
                            recent = SL.fetch(U._get, token, NIFTY, "days/1", now.date() - timedelta(days=20), now.date() - timedelta(days=1), 30)
                            recv = SL.fetch(U._get, token, IDX["vix"], "days/1", now.date() - timedelta(days=20), now.date() - timedelta(days=1), 30)
                            vmap = {r[0][:10]: r[4] for r in recv}
                            have = {r[0] for r in sdl["closes"]}
                            sdl["closes"] += [[r[0][:10], r[4], vmap[r[0][:10]]] for r in recent if r[0][:10] not in have and r[0][:10] in vmap and r[0][:10] < today]
                            sdl["closes"].sort()
                        except Exception:
                            pass
                        sdl["day"] = today
                    if sdl["closes"]:
                        open_ = (n.get("ohlc") or {}).get("open") or spot
                        mv_ = spot / sdl["closes"][-1][1] - 1
                        k_ = round(spot / 50) * 50
                        if rule_.get("strike_code") in ("with", "against") and abs(mv_) >= 0.003:
                            k_ += (-50 if mv_ > 0 else 50) * (1 if rule_["strike_code"] == "with" else -1)
                        f_ = SL.live_features(playbook, sdl["closes"], vixq, open_, (date.fromisoformat(sx_) - now.date()).days)
                        v_ = SL.today_view(playbook, f_)
                        sdl["view"] = {**v_, "strike": k_, "expiry": sx_, "entry": rule_.get("entry"), "target": rule_.get("target"), "stop": rule_.get("stop"), "rule": rule_,
                                       "train": {k: (playbook.get("train") or {}).get(k) for k in ("n", "avg_rs", "win_rate", "pf")},
                                       "test": {k: (playbook.get("test") or {}).get(k) for k in ("n", "avg_rs", "win_rate", "pf")}, "at": now.strftime("%H:%M")}
                        ctx["straddle"] = sdl["view"]
                        save("straddle.json", {"updated_at": now.isoformat(timespec="seconds"), "today": sdl["view"],
                                               "playbook": {k: v for k, v in playbook.items() if k not in ("table", "closes")}})
                # weekly and monthly structures claim margin first: they are held for days, the daily ones are flat by 15:15 and take what is left
                uq, fv_ = {}, ((fc.get("views") or {}) if fc.get("day") == today else {})
                for u_, k_ in UNDER.items():
                    qq_ = q_idx.get(k_) or {}
                    if qq_.get("last_price"):
                        uq[u_] = {"spot": qq_["last_price"], "prev": (qq_["last_price"] - qq_["net_change"]) if qq_.get("net_change") is not None else None, "exps": [e for e in U.expiries(token, k_) if e >= today]}
                try:
                    HZ.hold_step(xb, now, {"u": uq, "chain": lambda u_, e_: get_chain(u_, e_), "lot": lot_of, "margin": M, "room": rm["FNO"], "env": env, "acct": acct[0], "vix": vixq,
                                       "view": {u_: {"score": (fv_.get(VIEW_NAME[u_]) or {}).get("score", 0.0), "rv": (fv_.get(VIEW_NAME[u_]) or {}).get("rv")} for u_ in UNDER}}, paused)
                except Exception as e:                       # a fault in the held structures must never stop the daily desk
                    import traceback
                    traceback.print_exc()
                    info["fno_hold"] = f"error: {str(e)[:100]}"
                D.fno_step(xb, now, ctx, paused)
                rows_ = chains.get(exps[0]) or []
                if rows_ and spot:
                    atm = min((r["strike_price"] for r in rows_), key=lambda k: abs(k - spot))
                    st_ = D._buy(D._px(rows_, atm, "CE")) + D._buy(D._px(rows_, atm, "PE"))
                    snap["fno"] = {"spot": spot, "expiry": exps[0], "lot": ctx["lot"], "atm": atm, "straddle": round(st_, 1), "vix": vixq}
                info["fno"] = f"NIFTY {spot} , expiry {exps[0]}, {len(chains)} chain(s), real time"
            except Exception as e:
                import traceback
                traceback.print_exc()
                info["fno"] = f"error: {e}"
        T["fno"] = round(time.time() - it0, 1)
        try:
            ticks = D.kraken_ticks()
            D.crypto_step(xb, now, ticks, paused, rm["CRYPTO"], {"env": make_env(), "acct": acct[0]})
            snap["crypto"] = [{"name": k, "last": v["last"], "chg_pct": (v["last"] / v["open"] - 1) * 100, "high": v["high"], "low": v["low"], "unit": "$"} for k, v in ticks.items()]
            info["crypto"] = "6 coins from Kraken, real time"
        except Exception as e:
            info["crypto"] = f"error: {e}"
        T["crypto"] = round(time.time() - it0, 1)
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
        T["snapshots"] = round(time.time() - it0, 1)
        if token and now.weekday() < 5:
            try:
                if hhmm >= "08:45" and (plan.get("day") != today or (plan.get("world_at", 0) < world_at[0] and hhmm < "09:30")):                      # start of day: tone, news, the names to watch and their trigger levels
                    qi = q_idx or U.quotes(list(IDX.values()), token)
                    nf, vx = qi.get(NIFTY) or {}, qi.get(IDX["vix"]) or {}
                    results, events = load("results_filed.json", []), load("events_today.json", [])
                    syms = set(news) | {r.get("symbol") for r in results} | {e.get("symbol") for e in events if str(e.get("date", ""))[:10] == today}
                    keys = {sy: key_of[sy] for sy in syms if sy in key_of}
                    qq = U.quotes(list(keys.values()), token) if keys else {}
                    quotes = {sy: (qq[k]["last_price"], qq[k].get("net_change") or 0) for sy, k in keys.items() if k in qq and qq[k].get("last_price")}
                    prev_n = (nf.get("last_price") or 0) - (nf.get("net_change") or 0)
                    plan = SOD.build_plan(None, today, hhmm, world_rows(), events, results, load("news_feed.json", []), news, quotes, vx.get("last_price"),
                                          {"last": nf.get("last_price"), "chg_pct": round(nf["net_change"] / prev_n * 100, 2) if nf.get("net_change") is not None and prev_n else None})
                    plan["world_at"] = world_at[0]
                    save("intraday_plan.json", plan)
                    if told.get("plan") != today:
                        N.push("Day plan", f"Tone {plan['tone']['label']}. {len(plan['watch'])} names to watch. " + " ".join(plan["tone"]["notes"][:2]), 3, "sunrise")
                        told["plan"] = today
                if plan.get("day") == today and time.time() - fc_try[0] > 120 and (fc.get("day") != today or fc.get("plan_world_at") != plan.get("world_at") or any(n not in (fc.get("views") or {}) for n in FC_NAMES)):          # today's forecast for the indexes
                    fc_try[0] = time.time()
                    qi_ = q_idx or U.quotes(list(IDX.values()), token)
                    build_forecast(now, qi_, fc.get("day") == today and fc.get("stage") == 2)
                    fc["plan_world_at"] = plan.get("world_at")
                    save("forecast.json", fc)
                    info["forecast"] = f"built at {hhmm}"
                if fc.get("day") == today and fc.get("stage") == 1 and hhmm >= "09:16" and q_idx.get(NIFTY) and ((q_idx[NIFTY].get("ohlc") or {}).get("open")) and time.time() - fc_try[0] > 60:   # the open is known: add the gap
                    fc_try[0] = time.time()
                    build_forecast(now, q_idx, True)
                    fc["plan_world_at"] = plan.get("world_at")
                    save("forecast.json", fc)
                if fc.get("day") == today and not fc.get("scored") and hhmm >= "15:45" and q_idx.get(NIFTY):   # score the forecast against what the indexes did
                    rows_sc = []
                    for nm, k in FC_NAMES.items():
                        qv, vw = q_idx.get(k) or {}, (fc.get("views") or {}).get(nm)
                        if vw and qv.get("last_price"):
                            oh = qv.get("ohlc") or {}
                            rows_sc.append(FC.score_day({**vw, "day": today}, oh.get("open"), oh.get("high") or qv["last_price"], oh.get("low") or qv["last_price"], qv["last_price"]))
                    if rows_sc:
                        fc_hist[:] = FC.record(fc_hist, rows_sc, today)[-240:]
                        save("forecast_history.json", fc_hist)
                        fc["scored"], fc["result"] = True, rows_sc
                        fc["record"] = {nm: FC.hit_rate(fc_hist, nm) for nm in FC_NAMES}
                        save("forecast.json", fc)
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
        T["plan"] = round(time.time() - it0, 1)
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
            if not (news_thread and news_thread.is_alive()):        # the slow fetches (news, world markets, NSE files) can take a while from a cloud address: never hold up the price loop for them
                def _slow(at=now):
                    for name_, fn_ in (("news", lambda: (lambda n2: (news.clear(), news.update(n2)) if n2 else None)(I.filings_news())), ("news_feed", lambda: I.update_news_feed(at)), ("ai_sync", lambda: ai_sync(at)), ("news_ai", lambda: news_ai(at)), ("ipo", lambda: ipo_desk(at)), ("review", lambda: review_day(at)),
                                       ("world", lambda: refresh_world(at)), ("smart_money", lambda: token and refresh_smart(at)), ("margin_reference", lambda: margin_reference(at)), ("indstocks_master", lambda: load_master()), ("noop", lambda: None)):
                        try:
                            fn_()
                        except Exception as e:
                            info[name_] = f"error: {str(e)[:80]}"
                news_thread = threading.Thread(target=_slow, daemon=True)
                news_thread.start()
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
        hm_ = now.strftime("%H:%M")
        inbox_every = 60 if now.weekday() < 5 and "09:00" <= hm_ <= "15:35" else 300     # your instructions: checked every minute in market hours
        if time.time() - inbox_at[0] >= inbox_every and not (inbox_thread[0] and inbox_thread[0].is_alive()):
            inbox_at[0] = time.time()

            def _inbox(at=now):
                for fn_ in (ceo_inbox, ceo_commands):
                    try:
                        fn_(at)
                    except Exception as e:
                        status["desks"]["ceo_inbox"] = f"error: {str(e)[:80]}"
            inbox_thread[0] = threading.Thread(target=_inbox, daemon=True)
            inbox_thread[0].start()
        every_ = 60 if now.weekday() < 5 and "08:30" <= hm_ <= "15:35" else 600     # once a minute in market hours, every 10 minutes otherwise
        if time.time() - pulse_at[0] >= every_ and not (pulse_thread[0] and pulse_thread[0].is_alive()):
            pulse_at[0] = time.time()
            pulse_thread[0] = threading.Thread(target=pulse_scan, args=(now,), daemon=True)
            pulse_thread[0].start()
        if time.time() - charts_at[0] >= 60 and not (charts_thread[0] and charts_thread[0].is_alive()):
            charts_at[0] = time.time()
            charts_thread[0] = threading.Thread(target=build_charts, args=(now,), daemon=True)
            charts_thread[0].start()
        T["slow_and_intraday"] = round(time.time() - it0, 1)
        i += 1
        persist()
        T["persist"] = round(time.time() - it0, 1)
        if i == 1:
            status["first_iteration"] = T
            save("live_status.json", status)
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
