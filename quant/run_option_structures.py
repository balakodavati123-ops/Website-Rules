"""Real-option-price test of the CEO's structures (2 lots: calls, puts, both, or hedged) on the strategies that held up, Oct 2024 - Nov 2026.
python quant/run_option_structures.py [--only N] [--structures buy2,hedge] -> quant/results/option_structures.json. Research only."""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.backtest.straddle_engine import Backtester, Config   # noqa: E402
from src.data.upstox_client import IST, UpstoxClient           # noqa: E402
from src.research import option_structures as OS              # noqa: E402

VARIANTS = [("buy2", {"itm": 0}, "2 lots, at the money"), ("buy2", {"itm": 100}, "2 lots, 100 in the money"),
            ("hedge", {"wing": 200}, "1 lot + 1 opposite lot 200 out (hedge)"), ("spread", {"wing": 200}, "debit spread, 200 wide")]
EXITS = [({}, "signal exits"), ({"stop": 0.4}, "signal exits + 40% premium stop")]


def omni_signals(bt) -> dict:
    """Both-direction entries (1 call + 1 put): days the market looks set to move. side is ignored by straddle / strangle."""
    days = [d for d in bt.trading if d in bt.n1 and d >= date(2024, 10, 1)]
    rng = {d: (max(v[0] for v in bt.n1[d].values()), min(v[0] for v in bt.n1[d].values())) for d in days}
    nxt = {days[i]: days[i + 1] for i in range(len(days) - 1)}
    nr7 = [d for i, d in enumerate(days) if i >= 6 and (rng[d][0] - rng[d][1]) <= min(rng[x][0] - rng[x][1] for x in days[i - 6:i + 1]) and d in nxt]
    def fh(d):
        b = [v[0] for k, v in bt.n1[d].items() if "09:15" <= k <= "10:14"]
        return (max(b) - min(b)) / b[0] * 100 if b else 9
    quiet = [d for d in days if fh(d) < 0.35]
    two = lambda d: nxt.get(nxt.get(d, d), nxt.get(d, d))
    return {"Every day 10:00, out 15:15 (control)": [{"day": str(d), "inT": "10:00", "exitDay": str(d), "outT": "15:15", "side": 1} for d in days],
            "NR7 day: next day 09:30, held up to 2 days": [{"day": str(nxt[d]), "inT": "09:30", "exitDay": str(two(d)), "outT": "15:15", "side": 1} for d in nr7],
            "Quiet first hour (<0.35%): 10:15, out 15:15": [{"day": str(d), "inT": "10:15", "exitDay": str(d), "outT": "15:15", "side": 1} for d in quiet]}


def main() -> None:
    args = sys.argv[1:]
    only = int(args[args.index("--only") + 1]) if "--only" in args else None
    t0 = time.time()
    bt = Backtester(UpstoxClient(), Config(start=date(2024, 10, 1), end=datetime.now(IST).date()), log=lambda *a: None)
    bt.load()
    P = OS.Pricer(bt)
    sig = json.loads(Path("quant/results/signals.json").read_text())
    res = {"period": f"{bt.expiries[0]} to {bt.expiries[-1]} (expired weekly options)", "directional": [], "omni": []}
    for i, s in enumerate(sig):
        if only is not None and i != only:
            continue
        for st, kw, lab in VARIANTS:
            for ex, xl in EXITS:
                rows = OS.simulate(P, s["trades"], st, **kw, **ex)
                S = OS.stats(rows)
                res["directional"].append({"signal": s["label"], "kind": s["kind"], "structure": lab, "exits": xl, "stats": S,
                                           "byYear": {y: OS.stats([r for r in rows if r["day"][:4] == y]) for y in sorted({r["day"][:4] for r in rows})}})
                print(f"[{time.time() - t0:5.0f}s] {s['label'][:62]:62s} | {lab:38s} | {xl:31s} | {S.get('trades')} tr {S.get('winRate')}% PF {S.get('profitFactor')} net Rs {S.get('net')} DD Rs {S.get('maxDrawdown')} low Rs {S.get('lowestEquity')}", flush=True)
    if only is None:
        for name, tr in omni_signals(bt).items():
            for st, kw, lab in [("straddle", {}, "1 call + 1 put at the money"), ("strangle", {"wing": 200}, "1 call + 1 put, 200 out")]:
                for ex, xl in [({}, "time exit"), ({"stop": 0.3, "target": 0.4}, "+40% target / -30% stop")]:
                    rows = OS.simulate(P, tr, st, **kw, **ex)
                    S = OS.stats(rows)
                    res["omni"].append({"signal": name, "structure": lab, "exits": xl, "stats": S})
                    print(f"[{time.time() - t0:5.0f}s] OMNI {name:44s} | {lab:28s} | {xl:24s} | {S.get('trades')} tr {S.get('winRate')}% PF {S.get('profitFactor')} net Rs {S.get('net')} DD Rs {S.get('maxDrawdown')}", flush=True)
    res["exit_price_fallbacks"] = P.fallbacks
    print("exits with no option price at that minute (valued flat):", P.fallbacks)
    res["status"] = "VERIFIED_HISTORICAL: Upstox expired NIFTY weekly option 1-minute candles; index signals from the NIFTY 1-minute database"
    Path("quant/results").mkdir(exist_ok=True)
    Path("quant/results/option_structures.json" if only is None else f"quant/results/option_structures_{only}.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
