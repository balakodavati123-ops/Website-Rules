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
    run_p.add_argument("--model", default=None,
                       help="model name; default is the backend's own default")
    run_p.add_argument("--llm", choices=("auto", "cli", "api"), default="auto",
                       help="cli = Claude subscription via the `claude` command; "
                            "api = Anthropic API key; auto = api if a key is set, else cli")
    run_p.add_argument("--no-pdf", action="store_true")
    run_p.add_argument("--no-strategy-gate", action="store_true",
                       help="analyse the top of the plain screen instead of requiring "
                            "an entry signal from a backtested strategy")

    tk = sub.add_parser("ticket", help="print an order ticket (no orders are placed)")
    tk.add_argument("--ticker", required=True)
    tk.add_argument("--entry", type=float, required=True)
    tk.add_argument("--stop", type=float, required=True)
    tk.add_argument("--target", type=float, required=True)
    tk.add_argument("--equity", type=float, required=True, help="current portfolio equity, Rs")
    tk.add_argument("--risk-pct", type=float, default=0.5, help="risk per trade, %% of equity")
    tk.add_argument("--open-risk", type=float, default=0.0, help="risk already open, Rs")
    tk.add_argument("--cash", type=float, default=None)
    tk.add_argument("--live-price", type=float, default=None,
                    help="live price you or Claude read from INDmoney")
    tk.add_argument("--price-time", default=None, help="time of that price, HH:MM:SS IST")
    tk.add_argument("--vix", type=float, default=None)

    screen_p = sub.add_parser(
        "screen", help="print verified prices and indicators as JSON (no API key needed)")
    screen_p.add_argument("--watchlist", required=True)

    sub.add_parser("settle", help="settle open trades against later prices")
    sub.add_parser("stats", help="print the track record")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    settings = Settings()
    ledger = Ledger(args.ledger)

    if args.cmd == "ticket":
        from datetime import datetime
        from .ticket import IST, build_ticket, render_text
        pt = None
        if args.price_time:
            h, m, sec = (int(x) for x in (args.price_time.split(":") + ["0"])[:3])
            pt = datetime.now(IST).replace(hour=h, minute=m, second=sec, microsecond=0)
        t = build_ticket(ticker=args.ticker.upper(), entry=args.entry, stop=args.stop,
                         target=args.target, equity=args.equity,
                         risk_frac=args.risk_pct / 100, open_risk_rs=args.open_risk,
                         cash=args.cash, live_price=args.live_price, price_time=pt,
                         vix=args.vix)
        print(render_text(t))
        return 0

    if args.cmd == "stats":
        print(json.dumps(ledger.stats(), indent=2))
        return 0

    from .data import YFinanceProvider
    provider = YFinanceProvider()

    if args.cmd == "screen":
        from .data import DataAgent
        from .indicators import screen_score, technical_summary
        agent = DataAgent(provider, settings.history_days)
        market = agent.market()
        rows = []
        for t in read_watchlist(args.watchlist):
            snap = agent.snapshot(t)
            tech = technical_summary(snap.bars) if snap.bars else None
            rows.append({"ticker": t,
                         "screen_score": screen_score(tech) if tech else None,
                         "technicals": tech or "UNVERIFIED",
                         "unverified": snap.unverified_items()})
        rows.sort(key=lambda r: (r["screen_score"] is not None, r["screen_score"] or 0),
                  reverse=True)
        vix = market["india_vix"]
        print(json.dumps({"as_of": date.today().isoformat(),
                          "source": "Yahoo Finance daily bars (delayed, unofficial)",
                          "india_vix": vix.value if vix.verified else "UNVERIFIED",
                          "candidates": rows}, indent=2, default=str))
        return 0

    if args.cmd == "settle":
        settled = settle_open_trades(ledger, lambda t: provider.history(t, 400),
                                     settings.rules, date.today())
        print(json.dumps(settled, indent=2) if settled else "no open trades settled")
        return 0

    import os
    from .llm import AnthropicLLM, ClaudeCLILLM
    from .pipeline import TradingDesk
    tickers = read_watchlist(args.watchlist)
    if not tickers:
        print("watchlist is empty", file=sys.stderr)
        return 2
    backend = args.llm
    if backend == "auto":
        backend = "api" if os.environ.get("ANTHROPIC_API_KEY") else "cli"
    llm = (AnthropicLLM(args.model or settings.model) if backend == "api"
           else ClaudeCLILLM(args.model))
    if not args.no_strategy_gate:
        from dataclasses import replace
        from .strategies import VERDICT_FILE
        if VERDICT_FILE.exists():
            settings = replace(settings, strategy_file=str(VERDICT_FILE))
    desk = TradingDesk(provider, llm, ledger, settings)
    result = desk.run(tickers, write_report=not args.no_pdf)
    rec = result.recommendation
    print(f"{rec.run_date}: {rec.action}"
          + (f" {rec.ticker} entry {rec.entry_price} stop {rec.stop_loss} "
             f"target {rec.target}" if rec.is_trade else ""))
    if rec.strategy:
        print(f"entry strategy: {rec.strategy}")
    print(rec.rationale)
    for note in rec.risk_notes:
        print(f"  risk: {note}")
    if rec.unverified:
        print("  Data Unverified: " + "; ".join(rec.unverified))
    if result.pdf_path:
        print(f"report: {result.pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
