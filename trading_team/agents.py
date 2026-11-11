"""The analyst, debate and portfolio-manager agents.

Each agent is one LLM call with a fixed system prompt. Every agent is told to
use only numbers from the context and to report UNVERIFIED data as unverified.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .guardrails import ungrounded_numbers
from .llm import LLM, LLMFormatError, parse_json_object
from .models import Snapshot

GROUNDING = (
    "Use only the numbers and facts in the context JSON. If an item is missing or "
    "marked UNVERIFIED, say so; do not estimate or fill it in from memory. "
    "Quote figures exactly as given. Do not calculate new figures (differences, "
    "ratios, averages, price levels); an automated check deletes any reply that "
    "contains a number not present in the context. "
    "This is a research input, not a guarantee. "
)

ANALYST_PROMPTS = {
    "technical": (
        "You are the technical analyst. Assess trend, support and resistance, "
        "RSI(14), MACD and volatility from the technicals block. "
    ),
    "fundamentals": (
        "You are the fundamentals analyst. Assess the latest quarter in the "
        "quarterly_results block (revenue and profit growth against the same "
        "quarter a year earlier, margin change, EPS against the estimate, days to "
        "the next result), then valuation (P/E, P/B) and balance-sheet strength "
        "from the fundamentals block. "
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
    "reports (including, where available, a concall report whose quotes were "
    "verified against the transcript), a bull and a bear argument, and the team's "
    "track record. Choose AT "
    "MOST ONE idea for today, or choose NO_TRADE. Choosing NO_TRADE is normal and "
    "expected when the evidence is weak or mixed. Base the decision on what is "
    "specific to today's candidates. Conditions that are the same every day are "
    "not reasons to pass, because position size and the risk manager already "
    "account for them: a strategy's PROBATION status, FII/DII flows being "
    "unverified, or a short track record. When a candidate has an entry_signal "
    "from a breakout strategy, a high RSI is expected by construction and is not "
    "by itself a reason to pass. Pass when the candidates have specific problems: "
    "bearish fundamentals, a stronger bear than bull case, unverified prices, or "
    "nothing that stands out. Propose a stop-loss percentage "
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
        "quarterly_results": val(snap.points.get("quarterly_results")),
        "flows": val(snap.points.get("fii_dii_flows")),
        "news": val(snap.points.get("news")),
        "market": {k: val(p) for k, p in market.items()},
        "unverified_items": snap.unverified_items(),
    }


CONCALL_SYSTEM = (
    "You are the earnings-call analyst. You are given the transcript of a company's "
    "latest results conference call. Report what management said about demand, "
    "order book or volumes, margins, guidance for coming quarters, capital spending "
    "and risks, and how analysts on the call reacted. Use only the transcript. "
    "Every figure you state must appear in the transcript exactly. Support each "
    "point with a short verbatim quote (under 30 words) copied character for "
    "character from the transcript; an automated check deletes quotes that are not "
    "found in it. Reply with only a JSON object: "
    '{"signal": "bullish|bearish|neutral", "summary": "<three sentences>", '
    '"guidance": ["<point>", ...], "risks": ["<point>", ...], '
    '"quotes": ["<verbatim quote>", ...]}.'
)
MAX_TRANSCRIPT_CHARS = 120_000


def _norm(text: str) -> str:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"[^a-z0-9%.]+", " ", text).strip()


def run_concall_analyst(llm: LLM, concall: dict) -> dict:
    """Reads the transcript, then keeps only what can be verified against it:
    quotes must appear verbatim, and figures in the prose must appear in the text."""
    text = concall["text"][:MAX_TRANSCRIPT_CHARS]
    reply = llm.complete(CONCALL_SYSTEM, f"Call period: {concall['period']}\n\n{text}",
                         max_tokens=1200)
    base = {"period": concall["period"], "source": concall["url"]}
    try:
        out = parse_json_object(reply)
    except LLMFormatError:
        return {**base, "signal": "neutral", "summary": "concall reply could not be parsed",
                "guidance": [], "risks": [], "quotes": [], "quotes_dropped": 0}
    haystack = _norm(text)
    quotes = [q for q in out.get("quotes", []) if isinstance(q, str)]
    kept = [q for q in quotes if len(_norm(q)) >= 15 and _norm(q) in haystack]

    def grounded(items):
        return [x for x in items if isinstance(x, str) and not ungrounded_numbers(x, text)]

    summary = str(out.get("summary", ""))
    result = {**base, "signal": out.get("signal", "neutral"),
              "summary": summary if not ungrounded_numbers(summary, text)
              else "[removed: figures not in the transcript]",
              "guidance": grounded(out.get("guidance", [])),
              "risks": grounded(out.get("risks", [])),
              "quotes": kept, "quotes_dropped": len(quotes) - len(kept)}
    if not kept:  # nothing verifiable: do not let it sway the decision
        result["signal"] = "neutral"
    return result


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
