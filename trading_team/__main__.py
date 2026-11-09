"""Command line: python -m trading_team {run,settle,stats}"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from .config import Settings
from .ledger import Ledger, settle_open_trades


def read_watchlist(path: str) -> list[str]:
    tickers = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tickers.append(line.upper())
    return tickers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading_team")
    parser.add_argument("--ledger", default=Settings.ledger_path)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run the daily analysis")
    run_p.add_argument("--watchlist", required=True, help="file with one ticker per line")
    run_p.add_argument("--model", default=Settings.model)
    run_p.add_argument("--no-pdf", action="store_true")

    sub.add_parser("settle", help="settle open trades against later prices")
    sub.add_parser("stats", help="print the track record")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    settings = Settings()
    ledger = Ledger(args.ledger)

    if args.cmd == "stats":
        print(json.dumps(ledger.stats(), indent=2))
        return 0

    from .data import YFinanceProvider
    provider = YFinanceProvider()

    if args.cmd == "settle":
        settled = settle_open_trades(ledger, lambda t: provider.history(t, 400),
                                     settings.rules, date.today())
        print(json.dumps(settled, indent=2) if settled else "no open trades settled")
        return 0

    from .llm import AnthropicLLM
    from .pipeline import TradingDesk
    tickers = read_watchlist(args.watchlist)
    if not tickers:
        print("watchlist is empty", file=sys.stderr)
        return 2
    desk = TradingDesk(provider, AnthropicLLM(args.model), ledger, settings)
    result = desk.run(tickers, write_report=not args.no_pdf)
    rec = result.recommendation
    print(f"{rec.run_date}: {rec.action}"
          + (f" {rec.ticker} entry {rec.entry_price} stop {rec.stop_loss} "
             f"target {rec.target}" if rec.is_trade else ""))
    print(rec.rationale)
    if result.pdf_path:
        print(f"report: {result.pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
