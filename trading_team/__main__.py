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
    tk.add_argument("--from-json", default=None,
                    help="recommendation file written by `run` (reports/YYYY-MM-DD.json)")
    tk.add_argument("--mode", choices=("limit", "open"), default="limit",
                    help="limit: use the entry/stop/target given; open: enter at the live "
                         "price with the strategy's stop and target percentages (as backtested)")
    tk.add_argument("--max-gap-pct", type=float, default=3.0,
                    help="open mode: skip if live price is further than this from the analysed close")
    tk.add_argument("--ticker", default=None)
    tk.add_argument("--entry", type=float, default=None)
    tk.add_argument("--stop", type=float, default=None)
    tk.add_argument("--target", type=float, default=None)
    tk.add_argument("--equity", type=float, required=True, help="current portfolio equity, Rs")
    tk.add_argument("--risk-pct", type=float, default=0.5, help="risk per trade, %% of equity")
    tk.add_argument("--open-risk", type=float, default=0.0, help="risk already open, Rs")
    tk.add_argument("--cash", type=float, default=None)
    tk.add_argument("--live-price", type=float, default=None,
                    help="live price you or Claude read from INDmoney")
    tk.add_argument("--price-time", default=None, help="time of that price, HH:MM:SS IST")
    tk.add_argument("--vix", type=float, default=None)

    bd = sub.add_parser("board", help="print a context board from INDmoney mover lists")
    bd.add_argument("files", nargs="+", help="saved get_indian_stocks_movers outputs")
    bd.add_argument("--ticker", default=None, help="also check this ticker against the lists")

    screen_p = sub.add_parser(
        "screen", help="print verified prices and indicators as JSON (no API key needed)")
    screen_p.add_argument("--watchlist", required=True)

    sub.add_parser("settle", help="settle open trades against later prices")
    sub.add_parser("stats", help="print the track record")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    settings = Settings()
    ledger = Ledger(args.ledger)

    if args.cmd == "board":
        from .movers import parse, render_board, warnings_for
        boards = {}
        for f in args.files:
            cat, stocks = parse(Path(f).read_text())
            boards[cat] = stocks
        print(render_board(boards))
        for w in (warnings_for(args.ticker, boards) if args.ticker else []):
            print(f"WARNING: {w}")
        return 0

    if args.cmd == "ticket":
        from datetime import datetime
        from .ticket import IST, build_ticket, levels_from_pct, render_text
        ticker, ref_entry, stop, target = args.ticker, args.entry, args.stop, args.target
        stop_pct = target_pct = None
        if args.from_json:
            rec = json.loads(Path(args.from_json).read_text())
            if rec.get("action") != "BUY":
                print(f"NO TRADE on {rec.get('run_date')}: {rec.get('rationale', '')}")
                for n in rec.get("risk_notes", []):
                    print(f"  {n}")
                return 0
            ticker, ref_entry = rec["ticker"], rec["entry_price"]
            stop, target = rec["stop_loss"], rec["target"]
            stop_pct, target_pct = rec["stop_pct"], rec["target_pct"]
            print(f"Recommendation {rec['run_date']}: {rec.get('strategy') or 'no strategy tag'}")
        if not ticker or ref_entry is None:
            print("give --from-json, or --ticker with --entry --stop --target", file=sys.stderr)
            return 2
        pt = None
        if args.price_time:
            h, m, sec = (int(x) for x in (args.price_time.split(":") + ["0"])[:3])
            pt = datetime.now(IST).replace(hour=h, minute=m, second=sec, microsecond=0)
        entry, reference = ref_entry, None
        if args.mode == "open":
            if args.live_price is None or stop_pct is None:
                print("open mode needs --from-json and --live-price", file=sys.stderr)
                return 2
            entry, reference = args.live_price, ref_entry
            stop, target = levels_from_pct(entry, stop_pct, target_pct)
        if stop is None or target is None:
            print("need --stop and --target", file=sys.stderr)
            return 2
        ticker = ticker.upper().removesuffix(".NS").removesuffix(".BO")   # the app's symbol
        t = build_ticket(ticker=ticker, entry=entry, stop=stop, target=target,
                         equity=args.equity, risk_frac=args.risk_pct / 100,
                         open_risk_rs=args.open_risk, cash=args.cash,
                         live_price=args.live_price, price_time=pt, vix=args.vix,
                         reference_price=reference, max_gap_pct=args.max_gap_pct)
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
    import dataclasses
    out = Path(settings.report_dir) / f"{rec.run_date.isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dataclasses.asdict(rec), indent=2, default=str))
    print(f"recommendation file: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
