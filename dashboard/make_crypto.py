"""Crypto quotes and candles from free public sources that work in India.

  CoinDCX (Indian exchange)  rupee prices, 24-hour change, candles. No account needed.
  Kraken                     dollar prices, used as an independent cross-check.
  Yahoo Finance              USD/INR, to show how far the rupee price sits above the
                             global dollar price (the "India premium").

A quote is marked verified when the rupee price, turned into dollars at CoinDCX's own
USDT/INR rate, is within 2% of Kraken's dollar price. Otherwise it is single-source.
Writes dashboard/data/crypto_quotes.json and dashboard/data/crypto_candles.json.

Usage: python dashboard/make_crypto.py
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data"
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (research script)"}
COINS = [  # symbol, name, CoinDCX ticker market, CoinDCX candle pair, Kraken pair
    ("BTC", "Bitcoin", "BTCINR", "I-BTC_INR", "XBTUSD"),
    ("ETH", "Ethereum", "ETHINR", "I-ETH_INR", "ETHUSD"),
    ("SOL", "Solana", "SOLINR", "I-SOL_INR", "SOLUSD"),
]
FRAMES = [("1d", "1d"), ("1h", "1h"), ("15m", "15m")]
CANDLES = 160


def get(url: str, timeout: int = 25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


def candle_rows(symbol: str, tf: str, raw: list[dict]) -> list[dict]:
    """CoinDCX returns newest first; rows go out oldest first with UTC times."""
    rows = []
    for c in sorted(raw, key=lambda x: x["time"])[-CANDLES:]:
        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        if min(o, h, l, cl) <= 0 or h < l:
            continue
        t = datetime.fromtimestamp(c["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append({"symbol": symbol, "tf": tf, "t": t, "o": o, "h": h, "l": l, "c": cl, "v": float(c["volume"])})
    return rows


def quote_row(symbol, name, tick, usdt_inr, usd_price, usd_inr, spark, now) -> dict:
    price = float(tick["last_price"])
    implied_usd = price / usdt_inr if usdt_inr else None
    verified = bool(usd_price and implied_usd and abs(implied_usd / usd_price - 1) <= 0.02)
    premium = round((price / (usd_price * usd_inr) - 1) * 100, 1) if usd_price and usd_inr else None
    return {"symbol": symbol, "name": name, "price_inr": price, "chg_24h_pct": round(float(tick["change_24_hour"]), 2),
            "high_inr": float(tick["high"]), "low_inr": float(tick["low"]),
            "price_usd": round(usd_price, 2) if usd_price else None, "premium_pct": premium,
            "spark": json.dumps(spark), "as_of": now.isoformat(timespec="seconds"), "as_of_hm": now.strftime("%d %b %H:%M"),
            "source": "CoinDCX" + (", Kraken" if usd_price else ""), "verified": "yes" if verified else "single source"}


def kraken_prices() -> dict[str, float]:
    try:
        res = get("https://api.kraken.com/0/public/Ticker?pair=" + ",".join(c[4] for c in COINS))["result"]
    except Exception:
        return {}
    out = {}
    for key, v in res.items():
        for sym, _, _, _, _pair in COINS:
            if ("XBT" if sym == "BTC" else sym) in key:
                out[sym] = float(v["c"][0])
    return out


def usd_inr() -> float | None:
    try:
        import yfinance as yf
        return float(yf.Ticker("INR=X").history(period="5d").Close.iloc[-1])
    except Exception:
        return None


def main():
    now = datetime.now(IST)
    ticker = {t["market"]: t for t in get("https://api.coindcx.com/exchange/ticker")}
    usdt = float(ticker["USDTINR"]["last_price"]) if "USDTINR" in ticker else None
    kr, fx = kraken_prices(), usd_inr()
    quotes, candles = [], []
    for sym, name, market, pair, _ in COINS:
        per_tf = {}
        for tf, interval in FRAMES:
            raw = get(f"https://public.coindcx.com/market_data/candles?pair={pair}&interval={interval}&limit={CANDLES}")
            per_tf[tf] = candle_rows(sym, tf, raw)
            candles += per_tf[tf]
        spark = [r["c"] for r in per_tf["1h"][-24:]]
        quotes.append(quote_row(sym, name, ticker[market], usdt, kr.get(sym), fx, spark, now))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "crypto_quotes.json").write_text(json.dumps(quotes, indent=1))
    (OUT / "crypto_candles.json").write_text(json.dumps(candles))
    for q in quotes:
        print(f"{q['symbol']}: Rs {q['price_inr']:,.0f} ({q['chg_24h_pct']:+.2f}%), ${q['price_usd']}, "
              f"premium {q['premium_pct']}%, {q['verified']}")
    print(f"{len(candles)} candles, as of {quotes[0]['as_of_hm']} IST")


if __name__ == "__main__":
    main()
