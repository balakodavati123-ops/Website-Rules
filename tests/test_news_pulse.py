import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import news_pulse as NP   # noqa: E402

IDX = {"pair": {"indusind bank": "INDUSINDBK", "anand rathi": "ARSSBL"}, "one": {"infosys": "INFY", "wipro": "WIPRO"}, "sym": {"sbin": "SBIN"}}
NOW = datetime(2026, 11, 23, 10, 5, tzinfo=NP.IST)


def rss(*titles):
    return "<rss>" + "".join(f"<item><title>{t}</title><link>https://x/{i}</link><pubDate>Mon, 23 Nov 2026 04:30:00 GMT</pubDate></item>" for i, t in enumerate(titles)) + "</rss>"


def test_emotion_scores_phrases_once_and_softens_denials():
    assert NP.score("Larsen bags order worth Rs 5,000 crore")[0] == 5
    s, hits = NP.score("Infosys Q2 profit jumps 12%")
    assert hits == ["profit jumps"] and s == 3.9 and NP.emotion(s) == "Optimism"
    assert NP.emotion(NP.score("Infosys shares plunge 8% after CEO resigns")[0]) == "Panic"
    assert abs(NP.score("Company denies fraud allegation")[0]) < 2


def test_matching_ignores_brokers_and_market_wide_stories():
    assert NP.match("IndusInd Bank shares jump 8% on volume surge", IDX) == "INDUSINDBK"
    assert NP.match("Anand Rathi sees 30% upside in Infosys", IDX) == "INFY"
    assert NP.match("Infosys and Wipro rally", IDX) is None                        # two companies: ambiguous
    assert NP.match("Nifty IT stocks: infosys leads gains", IDX) is None            # market-wide story, one stray word


def test_scan_hands_fresh_signals_to_the_hunters_and_tracks_them():
    st = NP.new_state()
    feed = rss("Infosys profit jumps 12% in Q2", "Infosys profit jumps 12% in Q2", "Nifty ends flat", "Wipro shares plunge after CEO resigns")
    new = NP.scan(st, IDX, NOW, get=lambda u: feed if "economictimes" in u else "", filings=[{"symbol": "SBIN", "desc": "Board approves bonus issue", "ts": NOW.timestamp() - 60, "tone": "positive"}])
    assert {s["symbol"] for s in new} == {"INFY", "WIPRO", "SBIN"} and len(new) == 3 and all(s["lag_s"] is not None for s in new)
    assert NP.scan(st, IDX, NOW, get=lambda u: feed) == []                          # seen once: never signalled twice
    hunt = NP.for_hunters(st, NOW, doubted={"WIPRO"})
    assert set(hunt) == {"INFY", "SBIN"} and hunt["INFY"]["tone"] == "positive"
    NP.track(st, {"INFY": 100.0, "WIPRO": 50.0}, traded=set(), skipped={}, checks={"WIPRO": {"verdict": "doubt", "why": "old news"}})
    NP.track(st, {"INFY": 101.0, "WIPRO": 49.0}, traded={"INFY"}, skipped={}, checks={"WIPRO": {"verdict": "doubt", "why": "old news"}})
    by = {s["symbol"]: s for s in st["signals"]}
    assert by["INFY"]["move_pct"] == 1.0 and by["INFY"]["status"] == "traded" and by["WIPRO"]["status"].startswith("skipped")
