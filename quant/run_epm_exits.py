"""Does exiting at the EPM (expected premium move) help? Real NIFTY weekly option prices (Upstox expired-option 1-minute candles, cached),
every trading day from Oct 2024.

The trade: at 10:00 buy one lot of the at-the-money call, the at-the-money put, or the side the morning's move points to (NIFTY up 0.15%+
from the open: call; down 0.15%+: put; otherwise no trade). This is the desk's own 10:00 rule. Expiry: the nearest weekly with at least 3
sessions left.

Exit rules compared, all out by 15:15 at the latest:
  hold             no target, no stop
  desk rule        +50% target / -35% stop on the premium (the F&O desk's rule today)
  EPM 1 / 1        target at the premium NIFTY's expected rest-of-day move (1 standard deviation) gives; stop at the same move against
  EPM 0.5 / 1      target at half the expected move, stop at a full move against
  EPM 1 / 0.5      target at the full move, stop at half a move against
  EPM 1 / none     target at the full move, no stop
The EPM is worked out at 10:00 exactly as the dashboard does (backend/epm.py): the forward from put-call parity, ATM implied volatility from
the 10:00 call and put prices, the move for the 330 minutes left, each option repriced with Black-Scholes in trading time.

Fills: the option's 1-minute close; slippage 0.3% (at least Rs 0.10) against us on both fills; full charges. A level counts as reached
when a minute closes beyond it. Also measured: how well EPM predicts the real premium change for the move NIFTY actually made by 15:15.
Writes quant/results/epm_exits.json. Research only.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "quant"))
sys.path.insert(0, str(ROOT / "backend"))
from src.backtest.costs import charges                         # noqa: E402
from src.backtest.straddle_engine import Backtester, Config, _minute   # noqa: E402
from src.data.upstox_client import IST, UpstoxClient            # noqa: E402
from src.research import option_structures as OS               # noqa: E402
import epm as EPM                                              # noqa: E402

RULES = [("hold", None, None), ("desk rule +50% / -35%", "pct", (0.50, 0.35)), ("EPM 1 / 1", "epm", (1.0, 1.0)), ("EPM 0.5 / 1", "epm", (0.5, 1.0)),
         ("EPM 1 / 0.5", "epm", (1.0, 0.5)), ("EPM 1 / none", "epm", (1.0, None))]
SIDES = ("call every day", "put every day", "morning-move direction")


def stats(xs: list[dict]) -> dict:
    if not xs:
        return {"trades": 0}
    nets = [x["net"] for x in xs]
    w = [v for v in nets if v > 0]
    gp, gl = sum(w), -sum(v for v in nets if v <= 0)
    eq = pk = dd = 0.0
    for v in nets:
        eq += v
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    why = {k: sum(1 for x in xs if x["why"] == k) for k in ("target", "stop", "time")}
    return {"trades": len(xs), "win_rate": round(100 * len(w) / len(xs), 1), "profit_factor": round(gp / gl, 2) if gl else None, "net_rs": round(gp - gl),
            "avg_rs": round((gp - gl) / len(xs)), "max_drawdown_rs": round(dd), "exits": why, "best_rs": round(max(nets)), "worst_rs": round(min(nets))}


def main() -> None:
    t0 = time.time()
    c = UpstoxClient(min_interval=0.3)
    bt = Backtester(c, Config(start=date(2024, 10, 1), end=datetime.now(IST).date()), log=lambda *a: None)
    bt.load()
    P = OS.Pricer(bt)
    tr = sorted(bt.trading)
    days = [d for d in sorted(bt.n1) if d >= date(2024, 10, 1)]
    res = {r[0]: {s: [] for s in SIDES} for r in RULES}
    calib, skipped, touched = [], 0, {"call": 0, "put": 0, "n": 0}
    for d in days:
        e = P.expiry_for(d, 3)
        S = P.spot(d, "10:00")
        op = P.spot(d, "09:15")
        if not e or not S or not op:
            skipped += 1
            continue
        E = date.fromisoformat(e)
        T_min = 330 + EPM.DAY_MIN * sum(1 for x in tr if d < x <= E)
        K = int(round(S / 50) * 50)
        px = {k: P.px(e, K, k, d, "10:00") for k in ("CE", "PE")}
        meta = {k: P.series(e, K, k) for k in ("CE", "PE")}
        if not all(px.values()) or not all(meta.values()):
            skipped += 1
            continue
        lot = int(meta["CE"][0].get("lot_size") or 75)
        spot = S
        S = EPM.forward([{"k": K, "ce": px["CE"], "pe": px["PE"]}], S)          # price off the forward, as the dashboard does
        iv0 = EPM.atm_iv([{"k": K, "ce": px["CE"], "pe": px["PE"]}], S, T_min)
        if not iv0:
            skipped += 1
            continue
        move = EPM.expected_move(spot, iv0, 330)
        path = {k: [] for k in ("CE", "PE")}
        for mi in range(1, 316):                                       # 10:01 .. 15:15
            t = _minute("10:00", mi)
            for k in ("CE", "PE"):
                q = P.px(e, K, k, d, t, back=3)
                if q is not None:
                    path[k].append((t, q))
        if not path["CE"] or not path["PE"]:
            skipped += 1
            continue
        s_end = P.spot(d, "15:15")
        mm = (spot - op) / op * 100
        lean = "CE" if mm >= 0.15 else "PE" if mm <= -0.15 else None
        touched["n"] += 1
        hi = max(v[0] for kk, v in bt.n1[d].items() if "10:00" < kk <= "15:15")
        lo = min(v[0] for kk, v in bt.n1[d].items() if "10:00" < kk <= "15:15")
        touched["call"] += hi >= spot + move
        touched["put"] += lo <= spot - move
        for kind in ("CE", "PE"):
            iv = EPM.implied_vol(px[kind], S, K, EPM.years(T_min), kind) or iv0
            if s_end:                                                   # how well does EPM predict the real change for the move NIFTY made?
                m = s_end - spot
                pred = EPM.bs(S + m, K, EPM.years(T_min - 315), iv, kind) - EPM.bs(S, K, EPM.years(T_min), iv, kind)
                act = path[kind][-1][1] - px[kind]
                calib.append({"kind": kind, "pred": pred, "act": act, "prem": px[kind], "move_sd": m / move if move else 0})
            entry = px[kind] + OS._slip(px[kind])
            for name, typ, par in RULES:
                if typ == "pct":
                    tgt, stp = px[kind] * (1 + par[0]), px[kind] * (1 - par[1])
                elif typ == "epm":
                    a = EPM.epm(S, K, kind, px[kind], T_min, iv, move * par[0], 330)
                    b = EPM.epm(S, K, kind, px[kind], T_min, iv, move * par[1], 330) if par[1] else None
                    tgt, stp = a["target"], (b["stop"] if b else None)
                else:
                    tgt = stp = None
                x_px, why = path[kind][-1][1], "time"
                for t, q in path[kind]:
                    if stp is not None and q <= stp:
                        x_px, why = q, "stop"
                        break
                    if tgt is not None and q >= tgt:
                        x_px, why = q, "target"
                        break
                out = max(0.05, x_px - OS._slip(x_px))
                gross = (out - entry) * lot
                ch = charges(entry * lot, out * lot, orders=2)["total"]
                row = {"day": str(d), "kind": kind, "entry": round(entry, 2), "exit": round(out, 2), "why": why, "net": round(gross - ch, 2), "lot": lot}
                res[name]["call every day" if kind == "CE" else "put every day"].append(row)
                if lean == kind:
                    res[name]["morning-move direction"].append(row)
    cal = {}
    for kind in ("CE", "PE", "all"):
        cs = [x for x in calib if kind == "all" or x["kind"] == kind]
        if cs:
            err = [abs(x["pred"] - x["act"]) for x in cs]
            big = [x for x in cs if abs(x["move_sd"]) >= 0.7]
            cal[kind] = {"days": len(cs), "median_abs_error_pts": round(statistics.median(err), 2), "median_abs_error_pct_of_premium": round(statistics.median(e_ / x["prem"] * 100 for e_, x in zip(err, cs)), 1),
                         "corr": round(statistics.correlation([x["pred"] for x in cs], [x["act"] for x in cs]), 3) if len(cs) > 2 else None,
                         "bias_pts": round(statistics.mean(x["act"] - x["pred"] for x in cs), 2),
                         "big_move_days": len(big), "big_move_median_abs_error_pct": round(statistics.median(abs(x["pred"] - x["act"]) / x["prem"] * 100 for x in big), 1) if big else None}
    n = max(touched["n"], 1)
    out = {"generated": datetime.now(IST).isoformat(timespec="seconds"), "period": f"{days[0]} to {days[-1]}", "days_tested": touched["n"], "days_skipped": skipped,
           "status": "VERIFIED_HISTORICAL: Upstox expired NIFTY weekly option 1-minute candles (cached), NIFTY 1-minute database",
           "expected_move_reached_by_15_15_pct": {"up_1sd": round(100 * touched["call"] / n, 1), "down_1sd": round(100 * touched["put"] / n, 1), "model_each_side_touch_pct": 31.7},
           "calibration": cal, "results": {name: {s: stats(v) for s, v in by.items()} for name, by in res.items()},
           "unavailable": P.unavailable, "fallbacks": P.fallbacks, "network_calls": c.calls, "cache_hits": c.cache_hits, "seconds": round(time.time() - t0)}
    Path(ROOT / "quant/results").mkdir(exist_ok=True)
    (ROOT / "quant/results/epm_exits.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("period", "days_tested", "days_skipped", "expected_move_reached_by_15_15_pct", "calibration", "network_calls", "cache_hits", "seconds")}, indent=1))
    for name, by in out["results"].items():
        for s, v in by.items():
            print(f"{name:24s} {s:24s} n={v.get('trades')} win={v.get('win_rate')}% PF={v.get('profit_factor')} net={v.get('net_rs')} avg={v.get('avg_rs')} DD={v.get('max_drawdown_rs')} {v.get('exits')}")


if __name__ == "__main__":
    main()
