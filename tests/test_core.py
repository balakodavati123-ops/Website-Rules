from datetime import date, timedelta

import pytest

from trading_team.agents import CaseFile, build_context, run_analyst
from trading_team.config import RiskRules
from trading_team.data import DataAgent, validate_bars
from trading_team.indicators import atr, realized_vol, rsi, screen_score, technical_summary
from trading_team.ledger import Ledger, settle_open_trades
from trading_team.llm import LLMFormatError, parse_json_object
from trading_team.models import Bar, DataPoint, Recommendation
from trading_team.risk import CandidateRisk, RiskManager
from trading_team.pipeline import TradingDesk
from trading_team.config import Settings
from trading_team.report import write_pdf

from conftest import FakeLLM, FakeProvider, make_bars


# ---- indicators ---------------------------------------------------------

def test_rsi_all_up_is_100():
    closes = [float(i) for i in range(1, 40)]
    assert rsi(closes) == 100.0


def test_rsi_bounds(bars):
    v = rsi([b.close for b in bars])
    assert 0 <= v <= 100


def test_atr_and_vol_positive(bars):
    assert atr(bars) > 0
    assert realized_vol([b.close for b in bars]) > 0


def test_technical_summary_has_trend(bars):
    t = technical_summary(bars)
    assert t["trend"] == "uptrend"
    assert t["sma200"] is not None and t["macd_hist"] is not None


def test_screen_score_prefers_uptrend(bars):
    up = technical_summary(bars)
    down_bars = make_bars(drift=-0.004)
    assert screen_score(up) > screen_score(technical_summary(down_bars))


# ---- data validation ----------------------------------------------------

def test_validate_bars_flags_bad_rows():
    d = date(2025, 1, 2)
    bad = [Bar(d, 10, 9, 11, 10, 1)]  # high below low
    assert validate_bars(bad)
    assert validate_bars([]) == ["no bars returned"]
    good = [Bar(d, 10, 11, 9.5, 10.5, 1)]
    assert validate_bars(good) == []


def test_snapshot_marks_missing_flows_unverified(bars):
    provider = FakeProvider({"ABC.NS": bars})
    snap = DataAgent(provider).snapshot("ABC.NS")
    assert snap.bars
    items = snap.unverified_items()
    assert any(i.startswith("fii_dii_flows") for i in items)
    assert "price history" not in items


def test_snapshot_provider_failure_is_unverified():
    provider = FakeProvider(fail={"ABC.NS"})
    snap = DataAgent(provider).snapshot("ABC.NS")
    assert snap.bars == []
    assert "price history" in snap.unverified_items()


def test_context_labels_unverified(bars):
    provider = FakeProvider({"ABC.NS": bars})
    snap = DataAgent(provider).snapshot("ABC.NS")
    ctx = build_context(snap, technical_summary(bars), DataAgent(provider).market())
    assert ctx["flows"].startswith("UNVERIFIED")
    assert ctx["market"]["india_vix"] == 12.0


# ---- llm parsing --------------------------------------------------------

def test_parse_json_inside_prose():
    assert parse_json_object('Sure: {"a": 1} thanks') == {"a": 1}


def test_parse_json_rejects_garbage():
    with pytest.raises(LLMFormatError):
        parse_json_object("no json here")


def test_analyst_falls_back_on_bad_reply():
    class Bad:
        def complete(self, *a, **k):
            return "I cannot comply"
    out = run_analyst(Bad(), "technical", {})
    assert out["signal"] == "neutral"


# ---- risk manager -------------------------------------------------------

def _rm():
    return RiskManager(RiskRules())


def _cands(verified=True, vol=0.3):
    return {"ABC.NS": CandidateRisk(price_verified=verified, realized_vol=vol)}


def _vix(v):
    from trading_team.models import DataPoint
    return {"india_vix": DataPoint(value=v, verified=v is not None)}


def test_risk_clamps_stop_and_target():
    r = _rm().review({"action": "BUY", "ticker": "ABC.NS", "stop_pct": 9,
                      "target_pct": 50}, _cands(), _vix(12))
    assert r.approved
    assert r.stop_pct == 5.0 and r.target_pct == 30.0
    assert any("adjusted" in n for n in r.notes)


def test_risk_default_midpoints_when_missing():
    r = _rm().review({"action": "BUY", "ticker": "ABC.NS"}, _cands(), _vix(12))
    assert r.stop_pct == 4.0 and r.target_pct == 22.5


def test_risk_vetoes_high_vix():
    r = _rm().review({"action": "BUY", "ticker": "ABC.NS"}, _cands(), _vix(25))
    assert not r.approved and "staying in cash" in r.notes[0]


def test_risk_vetoes_unknown_vix():
    r = _rm().review({"action": "BUY", "ticker": "ABC.NS"}, _cands(), _vix(None))
    assert not r.approved


def test_risk_vetoes_unverified_price():
    r = _rm().review({"action": "BUY", "ticker": "ABC.NS"},
                     _cands(verified=False), _vix(12))
    assert not r.approved


def test_risk_vetoes_volatile_stock():
    r = _rm().review({"action": "BUY", "ticker": "ABC.NS"},
                     _cands(vol=0.9), _vix(12))
    assert not r.approved


def test_risk_rejects_non_candidate():
    r = _rm().review({"action": "BUY", "ticker": "ZZZ.NS"}, _cands(), _vix(12))
    assert not r.approved


