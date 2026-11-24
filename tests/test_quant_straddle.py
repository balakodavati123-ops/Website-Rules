import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "quant"))
from src.agent import trainer as TR                       # noqa: E402
from src.backtest.costs import charges                    # noqa: E402
from src.backtest.straddle_engine import Backtester, Config, as_rows   # noqa: E402
from src.data.upstox_client import Candle                 # noqa: E402
from src.models import regime_pricing as RP               # noqa: E402
from src.reports import report as RPT                     # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def test_black76_parity_greeks_and_modes():
    S, K, T, s = 25500.0, 25500.0, RP.t_years(2 * 375), 0.14
    c, p = RP.black76(S, K, T, s, "CE"), RP.black76(S, K, T, s, "PE")
    import math
    F = S * math.exp((0.065 - 0.012) * T)
    assert abs((c.price - p.price) - math.exp(-0.065 * T) * (F - K)) < 1e-6          # put-call parity on the futures price
    assert 0.45 < c.delta < 0.6 and -0.55 < p.delta < -0.4 and c.gamma > 0 and c.theta_per_day < 0 and c.vega_per_pt > 0
    assert RP.mode_of(RP.sigma_eff(0.12)) == "MODE_1_QUIET" and RP.mode_of(RP.sigma_eff(0.15)) == "MODE_2_VOLATILE" and RP.mode_of(RP.sigma_eff(0.12, 1, 1, 1)) == "MODE_3_HIGH_VOLATILITY"
    assert RP.sigma_eff(0.2, -5, -5, -5) == pytest.approx(0.05)                          # floored at 0.25x
    assert RP.trading_minutes_left(datetime(2026, 11, 20, 15, 0), date(2026, 11, 23)) == 30 + 375


def test_charges_both_legs():
    ch = charges(17000.0, 20000.0)
    assert ch["brokerage"] == 80 and ch["stt"] == 20.0 and 120 < ch["total"] < 140


def test_permission_gate_blocks_training(tmp_path, monkeypatch):
    monkeypatch.delenv("QUANT_APPROVALS", raising=False)
    with pytest.raises(TR.PermissionDenied):
        TR.train([], tmp_path)
    (tmp_path / "APPROVALS").write_text("APPROVE_AGENT_TRAINING\n")
    assert TR.approved("APPROVE_AGENT_TRAINING", tmp_path) and not TR.approved("APPROVE_PAPER_EXECUTION", tmp_path)
    assert TR.WalkForward(2).splits(["2025-01", "2025-02", "2025-03", "2025-04"]) == [(["2025-01", "2025-02"], "2025-03"), (["2025-01", "2025-02", "2025-03"], "2025-04")]


class FakeClient:
    """One expiry, one trading day: NIFTY rises 1% from 10:00 to 13:00; the 25000 call rises, the put falls."""
    calls = cache_hits = 0

    def __init__(self):
        self.day = date(2026, 11, 17)

    def _bars(self, f):
        out = []
        for i in range(0, 376):
            t = datetime(2026, 11, 17, 9, 15, tzinfo=IST) + timedelta(minutes=i)
            v = f(i)
            out.append(Candle(t, v, v, v, v, 100, 10))
        return out

    def index_candles(self, key, unit, interval, f, t, chunk_days=27):
        if unit == "days":
            return [Candle(datetime(2026, 11, 16, tzinfo=IST), 25000, 25000, 25000, 25000 if "Nifty" in key else 14.0, 0, 0),
                    Candle(datetime(2026, 11, 17, tzinfo=IST), 25000, 25300, 24990, 25250 if "Nifty" in key else 15.0, 0, 0)]
        if "VIX" in key:
            return self._bars(lambda i: 14.5)
        return self._bars(lambda i: 25000 + max(0, min(i - 45, 180)) * 250 / 180)

    def expired_expiries(self, u):
        return ["2026-11-17"]

    def expired_contracts(self, e, u=None):
        return [{"strike_price": 25000.0, "instrument_type": k, "instrument_key": f"K{k}", "trading_symbol": f"NIFTY 25000 {k}", "lot_size": 65} for k in ("CE", "PE")]

    def expired_candles(self, key, interval, f, t):
        if key == "KCE":
            return self._bars(lambda i: 60 + max(0, min(i - 45, 180)) * 200 / 180)
        return self._bars(lambda i: 60 - max(0, min(i - 45, 180)) * 50 / 180)


