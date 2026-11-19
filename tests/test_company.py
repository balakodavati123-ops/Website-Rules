import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ceo_inbox as CI     # noqa: E402
import company as CO       # noqa: E402
import desks as D          # noqa: E402
import quant as Q          # noqa: E402

IST = D.IST
EOD = datetime(2026, 11, 19, 15, 50, tzinfo=IST)


def tr(i, desk="EQUITY", strat="scalp_vwap_pullback", pnl=100.0, status="WIN", why="target", day="2026-11-19", opened="10:00:00", **kw):
    t = {"id": f"T{i}", "desk": desk, "strategy": strat, "label": f"X{i} long", "symbol": f"X{i}", "side": "LONG", "entry": 100.0, "stop": 99.7, "target_px": 100.45, "qty": 100,
         "status": status, "pnl_rs": pnl, "why": why, "day": day, "opened": opened, "closed": "10:10:00"}
    t.update(kw)
    return t


def test_quant_baseline_breakeven_and_kelly():
    assert abs(Q.baseline_p(1, 1.5) - 0.4) < 1e-9                       # a 1.5R target is reached first 40% of the time by chance
    assert abs(Q.breakeven_p(100, 150) - 0.4) < 1e-9 and Q.breakeven_p(100, 150, 20) > 0.4      # charges raise the bar
    assert abs(Q.kelly(0.4, 1.5)) < 1e-9 and Q.kelly(0.5, 1.5) > 0
    n = Q.trade_numbers(100, 99.7, 100.45, 100, cost=40, sigma_pct=0.4)
    assert n["base_p"] == 0.4 and n["stop_sigma"] == 0.75 and n["warnings"] and n["ev_rs"] < 0      # stop inside the noise, negative expectation at the baseline
    closes = [100 * (1.001 if i % 2 else 0.999) ** i for i in range(60)]
    assert Q.sigma_bars(closes, 10) > Q.sigma_bars(closes, 1) > 0


def test_team_edge_test_against_random():
    lucky = [tr(i, pnl=45, why="target") for i in range(8)] + [tr(10 + i, pnl=-30, status="LOSS", why="stop") for i in range(2)]
    r = Q.team_numbers(lucky)
    assert r["n"] == 10 and r["target_hits"] == 8 and r["expected_hits"] == 4.0 and r["edge_z"] > 2


def test_floor_shows_every_team_with_three_agents_and_what_they_do():
    st = CO.new_state()
    v = CO.build(st, datetime(2026, 11, 19, 11, 0, tzinfo=IST), [tr(1, status="OPEN", pnl=20.0), tr(2, desk="FNO", strat="credit_spread")], [], {"sessions": {"equity": True}})
    assert [t["id"] for t in v["teams"]] == [t["id"] for t in CO.TEAMS]
    sc = v["teams"][0]
    assert len(sc["agents"]) == 3 and sc["agents"][2]["doing"].startswith("Holding 1") and "1-minute" in sc["agents"][0]["doing"]
    assert v["coo"]["name"] == "Raghav" and v["teams"][3]["today"]["trades"] == 1


def test_end_of_day_bonuses():
    st = CO.new_state()
    trades = [tr(1, pnl=300.0), tr(2, desk="CRYPTO", strat="crypto_breakout", pnl=-50.0, status="LOSS")]
    v = CO.build(st, EOD, trades, [], {"nifty_chg": -0.4, "equity": 100000})
    assert st["tokens"]["team:scalp"] == 500 and st["eco"]["scalp"]["balance"] < st["eco"]["scalp"]["carried"] + 61 and st["eco"]["scalp"]["carried"] >= 500    # the bonus is the team's food
    assert st["tokens"]["Raghav"] == 1000 and any(m["kind"] == "award" for m in v["messages"])
    CO.build(st, EOD, trades, [], {"nifty_chg": -0.4})
    assert st["tokens"]["team:scalp"] == 500                            # once a day
    st2 = CO.new_state()
    CO.build(st2, EOD, [tr(1, pnl=-10.0, status="LOSS")], [], {"nifty_chg": 0.5})
    assert not st2["tokens"]


