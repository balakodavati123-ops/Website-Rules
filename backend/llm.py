"""The desk's AI analysts: Claude models reading news, writing IPO theses and reviewing the day, under a hard spending cap.

Three tiers, each used only where it pays for itself:
  read   -> Claude Haiku 5.5   news digests every half hour (cheapest)
  write  -> Claude Sonnet 5.5  IPO theses, once per IPO per day
  review -> Claude Opus 5.5    the COO's end-of-day review, once a day
The API key (ANTHROPIC_API_KEY, a GitHub secret) is billed per token, separately from any Claude subscription. Spending is capped in
dollars per rolling 5-hour window and per day (LLM_USD_5H, LLM_USD_DAY); a call that could cross either cap is not sent, and the desk
falls back to its written rules. Every call's real usage is recorded in llm_usage.json. Nothing here trades.
"""
from __future__ import annotations

import json
import os
import time

MODELS = {"read": "claude-haiku-5-5", "write": "claude-sonnet-5-5", "review": "claude-opus-5-5"}
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}   # $ per million input / output tokens
EFFORT = {"read": "low", "write": "medium", "review": "medium"}
MAXTOK = {"read": 1500, "write": 2500, "review": 3500}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WINDOW = 5 * 3600


def caps(env=os.environ) -> tuple[float, float]:
    return float(env.get("LLM_USD_5H") or 0.25), float(env.get("LLM_USD_DAY") or 0.75)


def new_usage() -> dict:
    return {"calls": [], "by_kind": {}, "refused": 0, "errors": 0, "last_error": ""}


def spent(u: dict, now: float, secs: float) -> float:
    return sum(c["usd"] for c in u["calls"] if now - c["ts"] < secs)


def cost(model: str, usage) -> float:
    pi, po = PRICE[model]
    g = lambda k: float(getattr(usage, k, 0) or (usage.get(k, 0) if isinstance(usage, dict) else 0) or 0)
    return (g("input_tokens") * pi + g("cache_creation_input_tokens") * pi * 1.25 + g("cache_read_input_tokens") * pi * 0.05 + g("output_tokens") * po) / 1e6


def worst_case(model: str, prompt_chars: int, max_tokens: int) -> float:
    pi, po = PRICE[model]
    return (prompt_chars / 3.0 * pi + max_tokens * po) / 1e6


