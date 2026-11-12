"""Runs the paper engine and writes the paper ledger and equity files for the dashboard.

Usage: python dashboard/refresh.py --state DIR [--date YYYY-MM-DD]
DIR holds the dashboard's current paper_ledger.json and paper_equity.json (downloaded from the
artifact). New versions are written to dashboard/data/. Signals come from the newest desk run
(reports/*.json) and from backtest/macro_lab_results.json (crypto Donchian breakouts).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_engine import YahooProvider, step  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def stock_signals(provider) -> list[dict]:
    files = sorted(p for p in (ROOT / "reports").glob("20??-??-??.json"))
    if not files:
        return []
    rec = json.loads(files[-1].read_text())
    if rec.get("action") != "BUY" or not rec.get("ticker"):
        return []
    sym = rec["ticker"].replace(".NS", "")
    bars = provider.daily(f"{sym}.NS")
    return [{"market": "NSE", "symbol": sym, "strategy": (rec.get("strategy") or "breakout_52w").split(" (")[0],
             "signal_date": str(bars.index[-1].date()), "signal_close": float(bars.Close.iloc[-1])}]


PRICE_STRATEGIES = ["breakout_52w", "breakout_52w_trail", "trend_ride", "momentum_screen", "pullback_in_uptrend", "rsi2_dip"]


def scan_signals(provider, per_strategy: int = 2) -> list[dict]:
    """Every price strategy on the whole watchlist; the strongest few signals of each go on paper.
    Strategies the 5-year test rejected are traded here too, on paper only, so their record is seen."""
    import yfinance as yf
    sys.path.insert(0, str(ROOT))
    from trading_team.strategies import STRATEGIES
    ticks = [t.strip() for t in (ROOT / "watchlists" / "nifty200_plus_etfs.txt").read_text().splitlines() if t.strip() and not t.startswith("#")]
    data = yf.download(ticks, period="2y", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    newest = max(data[t].Close.dropna().index[-1] for t in ticks if t in data and len(data[t].Close.dropna()))
    found: dict[str, list] = {}
    for t in ticks:
        try:
            df = data[t].dropna(subset=["Close"])
        except KeyError:
            continue
        if len(df) < 260 or df.index[-1] != newest:          # too short, or its last bar is stale
            continue
        df = df.copy()
        df.index = __import__("pandas").to_datetime(df.index.date)
        for name in PRICE_STRATEGIES:
            last = STRATEGIES[name].fn(df)[0].iloc[-1]
            if last == last:
                found.setdefault(name, []).append((float(last), t, df))
    out = []
    for name, hits in found.items():
        for _, t, df in sorted(hits, key=lambda x: -x[0])[:per_strategy]:
            provider._pre[t] = df
            out.append({"market": "NSE", "symbol": t.replace(".NS", ""), "strategy": name,
                        "signal_date": str(df.index[-1].date()), "signal_close": float(df.Close.iloc[-1])})
    print("signals:", {k: len(v) for k, v in found.items()}, "taken", len(out))
    return out


def crypto_signals() -> list[dict]:
    f = ROOT / "backtest" / "macro_lab_results.json"
    if not f.exists():
        return []
    out = []
    for s in json.loads(f.read_text())["signals"]:
        if s["strategy"] == "donchian_20_10" and s["kind"] == "crypto" and s["entry_signal_today"]:
            out.append({"market": "CRYPTO", "symbol": s["symbol"], "strategy": "donchian_20_10", "signal_date": s["last_date"],
                        "signal_close": s["last_close"], "atr": s["atr20"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    today = args.date or datetime.now(IST).date().isoformat()
    state = Path(args.state)
    ledger = json.loads((state / "paper_ledger.json").read_text())
    equity = json.loads((state / "paper_equity.json").read_text())
    rules = json.loads((ROOT / "dashboard" / "data" / "desk_rules.json").read_text())
    provider = YahooProvider()
    try:
        scanned = scan_signals(provider)
    except Exception as e:                                   # the scan is extra: the desk's own signal still runs
        print("strategy scan failed:", e)
        scanned = []
    ledger, equity = step(ledger, equity, rules, stock_signals(provider) + scanned + crypto_signals(), provider, today)
    out = ROOT / "dashboard" / "data"
    (out / "paper_ledger.json").write_text(json.dumps(ledger, indent=1))
    (out / "paper_equity.json").write_text(json.dumps(equity, indent=1))
    by = {}
    for r in ledger:
        by[r["status"]] = by.get(r["status"], 0) + 1
    print(f"{today}: ledger {len(ledger)} rows {by}; equity {equity[-1]['equity']}")


if __name__ == "__main__":
    main()
