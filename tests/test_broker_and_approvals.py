import io
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import broker as BR        # noqa: E402
import ceo_inbox as CI     # noqa: E402


class R(io.BytesIO):
    pass


def _opener(table):
    def op(req, timeout=20):
        assert req.get_method() == "GET" and req.headers["Authorization"] == "Bearer tok"
        for k, v in table.items():
            if k in req.full_url:
                if isinstance(v, int):
                    raise urllib.error.HTTPError(req.full_url, v, "x", {}, None)
                return R(json.dumps({"status": "success", "data": v}).encode())
        raise AssertionError(req.full_url)
    return op


def test_broker_snapshot_reads_wallet_holdings_positions_only():
    op = _opener({"get-funds-and-margin": {"equity": {"available_margin": 85000.5, "used_margin": 15000.0, "payin_amount": 0}},
                  "long-term-holdings": [{"tradingsymbol": "TCS", "quantity": 2, "average_price": 3500, "last_price": 3600, "pnl": 200, "day_change_percentage": 0.5}],
                  "short-term-positions": [{"tradingsymbol": "NIFTY25DEC26000CE", "quantity": 65, "average_price": 120, "last_price": 135, "pnl": 975, "product": "D", "exchange": "NFO"}]})
    s = BR.snapshot("tok", "2026-11-27T10:00:00+05:30", op)
    assert s["ok"] and s["wallet"]["available"] == 85000.5 and s["holdings_value"] == 7200 and s["holdings_pnl"] == 200 and s["positions_pnl"] == 975
    assert BR.snapshot("", "t")["reason"] == "no broker token"
    bad = BR.snapshot("tok", "t", _opener({"get-funds-and-margin": 401}))
    assert not bad["ok"] and bad["reason"] == "token expired or not valid"


def test_strategy_approval_titles_parse():
    assert CI.parse("CEO APPROVE STRATEGY EMA 9/21, 60-min|trailing 3 ATR after +2 + opposite signal|no filter") == \
        {"kind": "approve", "arg": "STRATEGY EMA 9/21, 60-min|trailing 3 ATR after +2 + opposite signal|no filter"}
    assert CI.parse("CEO REJECT STRATEGY x")["kind"] == "reject"
