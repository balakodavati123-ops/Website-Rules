import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backend import ipo

FX = Path(__file__).parent / "fixtures" / "ipo"
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 18, 0, tzinfo=IST)


def jf(name):
    return json.loads((FX / name).read_text())


def tf(name):
    return (FX / name).read_text()


SEBI_EXTRA = ("<table><tr role='row'><td>Nov 10, 2026</td><td><a href=\"https://www.sebi.gov.in/filings/mahanadi-drhp_1.html\" "
              "title=\"Mahanadi Coalfields Limited - DRHP\" class=\"points\">x</a></td></tr></table>")


def fake_fetch(fail=(), calls=None):
    def f(url, headers=None):
        if calls is not None:
            calls.append(url)
        for bad in fail:
            if bad in url:
                raise OSError("down")
        if "ipo-current-issue" in url:
            return json.dumps(jf("nse_current.json"))
        if "all-upcoming-issues" in url:
            return json.dumps(jf("nse_upcoming.json")).encode()
        if "public-past-issues" in url:
            return json.dumps(jf("nse_past.json"))
        if "ipo-active-category" in url:
            return json.dumps(jf("nse_subs_mahacoal.json")) if "MAHACOAL" in url else json.dumps({"dataList": []})
        if "ipo-detail" in url:
            return json.dumps(jf("nse_detail_mahacoal.json" if "MAHACOAL" in url else "nse_detail_watrana.json"
                                 if "WATRANA" in url else "nse_detail_watrana.json"))
        if "sebi.gov.in" in url:
            return tf("sebi_listing.html") + SEBI_EXTRA
        if "news.google.com" in url:
            return tf("news.xml")
        raise AssertionError(url)
    return f


def sample(**kw):
    d = {"name": "Acme Limited", "symbol": "ACME", "board": "Mainboard", "status": "open", "open_date": "2026-11-18", "close_date": "2026-11-20",
         "price_band": [95.0, 100.0], "lot_size": 150, "issue_size_cr": 1000.0, "fresh_cr": 600.0, "ofs_cr": 400.0, "drhp_url": "https://x",
         "subscription": {"qib": 40.0, "nii": 20.0, "retail": 5.0, "total": 25.0, "as_of": "x"}}
    d.update(kw)
    return d


# ---- parsers

def test_parse_issues_current_and_upcoming():
    cur = ipo.parse_issues(jf("nse_current.json"), "current")
    assert [r["symbol"] for r in cur] == ["MAHACOAL", "WATRANA"]
    m, w = cur
    assert m["board"] == "Mainboard" and w["board"] == "SME"
    assert m["price_band"] == [129.0, 136.0] and m["open_date"] == date(2026, 11, 19) and m["close_date"] == date(2026, 11, 23)
    assert abs(m["total_times"] - 0.114) < 0.001
    up = ipo.parse_issues(jf("nse_upcoming.json"), "upcoming")
    assert up[0]["board"] == "SME" and up[0]["price_band"] == [130.0, 142.0]


def test_parse_issues_variants_and_junk():
    rows = ipo.parse_issues({"data": [{"company": "Foo Ltd", "SYMBOL": "FOO", "series": "EQ", "priceRange": "Rs. 10 - Rs. 12", "lot_size": "1,000"}]})
    assert rows[0]["name"] == "Foo Ltd" and rows[0]["symbol"] == "FOO" and rows[0]["price_band"] == [10.0, 12.0] and rows[0]["lot_size"] == 1000
    assert ipo.parse_issues("<html>blocked</html>") == [] and ipo.parse_issues(None) == []
    past = ipo.parse_issues(jf("nse_past.json"), "past")
    assert past[0]["listing_date"] == date(2026, 11, 9) and past[0]["board"] == "SME"


def test_parse_subscription_and_detail():
    s = ipo.parse_subscription(jf("nse_subs_mahacoal.json"))
    assert s["qib"] == 1.37 and s["nii"] == 0.18 and s["retail"] == 0.24 and s["as_of"].startswith("20-Nov-2026")
    assert ipo.parse_subscription({"dataList": []}) is None and ipo.parse_subscription("nope") is None
    d = ipo.parse_detail(jf("nse_detail_mahacoal.json"), 136.0)
    assert d["lot_size"] == 110 and d["fresh_cr"] is None and d["ofs_cr"] == round(661836300 * 136 / 1e7, 2)
    d2 = ipo.parse_detail(jf("nse_detail_watrana.json"), 245.0)
    assert d2["lot_size"] == 600 and d2["fresh_cr"] == round(4902000 * 245 / 1e7, 2) and d2["ofs_cr"] is None


