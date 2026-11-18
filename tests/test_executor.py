import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import executor as X  # noqa: E402

NOW = datetime(2026, 11, 18, 11, 0, tzinfo=X.IST)


def eq(status="OPEN", **k):
    t = {"id": "E261118-1", "desk": "EQUITY", "strategy": "price_only", "label": "HAL long", "side": "LONG", "entry": 4800.0, "last": 4810.0, "exit": "", "qty": 1, "status": status, "pnl_rs": 0.0,
         "day": "2026-11-18", "opened": "10:30:00", "instrument_key": "NSE_EQ|INE066F01020"}
    t.update(k)
    return t


class Fake:
    def __init__(self): self.calls = []
    def __call__(self, url, body, token, algo=""):
        self.calls.append((url, body, token, algo))
        return 200, {"status": "success", "data": {"order_ids": [f"o{len(self.calls)}"]}}


def env(monkeypatch, **kv):
    for k in ("EXEC_MODE", "UPSTOX_EXEC_TOKEN", "EXEC_LIVE_CONFIRM", "EXEC_KILL", "EXEC_MAX_ORDER_RS", "EXEC_MAX_DAY_LOSS_RS", "EXEC_ALGO_NAME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def test_off_sends_nothing(tmp_path, monkeypatch):
    env(monkeypatch); f = Fake()
    st = X.run([eq()], [], tmp_path / "x.json", f, NOW)
    assert f.calls == [] and st["mode"] == "off"


def test_sandbox_sends_once_and_closes(tmp_path, monkeypatch):
    env(monkeypatch, EXEC_MODE="sandbox", UPSTOX_EXEC_TOKEN="t", EXEC_MAX_ORDER_RS="10000"); f = Fake(); p = tmp_path / "x.json"
    X.run([eq()], [], p, f, NOW); X.run([eq()], [], p, f, NOW)
    assert len(f.calls) == 1                                           # a second pass never re-sends the same trade
    url, b, tok, _ = f.calls[0]
    assert url == "https://api-sandbox.upstox.com/v3/order/place" and b["transaction_type"] == "BUY" and b["order_type"] == "LIMIT" and b["price"] >= 4800 * 1.003 - 0.05 and b["product"] == "I"
    X.run([eq("WIN", exit=4850.0, pnl_rs=50.0)], [], p, f, NOW)
    assert len(f.calls) == 2 and f.calls[1][1]["transaction_type"] == "SELL"


def test_short_buys_back_and_caps(tmp_path, monkeypatch):
    env(monkeypatch, EXEC_MODE="sandbox", UPSTOX_EXEC_TOKEN="t", EXEC_MAX_ORDER_RS="1000"); f = Fake()
    st = X.run([eq()], [], tmp_path / "x.json", f, NOW)
    assert f.calls == [] and "cap" in st["held"][0]["why"]


def test_options_buy_legs_first(tmp_path, monkeypatch):
    env(monkeypatch, EXEC_MODE="sandbox", UPSTOX_EXEC_TOKEN="t"); f = Fake()
    t = {"id": "F261118-1", "desk": "FNO", "strategy": "credit_spread", "label": "NIFTY credit spread", "side": "SHORT", "entry": 20.0, "last": 20.0, "qty": 1, "lot": 65, "status": "OPEN", "pnl_rs": 0.0, "day": "2026-11-18", "opened": "10:00:00",
         "legs": [{"side": "S", "strike": 25000, "kind": "PE", "entry": 60.0, "last": 60.0, "key": "NSE_FO|1"}, {"side": "B", "strike": 24850, "kind": "PE", "entry": 40.0, "last": 40.0, "key": "NSE_FO|2"}]}
    X.run([t], [], tmp_path / "x.json", f, NOW)
    assert [c[1]["transaction_type"] for c in f.calls] == ["BUY", "SELL"] and all(c[1]["quantity"] == 65 for c in f.calls)


def test_live_needs_the_gate_and_kill_switch_stops(tmp_path, monkeypatch):
    env(monkeypatch, EXEC_MODE="live", UPSTOX_EXEC_TOKEN="t", EXEC_MAX_ORDER_RS="10000"); f = Fake()
    X.run([eq()], [], tmp_path / "x.json", f, NOW)
    assert f.calls == []                                               # no confirmation, strategy not ready
    env(monkeypatch, EXEC_MODE="live", UPSTOX_EXEC_TOKEN="t", EXEC_LIVE_CONFIRM="I-UNDERSTAND-REAL-MONEY", EXEC_MAX_ORDER_RS="10000")
    stats = [{"strategy": "price_only", "verdict": "READY FOR REVIEW"}]
    (tmp_path / "KILL").write_text("")
    X.run([eq()], stats, tmp_path / "x.json", f, NOW)
    assert f.calls == []                                               # kill switch wins
    (tmp_path / "KILL").unlink()
    X.run([eq()], stats, tmp_path / "x.json", f, NOW)
    assert len(f.calls) == 1 and f.calls[0][0].startswith("https://api-hft.upstox.com/v3")


def test_day_loss_stops_new_entries(tmp_path, monkeypatch):
    env(monkeypatch, EXEC_MODE="sandbox", UPSTOX_EXEC_TOKEN="t", EXEC_MAX_ORDER_RS="10000", EXEC_MAX_DAY_LOSS_RS="100"); f = Fake(); p = tmp_path / "x.json"
    X.run([eq()], [], p, f, NOW)
    lost = eq("LOSS", exit=4700.0, pnl_rs=-150.0)
    second = eq(id="E261118-2", label="TCS long", instrument_key="NSE_EQ|X")
    X.run([lost, second], [], p, f, NOW)
    assert not any(c[1]["tag"].startswith("E261118-2") for c in f.calls)
