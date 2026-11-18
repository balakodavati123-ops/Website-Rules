"""Daily candles for every NSE equity (one year), saved as one small file per stock on the `charts` branch.

The page draws any of the ~2,700 stocks from these files. Upstox allows about 2,000 history calls per 30 minutes, so
this paces itself to one call a second, skips stocks whose file is already current, stops after MAX_MINUTES, and the
workflow starts it again until nothing remains. Nothing here trades.
Usage: python backend/candles.py OUT_DIR       (OUT_DIR may already hold files from the last run)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upstox as U  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
MAX_MINUTES = float(os.environ.get("MAX_MINUTES", "50"))


def fname(sym: str) -> str:
    return sym.replace("&", "_and_").replace("/", "_").replace(" ", "_")


def expected_last() -> str:
    """The latest session whose candle should exist now: today after 15:45 IST on a weekday, else the weekday before."""
    n = datetime.now(IST)
    d = n.date() if (n.hour, n.minute) >= (15, 45) else n.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def main() -> None:
    out = Path(sys.argv[1])
    (out / "c").mkdir(parents=True, exist_ok=True)
    token = os.environ.get("UPSTOX_TOKEN", "")
    eq = [x for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"]
    to, frm, want, t0, pending = date.today(), date.today() - timedelta(days=370), expected_last(), time.time(), 0

    def current(f: Path) -> bool:
        try:
            return json.loads(f.read_text())[-1][0] >= want
        except Exception:
            return False

    for x in eq:
        f = out / "c" / (fname(x["trading_symbol"]) + ".json")
        if current(f):
            continue
        if time.time() - t0 > MAX_MINUTES * 60:
            pending += 1
            continue
        url = f"https://api.upstox.com/v2/historical-candle/{urllib.parse.quote(x['instrument_key'], safe='')}/day/{to}/{frm}"
        for attempt in range(4):
            try:
                c = json.loads(U._get(url, token)).get("data", {}).get("candles", [])
                rows = [[k[0][:10], k[1], k[2], k[3], k[4], int(k[5])] for k in reversed(c)]
                if rows:
                    f.write_text(json.dumps(rows, separators=(",", ":")))
                break
            except urllib.error.HTTPError as e:
                time.sleep(30 if e.code == 429 else 2)
            except Exception:
                time.sleep(2)
        else:
            pending += 1
        time.sleep(1.0)
    (out / "symbols.json").write_text(json.dumps(sorted([[x["trading_symbol"], x.get("name", ""), x["instrument_key"]] for x in eq]), separators=(",", ":")))
    (out / "remaining.txt").write_text(str(pending))
    print(f"{len(eq) - pending} of {len(eq)} stocks current; {pending} remaining")


if __name__ == "__main__":
    main()
