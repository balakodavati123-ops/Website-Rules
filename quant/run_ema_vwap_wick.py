"""The reel's EMA9 / VWAP strategy on 3-minute NIFTY candles, on REAL option prices, 2 lots, Oct 2024 to Nov 2026.
python quant/run_ema_vwap_wick.py  ->  quant/results/ema_vwap_wick.json. Research only."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.backtest.straddle_engine import Backtester, Config   # noqa: E402
from src.data.upstox_client import IST, UpstoxClient           # noqa: E402
from src.research import ema_vwap as EV                       # noqa: E402


def stats(T, start=100000.0):
    xs = [t["net"] for t in T]
    if not xs:
        return {"trades": 0}
    w = [x for x in xs if x > 0]
    gp, gl = sum(w), -sum(x for x in xs if x <= 0)
    eq, pk, dd, low, run, cur = start, start, 0.0, start, 0, 0
    for x in xs:
        eq += x
        pk, low, dd = max(pk, eq), min(low, eq), max(dd, pk - eq)
        cur = cur + 1 if x <= 0 else 0
        run = max(run, cur)
    top5 = sum(sorted(xs, reverse=True)[:5])
    days = len({t["day"] for t in T})
    return {"trades": len(xs), "perDay": round(len(xs) / max(days, 1), 2), "winRate": round(100 * len(w) / len(xs), 1), "profitFactor": round(gp / gl, 2) if gl else None,
            "net": round(gp - gl), "avg": round((gp - gl) / len(xs)), "maxDrawdown": round(dd), "lowestEquity": round(low), "withoutTop5": round(gp - gl - top5),
            "longestLosingRun": run, "charges": round(sum(t["charges"] for t in T)), "avgOutlay": round(sum(t["outlay"] for t in T) / len(T)),
            "futPtsAvg": round(sum(t["fut_move"] for t in T) / len(T), 1)}


def main():
    rate = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--rate=")), "0.12"))
    cfg = Config(start=date(2024, 10, 1), end=datetime.now(IST).date())
    bt = Backtester(UpstoxClient(min_interval=rate), cfg, log=lambda *a: None)
    bt.load()
    bt.legs = {}
    fut = EV.futures_minutes(bt.c, bt.expiries, cfg.start, cfg.end, log=lambda *a: None)
    ind = EV.indicators(fut, sorted(fut))
    out = {"period": f"{cfg.start} to {cfg.end}", "data": "VERIFIED_HISTORICAL: near-month NIFTY futures 1-minute candles (VWAP with volume), weekly NIFTY option 1-minute candles", "runs": []}
    for name, fn in EV.RULES.items():
        for stop, sl in ((0.25, "-25% premium stop"), (None, "no premium stop")):
            for dte, dl in ((0, "nearest expiry"), (1, "skip expiry day")):
                T = EV.simulate_rule(bt, ind, fn, lots=2, stop=stop, min_dte=dte)
                S = stats(T)
                yr = {y: stats([t for t in T if t["day"][:4] == y]) for y in sorted({t["day"][:4] for t in T})}
                ex = {k: stats([t for t in T if t["why"] == k]) for k in Counter(t["why"] for t in T)}
                out["runs"].append({"rule": name, "stop": sl, "expiry": dl, "stats": S, "byYear": yr, "byExit": ex, "sides": {s: stats([t for t in T if t["side"] == s]) for s in ("CALL", "PUT")}})
                print(f"{name[:50]:50s} | {sl:18s} | {dl:15s} | {S.get('trades')} tr ({S.get('perDay')}/day) {S.get('winRate')}% won PF {S.get('profitFactor')} net Rs {S.get('net')} "
                      f"DD Rs {S.get('maxDrawdown')} low Rs {S.get('lowestEquity')} w/o top5 Rs {S.get('withoutTop5')} | fut pts/trade {S.get('futPtsAvg')} | "
                      + " ".join(f"{y}: PF {v.get('profitFactor')} Rs {v.get('net')}" for y, v in yr.items()), flush=True)
                Path("quant/results/ema_vwap_wick.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
