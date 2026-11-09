"""The analyst, debate and portfolio-manager agents.

Each agent is one LLM call with a fixed system prompt. Every agent is told to
use only numbers from the context and to report UNVERIFIED data as unverified.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .llm import LLM, LLMFormatError, parse_json_object
from .models import Snapshot

GROUNDING = (
    "Use only the numbers and facts in the context JSON. If an item is missing or "
    "marked UNVERIFIED, say so; do not estimate or fill it in from memory. "
    "This is a research input, not a guarantee. "
)

ANALYST_PROMPTS = {
    "technical": (
        "You are the technical analyst. Assess trend, support and resistance, "
        "RSI(14), MACD and volatility from the technicals block. "
    ),
    "fundamentals": (
        "You are the fundamentals analyst. Assess earnings growth, valuation "
        "(P/E, P/B) and balance-sheet strength from the fundamentals block. "
    ),
    "sentiment": (
        "You are the news and sentiment analyst. Assess headlines and market "
        "flows (FII/DII) from the news and flows blocks. If they are unverified, "
        "return neutral. "
    ),
}

ANALYST_REPLY = (
    'Reply with only a JSON object: {"signal": "bullish|bearish|neutral", '
    '"summary": "<two sentences>", "key_points": ["<point>", ...]}.'
)

BULL_SYSTEM = (
    "You are the BULL researcher. Make the strongest honest case for buying this "
    "stock over the next 1 to 3 months, using the analyst reports. Name the "
    "catalysts and what would prove you right. Keep it under 150 words."
)
BEAR_SYSTEM = (
    "You are the BEAR researcher. Make the strongest honest case against buying "
    "this stock over the next 1 to 3 months, using the analyst reports. Name the "
    "risks and what would prove you right. Keep it under 150 words."
)

PM_SYSTEM = (
    "You are the PORTFOLIO MANAGER. You see one case file per candidate: analyst "
    "reports, a bull and a bear argument, and the team's track record. Choose AT "
    "MOST ONE idea for today, or choose NO_TRADE. Choosing NO_TRADE is normal and "
    "expected when the evidence is weak or mixed. Propose a stop-loss percentage "
    "(3 to 5) and a target percentage (15 to 30); the risk manager may adjust them. "
    'Reply with only a JSON object: {"action": "BUY" or "NO_TRADE", "ticker": '
    '"<one candidate ticker or null>", "stop_pct": <number or null>, "target_pct": '
    '<number or null>, "confidence": <0 to 1>, "rationale": "<three sentences max>"}. '
    + GROUNDING
)


def build_context(snap: Snapshot, technicals: dict | None,
                  market: dict[str, Any]) -> dict:
    """The JSON context every agent reads. Unverified items are labelled."""
    def val(point):
        if point is None:
            return "UNVERIFIED"
        if not point.verified:
            return f"UNVERIFIED{' (' + point.note + ')' if point.note else ''}"
        return point.value

    fundamentals = {k: val(p) for k, p in snap.points.items()
                    if k in ("trailingPE", "forwardPE", "priceToBook", "trailingEps",
                             "returnOnEquity", "debtToEquity", "earningsGrowth",
                             "revenueGrowth", "marketCap")}
    return {
        "ticker": snap.ticker,
        "as_of": snap.as_of.isoformat(),
        "technicals": technicals if technicals else "UNVERIFIED (price history unavailable)",
        "fundamentals": fundamentals,
        "flows": val(snap.points.get("fii_dii_flows")),
        "news": val(snap.points.get("news")),
        "market": {k: val(p) for k, p in market.items()},
        "unverified_items": snap.unverified_items(),
    }


@dataclass
class CaseFile:
    ticker: str
    score: float
    context: dict
    analysts: dict[str, dict] = field(default_factory=dict)
    bull: str = ""
    bear: str = ""


def run_analyst(llm: LLM, name: str, context: dict) -> dict:
    system = ANALYST_PROMPTS[name] + GROUNDING + ANALYST_REPLY
    text = llm.complete(system, json.dumps(context, default=str), max_tokens=700)
    try:
        out = parse_json_object(text)
    except LLMFormatError:
        return {"signal": "neutral", "summary": "analyst reply could not be parsed",
                "key_points": []}
    out.setdefault("signal", "neutral")
    out.setdefault("summary", "")
    out.setdefault("key_points", [])
    return out


def run_debate(llm: LLM, context: dict, analysts: dict[str, dict]) -> tuple[str, str]:
    user = json.dumps({"context": context, "analyst_reports": analysts}, default=str)
    bull = llm.complete(BULL_SYSTEM + GROUNDING, user, max_tokens=400)
    bear = llm.complete(BEAR_SYSTEM + GROUNDING, user, max_tokens=400)
    return bull.strip(), bear.strip()


def run_portfolio_manager(llm: LLM, cases: list[CaseFile],
                          track_record: dict) -> dict:
    payload = {
        "track_record": track_record,
        "candidates": [
            {"ticker": c.ticker, "screen_score": c.score, "analysts": c.analysts,
             "bull": c.bull, "bear": c.bear, "context": c.context}
            for c in cases
        ],
    }
    text = llm.complete(PM_SYSTEM, json.dumps(payload, default=str), max_tokens=600)
    try:
        return parse_json_object(text)
    except LLMFormatError:
        return {"action": "NO_TRADE", "ticker": None, "rationale":
                "portfolio manager reply could not be parsed; staying in cash"}