class Desk:
    """ask(kind, system, prompt, tier, max_tokens) -> text or None. None means: no key, over budget, refused or failed (the rules carry on)."""

    def __init__(self, usage: dict, env=os.environ, client=None):
        self.u, self.env = usage, env
        self.key = bool(env.get("ANTHROPIC_API_KEY"))
        self.client = client
        if self.client is None and self.key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(max_retries=1, timeout=90.0)
            except Exception as e:                                       # the package is missing: run on rules
                self.u["last_error"] = f"anthropic package unavailable: {e}"[:200]
                self.client = None

    @property
    def on(self) -> bool:
        return self.client is not None

    def status(self, now: float | None = None) -> dict:
        now = now or time.time()
        c5, cd = caps(self.env)
        s5, sd = spent(self.u, now, WINDOW), spent(self.u, now, 86400)
        return {"on": self.on, "usd_5h": round(s5, 4), "cap_5h": c5, "usd_day": round(sd, 4), "cap_day": cd, "pct_5h": round(s5 / c5 * 100, 1) if c5 else 0,
                "calls_day": sum(1 for c in self.u["calls"] if now - c["ts"] < 86400), "by_kind": self.u["by_kind"], "models": MODELS, "last_error": self.u.get("last_error", "")}

    def ask(self, kind: str, system: str, prompt: str, tier: str = "read", max_tokens: int | None = None) -> str | None:
        if not self.on:
            return None
        model, mt, now = MODELS[tier], max_tokens or MAXTOK[tier], time.time()
        c5, cd = caps(self.env)
        need = worst_case(model, len(system) + len(prompt), mt)
        if spent(self.u, now, WINDOW) + need > c5 or spent(self.u, now, 86400) + need > cd:
            self.u["refused"] = self.u.get("refused", 0) + 1
            return None
        kw = dict(model=model, max_tokens=mt, system=system, messages=[{"role": "user", "content": prompt}])
        extra = {"output_config": {"effort": EFFORT[tier]}}

        def send(native: bool):
            if tier == "read":                                           # Haiku has no server-side fallback
                return self.client.messages.create(**kw, **extra) if native else self.client.messages.create(**kw, extra_body=extra)
            fb = {"fallbacks": "default"}                                # Sonnet / Opus: if a safety check declines, the API retries on its default fallback model
            return self.client.beta.messages.create(betas=[FALLBACK_BETA], **kw, **extra, **fb) if native else \
                self.client.beta.messages.create(betas=[FALLBACK_BETA], **kw, extra_body={**extra, **fb})
        try:
            try:
                r = send(True)
            except TypeError:                                            # an older SDK that does not know these parameters by name
                r = send(False)
        except Exception as e:
            self.u["errors"] = self.u.get("errors", 0) + 1
            self.u["last_error"] = f"{type(e).__name__}: {e}"[:200]
            return None
        usd = cost(getattr(r, "model", model) if getattr(r, "model", model) in PRICE else model, r.usage)
        self.u["calls"] = [c for c in self.u["calls"] if now - c["ts"] < 86400 * 2] + [{"ts": now, "kind": kind, "model": model, "usd": round(usd, 6),
                                                                                       "in": int(getattr(r.usage, "input_tokens", 0) or 0), "out": int(getattr(r.usage, "output_tokens", 0) or 0)}]
        k = self.u["by_kind"].setdefault(kind, {"calls": 0, "usd": 0.0})
        k["calls"] += 1
        k["usd"] = round(k["usd"] + usd, 6)
        if getattr(r, "stop_reason", "") == "refusal":
            return None
        text = "".join(getattr(b, "text", "") for b in (r.content or []) if getattr(b, "type", "") == "text").strip()
        return text or None


def parse_json(text: str | None):
    """The first JSON object in a model reply, or None."""
    if not text:
        return None
    a, b = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[a:b + 1]) if a >= 0 and b > a else None
    except ValueError:
        return None


NEWS_SYSTEM = ("You are the headlines analyst of an Indian paper-trading desk. You read only the headlines given. Never invent facts, prices or companies. "
               "Reply with one JSON object and nothing else: {\"mood\": \"bullish\"|\"bearish\"|\"mixed\", \"brief\": \"two plain sentences for the CEO\", "
               "\"themes\": [up to 4 short themes], \"companies\": [{\"name\": company named in a headline, \"tone\": \"positive\"|\"negative\"|\"neutral\", \"why\": \"under 12 words\"}] (up to 10, Indian listed companies only), "
               "\"global\": \"one sentence on international news that matters for Indian markets today\", \"risks\": [up to 3 short risks]}")


def news_digest(desk: Desk, headlines: list[dict]) -> dict | None:
    """Haiku reads up to 60 recent headlines (title + source only) and returns the mood, themes and companies they name."""
    rows = [f"- {h.get('headline') or h.get('title')} ({h.get('source', '')})" for h in headlines[:60] if (h.get("headline") or h.get("title"))]
    if len(rows) < 5:
        return None
    out = parse_json(desk.ask("news", NEWS_SYSTEM, "Headlines, newest first:\n" + "\n".join(rows), "read"))
    return out if isinstance(out, dict) and out.get("brief") else None


REVIEW_SYSTEM = ("You are the COO of an AI paper-trading desk reviewing the day for the CEO. Use only the numbers given; never invent results. "
                 "Paper trades are not proof of an edge; say so when samples are small. Reply in plain English, under 220 words, as: "
                 "'What worked', 'What did not', 'What I am changing tomorrow' (only changes the rules allow: pause, keep watching, propose a variant for the strategy lab), "
                 "'Watch tomorrow'.")


def day_review(desk: Desk, facts: dict) -> str | None:
    return desk.ask("review", REVIEW_SYSTEM, json.dumps(facts, separators=(",", ":"), default=str)[:12000], "review")
