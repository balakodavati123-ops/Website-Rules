"""Upstox read-only market data (Analytics token). One place for every call the desks make.

Quotes take 500 instruments per call, so all ~2,760 NSE equities come back in about 5 seconds.
The token only reads; it cannot place, change or cancel an order.
"""
from __future__ import annotations

import gzip
import json
import urllib.parse
import urllib.request

UA = "paper-desk/1.0"
_cache: dict = {}


def _get(url: str, token: str = "") -> bytes:
    h = {"Accept": "application/json", "User-Agent": UA}
    if token and token != "proxy-injected":       # in the build sandbox the network proxy adds the real header itself
        h["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60).read()


def instruments(exchange: str) -> list[dict]:
    if exchange not in _cache:
        _cache[exchange] = json.loads(gzip.decompress(_get(f"https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz")))
    return _cache[exchange]


def quotes(keys: list[str], token: str) -> dict[str, dict]:
    """{instrument_key: quote} with last_price, net_change, ohlc, volume, depth, oi."""
    out: dict[str, dict] = {}
    for i in range(0, len(keys), 500):
        q = urllib.parse.quote(",".join(keys[i:i + 500]), safe=",")
        data = json.loads(_get("https://api.upstox.com/v2/market-quote/quotes?instrument_key=" + q, token)).get("data", {})
        for v in data.values():
            out[v.get("instrument_token", "")] = v
    return out


def equity_rows(token: str) -> list[dict]:
    """Real-time snapshot of every NSE equity: price, change on the previous close, day high and low, volume."""
    keys = [x["instrument_key"] for x in instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"]
    rows = []
    for v in quotes(keys, token).values():
        last, net, oh = v.get("last_price"), v.get("net_change"), v.get("ohlc") or {}
        if not last or net is None or not v.get("volume") or last - net <= 0:
            continue
        rows.append({"symbol": v["symbol"], "price": float(last), "chg_pct": net / (last - net) * 100, "day_high": float(oh.get("high") or last),
                     "day_low": float(oh.get("low") or last), "volume": float(v["volume"])})
    return rows


def expiries(token: str, underlying_key: str) -> list[str]:
    if ("exp", underlying_key) not in _cache:
        d = json.loads(_get("https://api.upstox.com/v2/option/contract?instrument_key=" + urllib.parse.quote(underlying_key, safe=""), token)).get("data", [])
        _cache[("exp", underlying_key)] = sorted({x["expiry"] for x in d}), {x["expiry"]: x.get("lot_size") for x in d}
    return _cache[("exp", underlying_key)][0]


def lot_size(underlying_key: str, expiry: str) -> int:
    return int(_cache[("exp", underlying_key)][1].get(expiry) or 0)


def option_chain(token: str, underlying_key: str, expiry: str) -> list[dict]:
    q = f"instrument_key={urllib.parse.quote(underlying_key, safe='')}&expiry_date={expiry}"
    return json.loads(_get("https://api.upstox.com/v2/option/chain?" + q, token)).get("data", [])
