"""Data for the spike study: every NSE-listed EQ stock, daily prices, and NSE
corporate announcements with their dissemination timestamps."""
from __future__ import annotations

import io
import json
import pickle
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

NSE_HEADERS = {"User-Agent": "Mozilla/5.0 (research script)", "Accept": "application/json",
               "Referer": "https://www.nseindia.com/"}


def nse_symbols() -> list[str]:
    req = urllib.request.Request(
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", headers=NSE_HEADERS)
    df = pd.read_csv(io.BytesIO(urllib.request.urlopen(req, timeout=40).read()))
    df.columns = [c.strip() for c in df.columns]
    return sorted(df.loc[df["SERIES"].str.strip() == "EQ", "SYMBOL"].str.strip())


def fetch_daily(symbols: list[str], years: int, cache: Path) -> dict[str, pd.DataFrame]:
    f = cache / "daily.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    import yfinance as yf
    out: dict[str, pd.DataFrame] = {}
    batches = [symbols[i:i + 100] for i in range(0, len(symbols), 100)]
    for n, batch in enumerate(batches, 1):
        tick = [f"{s}.NS" for s in batch]
        try:
            raw = yf.download(tick, period=f"{years}y", interval="1d", auto_adjust=False,
                              group_by="ticker", threads=True, progress=False)
        except Exception as exc:
            print(f"batch {n} failed: {exc}", flush=True)
            continue
        for s, t in zip(batch, tick):
            try:
                df = raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna(
                    subset=["Open", "High", "Low", "Close"])
            except KeyError:
                continue
            df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1) & (df.High >= df.Low)]
            df.index = pd.to_datetime(df.index.date)
            if len(df) > 120:
                out[s] = df[~df.index.duplicated()]
        print(f"batch {n}/{len(batches)}: {len(out)} tickers so far", flush=True)
    cache.mkdir(parents=True, exist_ok=True)
    f.write_bytes(pickle.dumps(out))
    return out


def announcements(symbol: str, start: str, end: str, retries: int = 3) -> list[dict] | None:
    """NSE announcements for a symbol; dates as DD-MM-YYYY. None on failure."""
    q = urllib.parse.urlencode({"index": "equities", "symbol": symbol,
                                "from_date": start, "to_date": end})
    for k in range(retries):
        try:
            req = urllib.request.Request(
                f"https://www.nseindia.com/api/corporate-announcements?{q}", headers=NSE_HEADERS)
            rows = json.loads(urllib.request.urlopen(req, timeout=30).read())
            return [{"time": pd.to_datetime(r["an_dt"], format="%d-%b-%Y %H:%M:%S"),
                     "desc": r.get("desc") or "", "text": r.get("attchmntText") or ""}
                    for r in rows]
        except Exception:
            time.sleep(1.5 * (k + 1))
    return None


def fetch_announcements(requests: list[tuple[str, str, str]], cache: Path,
                        workers: int = 3) -> dict:
    """requests: (symbol, from_date, to_date). Cached per request key."""
    f = cache / "announcements.pkl"
    store = pickle.loads(f.read_bytes()) if f.exists() else {}
    todo = [r for r in requests if r not in store]

    def one(r):
        time.sleep(0.25)
        return r, announcements(*r)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (r, rows) in enumerate(pool.map(one, todo), 1):
            if rows is not None:
                store[r] = rows
            if i % 100 == 0:
                f.write_bytes(pickle.dumps(store))
                print(f"announcements {i}/{len(todo)}", flush=True)
    f.write_bytes(pickle.dumps(store))
    return store


if __name__ == "__main__":
    import sys
    cache = Path(sys.argv[1])
    syms = nse_symbols()
    print(len(syms), "EQ symbols", flush=True)
    d = fetch_daily(syms, 5, cache)
    print("daily done", len(d), flush=True)
