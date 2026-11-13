"""F&O paper desk: NIFTY index option structures with defined risk, held to expiry.

Three mechanical strategies, one lot each, each with its own pretend account:
  short_iron_condor  sell a call around 0.25 delta and a put around -0.25 delta, buy wings
                     3 strikes further out. Wins when the index stays inside the short strikes.
  bull_put_spread    sell a put around -0.35 delta, buy a put 3 strikes lower. Wins unless
                     the index falls through the short strike.
  iron_butterfly     sell the at-the-money call and put, buy wings 3 strikes out. Wins when
                     the index pins near today's level.

Booking needs a saved INDmoney option chain (shorts filled at the bid, longs at the ask).
Settlement needs no option data at all: at expiry each leg is worth its intrinsic value
against the index close (from Yahoo), minus Rs 50 a leg in costs. That close is a fair
approximation of NSE's official settlement price, not exactly it. Positions are held to
expiry: no stop, so a loss is the structure's full max loss. All paper; nothing is placed.

Usage:
  python dashboard/fo_engine.py book CHAIN.json     # CHAIN.json: get_indian_stocks_option_chain output
  python dashboard/fo_engine.py settle
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "dashboard" / "data" / "fo_ledger.json"
IST = timezone(timedelta(hours=5, minutes=30))
COST_PER_LEG = 50.0
WING_STEPS = 3


def load() -> list[dict]:
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else []


def save(rows: list[dict]):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, indent=1))


def quotes(chain: dict) -> tuple[dict, dict, float, str, int]:
    """{(strike, 'CE'|'PE'): {bid, ask, delta}}, strikes sorted, spot, expiry, lot."""
    if "result" in chain:
        chain = json.loads(chain["result"])
    q, lot = {}, 0
    for row in chain["option_chain_data"]:
        for side, key in (("CE", "call_data"), ("PE", "put_data")):
            d = row.get(key) or {}
            bid, ask = d.get("buy_price") or d.get("bp"), d.get("sell_price") or d.get("sp")
            if bid and ask:
                q[(row["strike_price"], side)] = {"bid": float(bid), "ask": float(ask), "delta": d.get("delta")}
                lot = int(d.get("lot_size") or lot)
    exp = chain["selected_expiry"]
    exp = f"{exp[:4]}-{exp[4:6]}-{exp[6:]}" if "-" not in exp else exp
    return q, sorted({k[0] for k in q}), float(chain["entity_details"]["live_price"]), exp, lot


def pick(q, strikes, side, limit, below):
    """Short-strike choice: the strike nearest the money whose delta is within `limit`."""
    cand = [s for s in strikes if (s < below if side == "PE" else s > below)
            and (s, side) in q and q[(s, side)]["delta"] is not None and abs(q[(s, side)]["delta"]) <= limit]
    return (max(cand) if side == "PE" else min(cand)) if cand else None


def structures(q, strikes, spot):
    step = min(b - a for a, b in zip(strikes, strikes[1:]))
    wing = WING_STEPS * step
    atm = min(strikes, key=lambda s: abs(s - spot))
    sc, sp = pick(q, strikes, "CE", 0.25, spot), pick(q, strikes, "PE", 0.25, spot)
    out = {}
    if sc and sp:
        out["short_iron_condor"] = [("S", sc, "CE"), ("B", sc + wing, "CE"), ("S", sp, "PE"), ("B", sp - wing, "PE")]
    bp = pick(q, strikes, "PE", 0.35, spot)
    if bp:
        out["bull_put_spread"] = [("S", bp, "PE"), ("B", bp - wing, "PE")]
    out["iron_butterfly"] = [("S", atm, "CE"), ("B", atm + wing, "CE"), ("S", atm, "PE"), ("B", atm - wing, "PE")]
    return out


def book(chain_file: str):
    q, strikes, spot, expiry, lot = quotes(json.loads(Path(chain_file).read_text()))
    today = datetime.now(IST).date()
    if (date.fromisoformat(expiry) - today).days < 2:
        print(f"skip: expiry {expiry} is under 2 days away; book from the next expiry's chain")
        return
    rows = load()
    nid = max([r["id"] for r in rows], default=0)
    held = {(r["strategy"], r["expiry"]) for r in rows if r["status"] == "OPEN"}
    for name, legs in structures(q, strikes, spot).items():
        if (name, expiry) in held:
            continue
        if any((s, side) not in q for _, s, side in legs):
            print(f"skip {name}: a leg has no quote")
            continue
        px = {leg: (q[(leg[1], leg[2])]["bid"] if leg[0] == "S" else q[(leg[1], leg[2])]["ask"]) for leg in legs}
        credit = sum((p if leg[0] == "S" else -p) for leg, p in px.items())
        lo, hi = spot, spot                                  # worst case at the band edges and far away
        pts = sorted({s for _, s, _ in legs} | {0.0, spot * 2})
        payoff = lambda S: sum((1 if b == "B" else -1) * (max(S - k, 0) if sd == "CE" else max(k - S, 0)) for b, k, sd in legs)
        worst = min(payoff(S) + credit for S in pts)
        best = max(payoff(S) + credit for S in pts)
        if credit <= 0 and name != "long_only":
            print(f"skip {name}: the structure takes in no credit at these quotes")
            continue
        nid += 1
        rows.append({"id": nid, "strategy": name, "underlying": "NIFTY", "expiry": expiry, "lot": lot,
                     "booked": str(today), "spot_at_booking": spot, "status": "OPEN",
                     "legs": [{"side": b, "strike": k, "kind": sd, "entry": px[(b, k, sd)]} for b, k, sd in legs],
                     "credit_rs": round(credit * lot, 2), "max_gain_rs": round(best * lot - COST_PER_LEG * len(legs), 2),
                     "max_loss_rs": round(-(worst * lot - COST_PER_LEG * len(legs)), 2),
                     "settle_close": "", "pnl_rs": 0,
                     "note": "One lot, held to expiry. Shorts filled at the bid, longs at the ask."})
        print(f"booked {name} exp {expiry}: credit Rs {credit * lot:,.0f}, max gain {rows[-1]['max_gain_rs']:,.0f}, max loss {rows[-1]['max_loss_rs']:,.0f}")
    save(rows)


def settle():
    rows = load()
    todo = [r for r in rows if r["status"] == "OPEN" and r["expiry"] < datetime.now(IST).date().isoformat()]
    if not todo:
        print("nothing to settle;", sum(r["status"] == "OPEN" for r in rows), "open")
        save(rows)
        return
    import yfinance as yf
    hist = yf.Ticker("^NSEI").history(period="3mo", auto_adjust=False).Close
    closes = {d.date().isoformat(): float(v) for d, v in hist.items()}
    for r in todo:
        S = closes.get(r["expiry"])
        if S is None:
            print(f"no index close for {r['expiry']} yet; left open")
            continue
        pnl = sum((1 if l["side"] == "B" else -1) * ((max(S - l["strike"], 0) if l["kind"] == "CE" else max(l["strike"] - S, 0)) - l["entry"]) for l in r["legs"])
        r["pnl_rs"] = round(pnl * r["lot"] - COST_PER_LEG * len(r["legs"]), 2)
        r["settle_close"] = S
        r["status"] = "WIN" if r["pnl_rs"] > 0 else "LOSS"
        r["note"] = f"Settled at the {r['expiry']} index close of {S:,.2f}."
        print(f"settled #{r['id']} {r['strategy']}: {r['status']} Rs {r['pnl_rs']:,.2f}")
    save(rows)


if __name__ == "__main__":
    book(sys.argv[2]) if sys.argv[1] == "book" else settle()
