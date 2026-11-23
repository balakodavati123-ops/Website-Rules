"""Run the NIFTY weekly long-straddle backtest on real Upstox option prices and write the ledgers and the report.

  UPSTOX_ACCESS_TOKEN=... python quant/run_backtest.py [--start 2024-10-01] [--end YYYY-MM-DD]
Outputs in quant/results/: trades_ledger.csv.gz, trades_ledger.json.gz, summary.json, report.md. No agent is trained and no order is sent:
see quant/src/agent/trainer.py for the permission gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.backtest.straddle_engine import Backtester, Config, as_rows   # noqa: E402
from src.data.upstox_client import IST, UpstoxClient                   # noqa: E402
from src.reports import report as RPT                                   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-10-01")
    ap.add_argument("--end", default=datetime.now(IST).date().isoformat())
    ap.add_argument("--out", default="quant/results")
    a = ap.parse_args()
    cfg = Config(start=date.fromisoformat(a.start), end=date.fromisoformat(a.end))
    bt = Backtester(UpstoxClient(), cfg)
    rows = as_rows(bt.run())
    out = Path(a.out)
    RPT.write_ledgers(rows, out)
    s = RPT.summary(rows, bt.status, cfg)
    (out / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps({k: s[k] for k in ("DATA_SOURCE_STATUS", "overall_all_configs", "best_config", "ranked_top10")}, indent=1, default=str)[:6000])
    print("\nPERMISSION GATE: no agent has been trained and no order sent. Reply APPROVE_AGENT_TRAINING (and separately APPROVE_PAPER_EXECUTION) to proceed.")


if __name__ == "__main__":
    main()