def test_engine_trades_one_day_on_real_style_candles(monkeypatch):
    import src.data.macro_news_feed as MF
    monkeypatch.setattr(MF, "load_all", lambda s, e, nb=None: {"nifty_bank": nb or {}})
    cfg = Config(start=date(2026, 11, 17), end=date(2026, 11, 17), entries=("10:00",), targets=(0.5,), stops=(0.35,), policies=("atm",))
    rows = as_rows(Backtester(FakeClient(), cfg, log=lambda *a: None).run())
    assert len(rows) == 1
    r = rows[0]
    assert r["dte"] == 0 and r["strike"] == 25000 and r["mode"] == "MODE_2_VOLATILE" and r["exit_reason"] == "TARGET_50PCT" and r["net_pnl_inr"] > 0
    assert r["data_source_status"] == "VERIFIED_HISTORICAL" and r["lot_size"] == 65 and r["combined_entry_premium"] > 120
    s = RPT.summary(rows, {"x": "test"}, cfg)
    assert s["overall_all_configs"]["trades"] == 1 and s["overall_all_configs"]["win_rate_pct"] == 100.0


def test_regime_walk_forward_picks_per_cell_from_past_months_only():
    from src.research import regime_strategy as RS
    rows = []
    for mi in range(1, 11):
        for dd in range(1, 21):
            d = f"2025-{mi:02d}-{dd:02d}"
            mode = "MODE_1_QUIET" if dd % 2 else "MODE_2_VOLATILE"
            for cid, pnl in (("good|09:20|TP50|SL35", 300 if mode == "MODE_1_QUIET" else -400), ("bad|09:20|TP50|SL35", -200)):
                rows.append({"entry_timestamp_ist": f"{d}T09:20:00+05:30", "entry_window": "09:20", "mode": mode, "dte": 0, "config_id": cid, "net_pnl_inr": pnl + (dd % 3) * 10,
                             "gross_pnl_inr": pnl, "est_charges_inr": 100, "slippage_inr": 50, "mae_pct": -5, "mfe_pct": 5, "capital_deployed": 15000, "data_source_status": "VERIFIED_HISTORICAL"})
    wf = RS.walk_forward(rows, min_months=6)
    assert wf["test_from"] == "2025-07" and wf["days_traded"] == 40 and wf["days_skipped"] == 40          # quiet days traded, volatile days skipped
    assert wf["out_of_sample"]["win_rate_pct"] == 100.0 and wf["rules_today_from_all_data"]["MODE_2_VOLATILE | DTE 0"]["rule"] is None


def test_ema_vwap_indicators_on_three_minute_candles():
    from src.research import ema_vwap as EV
    d = date(2026, 11, 17)
    bars = {}
    for i in range(30):
        t = (datetime(2026, 11, 17, 9, 15) + timedelta(minutes=i)).strftime("%H:%M")
        px = 100 - i * 0.5 if i < 15 else 92.5 + (i - 15) * 1.0                       # falls, then rallies
        bars[t] = (px, px + 0.2, px - 0.2, px, 10.0)
    three = EV.three_minute(bars)
    assert three[0][:2] == ("09:15", "09:18") and three[0][2] == 100 and three[0][5] == 99.0 and three[0][6] == 30.0
    rows = EV.indicators({d: bars}, [d])[d]
    s, e, o, h, l, c, ema, vw = rows[0]
    assert ema == c and abs(vw - (o + h + l + c) / 4) < 1e-9                              # VWAP starts at the first candle's (O+H+L+C)/4
    crosses = [(rows[i][1], "up" if rows[i][6] > rows[i][7] else "down") for i in range(1, len(rows)) if (rows[i - 1][6] - rows[i - 1][7]) * (rows[i][6] - rows[i][7]) < 0]
    assert crosses and crosses[-1][1] == "up"                                            # the rally lifts EMA9 back above VWAP
