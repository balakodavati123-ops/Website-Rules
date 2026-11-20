import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import company as CO   # noqa: E402
import lab as LB       # noqa: E402
import llm as LL       # noqa: E402


def tr(i, pnl, status, day, why="target", strat="momentum"):
    return {"id": f"T{i}", "desk": "EQUITY", "strategy": strat, "label": f"X{i}", "entry": 100.0, "stop": 99.0, "target_px": 102.0, "qty": 10, "status": status, "pnl_rs": pnl,
            "why": why, "day": day, "opened": "10:00:00", "closed": "10:30:00"}


def test_lab_stages_and_checks():
    good = [tr(i, 60.0, "WIN", f"2026-11-{1 + i % 20:02d}") if i % 3 else tr(i, -25.0, "LOSS", f"2026-11-{1 + i % 20:02d}", "stop") for i in range(40)]
    lab = LB.build(good, [{"strategy": "momentum", "verdict": "WORKING"}], CO.new_state(), CO.team_of)
    row = lab["strategies"][0]
    assert row["stage"] == "APPROVED" and row["passed"] == 7 and lab["approved"] == ["momentum"]
    few = LB.build(good[:12], [], CO.new_state(), CO.team_of)["strategies"][0]
    assert few["stage"] == "TESTED" and next(c for c in few["checks"] if c["name"] == "Enough trades")["ok"] is False
    st = CO.new_state()
    st["retired"].append("momentum")
    assert LB.build(good, [], st, CO.team_of)["strategies"][0]["stage"] == "REJECTED"
    bad = [tr(i, -40.0 if i % 2 else 30.0, "LOSS" if i % 2 else "WIN", f"2026-11-{1 + i % 20:02d}", "stop" if i % 2 else "target") for i in range(40)]
    assert LB.build(bad, [], CO.new_state(), CO.team_of)["strategies"][0]["stage"] == "INVESTIGATE"


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.messages = NS(create=self._create)
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        return NS(model=kw["model"], stop_reason="end_turn", usage=NS(input_tokens=2000, output_tokens=400, cache_creation_input_tokens=0, cache_read_input_tokens=0),
                  content=[NS(type="text", text='{"mood": "mixed", "brief": "Two sentences.", "themes": [], "companies": []}')])


def test_llm_budget_caps_spending():
    u, c = LL.new_usage(), FakeClient()
    d = LL.Desk(u, env={"ANTHROPIC_API_KEY": "x", "LLM_USD_5H": "0.01", "LLM_USD_DAY": "0.02"}, client=c)
    heads = [{"headline": f"Company {i} wins an order", "source": "ET"} for i in range(10)]
    assert LL.news_digest(d, heads)["mood"] == "mixed" and u["by_kind"]["news"]["calls"] == 1
    assert abs(u["calls"][0]["usd"] - (2000 * 0.10 + 400 * 0.50) / 1e6) < 1e-9
    assert d.ask("review", "s", "p" * 3000, "review") is None and u["refused"] == 1          # Opus could cost more than the 5-hour cap: not sent
    assert c.calls == 1
    off = LL.Desk(LL.new_usage(), env={})
    assert not off.on and off.ask("news", "s", "p") is None
