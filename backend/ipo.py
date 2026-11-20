"""IPO desk: upcoming and open public issues on NSE, what the issuer's draft offer document (DRHP) filing says it exists, and the news.

  NSE      ipo-current-issue, all-upcoming-issues, public-past-issues, ipo-active-category (subscription), ipo-detail (lot size, issue text)
  SEBI     the list of draft offer documents (DRHP) filed; matched to each IPO by company name. The PDFs are not downloaded or read.
  News     Google News RSS headlines, shown word for word with their publisher

The verdict is a transparent rule set (see analyse): subscription multiples weighted QIB 50 / NII 30 / retail 20, plus flags for SME boards,
offer-for-sale heavy issues and very small or very large issues. It is a rule of thumb, not a forecast. The most it ever suggests is ONE minimum
lot at the upper price band. Allotment is a lottery when retail is oversubscribed, so you may get nothing. Grey-market premium is not used.
An optional llm hook writes a short plain-English thesis from the same public facts, at most once per IPO per day.

Usage: build(now, state, fetch=None, llm=None) -> dict   (state is a dict the caller persists between runs, used as a cache)
"""
from __future__ import annotations

import difflib
import html
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

IST = timezone(timedelta(hours=5, minutes=30))
NSE = "https://www.nseindia.com"
URL_CURRENT = NSE + "/api/ipo-current-issue"
URL_UPCOMING = NSE + "/api/all-upcoming-issues?category=ipo"
URL_PAST = NSE + "/api/public-past-issues"
URL_SUBS = NSE + "/api/ipo-active-category?symbol={}"
URL_DETAIL = NSE + "/api/ipo-detail?symbol={}&series={}"
URL_SEBI = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10"
URL_NEWS = "https://news.google.com/rss/search?q={}&hl=en-IN&gl=IN&ceid=IN:en"
NSE_HEADERS = {"User-Agent": "Mozilla/5.0 (research script)", "Accept": "application/json", "Referer": NSE + "/"}
WEB_HEADERS = {"User-Agent": "Mozilla/5.0 (research script)"}

# Rules of thumb (not backtested). Weighted subscription multiple -> (base score, typical listing move low %, high %).
BANDS = [(1, 25, -15, 0), (3, 40, -5, 8), (10, 55, 0, 18), (30, 68, 8, 30), (80, 78, 15, 45), (float("inf"), 85, 20, 60)]
WEIGHTS = {"qib": 0.5, "nii": 0.3, "retail": 0.2}
OFS_HEAVY = 0.70
SME_SCORE_PENALTY, OFS_PENALTY, SIZE_PENALTY, WEAK_QIB_PENALTY = 15, 10, 5, 5
SME_WIDEN = (-8, 10)  # SME listings swing wider both ways
APPLY_MIN, APPLY_MIN_SME, AVOID_BELOW = 65, 70, 40
EARLY_OK_MULTIPLE = 10  # before the last bidding day, only this much demand already is read as a signal
TINY_CR = {"Mainboard": 100, "SME": 10}
HUGE_CR = 10000
MAX_COMPANY_NEWS, MAX_DETAIL, NEWS_KEEP = 8, 14, 5
NAME_STOP = {"limited", "ltd", "private", "pvt", "the", "and", "of", "india", "indian", "co", "company", "corporation", "corp", "inc", "llp"}


# ---------------------------------------------------------------- fetching

_OPENER = None
_WARM = False


def default_fetch(url: str, headers: dict | None = None) -> bytes:
    """Plain urllib with a shared cookie jar; NSE hosts get a one-time home-page warm-up so its API accepts the call."""
    global _OPENER, _WARM
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    if "nseindia.com" in url and not _WARM:
        _WARM = True
        try:
            _OPENER.open(urllib.request.Request(NSE + "/", headers={"User-Agent": NSE_HEADERS["User-Agent"]}), timeout=20).read()
        except Exception:
            pass
    return _OPENER.open(urllib.request.Request(url, headers=headers or WEB_HEADERS), timeout=25).read()


def _text(raw) -> str:
    return raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)


def _failure(err: Exception) -> str:
    code = getattr(err, "code", None)
    if code in (401, 403, 429) or isinstance(err, ValueError):
        return "blocked"
    return "error: " + (f"HTTP {code}" if code else str(err)[:80])


