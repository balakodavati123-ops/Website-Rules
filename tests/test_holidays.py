import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import engine as EN       # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
GURPURB = {"name": "Guru Nanak Jayanti", "closed": ["NSE", "NFO", "CDS", "BSE", "BFO", "BCD"],
           "open": {"MCX": (datetime(2026, 11, 24, 17, 0, tzinfo=IST).timestamp(), datetime(2026, 11, 24, 23, 55, tzinfo=IST).timestamp())}}


def test_sessions_close_nse_and_fno_on_a_holiday_and_keep_mcx_to_its_window(monkeypatch):
    monkeypatch.setattr(EN, "HOL", {"day": "2026-11-24", "at": 0.0, **GURPURB})
    noon, evening = datetime(2026, 11, 24, 12, 0, tzinfo=IST), datetime(2026, 11, 24, 18, 0, tzinfo=IST)
    assert EN.sessions(noon) == {"equity": False, "fno": False, "mcx": False, "crypto": True}
    assert EN.sessions(evening)["mcx"] and not EN.sessions(evening)["fno"]
    nxt = datetime(2026, 11, 25, 12, 0, tzinfo=IST)                                  # yesterday's holiday never closes today's market
    assert EN.sessions(nxt) == {"equity": True, "fno": True, "mcx": True, "crypto": True}


def test_trades_booked_on_a_closed_market_are_voided(monkeypatch):
    monkeypatch.setattr(EN, "HOL", {"day": "2026-11-24", "at": 0.0, **GURPURB})
    xb = {"trades": [{"id": "F1", "desk": "FNO", "strategy": "long_straddle", "day": "2026-11-24", "opened": "10:00:06", "status": "OPEN", "pnl_rs": -284.75},
                     {"id": "F0", "desk": "FNO", "strategy": "long_straddle", "day": "2026-11-23", "opened": "10:00:04", "status": "WIN", "pnl_rs": 900.0},
                     {"id": "C1", "desk": "COMMODITY", "strategy": "mcx_momentum", "day": "2026-11-24", "opened": "11:00:00", "status": "LOSS", "pnl_rs": -50.0},
                     {"id": "C2", "desk": "COMMODITY", "strategy": "mcx_momentum", "day": "2026-11-24", "opened": "18:30:00", "status": "OPEN", "pnl_rs": 20.0},
                     {"id": "K1", "desk": "CRYPTO", "strategy": "x", "day": "2026-11-24", "opened": "11:00:00", "status": "OPEN", "pnl_rs": 5.0}]}
    gone = EN.void_holiday_trades([xb], "2026-11-24", datetime(2026, 11, 24, 12, 40, tzinfo=IST))
    assert gone == ["F1", "C1"]
    by = {t["id"]: t for t in xb["trades"]}
    assert by["F1"]["status"] == "VOID" and by["F1"]["pnl_rs"] == 0.0 and "Guru Nanak Jayanti" in by["F1"]["why"]
    assert by["F0"]["status"] == "WIN" and by["C2"]["status"] == "OPEN" and by["K1"]["status"] == "OPEN"
    assert EN.void_holiday_trades([xb], "2026-11-24", datetime(2026, 11, 24, 12, 41, tzinfo=IST)) == []        # once only