def test_parse_sebi():
    rows = ipo.parse_sebi(tf("sebi_listing.html"))
    assert rows and rows[0]["date"] >= rows[-1]["date"]
    assert rows[0]["company"] == "Chartered Speed Limited" and rows[0]["url"].startswith("https://www.sebi.gov.in/filings/")
    assert any(r["company"] == "Sagar Defence Engineering Limited" for r in rows)
    assert ipo.parse_sebi("<html></html>") == []


def test_parse_rss():
    items = ipo.parse_rss(tf("news.xml"))
    assert items and all(i["title"] and i["link"] and i["time"].endswith("Z") for i in items)
    assert items == sorted(items, key=lambda i: i["time"], reverse=True)
    assert not items[0]["title"].endswith(" - " + items[0]["source"])
    assert ipo.parse_rss("not xml") == []


def test_match_drhp_fuzzy():
    d = [{"company": "Mahanadi Coalfields Limited", "url": "u1", "date": "2026-01-01"}, {"company": "Other Co", "url": "u2", "date": "2026-01-01"}]
    assert ipo.match_drhp("Mahanadi Coalfields Ltd.", d)["url"] == "u1"
    assert ipo.match_drhp("Zebra Foods Private Limited", d) is None


# ---- rules

def test_min_invest():
    assert ipo.min_invest(110, [129, 136]) == 14960.0
    assert ipo.min_invest(None, [129, 136]) is None and ipo.min_invest(110, None) is None


def test_apply_on_strong_mainboard():
    a = ipo.analyse(sample(), date(2026, 11, 20))
    assert a["verdict"] == "Apply (1 lot)" and a["score"] >= 65
    lv = a["listing_view"]
    assert lv["low_pct"] < lv["high_pct"] and a["listing_px"][0] == round(100 * (1 + lv["low_pct"] / 100), 2)
    assert "issue price" in a["after_listing"] and a["method"] == "rules"


def test_sme_penalised_and_flagged():
    a = ipo.analyse(sample(board="SME", issue_size_cr=60.0), date(2026, 11, 20))
    b = ipo.analyse(sample(issue_size_cr=60.0), date(2026, 11, 20))
    assert a["score"] < b["score"] and any("SME" in r for r in a["risks"])
    assert a["listing_view"]["low_pct"] < b["listing_view"]["low_pct"]
    assert "thinly traded" in a["after_listing"]


def test_ofs_heavy_flag():
    a = ipo.analyse(sample(ofs_cr=800.0, fresh_cr=200.0), date(2026, 11, 20))
    assert any("Offer-for-sale heavy" in r and "80%" in r for r in a["risks"])
    clean = ipo.analyse(sample(), date(2026, 11, 20))
    assert a["score"] == clean["score"] - ipo.OFS_PENALTY


def test_size_flags():
    assert any("small" in r for r in ipo.analyse(sample(issue_size_cr=20.0), date(2026, 11, 20))["risks"])
    assert any("large" in r for r in ipo.analyse(sample(issue_size_cr=20000.0), date(2026, 11, 20))["risks"])


def test_weak_demand_is_avoid_and_closed_is_watch():
    weak = sample(subscription={"qib": 0.4, "nii": 0.5, "retail": 0.9, "total": 0.6, "as_of": "x"})
    assert ipo.analyse(weak, date(2026, 11, 20))["verdict"] == "Avoid"
    closed = ipo.analyse(sample(status="closed"), date(2026, 11, 21))
    assert closed["verdict"] == "Watch" and closed["listing_px"]


def test_early_bidding_low_multiple_is_watch_without_range():
    a = ipo.analyse(sample(close_date="2026-11-23", subscription={"qib": 0.0, "nii": 0.2, "retail": 0.3, "total": 0.2, "as_of": "x"}), date(2026, 11, 20))
    assert a["verdict"] == "Watch" and a["listing_px"] is None and a["listing_view"]["low_pct"] is None


def test_no_subscription_and_missing_data():
    a = ipo.analyse(sample(subscription=None, status="upcoming"), date(2026, 11, 10))
    assert a["verdict"] == "Watch" and a["score"] is None and a["listing_view"]["basis"] == "unknown until bidding opens"
    b = ipo.analyse(sample(price_band=None, subscription=None), date(2026, 11, 10))
    assert b["verdict"] == "Not enough data"
    c = ipo.analyse(sample(lot_size=None), date(2026, 11, 20))
    assert c["verdict"] == "Watch" and any("Lot size" in r for r in c["risks"])


def test_weighted_subscription_renormalises():
    w, _ = ipo.weighted_subscription({"qib": 10, "nii": 20, "retail": None, "total": 5})
    assert w == round((10 * 0.5 + 20 * 0.3) / 0.8, 2)
    assert ipo.weighted_subscription({"qib": None, "nii": None, "retail": None, "total": 7})[0] == 7
    assert ipo.weighted_subscription(None)[0] is None


