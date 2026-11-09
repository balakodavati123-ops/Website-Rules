import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from trading_team.models import Bar  # noqa: E402


def make_bars(n=260, start=date(2025, 1, 1), base=100.0, drift=0.002, amp=0.01):
    """Deterministic uptrending bars with a small sine wobble. Weekdays only."""
    bars, price, day = [], base, start
    i = 0
    while len(bars) < n:
        if day.weekday() < 5:
            wobble = math.sin(i / 3) * amp
            close = price * (1 + drift + wobble)
            high = max(price, close) * 1.007
            low = min(price, close) * 0.993
            bars.append(Bar(day, round(price, 4), round(high, 4), round(low, 4),
                            round(close, 4), 1_000_000.0))
            price = close
            i += 1
        day += timedelta(days=1)
    return bars


class FakeProvider:
    def __init__(self, data=None, vix=12.0, fail=()):
        self.data = data or {}
        self._vix = vix
        self.fail = set(fail)

    def history(self, ticker, days):
        if ticker in self.fail:
            raise RuntimeError("network down")
        return self.data.get(ticker, [])

    def fundamentals(self, ticker):
        return {"trailingPE": 18.5, "priceToBook": 2.1}

    def india_vix(self):
        return self._vix

    def flows(self):
        return None

    def news(self, ticker):
        return None


class FakeLLM:
    """Answers each agent by inspecting its system prompt."""

    def __init__(self, pm_action="BUY", pm_ticker=None, stop=4.0, target=22.0):
        self.calls = []
        self.pm_action = pm_action
        self.pm_ticker = pm_ticker
        self.stop = stop
        self.target = target

    def complete(self, system, user, max_tokens=1200):
        self.calls.append(system.split("\n")[0][:40])
        if "PORTFOLIO MANAGER" in system:
            ticker = self.pm_ticker
            if ticker is None:
                ticker = json.loads(user)["candidates"][0]["ticker"]
            return json.dumps({"action": self.pm_action,
                               "ticker": ticker if self.pm_action == "BUY" else None,
                               "stop_pct": self.stop, "target_pct": self.target,
                               "confidence": 0.61,
                               "rationale": "Trend and momentum agree."})
        if "BULL researcher" in system:
            return "Bull case text."
        if "BEAR researcher" in system:
            return "Bear case text."
        return json.dumps({"signal": "bullish", "summary": "Looks fine.",
                           "key_points": ["a"]})


@pytest.fixture
def bars():
    return make_bars()
