"""Your broker account, read-only: wallet (funds and margin), holdings and today's positions from Upstox, for the dashboard's Overview.

Needs an Upstox trading access token in the UPSTOX_EXEC_TOKEN secret (the read-only Analytics token cannot see an account). Upstox
access tokens expire every day at 03:30 IST, so the connection shows "not connected" until a fresh token is saved. Nothing here can place,
change or cancel an order: it only calls GET endpoints.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "https://api.upstox.com/v2"


def _get(path: str, token: str, opener=urllib.request.urlopen) -> dict:
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "paper-desk/1.0"})
    return json.loads(opener(req, timeout=20).read())


def snapshot(token: str, now_iso: str, opener=urllib.request.urlopen) -> dict:
    if not token:
        return {"ok": False, "at": now_iso, "reason": "no broker token"}
    try:
        f = (_get("/user/get-funds-and-margin?segment=SEC", token, opener).get("data") or {}).get("equity") or {}
        h = _get("/portfolio/long-term-holdings", token, opener).get("data") or []
        p = _get("/portfolio/short-term-positions", token, opener).get("data") or []
    except urllib.error.HTTPError as e:
        return {"ok": False, "at": now_iso, "reason": "token expired or not valid" if e.code in (401, 403) else f"broker error {e.code}"}
    except Exception as e:                                                 # network and anything else: show it, never stop the engine
        return {"ok": False, "at": now_iso, "reason": str(e)[:80]}
    hold = [{"symbol": x.get("tradingsymbol"), "qty": x.get("quantity"), "avg": x.get("average_price"), "ltp": x.get("last_price"), "pnl": x.get("pnl"),
             "value": round((x.get("last_price") or 0) * (x.get("quantity") or 0), 2), "day_change_pct": x.get("day_change_percentage")} for x in h]
    pos = [{"symbol": x.get("tradingsymbol"), "qty": x.get("quantity"), "avg": x.get("average_price"), "ltp": x.get("last_price"), "pnl": x.get("pnl"),
            "product": x.get("product"), "exchange": x.get("exchange")} for x in p]
    return {"ok": True, "at": now_iso, "broker": "Upstox",
            "wallet": {"available": f.get("available_margin"), "used": f.get("used_margin"), "payin": f.get("payin_amount")},
            "holdings": hold, "positions": pos, "holdings_value": round(sum(x["value"] for x in hold), 2), "holdings_pnl": round(sum(x["pnl"] or 0 for x in hold), 2),
            "positions_pnl": round(sum(x["pnl"] or 0 for x in pos), 2)}
