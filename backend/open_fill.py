"""Fill pending paper orders at today's real opening price instead of waiting for the next morning's daily bars.

A paper order is created at a close and should fill at the next open. The daily engine only sees finished daily
bars, so a fill used to appear a full day late. This reads today's open from Upstox (real time, after 09:16 IST)
and applies the same rules as dashboard/paper_engine.try_fill: skip a gap over 3%, size from the stop, cap open
risk. An order whose signal is older than the previous session is expired rather than filled late.

Usage: python backend/open_fill.py LEDGER.json [RULES.json]     (token from UPSTOX_TOKEN)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_engine as PE  # noqa: E402
import upstox as U         # noqa: E402


class _OpenProvider:
    def __init__(self, opens: dict, day: date, vix):
        self.opens, self.day, self._vix = opens, day, vix

    def daily(self, ysym: str):
        o = self.opens.get(ysym.replace(".NS", ""))
        idx = pd.DatetimeIndex([pd.Timestamp(self.day)]) if o else pd.DatetimeIndex([])
        return pd.DataFrame({"Open": [o] if o else []}, index=idx)

    def vix(self, day):
        return self._vix

    def fx(self):
        return 1.0


def previous_session(day: date) -> date:
    p = day - timedelta(days=1)
    while p.weekday() >= 5:
        p -= timedelta(days=1)
    return p


def fill_pending(ledger: list[dict], rules: list[dict], opens: dict, day: date, vix=None) -> int:
    """Fill or expire PENDING NSE orders in place. Returns how many rows changed."""
    prov, changed, prev = _OpenProvider(opens, day, vix), 0, previous_session(day)
    for row in sorted((r for r in ledger if r["status"] == "PENDING" and r["market"] == "NSE"), key=lambda r: r["id"]):
        if PE.d(row["signal_date"]) < prev:
            row.update(status="SKIPPED", note=f"Expired: no fill price for the session after the {row['signal_date']} signal.")
            changed += 1
        elif PE.d(row["signal_date"]) < day:
            before = row["status"]
            PE.try_fill(row, ledger, rules, prov)
            changed += row["status"] != before
    return changed


def main() -> None:
    ledger_path = Path(sys.argv[1])
    import daily as DLY
    rules = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else DLY.RULES
    ledger = json.loads(ledger_path.read_text())
    token, day = os.environ.get("UPSTOX_TOKEN", ""), datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    want = {r["symbol"] for r in ledger if r["status"] == "PENDING" and r["market"] == "NSE"}
    keys = {x["trading_symbol"]: x["instrument_key"] for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ" and x["trading_symbol"] in want}
    q = U.quotes(list(keys.values()) + ["NSE_INDEX|India VIX"], token)
    opens = {s: float((q.get(k, {}).get("ohlc") or {}).get("open") or 0) or None for s, k in keys.items()}
    vix = (q.get("NSE_INDEX|India VIX") or {}).get("last_price")
    n = fill_pending(ledger, rules, opens, day, vix)
    ledger_path.write_text(json.dumps(ledger, indent=1))
    print(f"{n} orders changed;", {r["symbol"] + "/" + r["strategy"][:8]: r["status"] for r in ledger if r["id"] in {x["id"] for x in ledger if x["status"] in ("OPEN", "SKIPPED") and x.get("opened") == str(day)}})


if __name__ == "__main__":
    main()
