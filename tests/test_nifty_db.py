import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import nifty_db as NDB      # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
SESSIONS = {"2022-01-03": 375, "2022-01-04": 375, "2022-01-05": 372, "2022-01-06": 375}     # 5 Jan is missing three minutes


def _bars(day, n, start="09:15", base=17000.0):
    t0 = datetime.fromisoformat(f"{day}T{start}:00+05:30")
    out = []
    for i in range(n):
        if day == "2022-01-05" and i in (100, 101, 102):
            continue
        p = base + i
        out.append([(t0 + timedelta(minutes=i)).isoformat(), p, p + 2, p - 1, p + 1, 0, 0])
    return out


class FakeUpstox:
    def __init__(self, today_bars=None, bad=False):
        self.calls, self.today_bars, self.bad = [], today_bars or [], bad

    def __call__(self, url, token):
        self.calls.append(url)
        if "/intraday/" in url:
            return json.dumps({"data": {"candles": list(reversed(self.today_bars))}}).encode()
        to, frm = url.rstrip("/").split("/")[-2:]
        if "/days/" in url:
            c = [[f"{d}T00:00:00+05:30", 0, 0, 0, 17000.0 + 374, 0, 0] for d in SESSIONS if frm <= d <= to and d != "2022-01-04"] + \
                [["2022-01-07T00:00:00+05:30", 0, 0, 0, 1, 0, 0]] * (frm <= "2022-01-07" <= to)
            return json.dumps({"data": {"candles": c}}).encode()
        c = [b for d, n in SESSIONS.items() if frm <= d <= to for b in _bars(d, 375 if n == 372 else n)]
        if self.bad:
            c.append(["2022-01-06T16:00:00+05:30", 100, 90, 95, 99, 0, 0])                     # high below the open: dropped
        return json.dumps({"data": {"candles": list(reversed(c))}}).encode()


def test_builds_one_database_with_a_friendly_view_and_checks(tmp_path):
    fake = FakeUpstox(bad=True)
    m = NDB.build(tmp_path, "t", now=datetime(2022, 1, 8, 10, 0, tzinfo=IST), get=fake, log=lambda *a: None)
    con = sqlite3.connect(tmp_path / NDB.DB)
    assert m["sessions"] == 4 and m["candles"] == 375 * 3 + 372 and m["first_day"] == "2022-01-03" and m["last_day"] == "2022-01-06"
    assert m["dropped_bad_candles_this_run"] == 1 and [s["day"] for s in m["short_sessions"]] == ["2022-01-05"]
    assert m["missing_sessions"] == ["2022-01-07"]                                            # a session Upstox lists but has no minutes for
    row = con.execute("SELECT day, time, open, high, low, close FROM nifty50_1m ORDER BY ts LIMIT 1").fetchone()
    assert row == ("2022-01-03", "09:15", 17000.0, 17002.0, 16999.0, 17001.0)
    d = con.execute("SELECT open, high, low, close, candles, first, last, complete, official_close, close_diff FROM days WHERE day = '2022-01-03'").fetchone()
    assert d == (17000.0, 17376.0, 16999.0, 17375.0, 375, "09:15", "15:29", 1, 17374.0, 1.0)
    assert con.execute("SELECT official_close FROM days WHERE day = '2022-01-04'").fetchone()[0] is None
    assert json.loads((tmp_path / NDB.COVER).read_text())["sessions"] == 4


def test_update_adds_only_new_sessions_and_today_after_the_close(tmp_path):
    NDB.build(tmp_path, "t", now=datetime(2022, 1, 8, 10, 0, tzinfo=IST), get=FakeUpstox(), log=lambda *a: None)
    fake = FakeUpstox(today_bars=_bars("2022-01-10", 375, base=17500.0))
    early = NDB.build(tmp_path, "t", now=datetime(2022, 1, 10, 12, 0, tzinfo=IST), get=fake, log=lambda *a: None)
    assert early["last_day"] == "2022-01-06" and not [u for u in fake.calls if "/intraday/" in u]          # not before the close
    assert all("/2022-01-06" in u or "/days/" in u for u in fake.calls if "/minutes/" in u)                # starts again at the last stored day
    late = NDB.build(tmp_path, "t", now=datetime(2022, 1, 10, 16, 0, tzinfo=IST), get=fake, log=lambda *a: None)
    assert late["last_day"] == "2022-01-10" and late["sessions"] == 5 and late["candles"] == 375 * 4 + 372
