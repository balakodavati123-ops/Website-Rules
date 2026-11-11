"""Candidate universe: large and mid-cap NSE stocks plus commodity ETFs.

Names are today's index members, so any backtest on them has survivorship bias.
`fetch_universe` keeps only tickers that return a valid, current price history.
"""
from __future__ import annotations

import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ETFS = ["GOLDBEES", "SILVERBEES"]
STOCKS = """
RELIANCE TCS INFY HDFCBANK ICICIBANK KOTAKBANK SBIN AXISBANK BHARTIARTL ITC LT HINDUNILVR
BAJFINANCE MARUTI M&M TITAN SUNPHARMA ASIANPAINT ULTRACEMCO NTPC POWERGRID TATASTEEL JSWSTEEL
HINDALCO ADANIPORTS BEL ETERNAL HCLTECH WIPRO TECHM NESTLEIND BAJAJFINSV COALINDIA ONGC GRASIM
DRREDDY CIPLA EICHERMOT HEROMOTOCO BAJAJ-AUTO INDUSINDBK APOLLOHOSP DIVISLAB BRITANNIA
TATACONSUM ADANIENT HDFCLIFE SBILIFE SHRIRAMFIN TRENT JIOFIN TMPV
ABB ADANIGREEN ADANIPOWER AMBUJACEM DMART BAJAJHLDNG BANKBARODA BPCL BOSCHLTD CANBK CHOLAFIN
DABUR DLF GAIL GODREJCP HAVELLS HAL ICICIGI ICICIPRULI IOC INDIGO IRCTC IRFC JINDALSTEL
JSWENERGY LICI LODHA LTIM MARICO MOTHERSON NAUKRI PIDILITIND PFC PNB RECLTD SHREECEM SIEMENS
SRF TATAPOWER TVSMOTOR TORNTPHARM UNITDSPR VBL VEDL ZYDUSLIFE CGPOWER HYUNDAI BAJAJHFL SWIGGY
ABCAPITAL ACC ALKEM APLAPOLLO ASHOKLEY ASTRAL AUBANK AUROPHARMA BALKRISIND BANDHANBNK BANKINDIA
BHARATFORG BHEL BIOCON COFORGE COLPAL CONCOR CUMMINSIND DIXON ESCORTS EXIDEIND FEDERALBNK
GMRAIRPORT GODREJPROP HDFCAMC HINDPETRO IDFCFIRSTB IGL INDHOTEL INDUSTOWER JUBLFOOD KPITTECH
LTF LUPIN MRF MFSL MAXHEALTH MPHASIS MUTHOOTFIN NHPC NMDC OBEROIRLTY OFSS OIL PAGEIND PAYTM
PERSISTENT PETRONET PHOENIXLTD PIIND POLYCAB POLICYBZR PRESTIGE SAIL SBICARD SOLARINDS SONACOMS
SUPREMEIND SUZLON TATACOMM TATAELXSI TATATECH TIINDIA TORNTPOWER UPL UNIONBANK VOLTAS YESBANK
IDEA KALYANKJIL LICHSGFIN MANKIND MAZDOCK NYKAA PATANJALI RVNL BSE CDSL DELHIVERY APOLLOTYRE
ATGL BDL COCHINSHIP FACT HUDCO IREDA IDBI INDIANB IOB JSWINFRA JSL LTTS MAHABANK M&MFIN MRPL
NLCINDIA NTPCGREEN POONAWALLA SJVN TATAINVEST UCOBANK ZEEL GLENMARK FORTIS HINDZINC NATIONALUM
ABBOTINDIA BERGEPAINT COROMANDEL DALBHARAT DEEPAKNTR GUJGASLTD IPCALAB JKCEMENT LAURUSLABS
SYNGENE UBL
""".split()
INDEXES = ["^NSEI", "^INDIAVIX"]


def _fetch(sym: str, period: str):
    import yfinance as yf
    for _ in range(2):
        try:
            df = yf.Ticker(sym).history(period=period, auto_adjust=False)
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(
                subset=["Open", "High", "Low", "Close"])
            px = df[["Open", "High", "Low", "Close"]]
            df = df[(px > 0).all(axis=1) & (df["High"] >= df["Low"])]
            df.index = pd.to_datetime(df.index.date)
            return df[~df.index.duplicated()]
        except Exception:
            continue
    return None


def fetch_universe(years: int, cache: Path | None = None) -> dict[str, pd.DataFrame]:
    """Ticker -> daily OHLCV. Tickers with no data or a stale last bar are dropped."""
    if cache and (cache / "universe.pkl").exists():
        return pickle.loads((cache / "universe.pkl").read_bytes())
    names = STOCKS + ETFS + INDEXES
    syms = [n if n.startswith("^") else f"{n}.NS" for n in names]
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(lambda s: _fetch(s, f"{years + 2}y"), syms))
    latest = max(f.index[-1] for f in frames if f is not None and len(f))
    out = {}
    for name, f in zip(names, frames):
        if f is None or len(f) < 260 or (latest - f.index[-1]).days > 5:
            continue
        out[name] = f
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "universe.pkl").write_bytes(pickle.dumps(out))
    return out
