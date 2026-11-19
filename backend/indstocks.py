"""INDstocks (INDmoney) API client, written from the published reference at https://api-docs.indstocks.com/.

Reads (profile, funds, quotes, margin, order book, positions) work from any address. Placing, modifying and cancelling orders needs the
caller's public IP to be whitelisted on the INDstocks dashboard (a static IP), so orders can only be sent from a host that has one.
The token is the raw value in the `Authorization` header (no "Bearer"), valid for 24 hours. Nothing here is called unless the gateway
is asked to; every function returns {"ok", "code", "data", "error"} and never raises on a bad response.
"""
from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.indstocks.com"
UA = "paper-desk/1.0"


def _http(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                                           # network down, DNS, timeout
        return 0, json.dumps({"message": str(e)[:200]}).encode()


class Client:
    def __init__(self, token: str, transport=None, base: str = BASE):
        self.token, self.base, self._t = (token or "").strip(), base.rstrip("/"), transport or _http

    def call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = self.base + path + (("?" + urllib.parse.urlencode(params, safe=",")) if params else "")
        h = {"Authorization": self.token, "Accept": "application/json", "User-Agent": UA}
        data = None
        if body is not None:                                         # a few GET endpoints (margin, order details) read a JSON body
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        code, raw = self._t(method, url, h, data)
        try:
            j = json.loads(raw) if raw else {}
        except Exception:
            j = {"message": raw[:200].decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)[:200]}
        ok = 200 <= code < 300 and (j.get("status") == "success" or j.get("success") is True)
        err = None if ok else (j.get("message") or j.get("debug_info") or j.get("error") or f"HTTP {code}")
        return {"ok": ok, "code": code, "data": j.get("data") if isinstance(j, dict) else None, "error": err, "raw": j}

    # ---- reads (no static IP needed)
    def profile(self) -> dict: return self.call("GET", "/user/profile")
    def funds(self) -> dict: return self.call("GET", "/funds")
    def ltp(self, codes: list[str]) -> dict: return self.call("GET", "/market/quotes/ltp", {"scrip-codes": ",".join(codes)})
    def quotes(self, codes: list[str]) -> dict: return self.call("GET", "/market/quotes/full", {"scrip-codes": ",".join(codes)})
    def order_book(self) -> dict: return self.call("GET", "/order-book")
    def order_details(self, order_id: str, segment: str = "EQUITY") -> dict: return self.call("GET", "/order", body={"order_id": order_id, "segment": segment})
    def positions(self, segment: str = "equity", product: str = "intraday") -> dict: return self.call("GET", "/portfolio/positions", {"segment": segment, "product": product})

    def margin(self, security_id: str, txn: str, qty: int, price: float, product: str = "INTRADAY", segment: str = "EQUITY", exchange: str = "NSE") -> dict:
        """Margin and charges for one order, before it is sent. Strings, as the reference shows."""
        return self.call("GET", "/margin", body={"segment": segment, "exchange": exchange, "securityID": str(security_id), "txnType": txn, "quantity": str(int(qty)), "price": str(price), "product": product})

    def instruments(self, source: str = "equity") -> str:
        """The instrument master as CSV text ('' on failure)."""
        h = {"Authorization": self.token, "User-Agent": UA}
        code, raw = self._t("GET", f"{self.base}/market/instruments?source={source}", h, None)
        return raw.decode("utf-8", "replace") if code == 200 else ""

    # ---- orders (need the whitelisted static IP)
    def smart_order(self, payload: dict) -> dict: return self.call("POST", "/smart/order", body=payload)
    def order(self, payload: dict) -> dict: return self.call("POST", "/order", body=payload)

    def cancel(self, order_id: str, segment: str = "EQUITY", smart: bool = False) -> dict:
        return self.call("POST", "/smart/order/cancel" if smart else "/order/cancel", body={"order_id": order_id, "segment": segment})


class Master:
    """Cash-market instruments from the master CSV: symbol -> {id, tick, freeze, lot, leverage, upper, lower}."""

    def __init__(self, text: str = ""):
        self.by: dict = {}
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("EXCH") == "NSE" and r.get("SERIES", "EQ") in ("EQ", "") and r.get("TRADING_SYMBOL"):
                f = lambda k, d=0.0: float(r.get(k) or d) if str(r.get(k) or "").replace(".", "", 1).replace("-", "", 1).isdigit() else d
                self.by[r["TRADING_SYMBOL"]] = {"id": r["SECURITY_ID"], "tick": f("TICK_SIZE", 0.05) or 0.05, "freeze": int(f("FREEZE_QTY")), "lot": int(f("LOT_UNITS", 1)) or 1,
                                                 "leverage": f("INTRADAY_LEVERAGE", 1) or 1, "upper": f("UPPER_LIMIT"), "lower": f("LOWER_LIMIT")}

    def get(self, symbol: str) -> dict | None:
        return self.by.get(symbol)

    def __len__(self) -> int:
        return len(self.by)
