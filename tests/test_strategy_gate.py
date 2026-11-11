import json
from datetime import date

from trading_team.config import RiskRules, Settings
from trading_team.ledger import Ledger
from trading_team.pipeline import TradingDesk
from trading_team.strategies import STRATEGIES, Strategy, policy_compliant, tradable

from conftest import END_DAY, FakeLLM, FakeProvider, make_bars

VERDICT = {"status": "PROBATION", "trades": 300, "win_rate": 0.25, "avg_R": 0.2,
           "failed_criteria": ["t-stat 1.50 below 2.0"]}


def _gate(tmp_path, **strategies):
    f = tmp_path / "verdicts.json"
    f.write_text(json.dumps({"strategies": strategies}))
    return str(f)


def _always(df):
    """Test-only strategy that signals on every bar."""
    return df["Close"] * 0 + 1.0, None


def test_policy_compliance_and_tradable():
    rules = RiskRules()
    assert policy_compliant(STRATEGIES["breakout_52w"], rules)
    assert not policy_compliant(STRATEGIES["trend_ride"], rules)   # no fixed target
    got = tradable({"breakout_52w": {"status": "PROBATION"},
                    "trend_ride": {"status": "PROBATION"},
                    "momentum_screen": {"status": "REJECTED"}}, rules)
    assert got == {"breakout_52w": "PROBATION"}


def test_gate_trades_signal_with_tested_stop_and_target(tmp_path, monkeypatch):
    monkeypatch.setitem(STRATEGIES, "always", Strategy("always", _always, 0.04, 0.20, 40, "test"))
    bars = make_bars(n=300)
    desk = TradingDesk(FakeProvider({"ABC.NS": bars}),
                       FakeLLM(pm_action="BUY", pm_ticker="ABC.NS", stop=3.0, target=30.0),
                       Ledger(tmp_path / "l.sqlite"),
                       Settings(report_dir=str(tmp_path),
                                strategy_file=_gate(tmp_path, always=VERDICT)))
    rec = desk.run(["ABC.NS"], run_date=END_DAY, write_report=False).recommendation
    assert rec.action == "BUY"
    assert (rec.stop_pct, rec.target_pct) == (4.0, 20.0)     # the strategy's, not the PM's
    assert rec.strategy == "always (PROBATION)"
    assert any("PROBATION" in n for n in rec.risk_notes)


def test_gate_no_signal_means_no_trade_and_no_llm_calls(tmp_path):
    llm = FakeLLM()
    desk = TradingDesk(FakeProvider({"ABC.NS": make_bars(n=300, drift=-0.003)}), llm,
                       Ledger(tmp_path / "l.sqlite"),
                       Settings(report_dir=str(tmp_path),
                                strategy_file=_gate(tmp_path, momentum_screen=VERDICT)))
    rec = desk.run(["ABC.NS"], run_date=END_DAY, write_report=False).recommendation
    assert rec.action == "NO_TRADE" and llm.calls == []
    assert "No tested strategy gave an entry signal" in rec.rationale


def test_gate_with_nothing_tradable_says_so(tmp_path):
    rejected = dict(VERDICT, status="REJECTED")
    desk = TradingDesk(FakeProvider({"ABC.NS": make_bars(n=300)}), FakeLLM(),
                       Ledger(tmp_path / "l.sqlite"),
                       Settings(report_dir=str(tmp_path),
                                strategy_file=_gate(tmp_path, momentum_screen=rejected)))
    rec = desk.run(["ABC.NS"], run_date=END_DAY, write_report=False).recommendation
    assert rec.action == "NO_TRADE"
    assert "nothing it may trade" in rec.rationale


def test_ledger_tracks_results_by_strategy(tmp_path):
    from trading_team.models import Recommendation
    led = Ledger(tmp_path / "l.sqlite")
    tid = led.record(Recommendation(run_date=date(2026, 1, 2), action="BUY", ticker="X",
                                    entry_price=100, stop_pct=5, target_pct=20,
                                    stop_loss=95, target=120,
                                    strategy="breakout_52w (PROBATION)"))
    led.settle(tid, date(2026, 1, 9), 120, "TARGET", 20.0)
    assert led.stats()["live_results_by_strategy"] == {
        "breakout_52w (PROBATION)": {"closed_trades": 1, "wins": 1, "avg_return_pct": 20.0}}
