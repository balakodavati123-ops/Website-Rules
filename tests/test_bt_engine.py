"""docs/bt.js (the dashboard's backtester) through Node: fills, the stop-first rule, gaps, charges and the strategies on synthetic candles."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")

JS = r"""
const BT = require(process.argv[1]);
const IST = 19800, day0 = Date.UTC(2025, 0, 6) / 1000 - IST + 555 * 60;      // Monday 6 Jan 2025, 09:15 IST
function mk(days, f) { const a = []; for (let d = 0; d < days; d++) for (let i = 0; i < 375; i++) { const [o, h, l, c] = f(d, i); a.push(day0 + d * 86400 + i * 60, o * 100, h * 100, l * 100, c * 100); } return BT.decode(Int32Array.from(a).buffer); }
const out = {};
// a test strategy: enter long on the 10:00 one-minute candle, target 20 points, stop 10 points
BT.STRATS.push({ id: 't', name: 't', tf: 1, params: [], fixed: { from: '09:16', to: '15:00', exit: '15:15', maxTrades: 1 }, entry: (B, X, i) => B.m[i] === 600 ? { side: 1, tgt: 20, stp: 10 } : null });
// day 1: the 10:01 candle opens at 100.5 and both levels sit inside the 10:03 candle -> the stop counts first
let D = mk(1, (d, i) => i === 46 ? [100.5, 101, 100, 100.8] : i === 48 ? [101, 125, 85, 101] : [100, 100.2, 99.8, 100]);
let R = BT.run(D, 't', { mode: 'index', money: { costPts: 0 } });
out.stopFirst = R.trades.map((t) => [t.inT, t.entry, t.why, t.exit, t.pts]);
// day 2: the market gaps through the stop at 10:05's open -> filled at that open, not at the stop
D = mk(1, (d, i) => i === 46 ? [100.5, 101, 100, 100.8] : i >= 50 ? [80, 81, 79, 80] : [100, 100.2, 99.8, 100]);
out.gap = BT.run(D, 't', { mode: 'index', money: { costPts: 0 } }).trades.map((t) => [t.why, t.exit, t.pts]);
// day 3: nothing hits -> out at the 15:15 exit, futures charges as NSE's schedule
D = mk(1, (d, i) => i === 46 ? [100.5, 101, 100, 100.8] : [100, 100.2, 99.8, 100]);
R = BT.run(D, 't', { mode: 'futures', money: { lot: 65, slipPts: 0 } });
out.time = R.trades.map((t) => [t.why, t.outT, t.pts, +t.fees.toFixed(2), +t.net.toFixed(2)]);
out.fees = +BT.futFees(25000 * 65, 25050 * 65).toFixed(2);
R = BT.run(D, 't', { mode: 'option', money: { lot: 65, delta: 0.5, thetaPtsHr: 3, slipPts: 1, feesRs: 60 } });
out.option = R.trades.map((t) => [t.holdMin, +t.net.toFixed(2)]);
// the five strategies run on a trending, then reverting synthetic week without errors, and stats add up
D = mk(5, (d, i) => { const p = 20000 + (d % 2 ? -1 : 1) * i * 0.8 + 15 * Math.sin(i / 7); return [p, p + 4, p - 4, p + (i % 3) - 1]; });
out.five = BT.STRATS.filter((s) => s.id !== 't').map((s) => { const R = BT.run(D, s.id, { mode: 'index' }); const S = R.stats; return [s.id, S.trades, S.trades ? +(S.wins / S.trades * 100).toFixed(4) === +S.winRate.toFixed(4) : true, R.trades.every((t) => t.inT >= '09:16' && t.outT <= '15:30')]; });
out.patterns = Object.keys(BT.patterns(D));
console.log(JSON.stringify(out));
"""


def _run():
    r = subprocess.run(["node", "-e", JS, str(ROOT / "docs" / "bt.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_fills_stop_first_gaps_time_exit_and_charges():
    o = _run()
    assert o["stopFirst"] == [["10:01", 100.5, "stop", 90.5, -10]]           # entered at the next candle's open; stop before target in one candle
    assert o["gap"] == [["stop", 80, -20.5]]                                  # a gap through the stop fills at the open
    why, out_t, pts, fees, net = o["time"][0]                                 # at a price of 100 the charges are mostly Rs 40 brokerage + GST
    assert (why, out_t, pts) == ("time", "15:15", -0.5) and 45 < fees < 55 and abs(net - (-0.5 * 65 - fees)) < 0.01
    assert 470 < o["fees"] < 480                                              # one NIFTY lot at 25,000: STT, exchange, stamp, GST, brokerage
    hold, net_o = o["option"][0]
    assert hold == 314 and abs(net_o - ((0.5 * -0.5 - 3 * 314 / 60 - 1) * 65 - 60)) < 0.01


def test_five_strategies_run_and_patterns_build():
    o = _run()
    assert [x[0] for x in o["five"]] == ["trend_pullback", "orb_trend", "vwap_snapback", "gap_fill", "ema_st_adx", "reel_wick", "reel_written"]
    assert all(x[2] and x[3] for x in o["five"])
    assert {"gaps", "firstHour", "byDow", "expiry", "month"} <= set(o["patterns"])