def test_risk_respects_no_trade():
    r = _rm().review({"action": "NO_TRADE"}, _cands(), _vix(12))
    assert not r.approved


# ---- ledger -------------------------------------------------------------

def _rec(day, entry=100.0):
    return Recommendation(run_date=day, action="BUY", ticker="ABC.NS",
                          entry_price=entry, stop_pct=4, target_pct=20,
                          stop_loss=96.0, target=120.0, confidence=0.6,
                          rationale="x", risk_notes=[], unverified=[])


def test_ledger_records_and_stats(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.record(_rec(date(2025, 1, 2)))
    led.record(Recommendation(run_date=date(2025, 1, 3), action="NO_TRADE"))
    s = led.stats()
    assert s["open_trades"] == 1 and s["no_trade_days"] == 1
    assert s["closed_trades"] == 0 and s["win_rate_pct"] is None


def _bar(day, o, h, l, c):
    return Bar(day, o, h, l, c, 1)


def test_settle_target_hit(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.record(_rec(date(2025, 1, 2)))
    bars = [_bar(date(2025, 1, 3), 101, 110, 99, 105),
            _bar(date(2025, 1, 6), 105, 125, 104, 121)]
    out = settle_open_trades(led, lambda t: bars, RiskRules(), date(2025, 1, 10))
    assert out[0]["outcome"] == "TARGET" and out[0]["return_pct"] == 20.0
    assert led.stats()["wins"] == 1


def test_settle_stop_gap_fills_at_open(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.record(_rec(date(2025, 1, 2)))
    bars = [_bar(date(2025, 1, 3), 90, 92, 88, 91)]  # gaps below the 96 stop
    out = settle_open_trades(led, lambda t: bars, RiskRules(), date(2025, 1, 10))
    assert out[0]["outcome"] == "STOP" and out[0]["return_pct"] == -10.0


def test_settle_stop_first_when_both_hit(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.record(_rec(date(2025, 1, 2)))
    bars = [_bar(date(2025, 1, 3), 100, 125, 95, 110)]
    out = settle_open_trades(led, lambda t: bars, RiskRules(), date(2025, 1, 10))
    assert out[0]["outcome"] == "STOP"


def test_settle_leaves_open_when_nothing_hit(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.record(_rec(date(2025, 1, 2)))
    bars = [_bar(date(2025, 1, 3), 100, 105, 98, 102)]
    assert settle_open_trades(led, lambda t: bars, RiskRules(), date(2025, 1, 10)) == []
    assert led.stats()["open_trades"] == 1


# ---- pipeline end to end -------------------------------------------------

def test_pipeline_buy_path(tmp_path, bars):
    provider = FakeProvider({"ABC.NS": bars, "DEF.NS": make_bars(drift=-0.004)})
    led = Ledger(tmp_path / "l.sqlite")
    llm = FakeLLM(pm_action="BUY", pm_ticker="ABC.NS")
    desk = TradingDesk(provider, llm, led,
                       Settings(report_dir=str(tmp_path / "reports")))
    result = desk.run(["ABC.NS", "DEF.NS"], run_date=date(2026, 1, 5))
    rec = result.recommendation
    assert rec.action == "BUY" and rec.ticker == "ABC.NS"
    assert rec.stop_loss == round(rec.entry_price * 0.96, 2)
    assert rec.target == round(rec.entry_price * 1.22, 2)
    assert "india_vix" not in rec.unverified
    assert result.pdf_path.exists() and result.pdf_path.stat().st_size > 1000
    assert led.stats()["open_trades"] == 1


def test_pipeline_no_trade_when_vix_high(tmp_path, bars):
    provider = FakeProvider({"ABC.NS": bars}, vix=30.0)
    led = Ledger(tmp_path / "l.sqlite")
    desk = TradingDesk(provider, FakeLLM(pm_action="BUY", pm_ticker="ABC.NS"), led,
                       Settings(report_dir=str(tmp_path / "reports")))
    rec = desk.run(["ABC.NS"], run_date=date(2026, 1, 5), write_report=False).recommendation
    assert rec.action == "NO_TRADE"
    assert any("staying in cash" in n for n in rec.risk_notes)


def test_pipeline_no_candidates_skips_llm(tmp_path):
    provider = FakeProvider({})
    led = Ledger(tmp_path / "l.sqlite")
    llm = FakeLLM()
    desk = TradingDesk(provider, llm, led,
                       Settings(report_dir=str(tmp_path / "reports")))
    rec = desk.run(["NONE.NS"], run_date=date(2026, 1, 5), write_report=False).recommendation
    assert rec.action == "NO_TRADE" and llm.calls == []
    assert "NONE.NS: price history" in rec.unverified


def test_pipeline_pm_no_trade_is_logged(tmp_path, bars):
    provider = FakeProvider({"ABC.NS": bars})
    led = Ledger(tmp_path / "l.sqlite")
    desk = TradingDesk(provider, FakeLLM(pm_action="NO_TRADE"), led,
                       Settings(report_dir=str(tmp_path / "reports")))
    rec = desk.run(["ABC.NS"], run_date=date(2026, 1, 5), write_report=False).recommendation
    assert rec.action == "NO_TRADE"
    assert led.recent(1)[0]["action"] == "NO_TRADE"
