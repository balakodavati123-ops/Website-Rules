"""NIFTY 50 index: every 1-minute candle Upstox has (from 3 Jan 2022), in one SQLite database for backtesting.

    python backend/nifty_db.py OUT_DIR          (UPSTOX_TOKEN in the environment)

Writes OUT_DIR/nifty50_1m.sqlite and OUT_DIR/nifty50_1m.json (what it covers). It starts from the database already in OUT_DIR and adds
only what is new, re-reading its last stored session in case that one was cut short; a first run downloads everything (about 65 calls of
27 days each). Today's session is added after the close (15:35 IST) from Upstox's intraday candles, since its history ends at yesterday.

Tables and views
  candles     ts INTEGER PRIMARY KEY (Unix seconds at the minute the candle starts), open, high, low, close REAL.
              An index has no traded volume, so there is none.
  nifty50_1m  VIEW: ts, day 'YYYY-MM-DD', time 'HH:MM' (IST), open, high, low, close - the easy one to query.
  days        day TEXT PRIMARY KEY, open, high, low, close (from the minutes: close is the 15:29 candle's), candles, first, last,
              complete (1 = all 375 minutes 09:15-15:29), official_close (NSE's closing value, from Upstox's daily candle; NSE sets it
              from the last 30 minutes of trading, so it can differ from the 15:29 price), close_diff (close - official_close)
  meta        key TEXT PRIMARY KEY, value TEXT (JSON)
Checks: every candle must have low <= open, close <= high (others are dropped and counted); every session in Upstox's daily NIFTY candles
must be present (missing ones are listed); short sessions (Muhurat trading, special sessions, minutes Upstox lacks) are listed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upstox as U  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
KEY = "NSE_INDEX|Nifty 50"
START = date(2022, 1, 1)                 # Upstox keeps 1-minute candles from January 2022
DB, COVER = "nifty50_1m.sqlite", "nifty50_1m.json"
SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (ts INTEGER PRIMARY KEY, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL);
CREATE VIEW IF NOT EXISTS nifty50_1m AS SELECT ts, date(ts, 'unixepoch', '+330 minutes') AS day, strftime('%H:%M', ts, 'unixepoch', '+330 minutes') AS time,
    open, high, low, close FROM candles;
CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, candles INTEGER, first TEXT, last TEXT, complete INTEGER,
                                 official_close REAL, close_diff REAL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def day_span(d: str) -> tuple[int, int]:
    t0 = int(datetime.fromisoformat(d).replace(tzinfo=IST).timestamp())
    return t0, t0 + 86400


def fetch(token: str, unit: str, n: int, frm: date | None, to: date | None, get=U._get) -> list[list]:
    """Upstox v3 candles, newest first: [[iso time, open, high, low, close, volume, oi], ...]. frm=None reads today's intraday candles."""
    k = urllib.parse.quote(KEY, safe="")
    url = (f"https://api.upstox.com/v3/historical-candle/intraday/{k}/{unit}/{n}" if frm is None else
           f"https://api.upstox.com/v3/historical-candle/{k}/{unit}/{n}/{to:%Y-%m-%d}/{frm:%Y-%m-%d}")
    for i in range(4):
        try:
            return json.loads(get(url, token)).get("data", {}).get("candles") or []
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == 3:
                raise
            time.sleep(5 * (i + 1))
    return []


def valid(c: list) -> bool:
    try:
        o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
    except (TypeError, ValueError, IndexError):
        return False
    return 0 < l <= min(o, cl) and max(o, cl) <= h


def rows_of(cs: list[list]) -> tuple[list[tuple], int]:
    out, bad = [], 0
    for c in cs:
        if not valid(c):
            bad += 1
            continue
        t = datetime.fromisoformat(c[0])
        out.append((int(t.timestamp()), float(c[1]), float(c[2]), float(c[3]), float(c[4])))
    return out, bad


