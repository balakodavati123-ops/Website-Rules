"""Daily rule-based engines for the always-on backend (GitHub Actions, about 08:15 IST).

Runs, in order, each one allowed to fail without stopping the rest:
  world markets, events and headlines (Yahoo Finance, NSE) / crypto (CoinDCX, Kraken) / results filed
  paper engine: seven strategies scanned on the watchlist, each trading its own book
  F&O settlement of expired NIFTY option structures / signal desk (ATR stops, lessons)
State lives in docs/data/*.json (the ledgers); the engines' working copies are in dashboard/data.
The Claude research agents (they need a Claude login) are not part of this: where their output is
missing the signal desk simply has no signals.

Usage: python backend/daily.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK, DOCS = ROOT / "dashboard" / "data", ROOT / "docs" / "data"
STATE = ["paper_ledger.json", "paper_equity.json", "fo_ledger.json", "signal_ledger.json", "signal_lessons.json"]
OUTPUT = STATE + ["desk_signals.json", "world_markets.json", "events_today.json", "world_news.json", "results_filed.json", "crypto_quotes.json",
                  "crypto_candles.json", "alerts_log.json"]
RULES = [{"key": "trading_cash", "value": 32000}, {"key": "paper_start", "value": 32000}, {"key": "risk_normal", "value": 1.0},
         {"key": "risk_caution", "value": 0.5}, {"key": "gate_conf", "value": 98}, {"key": "gate_trades", "value": 100},
         {"key": "gate_dd", "value": 20}, {"key": "stop_pct", "value": 5}, {"key": "target_pct", "value": 20}]


def run(cmd: list[str]):
    r = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)
    print(f"$ {' '.join(cmd)} -> {'ok' if r.returncode == 0 else 'FAILED'}")
    print("\n".join((r.stdout + r.stderr).strip().splitlines()[-4:]))
    return r.returncode == 0


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    for n in STATE:
        if (DOCS / n).exists():
            shutil.copy(DOCS / n, WORK / n)
    (WORK / "desk_rules.json").write_text(json.dumps(RULES))
    for c in (["dashboard/make_world.py"], ["dashboard/make_crypto.py"], ["dashboard/make_alerts.py"]):
        run(c)
    run(["dashboard/refresh.py", "--state", str(DOCS)])
    run(["dashboard/fo_engine.py", "settle"])
    run(["dashboard/signal_desk.py"])
    for n in OUTPUT:
        if (WORK / n).exists():
            shutil.copy(WORK / n, DOCS / n)
    run(["backtest/macro_lab.py"])
    macro_file = ROOT / "backtest" / "macro_lab_results.json"
    if macro_file.exists():
        m = json.loads(macro_file.read_text())
        desc = {"donchian_20_10": "Buy a close above the 20-day high, exit below the 10-day low", "golden_cross": "Buy when the 50-day average crosses above the 200-day",
                "momentum_12_1": "Buy positive 12-month momentum above the 100-day average"}
        rows = []
        for key, v in m["strategies"].items():
            strat, kind = key.split(":")
            rows.append({"strategy": strat, "market": kind, "description": desc.get(strat, ""), "status": v["status"], "trades": v["trades"], "win_rate": v.get("win_rate", 0),
                         "avg_R": v.get("avg_R", 0), "conf_cluster": v.get("conf_cluster", 0), "conf_adjusted": v.get("conf_adjusted", 0)})
        (DOCS / "strategies_macro.json").write_text(json.dumps(rows, indent=1))
        sig = [{"symbol": s["symbol"], "name": s["name"], "market": s["kind"], "entry_signal_today": "YES" if s["entry_signal_today"] else "no",
                "last_close": s["last_close"], "last_date": s["last_date"], "buy_hold_pa": m["buy_and_hold"][s["symbol"]]}
               for s in m["signals"] if s["strategy"] == "donchian_20_10"]
        (DOCS / "macro_signals.json").write_text(json.dumps(sig, indent=1))
    print("daily engines done")


if __name__ == "__main__":
    main()
