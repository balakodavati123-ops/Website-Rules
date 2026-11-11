import json

import pandas as pd

from trading_team.agents import run_concall_analyst
from trading_team.fundamentals import find_transcript, summarise_quarters


def _stmt(cols):
    data = {pd.Timestamp(c): v for c, v in cols.items()}
    return pd.DataFrame(data, index=["Total Revenue", "Net Income", "Operating Income"])


def test_quarter_growth_uses_same_quarter_last_year():
    s = summarise_quarters(_stmt({"2026-09-30": [1200e7, 240e7, 300e7],
                                  "2026-06-30": [1100e7, 200e7, 250e7],
                                  "2025-09-30": [1000e7, 200e7, 200e7]}))
    assert s["revenue_cr"] == 1200.0 and s["revenue_yoy_pct"] == 20.0
    assert s["net_profit_yoy_pct"] == 20.0
    assert (s["operating_margin_pct"], s["operating_margin_year_ago_pct"]) == (25.0, 20.0)


def test_quarter_growth_unverified_when_year_ago_missing():
    s = summarise_quarters(_stmt({"2026-09-30": [1200e7, 240e7, 300e7],
                                  "2026-06-30": [1100e7, 200e7, 250e7]}))
    assert s["compared_with"] == "UNVERIFIED" and s["revenue_yoy_pct"] is None


def test_find_transcript_picks_newest():
    html = ('<h3>Concalls</h3><div>Nov 2026</div><a href="https://x/a.pdf?a=1&amp;b=2">'
            'Transcript</a><div>Jul 2026</div><a href="https://x/b.pdf">Transcript</a>')
    assert find_transcript(html) == ("Nov 2026", "https://x/a.pdf?a=1&b=2")
    assert find_transcript("<p>nothing</p>") is None


class CallLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user, max_tokens=1200):
        return json.dumps(self.reply)


TRANSCRIPT = ("Operator: welcome. Management: Our order book stands at 75,000 crores and "
              "we expect revenue growth of 15% for the full year. Margins should stay "
              "around 27%. Analyst: thank you, that is helpful.")


def test_concall_keeps_verified_quotes_and_drops_invented_ones():
    out = run_concall_analyst(CallLLM({
        "signal": "bullish", "summary": "Order book is 75,000 crores with 15% growth guided.",
        "guidance": ["Revenue growth of 15%", "Margins of 35% next year"],
        "risks": [],
        "quotes": ["we expect revenue growth of 15% for the full year",
                   "we will double our profits next year for sure"]}),
        {"period": "Nov 2026", "url": "https://x/a.pdf", "text": TRANSCRIPT})
    assert out["quotes"] == ["we expect revenue growth of 15% for the full year"]
    assert out["quotes_dropped"] == 1
    assert out["guidance"] == ["Revenue growth of 15%"]      # 35% is not in the call
    assert out["signal"] == "bullish"


def test_concall_with_no_verified_quote_is_neutral():
    out = run_concall_analyst(CallLLM({
        "signal": "bullish", "summary": "Profit will rise 90%.", "guidance": [], "risks": [],
        "quotes": ["completely made up statement by management"]}),
        {"period": "Nov 2026", "url": "https://x/a.pdf", "text": TRANSCRIPT})
    assert out["signal"] == "neutral" and out["quotes"] == []
    assert out["summary"].startswith("[removed")
