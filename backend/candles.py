"""Daily candles for every NSE equity (one year), saved as one small file per stock on the `charts` branch.

The page draws any of the ~2,700 stocks from these files. Run by .github/workflows/candles.yml after the close and once
before the open. Candles come from Upstox's historical-candle API; nothing here trades.
Usage: python backend/candles.py OUT_DIR
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upstox as U  # noqa: E402


def fname(sym: str) -> str:
    return sym.replace("&", "_and_").replace("/", "_").replace(" ", "_")


def main() -> None:
    import os
    out = Path(sys.argv[1])
    (out / "c").mkdir(parents=True, exist_ok=True)
    token = os.environ.get("UPSTOX_TOKEN", "")
    eq = [x for x in U.instruments("NSE") if x.get("segment") == "NSE_EQ" and x.get("instrument_type") == "EQ"]
    to, frm = date.today(), date.today() - timedelta(days=370)

    def one(x):
        url = f"https://api.upstox.com/v2/historical-candle/{urllib.parse.quote(x['instrument_key'], safe='')}/day/{to}/{frm}"
        for _ in range(3):
            try:
                c = json.loads(U._get(url, token)).get("data", {}).get("candles", [])
                rows = [[k[0][:10], k[1], k[2], k[3], k[4], int(k[5])] for k in reversed(c)]
                if rows:
                    (out / "c" / (fname(x["trading_symbol"]) + ".json")).write_text(json.dumps(rows, separators=(",", ":")))
                    return 1
                return 0
            except Exception:
                pass
        return 0

    with ThreadPoolExecutor(8) as ex:
        ok = sum(ex.map(one, eq))
    syms = sorted([[x["trading_symbol"], x.get("name", ""), x["instrument_key"]] for x in eq])
    (out / "symbols.json").write_text(json.dumps(syms, separators=(",", ":")))
    print(f"{ok} of {len(eq)} stocks saved")


if __name__ == "__main__":
    main()
