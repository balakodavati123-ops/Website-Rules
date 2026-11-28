"""Phone alerts through ntfy.sh: free, no account. Set NTFY_TOPIC to a long random name, install the ntfy app, subscribe to that name.
Anyone who knows the topic name can read the alerts, so keep it private. Nothing here places an order."""
from __future__ import annotations

import os
import urllib.request


def push(title: str, body: str, priority: int = 3, tags: str = "", links: list[tuple[str, str]] | None = None) -> bool:
    """links: up to three (label, url) buttons on the alert, e.g. Approve / Reject (they open the URL; nothing is approved by the tap alone)."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    try:
        h = {"Title": title.encode("ascii", "ignore").decode(), "Priority": str(priority), "User-Agent": "desk/1.0"}
        if tags:
            h["Tags"] = tags
        if links:
            h["Actions"] = "; ".join(f"view, {lab}, {url}, clear=true" for lab, url in links[:3])
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), headers=h, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception:
        return False


def ticket(t: dict) -> tuple[str, str]:
    """A trade as a ticket you can key into the Upstox app yourself: what to buy or sell, how many, at what price, where the stop is."""
    if t["desk"] == "FNO":
        u, hz = t.get("underlying", "NIFTY"), t.get("horizon", "daily")
        legs = "\n".join(f"{'SELL' if l['side'] == 'S' else 'BUY'} {u} {l['strike']} {l['kind']} @ {l['entry']}" for l in (t.get("legs") or []))
        hold = "Held position: keep it until the target, stop or expiry rule fires; the exit alert tells you when." if hz in ("weekly", "monthly") else "Intraday: flat by 15:15."
        return f"F&O {hz}: {t['label']}", f"{legs}\nLot {t.get('lot')} x {t.get('qty')}. Max loss {t.get('max_loss_rs') or 'see margin'}, margin {t.get('margin_rs')}.\n{hold}\n{t.get('reason', '')}"
    side = "SELL (short, intraday)" if t["side"] == "SHORT" else "BUY"
    if t.get("horizon") == "scalp":
        return f"SCALP {side}: {t['label'].rsplit(' ', 1)[0]}", f"Qty {t['qty']} at about {t['entry']}, product INTRADAY. Stop-loss {t.get('stop')}, target {t.get('target_px')}. Out within {t.get('hold_min')} minutes at the latest.\n{t.get('reason', '')}"
    return f"{side}: {t['label'].rsplit(' ', 1)[0]}", f"Qty {t['qty']} at about {t['entry']} (use a limit order a hair through the market). Stop {t.get('stop')}. Exit by 15:10.\n{t.get('reason', '')}"