# ---- build

def test_build_offline_shape():
    out = ipo.build(NOW, {}, fake_fetch())
    assert set(out) == {"updated_at", "ipos", "drhp_recent", "sources"}
    assert out["sources"] == {"nse": "ok", "sebi": "ok", "news": "ok"}
    by = {i["symbol"]: i for i in out["ipos"]}
    m = by["MAHACOAL"]
    assert m["board"] == "Mainboard" and m["status"] == "open" and m["lot_size"] == 110 and m["min_invest_rs"] == 14960.0
    assert m["subscription"]["qib"] == 1.37 and m["drhp_url"] == "https://www.sebi.gov.in/filings/mahanadi-drhp_1.html"
    assert m["thesis"] is None and m["analysis"]["method"] == "rules" and len(m["news"]) <= 5
    assert any(a in m["analysis"]["risks"][0] for a in ("Offer-for-sale",)) and m["fresh_cr"] is None
    w = by["WATRANA"]
    assert w["board"] == "SME" and w["lot_size"] == 600 and w["min_invest_rs"] == 600 * 245.0
    assert by["SHREESIDHI"]["status"] == "upcoming" and by["SHREESIDHI"]["analysis"]["verdict"] == "Watch"
    assert by["VPFL"]["status"] == "listed" and by["VPFL"]["listing_date"] == "2026-11-09"
    assert len(out["drhp_recent"]) <= 15 and set(out["drhp_recent"][0]) == {"date", "company", "url"}
    keys = {"name", "symbol", "board", "status", "open_date", "close_date", "listing_date", "price_band", "lot_size", "min_invest_rs", "issue_size_cr",
            "fresh_cr", "ofs_cr", "subscription", "drhp_url", "news", "analysis", "thesis"}
    assert set(m) == keys and set(m["analysis"]) == {"score", "verdict", "reasons", "risks", "listing_view", "listing_px", "after_listing", "method"}
    json.dumps(out)


def test_build_source_failures_are_reported_not_raised():
    out = ipo.build(NOW, {}, fake_fetch(fail=("nseindia", "sebi.gov.in", "news.google.com")))
    assert out["ipos"] == [] and out["drhp_recent"] == []
    assert out["sources"]["nse"].startswith("error") and out["sources"]["sebi"].startswith("error") and out["sources"]["news"].startswith("error")

    def blocked(url, headers=None):
        if "nseindia" in url:
            raise type("E", (OSError,), {"code": 403})("forbidden")
        return fake_fetch()(url, headers)
    assert ipo.build(NOW, {}, blocked)["sources"]["nse"] == "blocked"

    def html(url, headers=None):
        return "<html>Access Denied</html>" if "nseindia" in url else fake_fetch()(url, headers)
    assert ipo.build(NOW, {}, html)["sources"]["nse"] == "blocked"


def test_build_llm_thesis_and_cache():
    llm_calls = []

    def llm(kind, system, prompt, tier, max_tokens):
        llm_calls.append((kind, tier, max_tokens, json.loads(prompt)["name"]))
        return "A short plain thesis."
    state, fetch_calls = {}, []
    out = ipo.build(NOW, state, fake_fetch(calls=fetch_calls), llm)
    live = [i for i in out["ipos"] if i["status"] != "listed"]
    assert len(llm_calls) == len(live) == 3 and all(c[0] == "ipo_thesis" and c[1] == "write" for c in llm_calls)
    assert all(i["thesis"] == "A short plain thesis." and i["analysis"]["method"] == "rules+claude" for i in live)
    assert all(i["thesis"] is None for i in out["ipos"] if i["status"] == "listed")
    n_fetch = len(fetch_calls)
    json.dumps(state)  # must be persistable
    out2 = ipo.build(NOW + timedelta(hours=2), state, fake_fetch(calls=fetch_calls), llm)
    assert len(llm_calls) == 3  # same day: no new llm call
    assert [i["thesis"] for i in out2["ipos"]] == [i["thesis"] for i in out["ipos"]]
    news_calls = [u for u in fetch_calls[n_fetch:] if "news.google.com" in u]
    assert len(news_calls) == 1  # only the general query; per-company news is cached for the day
    ipo.build(NOW + timedelta(days=1), state, fake_fetch(), llm)
    assert len(llm_calls) == 6  # next day: one fresh call per IPO


def test_build_llm_none_keeps_rules_and_llm_error_is_swallowed():
    out = ipo.build(NOW, {}, fake_fetch(), lambda *a, **k: None)
    assert all(i["thesis"] is None and i["analysis"]["method"] == "rules" for i in out["ipos"])

    def boom(*a, **k):
        raise RuntimeError("no key")
    assert ipo.build(NOW, {}, fake_fetch(), boom)["ipos"]