def test_coo_asks_before_retiring_and_proposes_a_new_team():
    st = CO.new_state()
    losers = [tr(i, pnl=-160.0, status="LOSS", why="time") for i in range(35)]
    stats = [{"desk": "EQUITY", "strategy": "scalp_vwap_pullback", "closed": 35, "wins": 0, "win_rate": 0.0, "pnl_rs": -2100.0, "avg_rs": -60.0, "t_stat": -5, "confidence": 0, "verdict": "PAUSED"}]
    now = datetime(2026, 11, 19, 12, 0, tzinfo=IST)
    v = CO.build(st, now, losers, stats, {"scalp_params": {"vol_x": 1.2}})
    req = next(r for r in v["coo"]["requests"] if r.get("variant"))
    assert any(r.get("kind") == "team" for r in v["coo"]["requests"])                  # the team is also out of food: the COO asks about the whole team too
    assert req["status"] == "pending" and req["variant"]["params"]["vol_x"] == 1.5 and "time" in req["variant"]["why"]
    assert "scalp_vwap_pullback" not in st["retired"]                                   # nothing is retired without the CEO
    CO.build(st, now, losers, stats, {})
    assert len(st["requests"]) == 2                                                     # asked once each
    CO.apply(st, {"kind": "approve", "arg": req["id"]}, now)
    assert "scalp_vwap_pullback" in st["retired"] and st["variants"]["scalp"]["params"]["vol_x"] == 1.5
    assert "scalp_vwap_pullback" in CO.paused_strategies(st, set(), {})


def test_ceo_reject_keeps_the_team_and_pause_resume_work():
    st = CO.new_state()
    st["requests"].append({"id": "R1", "team": "mcx", "strategy": "mcx_pullback", "status": "pending"})
    now = datetime(2026, 11, 19, 12, 0, tzinfo=IST)
    CO.apply(st, {"kind": "reject", "arg": "r1"}, now)
    assert "mcx_pullback" not in CO.paused_strategies(st, {"mcx_pullback"}, {})
    CO.apply(st, {"kind": "pause", "arg": "crypto"}, now)
    assert st["paused_teams"] == ["crypto"]
    CO.apply(st, {"kind": "resume", "arg": "Crypto desk"}, now)
    assert st["paused_teams"] == []


def test_inbox_obeys_only_the_owner():
    assert CI.parse("CEO APPROVE R261119-scalp-1") == {"kind": "approve", "arg": "R261119-scalp-1"}
    assert CI.parse("ceo: pause scalp")["kind"] == "pause" and CI.parse("Bug report") is None and CI.parse("CEO well done team")["kind"] == "note"
    issues = [{"number": 1, "title": "CEO APPROVE R1", "author_association": "OWNER", "user": {"login": "someone"}},
              {"number": 2, "title": "CEO APPROVE R1", "author_association": "NONE", "user": {"login": "stranger"}},
              {"number": 3, "title": "Something else", "author_association": "OWNER", "user": {"login": "owner"}}]
    cmds = CI.poll("t", "owner/repo", call=lambda *a, **k: issues)
    assert [(c["issue"], c["owner"]) for c in cmds] == [(1, True), (2, False)]


def test_hunger_drives_the_hunt_but_losses_cap_it():
    st = CO.new_state()
    open_ses = {"equity": True, "fno": True, "mcx": True, "crypto": True}
    morning = datetime(2026, 11, 19, 11, 0, tzinfo=IST)
    v = CO.build(st, morning, [], [], {"sessions": open_ses})
    eco = {t["id"]: t["eco"] for t in v["teams"]}
    assert eco["intraday"]["mood"] == "Hungry" and st["effort"]["intraday"] == 3                       # nothing earned and an idle morning: hunts hardest
    assert eco["intraday"]["balance"] == CO.START_TOKENS - CO.LIVING * 7
    fed = [tr(i, desk="EQUITY", strat="momentum", pnl=150.0, opened="10:50:00", setup="momentum") for i in range(3)]       # Rs 450 net earns 45 tokens, more than the 35 a day the row eats
    v = CO.build(st, morning, fed, [], {"sessions": open_ses})
    assert {t["id"]: t["eco"] for t in v["teams"]}["intraday"]["mood"] in ("Fed", "Thriving") and st["effort"]["intraday"] == 0
    st2 = CO.new_state()
    losing = [tr(i, desk="EQUITY", strat="momentum", pnl=-40.0, status="LOSS", why="stop", day="2026-11-18", setup="momentum") for i in range(10)]
    CO.build(st2, morning, losing, [], {"sessions": open_ses})
    assert st2["effort"]["intraday"] <= 1                                                               # injured: may not hunt harder
    seats = next(t for t in v["teams"] if t["id"] == "intraday")["seats"]
    assert len(seats) == 7 and seats[-1]["officer"] and seats[-1]["name"] == "Vikram"
