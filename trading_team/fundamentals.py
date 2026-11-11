"""Company results and earnings-call transcripts.

Everything numeric is computed here in code; the analysts only read it.
Sources: Yahoo Finance for quarterly figures and EPS surprise, the company's
screener.in page to locate the latest concall transcript, and the transcript
PDF itself from BSE (the official filing).
"""
from __future__ import annotations

import hashlib
import io
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (research script)"}
CRORE = 1e7


def _pct(new, old):
    if new is None or old is None or old == 0 or new != new or old != old:
        return None
    return round((new / abs(old) - 1) * 100, 1) if old > 0 else None


def summarise_quarters(stmt) -> dict | None:
    """Latest quarter vs the same quarter a year earlier, from a yfinance
    quarterly income statement (columns = period ends, newest first)."""
    if stmt is None or stmt.empty or "Total Revenue" not in stmt.index:
        return None
    cols = sorted(stmt.columns, reverse=True)
    latest = cols[0]
    prior = next((c for c in cols[1:] if 350 <= (latest - c).days <= 380), None)

    def val(row, col):
        if col is None or row not in stmt.index:
            return None
        v = stmt.at[row, col]
        return None if v != v else float(v)

    def cr(v):
        return None if v is None else round(v / CRORE, 1)

    rev, rev0 = val("Total Revenue", latest), val("Total Revenue", prior)
    ni, ni0 = val("Net Income", latest), val("Net Income", prior)
    op, op0 = val("Operating Income", latest), val("Operating Income", prior)

    def margin(o, r):
        return None if o is None or not r else round(o / r * 100, 1)

    return {
        "quarter_end": latest.date().isoformat(),
        "compared_with": prior.date().isoformat() if prior is not None else "UNVERIFIED",
        "revenue_cr": cr(rev), "revenue_yoy_pct": _pct(rev, rev0),
        "net_profit_cr": cr(ni), "net_profit_yoy_pct": _pct(ni, ni0),
        "operating_margin_pct": margin(op, rev),
        "operating_margin_year_ago_pct": margin(op0, rev0),
    }


def summarise_earnings(dates, today: date) -> dict | None:
    """Last EPS surprise and the next results date from yfinance earnings dates."""
    if dates is None or not len(dates):
        return None
    out = {}
    past = dates.dropna(subset=["Reported EPS"])
    if len(past):
        row = past.iloc[0]
        out["last_result_date"] = past.index[0].date().isoformat()
        out["eps_reported"] = round(float(row["Reported EPS"]), 2)
        if row.get("EPS Estimate") == row.get("EPS Estimate"):
            out["eps_estimate"] = round(float(row["EPS Estimate"]), 2)
        if row.get("Surprise(%)") == row.get("Surprise(%)"):
            out["eps_surprise_pct"] = round(float(row["Surprise(%)"]), 1)
    future = [d.date() for d in dates.index if d.date() >= today]
    if future:
        nxt = min(future)
        out["next_result_date"] = nxt.isoformat()
        out["days_to_next_result"] = (nxt - today).days
    return out or None


def _get(url: str, referer: str | None = None, timeout: int = 40) -> bytes:
    headers = dict(UA)
    if referer:
        headers["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                timeout=timeout) as resp:
        return resp.read()


def find_transcript(page_html: str) -> tuple[str, str] | None:
    """(period label, transcript URL) of the newest concall on a screener.in
    company page, or None."""
    i = page_html.find("Concalls")
    if i == -1:
        return None
    seg = page_html[i:i + 20000]
    m = re.search(r'href="([^"]+)"[^>]*>\s*Transcript', seg)
    if not m:
        return None
    labels = re.findall(r">\s*([A-Z][a-z]{2} \d{4})\s*<", seg[:m.start()])
    return (labels[-1] if labels else "latest"), m.group(1).replace("&amp;", "&")


def latest_concall(ticker: str, cache_dir: str | Path = "data/concalls") -> dict | None:
    """Newest concall transcript as normalised text, cached on disk."""
    symbol = urllib.parse.quote(ticker.split(".")[0])
    html = None
    for path in (f"{symbol}/consolidated/", f"{symbol}/"):
        try:
            html = _get(f"https://www.screener.in/company/{path}").decode("utf8", "ignore")
        except Exception:
            continue
        if "Concalls" in html:
            break
    found = find_transcript(html or "")
    if not found:
        return None
    period, url = found
    if not url.lower().startswith("https://"):
        return None
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"{ticker.split('.')[0]}_{hashlib.sha1(url.encode()).hexdigest()[:10]}.txt"
    if f.exists():
        text = f.read_text()
    else:
        from pypdf import PdfReader
        pdf = _get(url, referer="https://www.bseindia.com/")
        reader = PdfReader(io.BytesIO(pdf))
        text = " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)
        f.write_text(text)
    if len(text) < 3000:  # scanned or empty PDF
        return None
    return {"period": period, "url": url, "text": text}
