"""Backtest the CEO's EMA9 / VWAP crossover strategy on real NIFTY futures and option prices; writes quant/results/ema_vwap*.{json,csv.gz}.
Research only: nothing is traded or trained."""
from __future__ import annotations

import csv
import gzip
import io
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.backtest.straddle_engine import Backtester, Config   # noqa: E402
from src.data.upstox_client import IST, UpstoxClient           # noqa: E402
from src.research import ema_vwap as EV                       # noqa: E402

OUT = Path("quant/results")


def main() -> None:
    cfg = Config(start=date(2024, 10, 1), end=datetime.now(IST).date())
    bt = Backtester(UpstoxClient(), cfg)
    bt.load()
    bt.legs = {}
    for e in bt.expiries:                                       # reuse the cached straddle contracts where they exist
        pass
    fut = EV.futures_minutes(bt.c, bt.expiries, cfg.start, cfg.end)
    days = sorted(d for d in fut if d >= cfg.start - date.resolution * 5)
    ind = EV.indicators(fut, days)
    variants = {"A: stop 25%, exit when a 3-min candle closes beyond EMA9": dict(stop=0.25, breach="close"),
                "B: stop 30%, exit on a close beyond EMA9": dict(stop=0.30, breach="close"),
                "C: stop 25%, exit when a 3-min candle touches EMA9": dict(stop=0.25, breach="touch"),
                "D: as A, entries 09:30-14:30 only": dict(stop=0.25, breach="close", first_entry="09:30", last_entry="14:30")}
    res, all_rows = {}, []
    for name, kw in variants.items():
        tr = EV.simulate(bt, ind, label=name, **kw)
        res[name] = EV.summarise(tr)
        all_rows += tr
        o = res[name]["overall"]
        print(f"{name}: {o.get('trades')} trades, {o.get('win_rate_pct')}% won, avg Rs {o.get('expectancy_inr')}, net Rs {o.get('net_pnl_inr')}, PF {o.get('profit_factor')}, "
              f"max DD Rs {o.get('max_drawdown_inr')}, t {o.get('t_stat')}; exits {res[name]['exit_reasons']}; hold {res[name]['avg_hold_min']} min; {res[name]['avg_trades_per_session']} trades a session")
    res["DATA_SOURCE_STATUS"] = {"signals": "VERIFIED_HISTORICAL (near-month NIFTY futures 1-minute candles with volume, Upstox expired instruments)",
                                 "options": "VERIFIED_HISTORICAL (weekly NIFTY option 1-minute candles)", "period": f"{cfg.start} to {cfg.end}"}
    (OUT / "ema_vwap.json").write_text(json.dumps(res, indent=1, default=str))
    buf = io.StringIO()
    if all_rows:
        w = csv.DictWriter(buf, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)
    (OUT / "ema_vwap_trades.csv.gz").write_bytes(gzip.compress(buf.getvalue().encode()))


if __name__ == "__main__":
    main()
