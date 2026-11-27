"""How world markets move NIFTY 50 and Sensex: measured on daily data, Jan 2022 - today.

1. Same day: NIFTY's close-to-close move against the same day's moves in crude, the rupee, the dollar, US yields, Asian markets and gold, and
   the previous night's US close (it is known before India opens). Ordinary least squares on all factors together -> each factor's effect
   (NIFTY % per 1% factor move), its t-statistic and how much of NIFTY's daily move they explain together (R squared).
2. Big moves: on days when one factor moved a lot (crude 2%+, the rupee 0.35%+, ...), how NIFTY did: how many days, its average move,
   how often it fell. A small average effect can hide a large one on big days.
3. Before the open: only what is known by 09:15 (last night's US close and US VIX, yesterday's crude, rupee, dollar and yields). Fitted on
   2022-2024, tested on 2025-2026: how often its sign gets the day's direction right (close to close, and open to close).
Writes docs/models/macro_model.json for the live engine (backend/macro.py). Research only.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.data.macro_news_feed import yahoo_daily   # noqa: E402

START, SPLIT = date(2022, 1, 1), date(2025, 1, 1)
FACT = {"brent": ("BZ=F", "Brent crude"), "usdinr": ("INR=X", "USD/INR (rupee)"), "dxy": ("DX-Y.NYB", "Dollar index"), "us10y": ("^TNX", "US 10-year yield"),
        "spx": ("^GSPC", "S&P 500"), "ndx": ("^IXIC", "Nasdaq"), "vix": ("^VIX", "US VIX"), "n225": ("^N225", "Nikkei 225"), "hsi": ("^HSI", "Hang Seng"),
        "gold": ("GC=F", "Gold")}
SAME_DAY = ["brent", "usdinr", "dxy", "us10y", "n225", "hsi", "gold"]           # trade during or across India's session
OVERNIGHT = ["spx", "ndx", "vix"]                                               # last night's US close: known before 09:15 IST


def pct(s: dict, d: date, back: int = 1) -> float | None:
    ks = sorted(k for k in s if k <= d)
    if len(ks) < back + 1 or ks[-1] != d:
        return None
    a, b = s[ks[-1 - back]], s[ks[-1]]
    return (b / a - 1) * 100 if a else None


def prev_pct(s: dict, d: date) -> float | None:
    """The most recent completed daily move strictly before day d (for US assets: last night's close)."""
    ks = sorted(k for k in s if k < d)
    if len(ks) < 2:
        return None
    return (s[ks[-1]] / s[ks[-2]] - 1) * 100 if s[ks[-2]] else None


def ols(X: np.ndarray, y: np.ndarray):
    X1 = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(X1, y, rcond=None)
    r = y - X1 @ b
    s2 = r @ r / max(len(y) - X1.shape[1], 1)
    cov = s2 * np.linalg.pinv(X1.T @ X1)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    r2 = 1 - (r @ r) / (((y - y.mean()) ** 2).sum() or 1)
    return b, se, r2


def main() -> None:
    end = datetime.now().date()
    nifty, sensex = yahoo_daily("^NSEI", START - timedelta(days=10), end), yahoo_daily("^BSESN", START - timedelta(days=10), end)
    nopen = {}
    import urllib.request
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?period1={int(datetime(2021, 12, 20).timestamp())}&period2={int(datetime.now().timestamp())}&interval=1d"
    r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())["chart"]["result"][0]
    for t, o in zip(r["timestamp"], r["indicators"]["quote"][0]["open"]):
        if o:
            nopen[datetime.utcfromtimestamp(t + 19800).date()] = o
    S = {k: yahoo_daily(sym, START - timedelta(days=10), end) for k, (sym, _) in FACT.items()}
    days = [d for d in sorted(nifty) if d >= START]
    rows = []
    for d in days:
        y = pct(nifty, d)
        x_same = [pct(S[k], d) if k != "us10y" else (lambda a: a)(pct(S[k], d)) for k in SAME_DAY]
        x_over = [prev_pct(S[k], d) for k in OVERNIGHT]
        x_pre = [prev_pct(S[k], d) for k in ["spx", "ndx", "vix", "brent", "usdinr", "dxy", "us10y"]]
        oc = (nifty[d] / nopen[d] - 1) * 100 if d in nopen and nopen[d] else None
        if y is None or any(v is None for v in x_same + x_over + x_pre):
            continue
        rows.append({"d": d, "y": y, "oc": oc, "sx": pct(sensex, d), "same": x_same + x_over, "pre": x_pre})
    names = SAME_DAY + [f"{k}_overnight" for k in OVERNIGHT]
    X, Y = np.array([r["same"] for r in rows]), np.array([r["y"] for r in rows])
    b, se, r2 = ols(X, Y)
    out = {"generated": datetime.now().isoformat(timespec="seconds"), "days": len(rows), "from": str(rows[0]["d"]), "to": str(rows[-1]["d"]),
           "same_day": {"r2": round(float(r2), 3), "intercept": round(float(b[0]), 4), "factors": {}}}
    for i, n in enumerate(names):
        k = n.replace("_overnight", "")
        out["same_day"]["factors"][n] = {"label": FACT[k][1] + (" (last night)" if n.endswith("_overnight") else ""), "beta": round(float(b[i + 1]), 4), "t": round(float(b[i + 1] / se[i + 1]), 1) if se[i + 1] else None,
                                         "corr": round(float(np.corrcoef(X[:, i], Y)[0, 1]), 3), "symbol": FACT[k][0]}
    # Sensex: the same model on Sensex
    rs = [r for r in rows if r["sx"] is not None]
    bs, ses, r2s = ols(np.array([r["same"] for r in rs]), np.array([r["sx"] for r in rs]))
    out["same_day"]["sensex_r2"] = round(float(r2s), 3)
    out["same_day"]["sensex_betas"] = {n: round(float(bs[i + 1]), 4) for i, n in enumerate(names)}
    # big moves: what NIFTY did on the days one factor moved a lot
    TH = {"brent": 2.0, "usdinr": 0.35, "dxy": 0.6, "us10y": 3.0, "n225": 2.0, "hsi": 2.0, "gold": 1.5, "spx_overnight": 1.5, "ndx_overnight": 2.0, "vix_overnight": 10.0}
    out["shocks"] = {}
    for i, n in enumerate(names):
        if n not in TH:
            continue
        th, col = TH[n], X[:, i]
        res = {"threshold_pct": th}
        for side, m in (("up", col >= th), ("down", col <= -th)):
            ys = Y[m]
            res[side] = {"days": int(m.sum()), "nifty_avg_pct": round(float(ys.mean()), 2) if len(ys) else None,
                         "nifty_fell_pct": round(100 * float((ys < 0).mean()), 1) if len(ys) else None}
        out["shocks"][n] = res
    ui = S["usdinr"]
    rk = max(ui, key=lambda k: ui[k])
    out["usdinr_record"] = {"value": round(ui[rk], 3), "day": str(rk)}
    # before the open: fit on 2022-2024, test on 2025-2026
    pn = ["spx_lastnight", "ndx_lastnight", "vix_lastnight", "brent_yday", "usdinr_yday", "dxy_yday", "us10y_yday"]
    tr, te = [r for r in rows if r["d"] < SPLIT], [r for r in rows if r["d"] >= SPLIT]
    bp, sep, r2p = ols(np.array([r["pre"] for r in tr]), np.array([r["y"] for r in tr]))
    pred = lambda r: float(bp[0] + np.dot(bp[1:], r["pre"]))
    hit = lambda R, key: round(100 * sum(1 for r in R if r[key] is not None and abs(pred(r)) > 1e-9 and (pred(r) > 0) == (r[key] > 0)) / max(1, sum(1 for r in R if r[key] is not None)), 1)
    strong = lambda R: [r for r in R if abs(pred(r)) >= 0.3]
    up = lambda R, key: round(100 * sum(1 for r in R if r[key] is not None and r[key] > 0) / max(1, sum(1 for r in R if r[key] is not None)), 1)
    out["pre_open"] = {"factors": {n: round(float(bp[i + 1]), 4) for i, n in enumerate(pn)}, "intercept": round(float(bp[0]), 4), "r2_train": round(float(r2p), 3),
                       "train": {"days": len(tr), "close_to_close_hit": hit(tr, "y"), "open_to_close_hit": hit(tr, "oc")},
                       "test": {"days": len(te), "close_to_close_hit": hit(te, "y"), "open_to_close_hit": hit(te, "oc"), "base_rate_up": up(te, "y"),
                                "strong_days": len(strong(te)), "strong_close_to_close_hit": hit(strong(te), "y"), "strong_open_to_close_hit": hit(strong(te), "oc")}}
    Path("docs/models").mkdir(parents=True, exist_ok=True)
    Path("docs/models/macro_model.json").write_text(json.dumps(out, indent=1))
    print(f"same-day model: {out['days']} days {out['from']} to {out['to']}, R2 {out['same_day']['r2']} (Sensex {out['same_day']['sensex_r2']})")
    for n, f in out["same_day"]["factors"].items():
        print(f"  {f['label']:28s} beta {f['beta']:+.4f}  t {f['t']:+.1f}  corr {f['corr']:+.3f}")
    print("big moves:", json.dumps(out["shocks"]))
    print("pre-open:", json.dumps(out["pre_open"]))


if __name__ == "__main__":
    main()
