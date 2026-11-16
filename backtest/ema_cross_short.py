"""Does a bearish 20/50 EMA cross near a high precede a fall? Forward returns after the cross, all tickers, 5 years."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from universe import fetch_universe
data = fetch_universe(5, Path(sys.argv[1]) if len(sys.argv) > 1 else None)
rows = []
for t, df in data.items():
    if t.startswith("^"):
        continue
    c = df["Close"].dropna(); e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    cross = (e20 < e50) & (e20.shift(1) >= e50.shift(1)); near_high = c.rolling(20).max() >= 0.95 * c.rolling(120).max()
    for d in c.index[(cross & near_high).values]:
        i = c.index.get_loc(d)
        if i + 11 < len(c):
            rows.append({"r5": c.iloc[i + 6] / c.iloc[i + 1] - 1, "r10": c.iloc[i + 11] / c.iloc[i + 1] - 1})
r = pd.DataFrame(rows); base = {k: float(np.mean([(v["Close"].iloc[j + h] / v["Close"].iloc[j] - 1) for v in list(data.values())[:60] for j in range(300, len(v) - h, 40)])) for k, h in (("r5", 5), ("r10", 10))}
print(f"bearish crosses near a high: {len(r)}")
for k in ("r5", "r10"):
    print(f"{k}: mean {r[k].mean()*100:+.2f}%  share that fell {(r[k] < 0).mean()*100:.0f}%  (any stock, any day: {base[k]*100:+.2f}%)")
