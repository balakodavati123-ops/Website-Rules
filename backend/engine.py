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
import margin as MG         # noqa: E402
import forecast as FC       # noqa: E402
import smart_money as SM    # noqa: E402
import horizons as HZ       # noqa: E402
import thesis as TH         # noqa: E402
import scalp as SC          # noqa: E402
import gateway as GW        # noqa: E402
import indstocks as IND     # noqa: E402

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
                    "why": t.get("why", ""), "day": t["day"], "opened": t["time"], "closed": t.get("closed", ""), "risk_class": "Intraday momentum", "margin_rs": round(t["entry"] * t["qty"] * 0.2)})
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
    paused = {s["strategy"] for s in load("strategy_stats.json", []) if s["verdict"] == "PAUSED"}
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
    bars_at, bars_thread = [0.0], [None]
    gw = GW.Gateway(DOCS / "gateway.json", ind, master)
    fc_try = [0.0]
    fc, fc_hist = load("forecast.json", {}), load("forecast_history.json", [])
    sm, parts = load("smart_money.json", {}), load("participants.json", {})
    hist_cache: dict = {}                                            # (index name, day) -> daily candles
    chain_cache: dict = {}                                           # (underlying, expiry) -> (time, rows)
    acct = [A.START]                                                 # account equity, for "per cent of the account" in the written thesis
    world_at = [0.0]                                                 # when world markets were last refreshed from the web

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
            gws = gw.process(allt, stats, datetime.now(IST), {k: v[0] for k, v in qs.items()})
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
        summ = A.summary(allt)
        acct[0] = summ["equity"]
        save("account.json", {"updated_at": status.get("updated_at"), **summ})
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
        T["equity"] = round(time.time() - it0, 1)
        if token and ses["equity"] and rows_now:                         # the scalping desk: 1-minute bars for the most liquid names, fetched once a minute off the price loop
            try:
                if not (bars_thread[0] and bars_thread[0].is_alive()) and time.time() - bars_at[0] >= 60:
                    bars_at[0] = time.time()

                    def _bars(syms=SC.universe(rows_now) + [t["symbol"] for t in xb["trades"] if t.get("strategy") == SC.STRATEGY and t["status"] == "OPEN"]):
                        for sy in dict.fromkeys(syms):
                            if sy in key_of:
                                try:
                                    scalp_bars[sy] = U.intraday(token, key_of[sy], 1)[:-1]       # drop the minute still forming
                                except Exception:
                                    pass
                    bars_thread[0] = threading.Thread(target=_bars, daemon=True)
                    bars_thread[0].start()
                rowd = {r["symbol"]: r for r in rows_now}
                SC.step(xb, now, {"rows": rowd, "bars": {k: v for k, v in scalp_bars.items() if k in rowd}, "room": rm["scalp"], "acct": acct[0], "paused": SC.STRATEGY in paused,
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
                chains = {e: get_chain("NIFTY", e, 5) for e in sorted(open_exp | {exps[0]}) if e >= today or e in open_exp}
                prev_n = (spot - n["net_change"]) if spot and n.get("net_change") is not None else None
                env = make_env()
                vixq = (q_idx.get(IDX["vix"]) or {}).get("last_price")
                ctx = {"spot": spot, "prev": prev_n, "chains": chains, "expiry": exps[0], "lot": U.lot_size(NIFTY, exps[0]), "room": rm["FNO"], "margin": M, "env": env, "vix": vixq,
                       "iv": D.atm_iv(chains.get(exps[0]) or [], spot), "acct": acct[0]}
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
                    for name_, fn_ in (("news", lambda: (lambda n2: (news.clear(), news.update(n2)) if n2 else None)(I.filings_news())), ("news_feed", lambda: I.update_news_feed(at)),
                                       ("world", lambda: refresh_world(at)), ("smart_money", lambda: token and refresh_smart(at)), ("margin_reference", lambda: margin_reference(at)), ("indstocks_master", lambda: load_master())):
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
