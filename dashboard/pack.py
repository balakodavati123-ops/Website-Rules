"""Builds the documents that make up the CEO Trading Desk dashboard.

Live datasets are calls on the viewer's own INDmoney connection (read-only tools).
File datasets are the desk's own saved data (agent notes, plan, ledger, strategy tests, and
crypto prices from CoinDCX and Kraken, which have no connector).
Writes dashboard/pack/*.json and prints the batch for ArtifactData.

Usage: python dashboard/pack.py ASSETS.json
  ASSETS.json maps file-dataset ids to their /_blob/ urls (printed by the uploads). A file
  dataset missing from it is left out, so one upload can be packed by itself.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "page"
PACK = ROOT / "pack"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
EDIT = {"via": "claude", "at": NOW}

IND = "INDmoney"
CAND_KEYS = ["INDI00012", "INDI00024", "INDS02423", "INDS01104", "INDS01992", "INDS04037", "INDS00972", "INDS01995",
             "INDS01620", "INDCF5UV5U5G", "INDCF4KF275C", "INDCF66J0IAV", "INDCFCC1F0V8", "INDCF5MMIWLR"]
WATCH_KEYS = ["INDS02423", "INDS01104", "INDS01992", "INDS39555", "INDS04037", "INDS00954", "INDS00972", "INDS01070",
              "INDS01995", "INDS01620"]
INDEX_KEYS = ["INDI00012", "INDI00024", "INDI00050", "INDI00318", "INDI00267"]
MCX_KEYS = ["INDCF5UV5U5G", "INDCF4KF275C", "INDCF66J0IAV", "INDCFCC1F0V8", "INDCF5MMIWLR", "INDCF9J2E7E6"]


def call(connector, tool, args, rules=None):
    s = {"kind": "call", "connector": connector, "tool": tool, "args": args}
    if rules:
        s["rules"] = rules
    return s


def live(title, desc, source):
    return {"title": title, "description": desc, "source": source, "edit": EDIT}


def mover(cat, limit):
    return call(IND, "get_indian_stocks_movers", {"category": cat, "limit": limit})


LIVE = {
    "snapshot": live("Net worth snapshot", "Totals, asset classes and loans from the INDmoney account.", call(IND, "networth_snapshot", {})),
    "mf_holdings": live("Mutual fund holdings", "Your mutual fund holdings with profit and loss.", call(IND, "networth_holdings", {"asset_type": "MF"})),
    "stock_holdings": live("Direct stock holdings", "Your direct Indian stock holdings with profit and loss.", call(IND, "networth_holdings", {"asset_type": "IND_STOCK"})),
    "gold_rows": live("Gold holdings", "Your gold holdings.", call(IND, "get_family_asset_holdings", {"asset": "gold"})),
    "silver_rows": live("Silver holdings", "Your silver holdings.", call(IND, "get_family_asset_holdings", {"asset": "silver"})),
    "indices": live("Index quotes", "Nifty 50, Bank Nifty, Sensex, India VIX and Nifty Midcap 100, live.", call(IND, "get_indian_stocks_details", {"ind_keys": INDEX_KEYS})),
    "watch_live": live("Watchlist quotes and targets", "Live quotes and analyst targets for the CEO's watchlist and today's signal.", call(IND, "get_indian_stocks_details", {"ind_keys": WATCH_KEYS, "segments": ["analyst"]})),
    "comm_live": live("MCX futures quotes", "Gold, gold mini, silver, crude oil, natural gas and copper futures, live.", call(IND, "get_indian_stocks_details", {"ind_keys": MCX_KEYS})),
    "m_gainers": live("Top gainers", "Today's top gaining stocks.", mover("top-gainers", 25)),
    "m_losers": live("Top losers", "Today's top losing stocks.", mover("top-losers", 15)),
    "m_52high": live("52-week highs", "Stocks at or near their 52-week high today.", mover("52-week-high", 25)),
    "m_active": live("Most active", "Most traded stocks by value today.", mover("most-active", 15)),
    "m_upper": live("Upper circuits", "Stocks locked at their upper circuit today.", mover("upper-circuit-stocks", 15)),
    "candles": live("Candles for the chosen instrument", "Open, high, low, close and volume for the instrument and timeframe picked on the chart.",
                    call(IND, "get_indian_stocks_ohlc", {"ind_key": "{{sym}}", "interval": "{{iv}}", "lookback": "{{lb}}"},
                         {"sym": {"enum": CAND_KEYS}, "iv": {"enum": ["5minute", "15minute", "60minute", "1day"]}, "lb": {"enum": ["1d", "7d", "14d", "1y"]}})),
    "news_live": live("Watchlist news", "INDmoney news and sentiment tags for the watchlist stocks.", call(IND, "get_indian_stocks_details", {"ind_keys": WATCH_KEYS, "segments": ["news"]})),
    "nifty_chain": live("NIFTY option chain", "Seven strikes around the money, nearest expiry, live.", call(IND, "get_indian_stocks_option_chain", {"ind_key": "INDI00012", "use_expiry_date": False, "strikes_around_atm": 3})),
    "mf_ideas": live("Long-term fund ideas", "Top-ranked funds in flexi cap, large and mid cap, and Nifty 50 index categories.",
                     call(IND, "get_mf_by_category", {"categories": ["flexi-cap", "large-mid-cap", "nifty-50-index-funds"], "size": 12, "sort_key": "category_ind_rank", "sort_asc": True})),
}

FILES = {  # id -> (title, description, file name)
    "agent_feed": ("Morning briefing messages", "What the agents said in their latest run, in order.", "agent_feed.json"),
    "plan_today": ("Today's plan", "Watchlist with reasons: algo signal, screened names, filings and results.", "plan_today.json"),
    "alerts_log": ("Company filing alerts", "Filings caught during the session with the price at the moment of filing.", "alerts_log.json"),
    "strategies_eq": ("Stock strategy tests", "Five-year tests of eight stock strategies with confidence figures.", "strategies_eq.json"),
    "strategies_macro": ("Crypto and commodity strategy tests", "Five-year tests of three trend strategies on crypto and commodities.", "strategies_macro.json"),
    "macro_signals": ("Breakout signals", "Today's 20-day breakout status for crypto and commodities.", "macro_signals.json"),
    "paper_ledger": ("Paper ledger", "Every paper order the agents take.", "paper_ledger.json"),
    "paper_equity": ("Paper equity", "Paper account equity by day.", "paper_equity.json"),
    "desk_rules": ("Desk rules", "Trading cash, risk limits and the real-money gate.", "desk_rules.json"),
    "crypto_quotes": ("Crypto prices in rupees", "Bitcoin, Ethereum and Solana on CoinDCX, cross-checked against Kraken's dollar price.", "crypto_quotes.json"),
    "desk_signals": ("Research signals", "The research agents' structured hand-off: trajectory, sentiment, conviction and the chart-gate verdict.", "desk_signals.json"),
    "signal_ledger": ("Signal desk ledger", "Every trade of the Rs 1,00,000 signal desk with conviction, deployment, stop and result.", "signal_ledger.json"),
    "signal_lessons": ("Signal desk lessons", "Diagnosis of every losing exit and the rule it adds to the pre-trade checklist.", "signal_lessons.json"),
    "news_feed": ("News feed", "High-impact headlines caught by the real-time watcher, with their category and whether they triggered a trade.", "news_feed.json"),
    "news_ledger": ("News desk ledger", "Intraday paper trades taken on market-moving headlines.", "news_ledger.json"),
    "fo_ledger": ("F&O paper positions", "NIFTY index option structures the desk paper trades, held to expiry.", "fo_ledger.json"),
    "world_markets": ("World markets before the bell", "Last close and change for world indices, the dollar, the rupee, crude, gold and US yields, from Yahoo Finance.", "world_markets.json"),
    "events_today": ("Company events", "Board meetings, results and corporate actions due in the next three days, from NSE.", "events_today.json"),
    "world_news": ("Headlines", "News headlines from Yahoo Finance, word for word with their publisher.", "world_news.json"),
    "crypto_candles": ("Crypto candles in rupees", "CoinDCX daily, hourly and 15-minute candles for Bitcoin, Ethereum and Solana.", "crypto_candles.json"),
}
SCHEDULE = "Rebuilt each weekday at 08:15 IST by the CEO Desk Daily Refresh task."
PAGE_FILES = ["index.html", "style.css", "lib.js", "data.js", "floor_data.js", "floor_engine.js", "floor_stage.js", "floor_views.js", "org_stage.js", "ls_engine.js", "live_session.js", "views_plus.js", "views_command.js", "views_pre.js", "views_alerts.js",
              "views_algo.js", "views_markets.js", "views_room.js", "tabs.js"]


def main():
    assets = json.loads(Path(sys.argv[1]).read_text())
    PACK.mkdir(exist_ok=True)
    for f in PACK.glob("*.json"):
        f.unlink()
    writes = []

    def put(collection, doc_id, data):
        path = PACK / f"{collection}__{doc_id}.json"
        path.write_text(json.dumps(data))
        writes.append({"op": "set", "collection": collection, "doc_id": doc_id, "file_path": str(path)})

    put("dash", "meta", {"title": "CEO Trading Desk", "lang": "en"})
    put("dash", "params", {"sym": "INDI00012", "iv": "15minute", "lb": "7d", "csym": "BTC", "ctf": "1d", "mode": "paper"})
    for did, doc in LIVE.items():
        put("datasets", did, doc)
    for did, (title, desc, fname) in FILES.items():
        if did not in assets:
            continue
        doc = {"title": title, "description": desc, "edit": EDIT,
               "source": {"kind": "file", "url": assets[did], "name": fname, "format": "json"},
               "updated": {"at": NOW, "by": "Claude (agent run)"}}
        if did not in ("strategies_eq", "desk_rules"):
            doc.update(schedule=SCHEDULE, staleAfterHours=96)
        put("datasets", did, doc)
    for name in PAGE_FILES:
        put("files", name, {"text": (PAGE / name).read_text(), "edit": EDIT})
    (PACK / "batch.json").write_text(json.dumps(writes))
    print(len(writes), "documents;", sum(len(json.dumps(json.loads(Path(w['file_path']).read_text()))) for w in writes), "bytes")


if __name__ == "__main__":
    main()
