"""Data agent: gathers prices, index levels, fundamentals, flows and news.

Anything that cannot be confirmed from a configured source is kept in the
snapshot with verified=False, and the rest of the team reports it as
"Data Unverified" rather than estimating it.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from .guardrails import is_fresh
from .models import Bar, DataPoint, Snapshot

log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

FUNDAMENTAL_KEYS = (
    "trailingPE", "forwardPE", "priceToBook", "trailingEps",
    "returnOnEquity", "debtToEquity", "earningsGrowth", "revenueGrowth", "marketCap",
)


class DataProvider(Protocol):
    def history(self, ticker: str, days: int) -> list[Bar]: ...
    def fundamentals(self, ticker: str) -> dict[str, Any]: ...
    def india_vix(self) -> float | None: ...
    def flows(self) -> dict[str, Any] | None: ...
    def news(self, ticker: str) -> list[dict[str, str]] | None: ...


def validate_bars(bars: list[Bar]) -> list[str]:
    """Returns a list of problems. An empty list means the bars are usable."""
    if not bars:
        return ["no bars returned"]
    problems: list[str] = []
    for b in bars:
        if min(b.open, b.high, b.low, b.close) <= 0:
            problems.append(f"{b.day}: non-positive price")
        elif b.high < b.low:
            problems.append(f"{b.day}: high below low")
        elif not (b.low <= b.close <= b.high and b.low <= b.open <= b.high):
            problems.append(f"{b.day}: open/close outside high-low range")
    days = [b.day for b in bars]
    if days != sorted(days) or len(set(days)) != len(days):
        problems.append("dates not strictly increasing")
    return problems


class DataAgent:
    MIN_BARS = 60

    def __init__(self, provider: DataProvider, history_days: int = 400):
        self.provider = provider
        self.history_days = history_days

    def snapshot(self, ticker: str, as_of: date | None = None,
                 enrich: bool = True) -> Snapshot:
        snap = Snapshot(ticker=ticker, as_of=as_of or date.today())

        # Price history: must pass validation and be long enough to analyse.
        try:
            bars = self.provider.history(ticker, self.history_days)
        except Exception as exc:  # network / provider failure
            log.warning("history failed for %s: %s", ticker, exc)
            bars = []
            snap.points["price_history_error"] = DataPoint(note=str(exc)[:120])
        problems = validate_bars(bars)
        if problems:
            snap.points["price_history_check"] = DataPoint(
                value=problems[:3], note="failed validation")
        elif len(bars) < self.MIN_BARS:
            snap.points["price_history_check"] = DataPoint(
                value=len(bars), note=f"fewer than {self.MIN_BARS} bars")
        elif not is_fresh(bars, snap.as_of):
            snap.points["price_freshness"] = DataPoint(
                value=bars[-1].day.isoformat(), note="last bar is stale")
        else:
            snap.bars = bars
            snap.points["price_history"] = DataPoint(
                value=len(bars), source="provider", verified=True)

        return self.enrich(snap) if enrich else snap

    def enrich(self, snap: Snapshot) -> Snapshot:
        """Adds fundamentals, flows and news. Skipped for tickers that are only
        screened on price, so a wide watchlist stays fast."""
        ticker = snap.ticker
        # Fundamentals: a field is verified only if the provider returned a value.
        try:
            info = self.provider.fundamentals(ticker) or {}
        except Exception as exc:
            log.warning("fundamentals failed for %s: %s", ticker, exc)
            info = {}
        for key in FUNDAMENTAL_KEYS:
            value = info.get(key)
            snap.points[key] = DataPoint(
                value=value, source="provider" if value is not None else None,
                verified=value is not None)

        # Flows and news: only verified when a configured source returns them.
        flows = self._safe(self.provider.flows)
        snap.points["fii_dii_flows"] = DataPoint(
            value=flows, source="provider" if flows else None,
            verified=bool(flows), note="" if flows else "no verified source")
        # Quarterly results and the latest concall transcript, where the provider has them.
        for name, note in (("results", "no quarterly results confirmed"),
                           ("concall", "no concall transcript found")):
            fn = getattr(self.provider, name, None)
            value = self._safe(lambda: fn(ticker)) if fn else None
            key = "quarterly_results" if name == "results" else "concall"
            snap.points[key] = DataPoint(
                value=value, source="provider" if value else None,
                verified=bool(value), note="" if value else note)
        news = self._safe(lambda: self.provider.news(ticker))
        snap.points["news"] = DataPoint(
            value=news, source="provider" if news else None,
            verified=bool(news), note="" if news else "no headlines confirmed")
        return snap

    def market(self) -> dict[str, DataPoint]:
        vix = self._safe(self.provider.india_vix)
        return {
            "india_vix": DataPoint(
                value=vix, source="provider" if vix is not None else None,
                verified=vix is not None,
                note="" if vix is not None else "India VIX unavailable"),
        }

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception as exc:
            log.warning("data call failed: %s", exc)
            return None


class YFinanceProvider:
    """Free Yahoo Finance data via yfinance. Tickers use exchange suffixes,
    e.g. RELIANCE.NS for NSE. Flows have no free verified source, so they
    always come back as unverified."""

    def __init__(self):
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install yfinance") from exc
        self._yf = yf

    def history(self, ticker: str, days: int) -> list[Bar]:
        period = "2y" if days > 365 else "1y"
        df = self._yf.Ticker(ticker).history(period=period, auto_adjust=False)
        # During market hours the last row is an unfinished session. Signals must
        # use completed bars only, so drop it until after the 15:30 IST close.
        now = datetime.now(IST)
        if len(df) and df.index[-1].date() == now.date() and now.hour * 60 + now.minute < 945:
            df = df.iloc[:-1]
        bars: list[Bar] = []
        for ts, row in df.iterrows():
            bars.append(Bar(
                day=ts.date(), open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=float(row["Volume"])))
        return bars

    def fundamentals(self, ticker: str) -> dict[str, Any]:
        info = self._yf.Ticker(ticker).info or {}
        return {k: info.get(k) for k in FUNDAMENTAL_KEYS}

    def india_vix(self) -> float | None:
        bars = self.history("^INDIAVIX", 30)
        return bars[-1].close if bars else None

    def flows(self) -> dict[str, Any] | None:
        return None  # no verified free source configured

    def results(self, ticker: str) -> dict[str, Any] | None:
        """Latest quarter vs a year earlier, plus EPS surprise and next results date."""
        from .fundamentals import summarise_earnings, summarise_quarters
        t = self._yf.Ticker(ticker)
        out = summarise_quarters(t.quarterly_income_stmt) or {}
        try:
            out.update(summarise_earnings(t.get_earnings_dates(limit=8),
                                          datetime.now(IST).date()) or {})
        except Exception as exc:
            log.warning("earnings dates failed for %s: %s", ticker, exc)
        return out or None

    def concall(self, ticker: str) -> dict[str, Any] | None:
        from .fundamentals import latest_concall
        return latest_concall(ticker)

    def news(self, ticker: str) -> list[dict[str, str]] | None:
        items = self._yf.Ticker(ticker).news or []
        out = []
        for item in items[:10]:
            content = item.get("content", item)
            title = content.get("title")
            link = (content.get("canonicalUrl") or {}).get("url") or content.get("link")
            if title and link:
                out.append({"title": title, "link": link})
        return out or None
