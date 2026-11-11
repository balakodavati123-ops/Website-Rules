import json
from datetime import datetime, timedelta

from trading_team.__main__ import main
from trading_team.movers import parse, render_board, tag, warnings_for
from trading_team.ticket import IST, build_ticket, levels_from_pct

NOW = datetime(2026, 11, 12, 9, 20, 0, tzinfo=IST)

GAINERS = {"result": json.dumps({"category": "top-gainers", "count": 3, "stocks": [
    {"symbol": "AVANTEL", "price": 161.21, "change_pct": 15.08, "volume": 20260180,
     "market_cap_category": "Small Cap", "circuit_upper_limit": 168.09, "circuit_lower_limit": 112.07},
    {"symbol": "TINY", "price": 50.0, "change_pct": 9.0, "volume": 1000,
     "market_cap_category": "Small Cap", "circuit_upper_limit": 55.0, "circuit_lower_limit": 45.0},
    {"symbol": "LOCKED", "price": 109.9, "change_pct": 10.0, "volume": 9000000,
     "market_cap_category": "Small Cap", "circuit_upper_limit": 110.0, "circuit_lower_limit": 90.0}]})}


def test_levels_from_pct_matches_the_backtest_convention():
    assert levels_from_pct(400.0, 5, 20) == (380.0, 480.0)


def test_open_mode_gap_check():
    stop, target = levels_from_pct(1640.0, 5, 20)
    ok = build_ticket(ticker="ICICIBANK", entry=1640.0, stop=stop, target=target,
                      equity=100000, live_price=1640.0, price_time=NOW, now=NOW,
                      reference_price=1608.0, max_gap_pct=3.0)
    assert ok.status == "READY"                      # +2.0% gap is inside the limit
    stop, target = levels_from_pct(1700.0, 5, 20)
    bad = build_ticket(ticker="ICICIBANK", entry=1700.0, stop=stop, target=target,
                       equity=100000, live_price=1700.0, price_time=NOW, now=NOW,
                       reference_price=1608.0, max_gap_pct=3.0)
    assert bad.status == "DO NOT TRADE"              # +5.7% gap: the premise changed


def test_movers_tags():
    cat, stocks = parse(GAINERS)
    assert cat == "top-gainers"
    tags = {s["symbol"]: tag(s) for s in stocks}
    assert "LATE, do not chase" in tags["AVANTEL"]
    assert "THIN" in tags["TINY"]
    assert "AT UPPER CIRCUIT" in tags["LOCKED"]
    assert "AVANTEL" in render_board({cat: stocks})


def test_candidate_warnings():
    cat, stocks = parse(GAINERS)
    w = warnings_for("AVANTEL", {cat: stocks})
    assert any("do not chase" in x for x in w)
    assert warnings_for("RELIANCE", {cat: stocks}) == []
    losers = {"top-losers": [{"symbol": "XYZ", "price": 10, "change_pct": -8, "volume": 1}]}
    assert any("top-losers" in x for x in warnings_for("XYZ", losers))


def _rec(tmp_path, **kw):
    rec = {"run_date": "2026-11-12", "action": "BUY", "ticker": "ICICIBANK.NS",
           "entry_price": 1608.0, "stop_pct": 5.0, "target_pct": 20.0,
           "stop_loss": 1527.6, "target": 1929.6, "strategy": "breakout_52w (PROBATION)",
           "rationale": "x", "risk_notes": []}
    rec.update(kw)
    f = tmp_path / "rec.json"
    f.write_text(json.dumps(rec))
    return str(f)


def test_cli_open_mode_prints_ticket(tmp_path, capsys):
    now = datetime.now(IST).strftime("%H:%M:%S")
    main(["--ledger", str(tmp_path / "l.sqlite"), "ticket", "--from-json", _rec(tmp_path),
          "--mode", "open", "--live-price", "1620", "--price-time", now, "--equity", "100000"])
    out = capsys.readouterr().out
    assert "ORDER TICKET: ICICIBANK " in out and ".NS" not in out and "LIMIT 1620.0" in out
    assert "STOP  trigger 1539.0" in out and "SELL  target 1944.0" in out


def test_cli_no_trade_file_prints_reason(tmp_path, capsys):
    f = _rec(tmp_path, action="NO_TRADE", ticker=None,
             rationale="No tested strategy gave an entry signal today.")
    main(["--ledger", str(tmp_path / "l.sqlite"), "ticket", "--from-json", f,
          "--equity", "100000"])
    assert "NO TRADE on 2026-11-12" in capsys.readouterr().out
