"""Event study of sudden single-stock jumps on NSE.

Questions answered from data, not opinion:
  1. How common are +10% and +15% intraday jumps in tradable stocks?
  2. What announcement (if any) was filed in the window before the jump?
  3. Was the jump a gap at the open (nobody can trade it) or built during the session?
  4. Did price move BEFORE the announcement, or after? (needs 5-minute data, last ~55 days)
  5. After the jump: how much of it was kept by the close, and what came next?
  6. How often does a scheduled results announcement end in a jump? (base rate)

Definitions, fixed before looking at results:
  spike     = session high at least 10% above the previous close, volume at least 2x its
              20-day average, 20-day average turnover of at least Rs 2 crore, price at
              least Rs 20, jump under 50% (screens out split artefacts).
  The universe is every NSE EQ-series stock that is listed today (survivorship bias:
  delisted stocks are missing).

Usage: python backtest/spike_study.py CACHE_DIR
"""
from __future__ import annotations

import json
import pickle
import random
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spike_data import announcements, fetch_announcements, nse_symbols  # noqa: E402

MIN_JUMP, BIG_JUMP = 0.10, 0.15
MIN_VOL_RATIO, MIN_TURNOVER, MIN_PRICE = 2.0, 2e7, 20.0
OPEN, CLOSE = dtime(9, 15), dtime(15, 30)


