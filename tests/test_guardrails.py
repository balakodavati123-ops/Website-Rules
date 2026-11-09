from datetime import date, timedelta

from trading_team.config import Settings
from trading_team.guardrails import (is_fresh, grounding_report, ungrounded_numbers,
                                     validate_pm_output)
from trading_team.ledger import Ledger
from trading_team.pipeline import TradingDesk
from trading_team.models import Bar

from conftest import FakeLLM, FakeProvider, make_bars


CTX = {"ticker": "ABC.NS", "technicals": {"last_close": 171.51, "rsi14": 68.8},
       "market": {"india_vix": 12.0}}


def test_grounded_figures_pass():
    assert ungrounded_numbers("RSI 68.8 and close 171.51", CTX) == []


def test_invented_figure_is_caught():
    assert ungrounded_numbers("Breakout above 190.25 target", CTX) == ["190.25"]


def test_rule_constants_allowed_and_percent_fraction_match():
    assert ungrounded_numbers("stop 4% target 22%", CTX) == ["22"]  # 22 not in data
    assert ungrounded_numbers("stop 4% and target 15%", CTX) == []


def test_grounding_report_lists_fields():
    rep = grounding_report({"a": "RSI 68.8", "b": "price 999.99"}, CTX)
    assert rep == {"b": ["999.99"]}


def test_freshness():
    today = date(2026, 1, 12)
    old = [Bar(today - timedelta(days=10), 1, 1, 1, 1, 1)]
    new = [Bar(today - timedelta(days=1), 1, 1, 1, 1, 1)]
    assert not is_fresh(old, today)
    assert is_fresh(new, today)
    assert not is_fresh([], today)


def test_pm_schema():
    assert validate_pm_output({"action": "BUY", "ticker": "X", "stop_pct": 4,
                               "target_pct": 20, "confidence": 0.5, "rationale": "r"},
                              {"X"}) == []
    probs = validate_pm_output({"action": "BUY", "ticker": "Y", "stop_pct": "4",
                                "target_pct": 20, "confidence": 2}, {"X"})
    assert len(probs) == 3
    assert validate_pm_output({"action": "MAYBE"}, {"X"})


class HallucinatingLLM(FakeLLM):
    def complete(self, system, user, max_tokens=1200):
        if "PORTFOLIO MANAGER" in system:
            return ('{"action":"BUY","ticker":"ABC.NS","stop_pct":4,"target_pct":20,'
                    '"confidence":0.7,"rationale":"Target 999.99 is certain."}')
        return super().complete(system, user, max_tokens)


class MalformedPM(FakeLLM):
    def complete(self, system, user, max_tokens=1200):
        if "PORTFOLIO MANAGER" in system:
            return "BUY ABC now!!"
        return super().complete(system, user, max_tokens)


def test_pipeline_rejects_hallucinated_pm(tmp_path, bars):
    desk = TradingDesk(FakeProvider({"ABC.NS": bars}), HallucinatingLLM(),
                       Ledger(tmp_path / "l.sqlite"),
                       Settings(report_dir=str(tmp_path)))
    rec = desk.run(["ABC.NS"], run_date=date(2026, 1, 5), write_report=False).recommendation
    assert rec.action == "NO_TRADE"
    assert any("999.99" in n for n in rec.risk_notes)


def test_pipeline_handles_malformed_pm(tmp_path, bars):
    desk = TradingDesk(FakeProvider({"ABC.NS": bars}), MalformedPM(),
                       Ledger(tmp_path / "l.sqlite"),
                       Settings(report_dir=str(tmp_path)))
    rec = desk.run(["ABC.NS"], run_date=date(2026, 1, 5), write_report=False).recommendation
    assert rec.action == "NO_TRADE"


def test_pipeline_stale_data_is_unverified(tmp_path, bars):
    provider = FakeProvider({"ABC.NS": bars})
    desk = TradingDesk(provider, FakeLLM(pm_action="BUY", pm_ticker="ABC.NS"),
                       Ledger(tmp_path / "l.sqlite"),
                       Settings(report_dir=str(tmp_path)))
    rec = desk.run(["ABC.NS"], run_date=date(2027, 6, 1), write_report=False).recommendation
    assert rec.action == "NO_TRADE"
    assert "ABC.NS: price history" in rec.unverified
