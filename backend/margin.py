"""Viability: what a trade really costs to hold, from the broker's own margin calculator, never from a guess.

A paper trade is only worth learning from if a retail account could carry it. This asks Upstox for the margin of the exact legs and
quantity (hedge benefit included when the legs are sent together) and caches the answer for ten minutes. If the calculator cannot be
reached the trade is not taken: we never trade on a margin we could not check.
"""
from __future__ import annotations

import time

import upstox as U

TTL = 600


class Margin:
    def __init__(self, token: str, fn=None):
        self.token, self.fn, self.cache, self.log = token, fn or U.margin_calc, {}, {}

    def basket(self, legs: list[tuple]) -> dict | None:
        """legs: [(instrument_key, quantity, 'BUY'|'SELL')] -> {'final','required','legs'} or None when it cannot be checked."""
        key = tuple(sorted(legs))
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
        try:
            out = self.fn(self.token, list(legs))
        except Exception:
            return None
        self.cache[key] = (time.time(), out)
        return out

    def final(self, legs: list[tuple]) -> float | None:
        m = self.basket(legs)
        return round(m["final"]) if m else None

    def skip(self, desk: str, what: str, need: float | None, room: float, why: str, now) -> None:
        """Remember a trade the desk wanted but could not afford or verify, so the page can show it."""
        self.log[f"{desk}|{what}"] = {"desk": desk, "what": what, "margin": need, "room": round(room), "why": why, "at": now.strftime("%H:%M:%S"), "day": now.strftime("%Y-%m-%d")}
