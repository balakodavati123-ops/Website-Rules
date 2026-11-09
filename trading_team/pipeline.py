"""Runs the full daily sequence: data -> screen -> analysts -> debate ->
portfolio manager -> risk manager -> ledger -> report."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .agents import (CaseFile, build_context, run_analyst, run_debate,
                     run_portfolio_manager)
from .config import Settings
from .data import DataAgent, DataProvider
from .indicators import screen_score, technical_summary
from .ledger import Ledger
from .llm import LLM
from .models import Recommendation
from .report import write_pdf
from .risk import CandidateRisk, RiskManager, RiskReview

log = logging.getLogger(__name__)
ANALYSTS = ("technical", "fundamentals", "sentiment")


@dataclass
class RunResult:
    recommendation: Recommendation
    review: RiskReview | None
    cases: list[CaseFile] = field(default_factory=list)
    pdf_path: Path | None = None


class TradingDesk:
    def __init__(self, provider: DataProvider, llm: LLM, ledger: Ledger,
                 settings: Settings | None = None):
        self.settings = settings or Settings()
        self.data = DataAgent(provider, self.settings.history_days)
        self.llm = llm
        self.ledger = ledger
        self.risk = RiskManager(self.settings.rules)

    def run(self, tickers: list[str], run_date: date | None = None,
            write_report: bool = True) -> RunResult:
        run_date = run_date or date.today()
        market = self.data.market()
        snaps = {t: self.data.snapshot(t, run_date) for t in tickers}

        # Screen: deterministic ranking; only the top few get LLM analysis.
        ranked = []
        for t, snap in snaps.items():
            tech = technical_summary(snap.bars) if snap.bars else None
            ranked.append((screen_score(tech) if tech else float("-inf"), t, tech))
        ranked.sort(key=lambda x: x[0], reverse=True)

        cases: list[CaseFile] = []
        risk_facts: dict[str, CandidateRisk] = {}
        for score, t, tech in ranked[: self.settings.candidates_per_run]:
            if tech is None:
                continue
            ctx = build_context(snaps[t], tech, market)
            analysts = {name: run_analyst(self.llm, name, ctx) for name in ANALYSTS}
            bull, bear = run_debate(self.llm, ctx, analysts)
            cases.append(CaseFile(ticker=t, score=score, context=ctx,
                                  analysts=analysts, bull=bull, bear=bear))
            risk_facts[t] = CandidateRisk(
                price_verified=True, realized_vol=tech.get("realized_vol_20d_ann"))

        unverified_market = [k for k, p in market.items() if not p.verified]
        track = self.ledger.stats()

        if cases:
            proposal = run_portfolio_manager(self.llm, cases, track)
        else:
            proposal = {"action": "NO_TRADE", "rationale":
                        "no candidate had a verified price history"}

        review = self.risk.review(proposal, risk_facts, market) if cases else None
        rec = self._build_recommendation(run_date, proposal, review, snaps,
                                         unverified_market)
        self.ledger.record(rec)

        pdf = None
        if write_report:
            pdf = write_pdf(
                rec, Path(self.settings.report_dir) / f"{run_date.isoformat()}.pdf",
                self.ledger.stats(),
                analyst_summaries={c.ticker: c.analysts["technical"].get("summary", "")
                                   for c in cases if c.ticker == rec.ticker})
        return RunResult(rec, review, cases, pdf)

    def _build_recommendation(self, run_date, proposal, review, snaps,
                              unverified_market) -> Recommendation:
        if review is None or not review.approved:
            # On a no-trade day, report any ticker whose price history failed,
            # plus the market data that was unavailable.
            base_unverified = [f"{t}: price history" for t, s in snaps.items()
                               if "price history" in s.unverified_items()]
            base_unverified += unverified_market
            notes = review.notes if review else [proposal.get("rationale", "")]
            return Recommendation(
                run_date=run_date, action="NO_TRADE",
                rationale=str(proposal.get("rationale", "")),
                risk_notes=list(notes), unverified=base_unverified)

        snap = snaps[review.ticker]
        base_unverified = snap.unverified_items() + unverified_market
        # Work from the rounded entry so the printed prices reconcile exactly.
        entry = round(snap.bars[-1].close, 2)
        stop = round(entry * (1 - review.stop_pct / 100), 2)
        target = round(entry * (1 + review.target_pct / 100), 2)
        return Recommendation(
            run_date=run_date, action="BUY", ticker=review.ticker,
            entry_price=entry, stop_pct=review.stop_pct,
            target_pct=review.target_pct, stop_loss=stop, target=target,
            confidence=_clamp01(proposal.get("confidence")),
            rationale=str(proposal.get("rationale", "")),
            risk_notes=review.notes, unverified=base_unverified)


def _clamp01(x) -> float | None:
    try:
        return min(max(float(x), 0.0), 1.0)
    except (TypeError, ValueError):
        return None
