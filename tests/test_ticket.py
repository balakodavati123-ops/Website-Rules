from datetime import datetime, timedelta

import pytest

from trading_team.ticket import IST, build_ticket

NOW = datetime(2026, 11, 12, 10, 0, 0, tzinfo=IST)


def bel(**kw):
    base = dict(ticker="BEL", entry=393.0, stop=376.0, target=470.0, equity=102797.0,
                risk_frac=0.005, now=NOW)
    base.update(kw)
    return build_ticket(**base)


def test_reproduces_the_daily_report_sizing():
    t = bel()
    # The 11 Nov report: 30 shares, stop 4.33%, target 19.59%, R:R 4.53, value about Rs 11,790.
    assert t.qty == 30
    assert (t.stop_pct, t.target_pct, t.reward_to_risk) == (4.33, 19.59, 4.53)
    assert t.position_value == 11790.0
    assert t.risk_rs == 510.0


def test_ready_when_price_is_near_entry_and_fresh():
    t = bel(live_price=393.4, price_time=NOW - timedelta(seconds=20))
    assert t.status == "READY"


def test_waiting_when_price_has_run_away():
    t = bel(live_price=400.3, price_time=NOW - timedelta(seconds=10))
    assert t.status == "WAITING"
    assert any("Do not raise the limit" in c.detail for c in t.checks)


def test_stale_price_blocks_the_ticket():
    t = bel(live_price=393.0, price_time=NOW - timedelta(minutes=10))
    assert t.status == "DO NOT TRADE"


def test_price_below_stop_blocks():
    t = bel(live_price=374.0, price_time=NOW)
    assert t.status == "DO NOT TRADE"


def test_open_risk_cap_shrinks_or_blocks_the_position():
    t = bel(open_risk_rs=0.04 * 102797 - 100)       # only Rs 100 of risk budget left
    assert t.qty == 5 and t.risk_rs <= 100
    full = bel(open_risk_rs=0.04 * 102797)
    assert full.qty == 0 and full.status == "DO NOT TRADE"


def test_position_cap_30_percent():
    t = build_ticket(ticker="X", entry=100.0, stop=99.0, target=104.0, equity=100000.0,
                     risk_frac=0.01, now=NOW)         # risk-sized would be 1000 shares = 100%
    assert t.pct_of_equity <= 30.0


def test_poor_reward_to_risk_blocks():
    t = bel(target=400.0)
    assert t.status == "DO NOT TRADE"


def test_high_vix_blocks():
    t = bel(vix=24.0, live_price=393.0, price_time=NOW)
    assert t.status == "DO NOT TRADE"


def test_bad_levels_raise():
    with pytest.raises(ValueError):
        bel(stop=395.0)