def _json(fetch, url: str):
    return json.loads(_text(fetch(url, NSE_HEADERS)))


# ---------------------------------------------------------------- small helpers

def _norm(k) -> str:
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def pick(d: dict, *names, default=None):
    """First present, non-empty value among key-name variants (case and punctuation insensitive)."""
    idx = {_norm(k): v for k, v in d.items()}
    for n in names:
        v = idx.get(_norm(n))
        if v not in (None, "", "-"):
            return v
    return default


def num(x) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[,\s₹]|rs\.?", "", str(x), flags=re.I)
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(s) -> date | None:
    if not s:
        return None
    s = str(s).strip()[:20]
    for f in ("%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b %d, %Y", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return date.fromisoformat(m.group(1)) if m else None


def price_band(s) -> list[float] | None:
    """'Rs.129 to Rs.136' -> [129, 136]; a single price '94' -> [94, 94]."""
    if s is None:
        return None
    if isinstance(s, (list, tuple)):
        v = [num(x) for x in s if num(x) is not None]
    else:
        v = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", str(s))]
    v = [x for x in v if x > 0]
    if not v:
        return None
    return [min(v), max(v)]


def short_name(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\b(limited|ltd\.?)\b", "", name or "", flags=re.I)).strip(" .,-")


def tokens(name: str) -> list[str]:
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split() if t not in NAME_STOP]


def name_match(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    jac = len(set(ta) & set(tb)) / len(set(ta) | set(tb))
    seq = difflib.SequenceMatcher(None, "".join(ta), "".join(tb)).ratio()
    return max(jac, seq)


def min_invest(lot_size, band) -> float | None:
    """Rupees for one minimum lot at the upper price band."""
    if not lot_size or not band:
        return None
    return round(float(lot_size) * max(band), 2)


# ---------------------------------------------------------------- parsers

def _board(row: dict) -> str:
    v = " ".join(str(pick(row, k, default="")) for k in ("series", "segment", "securityType", "board", "issueType"))
    return "SME" if "sme" in v.lower() else "Mainboard"


def parse_issues(data, kind: str = "current") -> list[dict]:
    """NSE ipo-current-issue / all-upcoming-issues / public-past-issues rows -> normalised dicts. Unknown shapes give []."""
    if isinstance(data, dict):
        data = pick(data, "data", "dataList", "records", default=[])
    out = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict):
            continue
        name = pick(r, "companyName", "company", "name", "issuerName")
        if not name:
            continue
        band = price_band(pick(r, "issuePrice", "priceRange", "priceBand", "price"))
        shares = num(pick(r, "issueSize", "noOfSharesOffered", "noOfShareOffered"))
        out.append({
            "name": str(name).strip(), "symbol": pick(r, "symbol"), "board": _board(r), "kind": kind, "nse_status": pick(r, "status"),
            "open_date": parse_date(pick(r, "issueStartDate", "ipoStartDate", "openDate", "orderStartDate")),
            "close_date": parse_date(pick(r, "issueEndDate", "ipoEndDate", "closeDate", "orderEndDate")),
            "listing_date": parse_date(pick(r, "listingDate")),
            "price_band": band, "lot_size": num(pick(r, "lotSize", "marketLot", "minBidQuantity")),
            "shares_offered": shares, "total_times": num(pick(r, "noOfTime", "noOfTimes", "subscriptionTimes")),
        })
    return out


def _times(r: dict) -> float | None:
    t = num(pick(r, "noOfTotalMeant", "noOfTime", "noOfTimes", "times"))
    if t is not None and t > 0:
        return round(t, 2)
    off, bid = num(pick(r, "noOfShareOffered", "noOfSharesOffered")), num(pick(r, "noOfSharesBid", "noOfshareBid"))
    if off and bid is not None and off > 0:
        return round(bid / off, 2)
    return None  # offered 0 / missing means the category does not exist here: not "zero demand"


def parse_subscription(data) -> dict | None:
    """ipo-active-category -> {qib, nii, retail, total, as_of}; each is a multiple of the shares reserved, None when NSE gives none."""
    rows = pick(data, "dataList", "data", default=None) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None
    sub = {"qib": None, "nii": None, "retail": None, "total": None, "as_of": None}
    for r in rows:
        if not isinstance(r, dict):
            continue
        cat, sr = str(pick(r, "category", default="")).strip().lower(), str(pick(r, "srNo", default="")).strip()
        if cat.startswith("qualified"):
            sub["qib"] = _times(r)
        elif cat.startswith("non institutional") and sr in ("2", ""):
            sub["nii"] = _times(r)
        elif cat.startswith("retail") or (cat.startswith("individual investor") and sr in ("3", "")):
            sub["retail"] = _times(r)
        elif cat == "total":
            sub["total"] = _times(r)
    m = re.search(r"as on\s+(.+)$", str(pick(data, "updateTime", default="")) if isinstance(data, dict) else "", re.I)
    sub["as_of"] = m.group(1).strip() if m else None
    return sub if any(sub[k] is not None for k in ("qib", "nii", "retail", "total")) else None


def _shares_cr(text: str, label: str, upper: float | None) -> float | None:
    """Crore rupees for the part of the issue text that follows `label` (fresh issue / offer for sale)."""
    m = re.search(label, text, re.I)
    if not m:
        return None
    win = text[m.end(): m.end() + 140]
    c = re.search(r"(?:₹|rs\.?)\s*([\d,\.]+)\s*(crore|cr\b|million|lakh)", win, re.I)
    if c:
        v = num(c.group(1))
        if v is not None:
            return round(v * {"crore": 1, "cr": 1, "million": 0.1, "lakh": 0.01}[c.group(2).lower()], 2)
    s = re.search(r"([\d,]{4,})\s*(?:fully paid[- ]up\s*)?(?:equity\s*)?shares", win, re.I)
    if s and upper:
        sh = num(s.group(1))
        return round(sh * upper / 1e7, 2) if sh else None
    return None


def parse_detail(data, upper: float | None = None) -> dict:
    """ipo-detail -> {lot_size, issue_text, fresh_cr, ofs_cr, issue_size_cr}. Missing pieces stay None."""
    out = {"lot_size": None, "issue_text": None, "fresh_cr": None, "ofs_cr": None, "issue_size_cr": None}
    rows = (data.get("issueInfo") or {}).get("dataList") if isinstance(data, dict) else None
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        title, val = str(r.get("title") or "").strip().lower(), str(r.get("value") or "")
        if out["lot_size"] is None and re.search(r"lot size|bid lot|minimum order quantity|minimum bid quantity", title):
            m = re.search(r"[\d,]+", val)
            out["lot_size"] = num(m.group(0)) if m else None
        if title == "issue size":
            out["issue_text"] = val.strip('" ')[:400]
    t = out["issue_text"] or ""
    out["fresh_cr"] = _shares_cr(t, r"fresh issue", upper)
    out["ofs_cr"] = _shares_cr(t, r"offer for sale", upper)
    parts = [x for x in (out["fresh_cr"], out["ofs_cr"]) if x is not None]
    out["issue_size_cr"] = round(sum(parts), 2) if parts else None
    return out


def parse_sebi(page) -> list[dict]:
    """SEBI draft-offer-document listing HTML -> [{date, company, url, kind}] newest first (DRHP, UDRHP and their addenda only)."""
    page, out = _text(page), []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        d = re.search(r"<td[^>]*>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</td>", row)
        a = re.search(r"<a\s+href=\"([^\"]+)\"[^>]*?title=\"([^\"]*)\"", row, re.S)
        if not (d and a):
            continue
        title = html.unescape(re.split(r"<br", a.group(2), maxsplit=1)[0]).strip()
        if not re.search(r"drhp", title, re.I):
            continue
        company = re.split(r"\s*(?:[-–—_]+\s*)?(?:addendum|corrigendum|udrhp|drhp|draft)\b", title, maxsplit=1, flags=re.I)[0].strip(" -–—_.,")
        when = parse_date(d.group(1))
        if company and when:
            out.append({"date": when.isoformat(), "company": company, "url": html.unescape(a.group(1)), "kind": title})
    out.sort(key=lambda r: r["date"], reverse=True)
    seen, uniq = set(), []
    for r in out:  # one row per company (its newest filing)
        k = " ".join(tokens(r["company"]))
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def parse_rss(xml, keep: int = 30) -> list[dict]:
    """Google News RSS -> [{title, source, link, time}] newest first. time is UTC ISO."""
    try:
        root = ET.fromstring(_text(xml).encode("utf-8"))
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        t = ""
        try:
            t = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            pass
        if title:
            out.append({"title": title, "source": src, "link": (it.findtext("link") or "").strip(), "time": t})
    out.sort(key=lambda r: r["time"], reverse=True)
    return out[:keep]


def match_drhp(name: str, drhps: list[dict], cutoff: float = 0.72) -> dict | None:
    best, score = None, 0.0
    for d in drhps:
        s = name_match(name, d["company"])
        if s > score:
            best, score = d, s
    return best if score >= cutoff else None


def news_for(name: str, items: list[dict]) -> list[dict]:
    """Headlines that name the company (its first two distinctive words appear in the title)."""
    toks = tokens(name)[:2]
    if not toks:
        return []
    hits = [n for n in items if all(t in re.sub(r"[^a-z0-9 ]", " ", n["title"].lower()).split() for t in toks)]
    return hits[:NEWS_KEEP]


# ---------------------------------------------------------------- the rules

def weighted_subscription(sub: dict | None) -> tuple[float | None, str]:
    """QIB 50 / NII 30 / retail 20, renormalised over the categories NSE reports; the total multiple if no category is available."""
    if not sub:
        return None, "no subscription data"
    parts = [(k, sub[k], w) for k, w in WEIGHTS.items() if sub.get(k) is not None]
    if not parts:
        if sub.get("total") is None:
            return None, "no subscription data"
        return round(sub["total"], 2), f"overall {sub['total']:.2f}x (NSE gave no category split)"
    wsum = sum(w for _, _, w in parts)
    val = sum(v * w for _, v, w in parts) / wsum
    txt = ", ".join(f"{k.upper()} {v:.2f}x*{w:g}" for k, v, w in parts)
    return round(val, 2), f"{txt} -> weighted {val:.2f}x"


def _band_for(w: float) -> tuple[int, int, int]:
    for top, score, lo, hi in BANDS:
        if w < top:
            return score, lo, hi
    return BANDS[-1][1:]


def analyse(ipo: dict, today: date) -> dict:
    """Score, verdict, reasons, risks, listing range and the plan if allotted. Pure function of the structured facts."""
    board, status, band = ipo.get("board"), ipo.get("status"), ipo.get("price_band")
    sub, reasons, risks = ipo.get("subscription"), [], []
    upper = max(band) if band else None
    size, fresh, ofs = ipo.get("issue_size_cr"), ipo.get("fresh_cr"), ipo.get("ofs_cr")
    out = {"score": None, "verdict": "Not enough data", "reasons": reasons, "risks": risks,
           "listing_view": {"low_pct": None, "high_pct": None, "basis": "unknown until bidding opens"}, "listing_px": None,
           "after_listing": "", "method": "rules"}

    if status == "listed":
        reasons.append("Already listed on NSE: nothing to apply for.")
        out["verdict"] = "Watch"
        out["listing_view"]["basis"] = "already listed"
        return out
    if not band:
        risks.append("Price band not published yet, so no price or minimum investment can be worked out.")
        return out

    if board == "SME":
        risks.append("SME board: lots are large, trading is thin and prices swing far more than on the mainboard. Higher risk.")
    if ofs is not None and size and ofs / size > OFS_HEAVY:
        risks.append(f"Offer-for-sale heavy: {ofs / size * 100:.0f}% of the issue (Rs {ofs:,.0f} cr of Rs {size:,.0f} cr) pays existing holders, not the company.")
    if size is None:
        risks.append("Issue size could not be read from NSE.")
    elif size < TINY_CR[board]:
        risks.append(f"Very small issue (Rs {size:,.0f} cr): easy to move, hard to exit.")
    elif size > HUGE_CR:
        risks.append(f"Very large issue (Rs {size:,.0f} cr): a lot of stock to absorb, big listing pops are rarer.")
    if fresh is not None and fresh > 0 and size:
        reasons.append(f"Fresh issue is Rs {fresh:,.0f} cr of Rs {size:,.0f} cr, money that goes to the company.")
    if not ipo.get("lot_size"):
        risks.append("Lot size not available, so the rupee cost of one lot is unknown.")
    if not ipo.get("drhp_url"):
        risks.append("No matching DRHP found in SEBI's recent listing (older filings are not searched).")

    w, wtxt = weighted_subscription(sub)
    close = ipo.get("close_date")
    early = status == "open" and close is not None and today < parse_date(close)
    if w is None:
        out["verdict"] = "Watch"
        reasons.append("No subscription data yet: demand is the main signal and it appears only once bidding opens.")
        out["after_listing"] = _plan(ipo, None)
        return out

    base, lo, hi = _band_for(w)
    reasons.append(f"Subscription: {wtxt}.")
    score = base
    if board == "SME":
        score -= SME_SCORE_PENALTY
        lo, hi = lo + SME_WIDEN[0], hi + SME_WIDEN[1]
    if ofs is not None and size and ofs / size > OFS_HEAVY:
        score -= OFS_PENALTY
    if size is not None and (size < TINY_CR[board] or size > HUGE_CR):
        score -= SIZE_PENALTY
    if sub.get("qib") is not None and sub.get("retail") is not None and sub["qib"] < 2 <= sub["retail"]:
        score -= WEAK_QIB_PENALTY
        risks.append(f"Institutions (QIB {sub['qib']:.2f}x) are far less keen than retail ({sub['retail']:.2f}x).")
    score = max(0, min(100, score))
    out["score"] = score

    if early and w < EARLY_OK_MULTIPLE:
        out["verdict"] = "Watch"
        reasons.append("Bidding is still open; institutions usually bid on the last day, so an early low multiple says little. Re-check on the final day.")
        out["listing_view"] = {"low_pct": None, "high_pct": None,
                               "basis": f"too early to read: {wtxt}; the final-day demand is not visible yet"}
        out["after_listing"] = _plan(ipo, None)
        return out

    out["listing_view"] = {"low_pct": lo, "high_pct": hi,
                           "basis": f"{wtxt}. Rule of thumb for this multiple on a {board} issue, not a forecast"}
    if upper:
        out["listing_px"] = [round(upper * (1 + lo / 100), 2), round(upper * (1 + hi / 100), 2)]

    need = APPLY_MIN_SME if board == "SME" else APPLY_MIN
    if score >= need and status == "open" and ipo.get("lot_size"):
        out["verdict"] = "Apply (1 lot)"
        reasons.append(f"Score {score} is at or above the {need} bar for a {board} issue.")
    elif score < AVOID_BELOW:
        out["verdict"] = "Avoid"
        reasons.append(f"Score {score} is below {AVOID_BELOW}: demand is weak for the size.")
    else:
        out["verdict"] = "Watch"
        if status != "open":
            reasons.append("Bidding is not open, so there is nothing to apply for now; the plan below is for holders of an allotment.")
        elif not ipo.get("lot_size"):
            reasons.append("Lot size unknown, so no application is suggested.")
        else:
            reasons.append(f"Score {score} is below the {need} bar to apply.")
    out["after_listing"] = _plan(ipo, out["listing_px"])
    return out


def _plan(ipo: dict, px: list | None) -> str:
    band, lot = ipo.get("price_band"), ipo.get("lot_size")
    if not band:
        return ""
    issue = max(band)
    half = "half" if lot and lot >= 2 else "all"
    s = ("If allotted (retail allotment can be a lottery, so you may get nothing): on listing day place a sell order for " + half + " at your target, "
         f"and sell everything if it lists below the issue price of Rs {issue:,.2f}. ")
    if px:
        s += f"Target for the first half: inside the Rs {px[0]:,.2f} to Rs {px[1]:,.2f} range, ideally near the top. "
    else:
        s += "No target range yet: it needs subscription numbers. "
    s += "Keep the rest only with a stop at the issue price and move it up as the price rises. Risk is limited to the one lot."
    if ipo.get("board") == "SME":
        s += " SME shares are thinly traded, so a sell order may not fill at the price you want."
    return s


# ---------------------------------------------------------------- LLM thesis

THESIS_SYSTEM = ("You write a short plain-English note on one Indian IPO for a small retail investor. Use ONLY the facts in the JSON given. "
                 "If a fact is missing, say it is missing; never invent numbers, financials, peers or valuations. Do not promise or predict returns "
                 "and do not call anything guaranteed. Mention the main risk and that the DRHP (link given) should be read. Maximum 150 words, no headings.")


def _thesis(llm, ipo: dict, cache: dict, day: str) -> str | None:
    key = f"{ipo['symbol'] or ipo['name']}|{day}"
    if key in cache:
        return cache[key]
    facts = {k: ipo.get(k) for k in ("name", "board", "status", "open_date", "close_date", "price_band", "lot_size", "min_invest_rs", "issue_size_cr",
                                     "fresh_cr", "ofs_cr", "subscription", "drhp_url")}
    facts["rule_verdict"] = ipo["analysis"]["verdict"]
    facts["flags"] = ipo["analysis"]["risks"]
    facts["headlines"] = [n["title"] for n in ipo["news"]]
    try:
        txt = llm("ipo_thesis", THESIS_SYSTEM, json.dumps(facts, default=str), "write", 400)
    except Exception:
        txt = None
    txt = (txt or "").strip()
    if not txt:
        return None
    cache[key] = txt
    return txt


# ---------------------------------------------------------------- build

def _today(now: datetime) -> date:
    return (now.astimezone(IST) if now.tzinfo else now).date()


def _status(i: dict, today: date) -> str:
    o, c, l = i["open_date"], i["close_date"], i["listing_date"]
    if l and l <= today:
        return "listed"
    if c and today > c:
        return "closed"
    if o and c and o <= today <= c:
        return "open"
    if o and today < o:
        return "upcoming"
    s = str(i.get("nse_status") or "").lower()
    return "open" if s == "active" else "upcoming" if s in ("forthcoming", "upcoming") else "closed" if s in ("closed", "listed") else "upcoming"


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def build(now: datetime, state: dict, fetch=None, llm=None) -> dict:
    fetch = fetch or default_fetch
    today, day = _today(now), _today(now).isoformat()
    cache = state.setdefault("ipo", {})
    for k in ("news", "thesis", "detail"):
        cache.setdefault(k, {})
    cache["news"] = {k: v for k, v in cache["news"].items() if v.get("d") == day}
    cache["thesis"] = {k: v for k, v in cache["thesis"].items() if k.endswith("|" + day)}
    src = {"nse": "blocked", "sebi": "blocked", "news": "blocked"}

    # NSE lists
    raw, errs = [], []
    for url, kind in ((URL_CURRENT, "current"), (URL_UPCOMING, "upcoming"), (URL_PAST, "past")):
        try:
            rows = parse_issues(_json(fetch, url), kind)
            if kind != "past":
                src["nse"] = "ok"
            raw += rows
        except Exception as e:
            if kind != "past":
                errs.append(_failure(e))
    if src["nse"] != "ok":
        src["nse"] = errs[0] if errs else "blocked"
    seen, ipos = set(), []
    for r in raw:  # current beats upcoming beats past for the same company
        key = r["symbol"] or r["name"]
        if key in seen:
            continue
        seen.add(key)
        r["status"] = _status(r, today)
        if r["kind"] == "past" and not (r["listing_date"] and today - r["listing_date"] <= timedelta(days=30)
                                        and r["open_date"] and today - r["open_date"] <= timedelta(days=60)):
            continue  # recent equity listings only (the past-issues feed also carries old and debt issues)
        ipos.append(r)
    ipos.sort(key=lambda r: ({"open": 0, "upcoming": 1, "closed": 2, "listed": 3}[r["status"]], r["open_date"] or date.max))

    # per-IPO NSE detail (lot size, fresh vs OFS) and subscription
    ndetail = 0
    for r in ipos:
        r.update({"fresh_cr": None, "ofs_cr": None, "issue_size_cr": None, "subscription": None, "issue_size_note": None})
        if r["status"] == "listed" or not r["symbol"]:
            continue
        upper = max(r["price_band"]) if r["price_band"] else None
        dk = f"{r['symbol']}|{max(r['price_band']) if r['price_band'] else ''}"
        det = cache["detail"].get(dk)
        if det is None and ndetail < MAX_DETAIL:
            ndetail += 1
            try:
                det = parse_detail(_json(fetch, URL_DETAIL.format(urllib.parse.quote(r["symbol"]), "SME" if r["board"] == "SME" else "EQ")), upper)
                if det["lot_size"] or det["issue_size_cr"]:
                    cache["detail"][dk] = det
            except Exception:
                det = None
        if det:
            r["lot_size"] = r["lot_size"] or det["lot_size"]
            r["fresh_cr"], r["ofs_cr"], r["issue_size_cr"] = det["fresh_cr"], det["ofs_cr"], det["issue_size_cr"]
        if r["issue_size_cr"] is None and r["shares_offered"] and upper:
            r["issue_size_cr"] = round(r["shares_offered"] * upper / 1e7, 2)
            r["issue_size_note"] = "approximate: shares offered to the public at the upper band, excluding any anchor portion"
        if r["status"] in ("open", "closed") and r["kind"] == "current":
            try:
                r["subscription"] = parse_subscription(_json(fetch, URL_SUBS.format(urllib.parse.quote(r["symbol"]))))
            except Exception:
                pass
            if r["total_times"] is not None:
                sub = r["subscription"] or {"qib": None, "nii": None, "retail": None, "total": None, "as_of": None}
                if sub["total"] is None:
                    sub["total"] = round(r["total_times"], 2)
                r["subscription"] = sub
    cache["detail"] = {k: v for k, v in cache["detail"].items() if k.split("|")[0] in {r["symbol"] for r in ipos}}

    # SEBI DRHP list
    drhps = []
    try:
        drhps = parse_sebi(fetch(URL_SEBI, WEB_HEADERS))
        src["sebi"] = "ok" if drhps else "error: no rows parsed"
    except Exception as e:
        src["sebi"] = _failure(e)

    # news: one general query, then at most MAX_COMPANY_NEWS per-company queries (cached per day)
    general = []
    try:
        general = parse_rss(fetch(URL_NEWS.format(urllib.parse.quote_plus("IPO India price band")), WEB_HEADERS))
        src["news"] = "ok" if general else "error: no items parsed"
    except Exception as e:
        src["news"] = _failure(e)
    asked = 0
    for r in ipos:
        if r["status"] == "listed":
            r["news"] = news_for(r["name"], general)
            continue
        ck = r["symbol"] or r["name"]
        if ck not in cache["news"] and asked < MAX_COMPANY_NEWS:
            asked += 1
            items = []
            try:
                items = news_for(r["name"], parse_rss(fetch(URL_NEWS.format(urllib.parse.quote_plus(short_name(r["name"]) + " IPO")), WEB_HEADERS)))
            except Exception:
                pass
            cache["news"][ck] = {"d": day, "items": items}
        merged, links = [], set()
        for n in news_for(r["name"], general) + cache["news"].get(ck, {}).get("items", []):
            if n["link"] not in links:
                links.add(n["link"])
                merged.append(n)
        merged.sort(key=lambda n: n["time"], reverse=True)
        r["news"] = merged[:NEWS_KEEP]

    # assemble
    out_ipos = []
    for r in ipos:
        d = match_drhp(r["name"], drhps)
        o = {"name": r["name"], "symbol": r["symbol"], "board": r["board"], "status": r["status"],
             "open_date": _iso(r["open_date"]), "close_date": _iso(r["close_date"]), "listing_date": _iso(r["listing_date"]),
             "price_band": r["price_band"], "lot_size": int(r["lot_size"]) if r["lot_size"] else None,
             "min_invest_rs": min_invest(r["lot_size"], r["price_band"]), "issue_size_cr": r["issue_size_cr"],
             "fresh_cr": r["fresh_cr"], "ofs_cr": r["ofs_cr"], "subscription": r["subscription"],
             "drhp_url": d["url"] if d else None, "news": r["news"], "thesis": None}
        o["analysis"] = analyse(o, today)
        if r["issue_size_note"]:
            o["analysis"]["risks"].append("Issue size is " + r["issue_size_note"] + ".")
        if llm and r["status"] != "listed" and r["price_band"]:
            t = _thesis(llm, o, cache["thesis"], day)
            if t:
                o["thesis"], o["analysis"]["method"] = t, "rules+claude"
        out_ipos.append(o)
    return {"updated_at": now.isoformat(timespec="seconds"), "ipos": out_ipos,
            "drhp_recent": [{"date": d["date"], "company": d["company"], "url": d["url"]} for d in drhps[:15]], "sources": src}
