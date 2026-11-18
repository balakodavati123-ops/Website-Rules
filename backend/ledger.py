"""One ledger. Every desk's trades, plus the daily swing, F&O and signal books, mapped to a single shape so the page,
the scoreboard and the learning loop all read the same list. Nothing here places an order."""
from __future__ import annotations

CLOSED_OTHER = ("TIME STOP", "SIDEWAYS_EXIT", "SIDEWAYS EXIT")


def _status(s: str, pnl: float) -> str:
    return s if s in ("OPEN", "PENDING", "WIN", "LOSS") else ("WIN" if pnl > 0 else "LOSS") if s in CLOSED_OTHER else s


def swing(rows: list[dict]) -> list[dict]:
    """The daily swing strategies (paper_ledger.json): signal at a close, fill at the next open."""
    out = []
    for r in rows:
        if r.get("status") == "SKIPPED":
            continue
        closed = r["status"] not in ("OPEN", "PENDING")
        pnl = float(r.get("pnl_rs") or 0) if closed else float(r.get("unrealized_rs") or 0)
        last = float(r.get("exit") or 0) if closed and r.get("exit") not in ("", None) else r.get("last_close", r.get("entry"))
        out.append({"id": f"S{r['id']}", "desk": "EQUITY", "strategy": r["strategy"], "label": f"{r['symbol']} long", "symbol": r["symbol"], "side": "LONG", "entry": r.get("entry") or r.get("signal_close"),
                    "last": last, "exit": r.get("exit", ""), "qty": r.get("qty", ""), "stop": r.get("stop"), "target_px": r.get("target") or None, "status": _status(r["status"], pnl), "pnl_rs": round(pnl, 2),
                    "reason": r.get("note", ""), "why": "", "day": str(r.get("opened") or r["signal_date"]), "opened": "swing", "closed": str(r.get("closed") or ""), "risk_class": "Swing (daily bars)",
                    "margin_rs": round(float(r.get("entry") or 0) * float(r.get("qty") or 0)) if r.get("qty") != "" else None})
    return out


def weekly_fno(rows: list[dict]) -> list[dict]:
    """The weekly NIFTY structures booked from the option chain and held to expiry (fo_ledger.json)."""
    out = []
    for r in rows:
        pnl = float(r.get("pnl_rs") or 0) if r["status"] != "OPEN" else 0.0
        out.append({"id": f"W{r['id']}", "desk": "FNO", "strategy": "weekly_" + r["strategy"].replace("short_", ""), "label": f"NIFTY {r['strategy'].replace('_', ' ')} · {str(r['expiry'])[5:]}", "side": "SHORT",
                    "entry": round(float(r.get("credit_rs") or 0) / float(r.get("lot") or 1), 2), "last": "", "exit": "", "qty": 1, "status": _status(r["status"], pnl), "pnl_rs": pnl,
                    "reason": f"Booked from the NIFTY chain at {r.get('spot_at_booking', '')}; held to expiry {r['expiry']}.", "why": "expiry" if r["status"] != "OPEN" else "", "day": str(r["booked"]), "opened": "weekly",
                    "closed": "", "risk_class": "Fixed return · controlled loss", "margin_rs": r.get("max_loss_rs"), "max_gain_rs": r.get("max_gain_rs"), "max_loss_rs": r.get("max_loss_rs"), "legs": r.get("legs")})
    return out


def signals(rows: list[dict]) -> list[dict]:
    """The Rs 1,00,000 signal desk (signal_ledger.json)."""
    out = []
    for r in rows:
        closed = r["status"] not in ("OPEN", "PENDING")
        pnl = float(r.get("pnl_rs") or 0) if closed else float(r.get("unreal_rs") or 0)
        out.append({"id": f"G{r['id']}", "desk": "EQUITY", "strategy": "signal_desk", "label": f"{str(r['ticker']).replace('.NS', '')} long", "symbol": str(r["ticker"]).replace(".NS", ""), "side": "LONG", "entry": r.get("entry") or r.get("signal_close"),
                    "last": r.get("last_close", ""), "exit": r.get("exit", ""), "qty": r.get("qty", ""), "stop": r.get("stop"), "status": _status(r["status"], pnl), "pnl_rs": round(pnl, 2),
                    "reason": f"Conviction {r.get('conviction')}; {r.get('note', '')}", "why": "", "day": str(r.get("opened") or r["signal_date"]), "opened": "signal", "closed": str(r.get("closed") or ""),
                    "risk_class": "Signal desk (chart-gated)", "margin_rs": r.get("deploy_rs")})
    return out


def day_series(prev: dict, day: str, hms: str, trades: list[dict], nifty, every: int = 30) -> dict:
    """Append one point to today's profit-and-loss line: total and per desk, from trades opened today, plus Nifty."""
    if prev.get("day") != day:
        prev = {"day": day, "points": []}
    pts = prev["points"]
    if pts:
        h, m, s = (int(x) for x in hms.split(":"))
        a, b, c = (int(x) for x in pts[-1][0].split(":"))
        if (h * 3600 + m * 60 + s) - (a * 3600 + b * 60 + c) < every:
            return prev
    by = {"EQUITY": 0.0, "FNO": 0.0, "COMMODITY": 0.0, "CRYPTO": 0.0}
    for t in trades:
        if t["day"] == day and t["desk"] in by and t.get("opened") not in ("swing", "weekly", "signal") and t.get("horizon") not in ("weekly", "monthly"):
            by[t["desk"]] += float(t["pnl_rs"] or 0)
    pts.append([hms, round(sum(by.values()), 2), *(round(by[k], 2) for k in by), nifty])
    return prev