def prep(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["prev"] = d.Close.shift(1)
    d["gap_days"] = d.index.to_series().diff().dt.days
    d["jump"] = d.High / d.prev - 1
    d["gap"] = d.Open / d.prev - 1
    d["ret"] = d.Close / d.prev - 1
    d["close_vs_high"] = d.Close / d.High - 1
    d["vol_ratio"] = d.Volume / d.Volume.rolling(20).mean().shift(1)
    d["turn20"] = (d.Close * d.Volume).rolling(20).mean().shift(1)
    d["next1"] = d.Close.shift(-1) / d.Close - 1
    d["next5"] = d.Close.shift(-5) / d.Close - 1
    r = d.Close.pct_change()
    d["pre_vol5"] = d.Volume.shift(1).rolling(5).mean() / d.Volume.shift(1).rolling(50).mean()
    d["vol_squeeze"] = r.shift(1).rolling(20).std() / r.shift(1).rolling(100).std()
    d["ret20"] = d.prev / d.Close.shift(21) - 1
    d["off_high"] = d.prev / d.High.shift(1).rolling(252).max() - 1
    d["liquid"] = (d.turn20 >= MIN_TURNOVER) & (d.prev >= MIN_PRICE) & (d.gap_days <= 5)
    return d


def find_spikes(daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for sym, df in daily.items():
        d = prep(df)
        m = d.liquid & (d.jump >= MIN_JUMP) & (d.jump < 0.5) & (d.vol_ratio >= MIN_VOL_RATIO)
        for day, r in d[m].iterrows():
            rows.append({"symbol": sym, "day": day, **r.drop(["Open", "High", "Low", "Close", "Volume"]).to_dict(),
                         "open": d.at[day, "Open"], "high": d.at[day, "High"],
                         "close": d.at[day, "Close"]})
    return pd.DataFrame(rows)


def liquid_stock_days(daily) -> int:
    n = 0
    for df in daily.values():
        d = prep(df)
        n += int((d.liquid & d.jump.notna() & (d.index >= d.index[0] + pd.Timedelta(days=60))).sum())
    return n


CAUSES = [
    ("results", ["financial result", "results for the", "unaudited", "audited financial"]),
    ("order / contract win", ["order", "contract", "letter of award", "loa ", "bagged", "work order"]),
    ("acquisition / merger / stake", ["acquisition", "acquire", "merger", "amalgamation",
                                      "scheme of arrangement", "stake", "joint venture"]),
    ("fund raise", ["preferential", "warrant", "qip", "rights issue", "fund raising",
                    "fundraising", "raising of funds"]),
    ("approval / regulatory", ["usfda", "approval", "patent", "licen", "certificat"]),
    ("bonus / split / buyback / dividend", ["bonus", "split", "buyback", "buy back", "dividend"]),
]
NOISE = ("copy of newspaper", "analysts/institutional", "trading window", "shareholders meeting",
         "loss of share certificate", "certificate under", "compliances-reg")


def classify(rows: list[dict]) -> str:
    if not rows:
        return "no announcement"
    for label, keys in CAUSES:
        for r in rows:
            blob = f"{r['desc']} {r['text']}".lower()
            if label == "results" and not (
                    "financial result" in r["desc"].lower() or any(k in blob for k in keys[:2])):
                continue
            if label != "results" and not any(k in blob for k in keys):
                continue
            return label
    if all(any(n in r["desc"].lower() for n in NOISE) for r in rows):
        return "routine filing only"
    return "other announcement"


def window(rows, day: pd.Timestamp, prev_day: pd.Timestamp):
    lo, hi = prev_day + pd.Timedelta(hours=15, minutes=30), day + pd.Timedelta(hours=15, minutes=30)
    return [r for r in rows if lo <= r["time"] <= hi]


def pct(x, n):
    return f"{100 * x / n:.0f}%" if n else "n/a"


def part_frequency(spikes: pd.DataFrame, stock_days: int, years: float) -> dict:
    big = spikes[spikes.jump >= BIG_JUMP]
    out = {"spikes_10pct": len(spikes), "spikes_15pct": len(big),
           "liquid_stock_days": stock_days,
           "per_year_10pct": round(len(spikes) / years), "per_year_15pct": round(len(big) / years),
           "chance_per_stock_day_pct": round(100 * len(spikes) / stock_days, 3),
           "by_year": spikes.groupby(spikes.day.dt.year).size().to_dict()}
    print(f"\n1. FREQUENCY ({years:.1f} years, liquid NSE EQ stocks)")
    print(f"   {len(spikes)} jumps of 10%+ ({out['per_year_10pct']}/yr, about "
          f"{out['per_year_10pct'] / 250:.1f} per trading day across the whole market)")
    print(f"   {len(big)} of 15%+ ({out['per_year_15pct']}/yr)")
    print(f"   chance a given liquid stock jumps 10%+ on a given day: "
          f"{out['chance_per_stock_day_pct']}%")
    per_day = spikes.groupby("day").size()
    wide = per_day[per_day >= 40]
    out["market_wide_days"] = len(wide)
    out["jumps_on_market_wide_days_pct"] = round(100 * wide.sum() / len(spikes))
    out["median_jumps_per_day"] = float(per_day.median())
    print(f"   median {per_day.median():.0f} jumps per trading day; {len(wide)} days had 40+ "
          f"(broad rallies) and hold {out['jumps_on_market_wide_days_pct']}% of all jumps")
    return out


def part_shape(spikes: pd.DataFrame) -> dict:
    n = len(spikes)
    gap_at_open = (spikes.gap >= 0.7 * spikes.jump)
    built = (spikes.gap < 0.3 * spikes.jump)
    out = {"gap_at_open_pct": round(100 * gap_at_open.mean()),
           "built_in_session_pct": round(100 * built.mean()),
           "median_gap_pct": round(100 * spikes.gap.median(), 1),
           "median_jump_pct": round(100 * spikes.jump.median(), 1),
           "closed_below_high_median_pct": round(100 * spikes.close_vs_high.median(), 1),
           "close_gave_back_half_or_more_pct": round(
               100 * ((spikes.jump - spikes.ret) >= 0.5 * spikes.jump).mean()),
           "median_next_day_pct": round(100 * spikes.next1.median(), 1),
           "median_next_5d_pct": round(100 * spikes.next5.median(), 1),
           "next_day_down_pct": round(100 * (spikes.next1 < 0).mean()),
           "median_ret_close_pct": round(100 * spikes.ret.median(), 1)}
    print("\n3. SHAPE OF THE DAY")
    print(f"   opened already {out['median_gap_pct']}% up (median); {out['gap_at_open_pct']}% of jumps "
          f"were mostly a gap at the open, {out['built_in_session_pct']}% were built during the session")
    print(f"   median high was +{out['median_jump_pct']}%, median close +{out['median_ret_close_pct']}%; "
          f"{out['close_gave_back_half_or_more_pct']}% gave back half or more of the move by the close")
    print(f"   after the close: next day median {out['median_next_day_pct']}%, "
          f"next 5 days {out['median_next_5d_pct']}%, next day down in {out['next_day_down_pct']}% of cases")
    return out


def part_precursors(spikes: pd.DataFrame, daily) -> dict:
    """Do quiet-before-the-storm features separate spike days from ordinary days?"""
    rng = random.Random(1)
    rows = []
    for sym in rng.sample(list(daily), min(400, len(daily))):
        d = prep(daily[sym])
        d = d[d.liquid & d.pre_vol5.notna() & d.vol_squeeze.notna()]
        rows.append(d.sample(min(60, len(d)), random_state=1)[["pre_vol5", "vol_squeeze", "ret20", "off_high"]])
    base = pd.concat(rows)
    out = {}
    print("\n2b. WHAT THE 20 DAYS BEFORE A JUMP LOOK LIKE (median, jumps vs ordinary liquid days)")
    for col, label in (("pre_vol5", "5-day volume vs 50-day average"),
                       ("vol_squeeze", "recent volatility vs 100-day (below 1 = quiet)"),
                       ("ret20", "return over prior month"),
                       ("off_high", "distance below 52-week high")):
        a, b = spikes[col].median(), base[col].median()
        out[col] = {"spikes": round(float(a), 3), "ordinary": round(float(b), 3)}
        print(f"   {label}: jumps {a:+.2f} vs ordinary {b:+.2f}")
    return out


def part_causes(spikes: pd.DataFrame, cache: Path, max_events: int) -> pd.DataFrame:
    rng = random.Random(7)
    idx = list(spikes.index)
    recent_cut = spikes.day.max() - pd.Timedelta(days=62)
    must = [i for i in idx if spikes.at[i, "day"] >= recent_cut]
    rest = [i for i in idx if i not in set(must)]
    pick = must + rng.sample(rest, min(len(rest), max(0, max_events - len(must))))
    sub = spikes.loc[pick].copy()
    reqs = []
    for _, r in sub.iterrows():
        d0 = r.day - pd.Timedelta(days=4)
        reqs.append((r.symbol, d0.strftime("%d-%m-%Y"), r.day.strftime("%d-%m-%Y")))
    store = fetch_announcements(reqs, cache)
    causes, ann_rows = [], []
    for (_, r), req in zip(sub.iterrows(), reqs):
        rows = store.get(req)
        if rows is None:
            causes.append(None)
            ann_rows.append(None)
            continue
        prev_day = r.day - pd.Timedelta(days=int(r.gap_days))
        rel = window(rows, r.day, prev_day)
        causes.append(classify(rel))
        ann_rows.append(rel)
    sub["cause"], sub["ann"] = causes, ann_rows
    return sub[sub.cause.notna()]


def print_causes(sub: pd.DataFrame) -> dict:
    n = len(sub)
    counts = sub.cause.value_counts()
    print(f"\n2. WHAT WAS FILED BEFORE THE JUMP ({n} jumps checked against NSE announcements)")
    out = {"n": n, "share_pct": {}, "median_jump_pct": {}, "median_close_pct": {}}
    for cause, c in counts.items():
        g = sub[sub.cause == cause]
        out["share_pct"][cause] = round(100 * c / n)
        out["median_jump_pct"][cause] = round(100 * g.jump.median(), 1)
        out["median_close_pct"][cause] = round(100 * g.ret.median(), 1)
        print(f"   {cause:<34} {c:>4} ({pct(c, n):>4})   median high +{100 * g.jump.median():.1f}%, "
              f"median close +{100 * g.ret.median():.1f}%")
    return out


def part_timing(sub: pd.DataFrame, cache: Path) -> dict:
    """Announcement time vs price path, from 5-minute bars (last ~60 days only)."""
    import yfinance as yf
    recent = sub[sub.day >= sub.day.max() - pd.Timedelta(days=55)]
    recent = recent[recent.cause.isin([c for c, _ in CAUSES] + ["other announcement"])]
    syms = sorted(recent.symbol.unique())
    f = cache / "bars5m.pkl"
    bars = pickle.loads(f.read_bytes()) if f.exists() else {}
    for i in range(0, len(syms), 40):
        chunk = [s for s in syms[i:i + 40] if s not in bars]
        if not chunk:
            continue
        raw = yf.download([f"{s}.NS" for s in chunk], period="60d", interval="5m",
                          auto_adjust=False, group_by="ticker", threads=True, progress=False)
        for s in chunk:
            try:
                bars[s] = raw[f"{s}.NS"][["Open", "High", "Low", "Close", "Volume"]].dropna()
            except KeyError:
                pass
    f.write_bytes(pickle.dumps(bars))

    res = []
    for _, r in recent.iterrows():
        b = bars.get(r.symbol)
        if b is None or not len(b):
            continue
        idx = b.index.tz_convert("Asia/Kolkata") if b.index.tz is not None else b.index
        b = b.set_axis(idx.tz_localize(None))
        day_b = b[b.index.normalize() == r.day]
        if len(day_b) < 30:
            continue
        in_session = [a for a in r.ann if r.day.normalize() == a["time"].normalize()
                      and OPEN <= a["time"].time() <= CLOSE]
        if not in_session:   # filed overnight / after close: shows up as a gap
            res.append({"symbol": r.symbol, "day": r.day, "kind": "overnight"})
            continue
        a = min(in_session, key=lambda x: x["time"])
        move = day_b[day_b.High >= r.prev * 1.03]
        if not len(move):
            continue
        t3 = move.index[0]                                   # first 5-min bar touching +3%
        t3_end = t3 + pd.Timedelta(minutes=5)
        peak_t = day_b.High.idxmax()
        ab = day_b[day_b.index <= a["time"]]
        entry = ab.Close.iloc[-1] if len(ab) else day_b.Open.iloc[0]
        before = t3_end <= a["time"]                         # +3% already reached before filing
        res.append({"symbol": r.symbol, "day": r.day, "kind": "in_session",
                    "ann_time": a["time"], "t3": t3, "before": before,
                    "mins_ann_to_t3": (t3 - a["time"]).total_seconds() / 60,
                    "mins_ann_to_peak": (peak_t - a["time"]).total_seconds() / 60,
                    "left_after_ann_pct": 100 * (r.high / entry - 1),
                    "already_up_at_ann_pct": 100 * (entry / r.prev - 1)})
    t = pd.DataFrame(res)
    out = {"n": len(t)}
    print(f"\n4. TIMING: announcement vs price ({len(t)} recent jumps with 5-minute data)")
    if not len(t):
        return out
    ov = t[t.kind == "overnight"]
    ins = t[t.kind == "in_session"]
    out["overnight_pct"] = round(100 * len(ov) / len(t))
    print(f"   filed overnight or after the close (shows as a gap at the open): "
          f"{len(ov)} ({pct(len(ov), len(t))})")
    if len(ins):
        pre = ins.before.mean()
        out.update({"in_session": len(ins), "moved_3pct_before_filing_pct": round(100 * pre),
                    "median_already_up_at_filing_pct": round(float(ins.already_up_at_ann_pct.median()), 1),
                    "median_mins_ann_to_peak": round(float(ins.mins_ann_to_peak.median())),
                    "median_left_after_filing_pct": round(float(ins.left_after_ann_pct.median()), 1)})
        print(f"   filed during the session: {len(ins)}")
        print(f"     price was already up 3%+ BEFORE the filing time in {100 * pre:.0f}% of them")
        print(f"     median move already made at filing time: +{ins.already_up_at_ann_pct.median():.1f}%")
        print(f"     median minutes from filing to the day's high: {ins.mins_ann_to_peak.median():.0f}")
        print(f"     median further gain available from the filing to the high: "
              f"+{ins.left_after_ann_pct.median():.1f}%")
    return out


def part_base_rate(daily, cache: Path, n_stocks: int = 120) -> dict:
    """Of all scheduled results announcements, what share were followed by a 10%+ jump?"""
    rng = random.Random(3)
    liquid = [s for s, df in daily.items()
              if len(df) > 1000 and (df.Close * df.Volume).tail(250).median() >= 5e7]
    syms = rng.sample(liquid, min(n_stocks, len(liquid)))
    end = max(df.index[-1] for df in daily.values())
    years = [(f"01-01-{y}" if y > end.year - 5 else (end - pd.DateOffset(years=5)).strftime("%d-%m-%Y"),
              f"31-12-{y}" if y < end.year else end.strftime("%d-%m-%Y"))
             for y in range(end.year - 5, end.year + 1)]
    reqs = [(s, a, b) for s in syms for a, b in years]
    store = fetch_announcements(reqs, cache)
    events, base_total, base_hit = [], 0, 0
    for s in syms:
        d = prep(daily[s])
        hit_days = d.index[(d.jump >= MIN_JUMP) & (d.jump < 0.5) & (d.vol_ratio >= MIN_VOL_RATIO)]
        base_total += int((d.liquid & d.jump.notna()).sum())
        base_hit += int(((d.liquid) & (d.index.isin(hit_days))).sum())
        seen = set()
        for req in (r for r in reqs if r[0] == s):
            for a in store.get(req) or []:
                blob = f"{a['desc']} {a['text']}".lower()
                if "financial result" not in a["desc"].lower() and "results for the" not in blob:
                    continue
                t = a["time"]
                react = t.normalize() + pd.Timedelta(days=1 if t.time() > CLOSE else 0)
                pos = d.index.searchsorted(react)
                if pos >= len(d) or pos in seen:
                    continue
                seen.add(pos)
                row = d.iloc[pos]
                if not row.liquid or pd.isna(row.jump):
                    continue
                events.append({"jump": row.jump, "ret": row.ret, "vol_ratio": row.vol_ratio,
                               "hit10": bool(row.jump >= MIN_JUMP and row.jump < 0.5
                                             and row.vol_ratio >= MIN_VOL_RATIO),
                               "hit15": bool(row.jump >= BIG_JUMP and row.jump < 0.5
                                             and row.vol_ratio >= MIN_VOL_RATIO)})
    e = pd.DataFrame(events)
    out = {"stocks": len(syms), "results_events": len(e),
           "results_hit10_pct": round(100 * e.hit10.mean(), 1),
           "results_hit15_pct": round(100 * e.hit15.mean(), 1),
           "ordinary_day_hit10_pct": round(100 * base_hit / base_total, 2),
           "results_median_high_pct": round(100 * e.jump.median(), 1)}
    out["lift"] = round(out["results_hit10_pct"] / max(out["ordinary_day_hit10_pct"], 1e-9))
    print(f"\n6. SCHEDULED RESULTS: HOW OFTEN DOES ONE END IN A JUMP? ({len(syms)} liquid stocks)")
    print(f"   {len(e)} results announcements; a 10%+ jump followed {out['results_hit10_pct']}% "
          f"(15%+: {out['results_hit15_pct']}%); median high that session +{out['results_median_high_pct']}%")
    print(f"   an ordinary day: {out['ordinary_day_hit10_pct']}%  -> results days are about "
          f"{out['lift']}x likelier, yet {100 - out['results_hit10_pct']:.0f}% of them did NOT jump 10%")
    return out


def main():
    cache = Path(sys.argv[1])
    daily = pickle.loads((cache / "daily.pkl").read_bytes())
    last = max(df.index[-1] for df in daily.values())
    first = min(df.index[0] for df in daily.values())
    years = (last - first).days / 365.25
    print(f"{len(daily)} NSE EQ stocks, {first.date()} to {last.date()}")
    spikes = find_spikes(daily)
    result = {"period": [str(first.date()), str(last.date())], "stocks": len(daily)}
    result["frequency"] = part_frequency(spikes, liquid_stock_days(daily), years)
    result["shape"] = part_shape(spikes)
    result["precursors"] = part_precursors(spikes, daily)
    sub = part_causes(spikes, cache, max_events=int(sys.argv[2]) if len(sys.argv) > 2 else 900)
    result["causes"] = print_causes(sub)
    result["timing"] = part_timing(sub, cache)
    result["base_rate"] = part_base_rate(daily, cache)
    out = Path(__file__).resolve().parent / "spike_study_results.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