def summarise_days(con: sqlite3.Connection, days: list[str], official: dict) -> None:
    for d in days:
        a, b = day_span(d)
        r = con.execute("SELECT MIN(ts), MAX(ts), MAX(high), MIN(low), COUNT(*) FROM candles WHERE ts >= ? AND ts < ?", (a, b)).fetchone()
        if not r or not r[4]:
            continue
        first = con.execute("SELECT strftime('%H:%M', ts, 'unixepoch', '+330 minutes'), open FROM candles WHERE ts = ?", (r[0],)).fetchone()
        last = con.execute("SELECT strftime('%H:%M', ts, 'unixepoch', '+330 minutes'), close FROM candles WHERE ts = ?", (r[1],)).fetchone()
        n_reg = con.execute("SELECT COUNT(*) FROM candles WHERE ts BETWEEN ? AND ?", (a + 33300, a + 55740)).fetchone()[0]        # 09:15 to 15:29
        oc = official.get(d)
        con.execute("INSERT OR REPLACE INTO days VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (d, first[1], r[2], r[3], last[1], r[4], first[0], last[0], int(n_reg == 375), oc, round(last[1] - oc, 2) if oc else None))


def build(out_dir: Path, token: str, now: datetime | None = None, get=U._get, log=print) -> dict:
    now = now or datetime.now(IST)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out_dir / DB)
    con.executescript(SCHEMA)
    last = con.execute("SELECT date(MAX(ts), 'unixepoch', '+330 minutes') FROM candles").fetchone()[0]
    frm = date.fromisoformat(last) if last else START
    closed = now.strftime("%H:%M") >= "15:35"
    end = now.date() - timedelta(days=1)                                # Upstox's history runs to yesterday; today comes from the intraday candles
    added, bad, touched, calls = 0, 0, set(), 0
    a = frm
    while a <= end:
        b = min(a + timedelta(days=26), end)
        cs = fetch(token, "minutes", 1, a, b, get)
        calls += 1
        rows, nb = rows_of(cs)
        bad += nb
        before = con.total_changes
        con.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?)", rows)
        added += con.total_changes - before
        touched |= {datetime.fromtimestamp(r[0], IST).strftime("%Y-%m-%d") for r in rows}
        log(f"{a} to {b}: {len(rows)} candles")
        a = b + timedelta(days=1)
    if closed:                                                          # a holiday or weekend simply returns no candles dated today
        rows, nb = rows_of([c for c in fetch(token, "minutes", 1, None, None, get) if c[0][:10] == now.strftime("%Y-%m-%d")])
        calls += 1
        if rows:
            bad += nb
            before = con.total_changes
            con.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?)", rows)
            added += con.total_changes - before
            touched.add(now.strftime("%Y-%m-%d"))
            log(f"today {now:%Y-%m-%d}: {len(rows)} candles")
    official = {}
    for c in fetch(token, "days", 1, START, end, get):                 # Upstox's own daily candles: the list of sessions and their closes
        official[c[0][:10]] = float(c[4])
    calls += 1
    have = {r[0] for r in con.execute("SELECT DISTINCT date(ts, 'unixepoch', '+330 minutes') FROM candles")}
    redo = touched | {d for d, in con.execute("SELECT day FROM days WHERE official_close IS NULL")}
    summarise_days(con, sorted(redo & have), official)
    con.commit()
    s = {k: v for k, v in zip(("sessions", "candles", "first_day", "last_day"),
                               con.execute("SELECT (SELECT COUNT(*) FROM days), (SELECT COUNT(*) FROM candles), MIN(day), MAX(day) FROM days").fetchone())}
    short = [dict(zip(("day", "candles", "first", "last"), r)) for r in con.execute("SELECT day, candles, first, last FROM days WHERE complete = 0 ORDER BY day")]
    missing = sorted(d for d in official if s["first_day"] and s["first_day"] <= d <= end.isoformat() and d not in have)      # up to the end asked for
    diffs = sorted(abs(r[0]) for r in con.execute("SELECT close_diff FROM days WHERE close_diff IS NOT NULL"))
    by_year = {y: {"sessions": n, "candles": c} for y, n, c in con.execute("SELECT substr(day,1,4), COUNT(*), SUM(candles) FROM days GROUP BY 1 ORDER BY 1")}
    meta = {"source": "Upstox v3 historical candles, NSE_INDEX|Nifty 50, 1 minute (VERIFIED_HISTORICAL)", "updated_at": now.isoformat(timespec="seconds"),
            **s, "complete_sessions": s["sessions"] - len(short), "short_sessions": short, "missing_sessions": missing, "dropped_bad_candles_this_run": bad,
            "written_this_run": added, "api_calls_this_run": calls, "close_vs_official": {"days": len(diffs), "median_abs_points": diffs[len(diffs) // 2] if diffs else None,
                                                                                         "max_abs_points": diffs[-1] if diffs else None,
                                                                                         "note": "NSE sets the official close from the last 30 minutes, so it can differ from the 15:29 candle"},
            "by_year": by_year, "tables": {"nifty50_1m (view)": "ts, day, time, open, high, low, close", "candles": "ts, open, high, low, close",
                       "days": "day, open, high, low, close, candles, first, last, complete, official_close, close_diff"}}
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.execute("VACUUM")
    con.close()
    meta["size_mb"] = round((out_dir / DB).stat().st_size / 1e6, 1)
    (out_dir / COVER).write_text(json.dumps(meta, indent=1))
    log(f"{s['sessions']} sessions, {s['candles']:,} candles, {s['first_day']} to {s['last_day']}; {len(short)} short, {len(missing)} missing; {meta['size_mb']} MB")
    return meta


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "."), os.environ.get("UPSTOX_TOKEN", ""))
