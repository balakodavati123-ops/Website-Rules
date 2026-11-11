"""Context board from INDmoney's market-mover lists.

Movers are used for context and sanity checks, not as entry signals: the spike study
found that by the time a stock shows on a gainers list, most of the move is made.
"""
from __future__ import annotations

import json

MIN_TRADED_CR = 5.0       # price x volume so far today, Rs crore
LATE_PCT = 15.0           # already up this much: do not chase
STUCK_AT_CIRCUIT = 0.995  # price this close to a circuit limit cannot be bought or sold freely


def parse(payload) -> tuple[str, list[dict]]:
    """Accepts the raw tool output ({"result": "<json>"}), the inner JSON string, or a dict."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, dict) and isinstance(payload.get("result"), str):
        payload = json.loads(payload["result"])
    return payload.get("category", "movers"), list(payload.get("stocks", []))


def tag(stock: dict) -> list[str]:
    tags = []
    price, vol = stock.get("price") or 0, stock.get("volume") or 0
    traded = price * vol / 1e7
    chg = stock.get("change_pct") or 0
    upper, lower = stock.get("circuit_upper_limit"), stock.get("circuit_lower_limit")
    if upper and price >= STUCK_AT_CIRCUIT * upper:
        tags.append("AT UPPER CIRCUIT")
    if lower and price <= lower / STUCK_AT_CIRCUIT:
        tags.append("AT LOWER CIRCUIT")
    if traded < MIN_TRADED_CR:
        tags.append("THIN")
    if chg >= LATE_PCT:
        tags.append("LATE, do not chase")
    return tags


def render_board(boards: dict[str, list[dict]], top: int = 8) -> str:
    lines = []
    for category, stocks in boards.items():
        lines.append(f"-- {category} --")
        for s in stocks[:top]:
            traded = (s.get("price") or 0) * (s.get("volume") or 0) / 1e7
            tags = tag(s)
            lines.append(f"  {s.get('symbol', '?'):<12} {s.get('price', 0):>9.2f} "
                         f"{s.get('change_pct', 0):>+6.1f}%  traded Rs {traded:>7.1f} cr  "
                         f"{s.get('market_cap_category', ''):<9} {', '.join(tags)}")
    return "\n".join(lines)


def warnings_for(ticker: str, boards: dict[str, list[dict]]) -> list[str]:
    """Sanity checks on a recommended ticker against today's lists."""
    out = []
    for category, stocks in boards.items():
        for s in stocks:
            if s.get("symbol", "").upper() != ticker.upper():
                continue
            if category in ("top-losers", "lower-circuit-stocks", "52-week-low"):
                out.append(f"{ticker} is on today's {category} list: check why before buying")
            if category in ("upper-circuit-stocks",) or "AT UPPER CIRCUIT" in tag(s):
                out.append(f"{ticker} is at its upper circuit: you may not be able to buy")
            if (s.get("change_pct") or 0) >= LATE_PCT:
                out.append(f"{ticker} is already up {s['change_pct']:.1f}% today: do not chase")
    return out
