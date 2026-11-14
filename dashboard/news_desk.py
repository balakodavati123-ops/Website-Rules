"""News desk paper book: instant intraday paper trades on market-moving headlines.

Stocks (long or short, intraday: a cash-market short must be closed the same day) and index or
stock options (buy a call for a long lean, a put for a short lean). Prices are the INDmoney live
quote or option-chain quote the operator passes in. Every trade is closed the same afternoon
(about 15:10) at the live quote then. Stocks: Rs 8,000 notional, stop 1% from entry, cost 0.1%
round trip. Options: one lot if its premium cost is under Rs 12,000, stop -30% of premium, cost
Rs 80 round trip. A Rs 32,000 pool; nothing is placed with a broker.

  python dashboard/news_desk.py book stock SYMBOL LONG|SHORT PRICE "headline"
  python dashboard/news_desk.py book option SYMBOL LONG|SHORT STRIKE CE|PE PREMIUM LOT EXPIRY "headline"
  python dashboard/news_desk.py close ID PRICE            # price of the stock, or the option premium
  python dashboard/news_desk.py open                      # list open trades
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LED = Path(__file__).resolve().parent / "data" / "news_ledger.json"
IST = timezone(timedelta(hours=5, minutes=30))
STOCK_NOTIONAL, OPT_MAX_COST, STOCK_COST, OPT_COST = 8000.0, 12000.0, 0.001, 80.0


def load():
    return json.loads(LED.read_text()) if LED.exists() else []


def save(rows):
    LED.parent.mkdir(parents=True, exist_ok=True)
    LED.write_text(json.dumps(rows, indent=1))


def book(kind, symbol, side, headline, **k):
    rows = load()
    now = datetime.now(IST)
    r = {"id": max([x["id"] for x in rows], default=0) + 1, "day": now.date().isoformat(), "time": now.strftime("%H:%M"), "kind": kind, "symbol": symbol,
         "side": side, "headline": headline[:160], "status": "OPEN", "exit": "", "pnl_rs": 0, "closed": ""}
    if kind == "stock":
        p = float(k["price"])
        r.update(entry=p, qty=int(STOCK_NOTIONAL // p), stop=round(p * (0.99 if side == "LONG" else 1.01), 2), label=f"{symbol} {side.lower()} (intraday)")
        if r["qty"] < 1:
            raise SystemExit("one share costs more than the trade size")
    else:
        prem, lot = float(k["premium"]), int(k["lot"])
        if prem * lot > OPT_MAX_COST:
            raise SystemExit(f"one lot costs Rs {prem * lot:,.0f}, above the Rs {OPT_MAX_COST:,.0f} cap")
        r.update(entry=prem, qty=lot, stop=round(prem * 0.7, 2), strike=k["strike"], opt=k["opt"], expiry=k["expiry"],
                 label=f"{symbol} {k['strike']} {k['opt']} buy ({'call' if k['opt'] == 'CE' else 'put'})")
    rows.append(r)
    save(rows)
    print("booked", r["id"], r["label"], "entry", r["entry"], "qty", r["qty"], "stop", r["stop"])


def close(i, price):
    rows = load()
    r = next(x for x in rows if x["id"] == i and x["status"] == "OPEN")
    price = float(price)
    if r["kind"] == "stock":
        move = price - r["entry"] if r["side"] == "LONG" else r["entry"] - price
        pnl = move * r["qty"] - STOCK_COST * r["entry"] * r["qty"]
    else:
        pnl = (price - r["entry"]) * r["qty"] - OPT_COST
    r.update(exit=price, pnl_rs=round(pnl, 2), status="WIN" if pnl > 0 else "LOSS", closed=datetime.now(IST).strftime("%H:%M"))
    save(rows)
    print("closed", i, r["label"], r["status"], r["pnl_rs"])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "book" and a[1] == "stock":
        book("stock", a[2], a[3], a[5], price=a[4])
    elif a[0] == "book":
        book("option", a[2], a[3], a[9], strike=a[4], opt=a[5], premium=a[6], lot=a[7], expiry=a[8])
    elif a[0] == "close":
        close(int(a[1]), a[2])
    else:
        print([f"{r['id']} {r['label']} entry {r['entry']}" for r in load() if r["status"] == "OPEN"])
