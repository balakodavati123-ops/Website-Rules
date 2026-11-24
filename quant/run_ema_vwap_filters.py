"""Cleaner-signal filters for the EMA9/VWAP strategy, chosen on the first year (Oct 2024 - Sep 2025) and checked on the second
(Oct 2025 - Oct 2026). Writes quant/results/ema_vwap_filters.json. Research only."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.backtest.straddle_engine import Backtester, Config   # noqa: E402
from src.data.upstox_client import IST, UpstoxClient           # noqa: E402
from src.reports.report import metrics                         # noqa: E402
from src.research import ema_vwap as EV                       # noqa: E402

SPLIT = "2025-10-01"


def main() -> None:
    cfg = Config(start=date(2024, 10, 1), end=datetime.now(IST).date())
    bt = Backtester(UpstoxClient(), cfg)
    bt.load()
    bt.legs = {}
    fut = EV.futures_minutes(bt.c, bt.expiries, cfg.start, cfg.end)
    ind = EV.indicators(fut, sorted(fut))
    grid = {"no filter (your rules)": {}, "VWAP slope, 1 candle": dict(slope_bars=1), "VWAP slope, 3 candles": dict(slope_bars=3), "VWAP slope, 5 candles": dict(slope_bars=5),
            "skip a crossover within 15 min": dict(cooldown_min=15), "skip within 30 min": dict(cooldown_min=30),
            "slope 1 + 15 min": dict(slope_bars=1, cooldown_min=15), "slope 3 + 15 min": dict(slope_bars=3, cooldown_min=15), "slope 5 + 15 min": dict(slope_bars=5, cooldown_min=15),
            "slope 3 + 30 min": dict(slope_bars=3, cooldown_min=30), "slope 3 + 15 min, touch exit": dict(slope_bars=3, cooldown_min=15, breach="touch")}
    out = {}
    for name, kw in grid.items():
        tr = EV.simulate(bt, ind, stop=0.25, label=name, **kw)
        y1, y2 = [t for t in tr if t["day"] < SPLIT], [t for t in tr if t["day"] >= SPLIT]
        out[name] = {"all": metrics(tr), "year1": metrics(y1), "year2": metrics(y2), "per_session": round(len(tr) / max(1, len({t["day"] for t in tr})), 2)}
        f = lambda m: f"{m.get('trades')} tr, {m.get('win_rate_pct')}% won, avg Rs {m.get('expectancy_inr')}, net Rs {m.get('net_pnl_inr')}, charges Rs {m.get('charges_inr')}"
        print(f"{name:32s} | year 1: {f(out[name]['year1'])} | year 2: {f(out[name]['year2'])} | {out[name]['per_session']}/session")
    ok = {k: v for k, v in out.items() if (v["year1"].get("trades") or 0) >= 100}
    pick = max(ok, key=lambda k: ok[k]["year1"].get("expectancy_inr") or -1e9)
    out["_chosen_on_year1"] = pick
    print("chosen on year 1:", pick, "-> year 2:", out[pick]["year2"])
    Path("quant/results/ema_vwap_filters.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
