"""NSE index-option charges for one straddle round trip (2 legs bought, 2 legs sold = 4 orders), October 2024 schedule.

Brokerage Rs 20 an executed order; STT 0.1% of the sell-side premium; NSE transaction charge 0.03503% of premium turnover; SEBI fee Rs 10 a
crore (0.0001%); stamp duty 0.003% of the buy-side premium; GST 18% on brokerage, transaction and SEBI charges. Slippage is separate and
applied to the prices themselves (see straddle_engine.Config.slip).
"""
from __future__ import annotations


def charges(buy_value: float, sell_value: float, orders: int = 4, brokerage: float = 20.0) -> dict:
    brok = brokerage * orders
    txn = 0.0003503 * (buy_value + sell_value)
    sebi = 0.000001 * (buy_value + sell_value)
    stt = 0.001 * sell_value
    stamp = 0.00003 * buy_value
    gst = 0.18 * (brok + txn + sebi)
    total = brok + txn + sebi + stt + stamp + gst
    return {"brokerage": round(brok, 2), "stt": round(stt, 2), "txn": round(txn, 2), "sebi": round(sebi, 2), "stamp": round(stamp, 2), "gst": round(gst, 2), "total": round(total, 2)}
