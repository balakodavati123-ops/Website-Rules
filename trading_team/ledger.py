"""Ledger agent: logs every recommendation, settles open trades against later
prices, and produces the win/loss record that is fed into the next run."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .models import Bar, Recommendation
from .config import RiskRules

SCHEMA = """
create table if not exists recommendations (
    id integer primary key autoincrement,
    run_date text not null,
    created_at text not null,
    action text not null,
    ticker text,
    entry_price real,
    stop_pct real,
    target_pct real,
    stop_loss real,
    target real,
    confidence real,
    rationale text,
    risk_notes text,
    unverified text,
    status text not null default 'open',
    exit_date text,
    exit_price real,
    outcome text,
    return_pct real
)
"""


class Ledger:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def record(self, rec: Recommendation) -> int:
        cur = self._db.execute(
            """insert into recommendations
               (run_date, created_at, action, ticker, entry_price, stop_pct, target_pct,
                stop_loss, target, confidence, rationale, risk_notes, unverified)
               values (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec.run_date.isoformat(), datetime.now().isoformat(timespec="seconds"),
             rec.action, rec.ticker, rec.entry_price, rec.stop_pct, rec.target_pct,
             rec.stop_loss, rec.target, rec.confidence, rec.rationale,
             json.dumps(rec.risk_notes), json.dumps(rec.unverified)))
        self._db.commit()
        return int(cur.lastrowid)

    def open_trades(self) -> list[dict]:
        rows = self._db.execute(
            "select * from recommendations where action='BUY' and status='open' "
            "order by run_date, id").fetchall()
        return [dict(r) for r in rows]

    def settle(self, trade_id: int, exit_date: date, exit_price: float,
               outcome: str, return_pct: float) -> None:
        self._db.execute(
            """update recommendations set status='closed', exit_date=?, exit_price=?,
               outcome=?, return_pct=? where id=?""",
            (exit_date.isoformat(), exit_price, outcome, return_pct, trade_id))
        self._db.commit()

    def recent(self, n: int = 10) -> list[dict]:
        rows = self._db.execute(
            "select * from recommendations order by run_date desc, id desc limit ?",
            (n,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Track record used by the portfolio manager and printed by `stats`."""
        closed = self._db.execute(
            "select return_pct, outcome from recommendations "
            "where action='BUY' and status='closed'").fetchall()
        returns = [r["return_pct"] for r in closed]
        wins = sum(1 for x in returns if x > 0)
        no_trade_days = self._db.execute(
            "select count(*) from recommendations where action='NO_TRADE'").fetchone()[0]
        open_count = len(self.open_trades())
        return {
            "closed_trades": len(returns),
            "wins": wins,
            "losses": len(returns) - wins,
            "win_rate_pct": round(100 * wins / len(returns), 1) if returns else None,
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
            "open_trades": open_count,
            "no_trade_days": no_trade_days,
        }


def settle_open_trades(ledger: Ledger, fetch_bars: Callable[[str], list[Bar]],
                       rules: RiskRules, today: date) -> list[dict]:
    """Checks each open trade against bars after its run date.

    Rules, applied bar by bar in order:
      * if the bar opens at or below the stop, exit at that open; otherwise if
        the low reaches the stop, exit at the stop (stop-first when both are hit)
      * if the bar opens at or above the target, exit at that open; otherwise if
        the high reaches the target, exit at the target
      * if the trade is still open after max_hold_trading_days bars, exit at the close
    """
    settled: list[dict] = []
    for t in ledger.open_trades():
        run_date = date.fromisoformat(t["run_date"])
        bars = [b for b in fetch_bars(t["ticker"]) if b.day > run_date and b.day <= today]
        entry, stop, target = t["entry_price"], t["stop_loss"], t["target"]
        for i, b in enumerate(bars, start=1):
            if b.open <= stop:
                exit_px, outcome = b.open, "STOP"
            elif b.low <= stop:
                exit_px, outcome = stop, "STOP"
            elif b.open >= target:
                exit_px, outcome = b.open, "TARGET"
            elif b.high >= target:
                exit_px, outcome = target, "TARGET"
            elif i >= rules.max_hold_trading_days:
                exit_px, outcome = b.close, "TIMEOUT"
            else:
                continue
            ret = round((exit_px / entry - 1) * 100, 2)
            ledger.settle(t["id"], b.day, exit_px, outcome, ret)
            settled.append({"id": t["id"], "ticker": t["ticker"], "outcome": outcome,
                            "exit_date": b.day.isoformat(), "return_pct": ret})
            break
    return settled
