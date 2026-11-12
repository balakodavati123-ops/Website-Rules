"""Rise and fall alerts for a scheduled task: names that START rising, and names that START falling.

Reads 15-minute bars from Yahoo Finance (NSE data is delayed about 15 minutes) for the watchlist, and
tells the two conditions apart by checking them now and again one hour earlier: an alert is only for a
name whose condition is new since the last run, so the same stock does not ring every hour.

  RISE  up 2% or more on the day, within 1% of the day's high, above yesterday's high, and the last
        hour's volume at least 1.5x a normal hour.
  FALL  down 2% or more on the day, or 3% under the day's high while under the open.
  Both  need at least Rs 10 crore traded and a price of Rs 20 or more.

Optional --ledger FILE adds paper positions that touched their stop or are falling.
It screens and warns. It is not a forecast and not advice. Writes /tmp/trend_alert.txt (the alert text).

Usage: python dashboard/trend_alert.py [--ledger paper_ledger.json] [--out /tmp/trend_alert.txt]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
CR = 1e7


def state(df, avg_vol):
    """('RISE'|'FALL'|'', info) from the bars up to the last one in df, or None if today has no bars."""
    day = df[df.index.date == df.index[-1].date()]
    prev = df[df.index.date < df.index[-1].date()]
    if len(day) < 3 or prev.empty:
        return None
    last, hi, op = float(day.Close.iloc[-1]), float(day.High.max()), float(day.Open.iloc[0])
    pc, ph = float(prev.Close.iloc[-1]), float(prev.High[prev.index.date == prev.index[-1].date()].max())
    chg, off_hi = (last / pc - 1) * 100, (1 - last / hi) * 100
    traded = last * float(day.Volume.sum()) / CR
    hour_vol = float(day.Volume.iloc[-4:].sum())
    if last < 20 or traded < 10:
        return "", dict(last=last, chg=chg, traded=traded)
    info = dict(last=last, chg=chg, off_hi=off_hi, traded=traded, hour_x=(hour_vol / (4 * avg_vol) if avg_vol else 0))
    if chg >= 2 and off_hi <= 1 and last > ph and info["hour_x"] >= 1.5:
        return "RISE", info
    if chg <= -2 or (off_hi >= 3 and last < op):
        return "FALL", info
    return "", info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger")
    ap.add_argument("--out", default="/tmp/trend_alert.txt")
    args = ap.parse_args()
    import yfinance as yf
    ticks = [t.strip() for t in (ROOT / "watchlists" / "nifty200_plus_etfs.txt").read_text().splitlines() if t.strip() and not t.startswith("#")]
    data = yf.download(ticks, period="5d", interval="15m", group_by="ticker", auto_adjust=False, threads=True, progress=False)
    now = datetime.now(IST)
    rises, falls, seen = [], [], 0
    for t in ticks:
        try:
            df = data[t].dropna(subset=["Close"])
        except KeyError:
            continue
        if len(df) < 20 or (now - df.index[-1].to_pydatetime()).total_seconds() > 3 * 3600:
            continue                                                   # no fresh bars: market closed or no data
        seen += 1
        before = df[df.index <= df.index[-1] - timedelta(minutes=60)]
        avg = float(df.Volume.iloc[:-4].mean() or 0)
        a, b = state(df, avg), (state(before, avg) if len(before) > 20 else None)
        if not a or not a[0] or (b and b[0] == a[0]):
            continue                                                   # nothing, or already true an hour ago
        (rises if a[0] == "RISE" else falls).append((t.replace(".NS", ""), a[1]))
    lines = []
    for sym, i in sorted(rises, key=lambda r: -r[1]["chg"])[:5]:
        lines.append(f"RISING {sym} {i['last']:.2f} ({i['chg']:+.1f}% today, volume {i['hour_x']:.1f}x normal). Ride only with a stop under the day's low.")
    for sym, i in sorted(falls, key=lambda r: r[1]["chg"])[:5]:
        lines.append(f"FALLING {sym} {i['last']:.2f} ({i['chg']:+.1f}% today). If you hold it, this is the time to think about selling.")
    if args.ledger and Path(args.ledger).exists():
        for r in json.loads(Path(args.ledger).read_text()):
            if r["status"] != "OPEN" or r["market"] != "NSE":
                continue
            try:
                d = data[r["symbol"] + ".NS"].dropna(subset=["Close"])
                last = float(d.Close.iloc[-1])
            except KeyError:
                continue
            if last <= float(r["stop"]):
                lines.append(f"PAPER STOP {r['symbol']} ({r['strategy']}) at {last:.2f}, stop was {r['stop']}. The paper engine closes it.")
    stamp = now.strftime("%H:%M IST")
    text = "\n".join(lines) if lines else f"{stamp}: no new risers or fallers among {seen} names."
    Path(args.out).write_text(text + "\n")
    print(f"{stamp}: {seen} names with fresh bars, {len(rises)} new risers, {len(falls)} new fallers")
    print(text)


if __name__ == "__main__":
    main()
