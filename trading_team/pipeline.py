"""Runs the full daily sequence: data -> screen -> analysts -> debate ->
portfolio manager -> risk manager -> ledger -> report."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .agents import (CaseFile, build_context, run_analyst, run_concall_analyst,
                     run_debate, run_portfolio_manager)
from .config import Settings
from .data import DataAgent, DataProvider
from .indicators import screen_score, technical_summary
from .ledger import Ledger
from .guardrails import ungrounded_numbers, validate_pm_output
from .llm import LLM
from .models import Recommendation
from .report import write_pdf
from .risk import CandidateRisk, RiskManager, RiskReview
from .strategies import STRATEGIES, live_signals, load_verdicts, tradable

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
        # Price history for the whole watchlist, fetched in parallel. Fundamentals
        # and news are fetched later, only for the candidates that get analysed.
        with ThreadPoolExecutor(max_workers=6) as pool:
            snaps = dict(zip(tickers, pool.map(
                lambda t: self.data.snapshot(t, run_date, enrich=False), tickers)))

        verdicts = load_verdicts(self.settings.strategy_file)
        gated = bool(verdicts)
        allowed = tradable(verdicts, self.settings.rules)
        watch_only = [n for n, v in verdicts.items()
                      if v.get("status") in ("APPROVED", "PROBATION") and n not in allowed]
        watch_hits: list[str] = []

        # Screen: deterministic; only the top few get LLM analysis.
        # Each entry is (score, ticker, technicals, strategy name or None).
        ranked = []
        for t, snap in snaps.items():
            if not snap.bars:
                continue
            if gated:
                sigs = live_signals(snap.bars, list(allowed) + watch_only)
                watch_hits += [f"{t} ({n})" for n, _ in sigs if n in watch_only]
                sigs = [x for x in sigs if x[0] in allowed]
                if sigs:
                    name, score = max(sigs, key=lambda x: x[1])
                    ranked.append((score, t, technical_summary(snap.bars), name))
            else:
                tech = technical_summary(snap.bars)
                ranked.append((screen_score(tech), t, tech, None))
        ranked.sort(key=lambda x: x[0], reverse=True)

        cases: list[CaseFile] = []
        risk_facts: dict[str, CandidateRisk] = {}
        grounding_flags: list[str] = []
        def analyse(item):
            score, t, tech, strat_name = item
            self.data.enrich(snaps[t])
            ctx = build_context(snaps[t], tech, market)
            if strat_name:
                v = verdicts[strat_name]
                ctx["entry_signal"] = {
                    "strategy": strat_name, "lab_status": v["status"],
                    "backtest_trades": v["trades"],
                    "backtest_win_rate_pct": round(v["win_rate"] * 100, 1),
                    "backtest_avg_R": round(v["avg_R"], 2),
                    "note": "backtest on today's index members; flattered by "
                            "survivorship bias"}
            analysts = {name: run_analyst(self.llm, name, ctx) for name in ANALYSTS}
            concall = snaps[t].points.get("concall")
            concall_report = None
            if concall is not None and concall.verified:
                concall_report = run_concall_analyst(self.llm, concall.value)
                if concall_report["quotes_dropped"]:
                    grounding_flags.append(
                        f"{t} concall: {concall_report['quotes_dropped']} quote(s) "
                        f"removed, not found in the transcript")
            for name, rep in analysts.items():
                bad = ungrounded_numbers(rep.get("summary", ""), ctx)
                if bad:
                    grounding_flags.append(
                        f"{t} {name} analyst summary removed: quoted figures not in "
                        f"the data ({', '.join(bad)})")
                    rep["summary"] = "[removed: figures not in the data]"
                    rep["signal"] = "neutral"
            if concall_report:
                analysts["concall"] = concall_report
            bull, bear = run_debate(self.llm, ctx, analysts)
            evidence = {"context": ctx, "analysts": analysts}
            for side, text in (("bull", bull), ("bear", bear)):
                bad = ungrounded_numbers(text, evidence)
                if bad:
                    grounding_flags.append(
                        f"{t} {side} argument removed: quoted figures not in the "
                        f"data ({', '.join(bad)})")
                    if side == "bull":
                        bull = "[removed: figures not in the data]"
                    else:
                        bear = "[removed: figures not in the data]"
            return CaseFile(ticker=t, score=score, context=ctx,
                            analysts=analysts, bull=bull, bear=bear), tech

        # Candidates are analysed in parallel; each one is several model calls.
        todo = ranked[: self.settings.candidates_per_run]
        strategy_of = {t: name for _, t, _, name in todo if name}
        with ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:
            for case, tech in pool.map(analyse, todo):
                cases.append(case)
                risk_facts[case.ticker] = CandidateRisk(
                    price_verified=True, realized_vol=tech.get("realized_vol_20d_ann"))

        unverified_market = [k for k, p in market.items() if not p.verified]
        track = self.ledger.stats()

        if cases:
            proposal = run_portfolio_manager(self.llm, cases, track)
        elif gated and any(sn.bars for sn in snaps.values()):
            n_ok = sum(1 for sn in snaps.values() if sn.bars)
            why = (f"No tested strategy gave an entry signal today across {n_ok} "
                   f"tickers with verified prices.")
            if not allowed:
                why = ("No strategy has passed the backtest lab with exits that fit "
                       "the risk policy, so the desk has nothing it may trade.")
            if watch_hits:
                why += (" Signals from strategies outside the current risk policy "
                        "(not tradable): " + ", ".join(sorted(watch_hits)[:8]) + ".")
            proposal = {"action": "NO_TRADE", "rationale": why}
        else:
            proposal = {"action": "NO_TRADE", "rationale":
                        "no candidate had a verified price history"}

        # Schema and grounding checks on the PM before the risk manager sees it.
        problems = validate_pm_output(proposal, {c.ticker for c in cases})
        if not problems and proposal.get("action") == "BUY":
            case_data = {c.ticker: {"context": c.context, "analysts": c.analysts}
                         for c in cases}
            bad = ungrounded_numbers(str(proposal.get("rationale", "")), case_data)
            if bad:
                problems.append(f"rationale quotes figures not in the data: {bad}")
        if problems:
            grounding_flags.append("PM output rejected: " + "; ".join(problems))
            proposal = {"action": "NO_TRADE", "rationale":
                        "portfolio manager output failed checks; staying in cash"}

        review = self.risk.review(proposal, risk_facts, market) if cases else None
        strategy_label = None
        if review is not None and review.approved and review.ticker in strategy_of:
            # Trade the strategy exactly as it was tested: its own stop and target.
            name = strategy_of[review.ticker]
            strat, v = STRATEGIES[name], verdicts[name]
            review.stop_pct = round(strat.stop_pct * 100, 2)
            review.target_pct = round(strat.target_pct * 100, 2)
            strategy_label = f"{name} ({v['status']})"
            review.notes.append(
                f"entry signal: {name}; stop and target set to the tested values")
            if v["status"] != "APPROVED":
                review.notes.append(
                    f"{name} is on PROBATION, not validated: "
                    + "; ".join(v.get("failed_criteria", [])))
        if review is not None:
            review.notes = review.notes + grounding_flags
        rec = self._build_recommendation(run_date, proposal, review, snaps,
                                         unverified_market, [c.ticker for c in cases])
        rec.strategy = strategy_label
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
                              unverified_market, analysed=()) -> Recommendation:
        if review is None or not review.approved:
            # On a no-trade day, report any ticker whose price history failed,
            # plus the market data that was unavailable.
            base_unverified = [f"{t}: price history" for t, s in snaps.items()
                               if "price history" in s.unverified_items()]
            # Items missing for the analysed candidates, grouped by item.
            missing: dict[str, list[str]] = {}
            for t in analysed:
                for item in snaps[t].unverified_items():
                    missing.setdefault(item, []).append(t)
            for item, ts in missing.items():
                who = "all candidates" if len(ts) == len(analysed) else ", ".join(ts)
                base_unverified.append(f"{item}: {who}")
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
