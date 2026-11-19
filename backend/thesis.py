"""The reasoning behind a trade, written down at the moment it is booked so it can be studied later.

Every trade carries a `thesis`: the news and data that were true when it was taken, what the strategy is, why this strategy fits
today, the numbers a forecast needs (expected move, break-evens, chance of profit, reward against risk) and what would make us exit.
The numbers come from the live option chain and the broker's margin calculator, not from a model of our own. Chance of profit is
priced from the options market's own implied volatility, so it is the market's odds, not ours. Nothing here places an order.
"""
from __future__ import annotations

import math


def inr(x) -> str:
    return f"₹{float(x):,.0f}"


def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def exp_move(spot: float, iv: float, days: float) -> float:
    """One standard deviation of the index over `days`, in points, from an annualised implied volatility in percent."""
    return spot * iv / 100 * math.sqrt(max(days, 0.25) / 365)


def profit_at(legs: list[dict], net: float, s: float) -> float:
    """Profit per unit at expiry if the index settles at s. net = points received (+) or paid (-) when the legs were opened."""
    tot = net
    for lg in legs:
        k = lg["strike"]
        v = max(s - k, 0) if lg["kind"] == "CE" else max(k - s, 0)
        tot += v if lg["side"] == "B" else -v
    return tot


def payoff_stats(legs: list[dict], net: float, spot: float, iv: float, days: float) -> dict:
    """Break-evens, best and worst case, and the chance of finishing in profit, all at expiry, priced on the market's implied volatility."""
    lo, hi, n = spot * 0.7, spot * 1.3, 1200
    xs = [lo + (hi - lo) * i / n for i in range(n + 1)]
    ys = [profit_at(legs, net, x) for x in xs]
    be = [round(xs[i] - ys[i] * (xs[i + 1] - xs[i]) / (ys[i + 1] - ys[i]), 0) for i in range(n) if ys[i] * ys[i + 1] < 0]
    sig = max(iv, 1) / 100 * math.sqrt(max(days, 0.25) / 365)
    mu = math.log(spot) - 0.5 * sig * sig
    cdf = lambda s: ncdf((math.log(s) - mu) / sig)
    pop = sum(cdf(xs[i + 1]) - cdf(xs[i]) for i in range(n) if (ys[i] + ys[i + 1]) > 0)
    return {"max_gain": max(ys), "max_loss": -min(ys), "breakevens": be, "pop": pop}


def legs_text(legs: list[dict]) -> str:
    return ", ".join(f"{'Sell' if l['side'] == 'S' else 'Buy'} {l['strike']:,.0f} {l['kind']}" for l in legs)


# strategy -> (what it is, why it is used, when it fails)
STRATEGY = {
    "iron_condor": ("Sell a call and a put out of the money, buy a farther call and put as protection.",
                    "Used on a quiet day: you are paid for time passing while the index stays inside a band. Options usually price in a bigger move than the index delivers, and this collects that gap.",
                    "A breakout beyond either short strike. The bought wings cap the loss."),
    "credit_spread": ("Sell one option and buy a farther one of the same kind, collecting a net credit.",
                      "Used when the index leans one way: we sell the side it is moving away from, so time and direction both work for us. Risk is fixed by the bought leg.",
                      "A sharp reversal through the short strike."),
    "long_straddle": ("Buy the at-the-money call and put.",
                      "Used when a big move is plausible but its direction is not: either leg can pay for both. It loses if the index drifts, because time decay eats the premium.",
                      "A quiet day. The cost of both options is the most you can lose."),
    "debit_spread": ("Buy the at-the-money option and sell a farther one in the same direction, paying a net debit.",
                     "Used when the index is already trending: selling the farther option cuts the cost and the time decay, in return for capping the profit.",
                     "The trend fades. The debit paid is the most you can lose."),
    "long_breakout": ("Buy a single at-the-money call (up day) or put (down day).",
                      "Used when the index has already moved 0.5% or more: a continuing trend pays quickly because the option gains from direction and from rising volatility.",
                      "The move stalls. The premium is the most you can lose."),
    "weekly_credit_spread": ("Sell an out-of-the-money option about one standard deviation away and buy a farther one, held toward the weekly expiry.",
                             "Used when options are priced richer than the index has actually been moving (implied volatility above realised): the seller is paid for that gap, and each day that passes without a big move is profit.",
                             "A move through the short strike before expiry. Loss is capped by the bought option."),
    "weekly_debit_spread": ("Buy an at-the-money option and sell a farther one in the forecast direction, held toward the weekly expiry.",
                            "Used when options are cheap against realised movement and the forecast has a direction: you pay little for a defined bet on the move.",
                            "The index goes nowhere or the other way. The debit is the most you can lose."),
    "monthly_credit_spread": ("Sell an out-of-the-money option well away from the index and buy a farther one, held for weeks toward the monthly expiry.",
                              "Used for a slower, larger-premium version of the weekly trade: more time to be right, a wider cushion, and a smaller daily swing in value.",
                              "A trend that carries the index through the short strike. Loss is capped by the bought option."),
    "monthly_debit_spread": ("Buy an at-the-money option and sell a farther one in the forecast direction, held for weeks.",
                             "Used when the month's backdrop has a direction and options are not expensive: a defined-risk position that can ride a trend.",
                             "The trend stalls or reverses. The debit is the most you can lose."),
    "scalp_vwap_pullback": ("A short intraday position taken in the direction a stock is already trending, on a shallow pullback, with the stop just beyond the pullback and the target 1.5 times as far.",
                           "Used when price is on the right side of VWAP, the 9-bar average is stacked over the 21-bar average, and a strong bar on above-average volume ends a pullback to the 9-bar average: joining the trend after a dip gives a tight, well-defined stop.",
                           "The pullback becomes a reversal, or the move stalls inside the 10-minute window. Charges (flat Rs 10 an order plus STT and fees) are a real drag on small trades."),
    "mcx_momentum": ("A futures position in the direction the market is already moving hard.",
                     "Used when a commodity is up or down 0.8% or more and sitting at its day extreme: strong days tend to extend into the evening session when global markets open.",
                     "A reversal from the extreme. The 0.6% stop caps the loss."),
    "mcx_pullback": ("Buy a dip inside an up day or sell a bounce inside a down day.",
                     "Used after a trend day pulls back 0.4% to 1.2%: you join the trend at a better price than the chasers.",
                     "The pullback becomes a reversal. The 0.5% stop caps the loss."),
    "crypto_breakout": ("Buy a coin pushing to a 24-hour high.", "Used when a coin is up 1% or more and within 0.6% of its high: breakouts tend to attract follow-through buying.", "A false breakout. The 1.5% stop caps the loss."),
    "crypto_dip_bounce": ("Buy a coin that has dropped and started to recover.", "Used when a coin is 3% or more under its 24-hour high yet 0.5% off its low: sellers look exhausted.", "The bounce fails and the fall resumes. The stop caps the loss."),
}


def pack(horizon: str, headline: str, news: list[str], data: list[str], strategy: str, why: list[str], numbers: list[list[str]], risk: str, viability: str) -> dict:
    return {"horizon": horizon, "headline": headline, "news": news, "data": data, "strategy": strategy, "why": why, "numbers": numbers, "risk": risk, "viability": viability}


def fno(name: str, horizon: str, legs: list[dict], net: float, spot: float, prev: float | None, iv: float | None, vix: float | None, days: float, lot: int, margin: float,
        acct: float, expiry: str, env: dict, under: str = "NIFTY", exit_rule: str = "", unit_target: float = 0, unit_stop: float = 0) -> dict:
    """The written thesis for an index option structure. legs carry side S/B, strike, kind, entry."""
    env = env or {}
    iv = iv or vix or 15.0
    st = payoff_stats(legs, net, spot, iv, days)
    em = exp_move(spot, iv, days)
    what, why_s, fails = STRATEGY.get(name) or STRATEGY[name.split('_', 1)[1]]
    view = (env.get("view") or {}).get(under) or {}
    chain = (env.get("chain") or {}).get(under) or {}
    chg = (spot / prev - 1) * 100 if prev else 0
    data = [f"{under} {spot:,.0f}, {chg:+.2f}% on the previous close." + (f" India VIX {vix:.1f}." if vix else ""),
            f"Implied volatility at the money {iv:.1f}% a year. Over {days:.0f} day{'s' if days != 1 else ''} to {expiry} that prices a one-standard-deviation move of about ±{em:,.0f} points (±{em / spot * 100:.1f}%), "
            f"so the market gives roughly a 68% chance of finishing between {spot - em:,.0f} and {spot + em:,.0f}."]
    if env.get("rv") and horizon != "daily":
        data.append(f"Realised volatility over the last 10 sessions is {env['rv']:.1f}% against {iv:.1f}% implied: options are {'richer' if iv > env['rv'] else 'cheaper'} than the index has actually moved.")
    if chain:
        data.append(f"Option positioning: put-to-call ratio {chain.get('pcr')}, largest call open interest at {chain.get('call_wall'):,.0f} (a ceiling), largest put open interest at {chain.get('put_wall'):,.0f} (a floor), max pain {chain.get('max_pain'):,.0f}.")
    if env.get("participants"):
        data.append(env["participants"])
    if view:
        data.append(f"Our forecast for today: {view.get('bias')} (score {view.get('score'):+.2f}); likely range {view.get('lo'):,.0f} to {view.get('hi'):,.0f}.")
    why = [why_s]
    shorts = [l for l in legs if l["side"] == "S"]
    if shorts:
        k = shorts[0]["strike"]
        dist = abs(k - spot)
        why.append(f"The short strike {k:,.0f} is {dist:,.0f} points ({dist / spot * 100:.1f}%) from the index, {dist / em:.1f} times the expected move to expiry" +
                   (", so the market itself puts it outside the likely range." if dist >= em else ", inside the expected move, which is why the credit is larger and the risk higher."))
        if chain and ((shorts[0]["kind"] == "CE" and chain.get("call_wall") and k >= chain["call_wall"] - 1) or (shorts[0]["kind"] == "PE" and chain.get("put_wall") and k <= chain["put_wall"] + 1)):
            why.append(f"It sits at or beyond the heaviest open-interest strike ({chain['call_wall' if shorts[0]['kind'] == 'CE' else 'put_wall']:,.0f}), where option writers have the most at stake.")
    if view and name in ("credit_spread", "debit_spread", "long_breakout", "weekly_credit_spread", "weekly_debit_spread", "monthly_credit_spread", "monthly_debit_spread"):
        why.append(f"Direction: today's forecast leans {view.get('bias').lower()} ({'; '.join((view.get('reasons') or [])[:2])}).")
    be = " and ".join(f"{b:,.0f}" for b in st["breakevens"]) or "none inside ±30%"
    numbers = [["Net " + ("credit" if net > 0 else "debit"), f"{abs(net):.1f} points = {inr(abs(net) * lot)} per lot", "What you receive (or pay) up front"],
               ["Most you can make", inr(st["max_gain"] * lot), "At expiry, if everything goes right"],
               ["Most you can lose", inr(st["max_loss"] * lot), "At expiry, if everything goes wrong (fixed by the bought options)"],
               ["Break-even at expiry", be, "Where the structure stops losing money"],
               ["Chance of profit at expiry", f"{st['pop'] * 100:.0f}%", "From the options market's own implied volatility; not our edge, the market's odds"],
               ["Expected move to expiry", f"±{em:,.0f} points", f"{days:.0f} days at {iv:.1f}% implied volatility"],
               ["Reward for the risk", f"{st['max_gain'] / st['max_loss']:.2f} to 1" if st["max_loss"] else "n/a", "Best case divided by worst case"],
               ["Margin the broker asks", inr(margin), f"{margin / acct * 100:.0f}% of the account (Upstox margin calculator)"]]
    if unit_target:
        numbers.append(["Our exit levels", f"Take profit at {inr(unit_target * lot)}, cut at {inr(unit_stop * lot)}", "Rupees on one lot, before the exit rule below"])
    return pack(horizon, f"{legs_text(legs)} · {under} {expiry}", env.get("news") or [], data, what, why,
                numbers, f"{exit_rule} Fails when: {fails}", f"One lot of {lot} needs {inr(margin)} of margin, checked with the broker's calculator when the trade was booked.")


def directional(desk: str, strat: str, horizon: str, label: str, side: str, entry: float, stop: float, target: float, risk_rs: float, reward_rs: float, margin: float,
                acct: float, data: list[str], news: list[str], exit_rule: str, extra_why: str = "") -> dict:
    what, why_s, fails = STRATEGY[strat]
    rr = reward_rs / risk_rs if risk_rs else 0
    why = [why_s] + ([extra_why] if extra_why else [])
    numbers = [["Entry", f"{entry:,.2f}", "Price when the paper trade was opened"], ["Stop (exit if wrong)", f"{stop:,.2f}", f"Costs about {inr(risk_rs)}"], ["Target (exit if right)", f"{target:,.2f}", f"Earns about {inr(reward_rs)}"],
               ["Reward for the risk", f"{rr:.1f} to 1", "Target gain divided by stop loss"], ["Needs to be right", f"{1 / (1 + rr) * 100:.0f}% of the time", "The win rate this reward-to-risk must beat to break even, before costs"],
               ["Capital tied up", inr(margin), f"{margin / acct * 100:.0f}% of the account"]]
    return pack(horizon, f"{label}", news, data, what, why, numbers, f"{exit_rule} Fails when: {fails}", f"Needs {inr(margin)} to hold" + (" (Upstox margin calculator)." if desk == "COMMODITY" else "."))


def for_trade(t: dict, env: dict, acct: float, rule: tuple | None = None) -> dict:
    """A thesis for trades that were not booked with one (equity trades from the chart scan and the signal desk), built from their own fields."""
    entry, stop, tgt = float(t.get("entry") or 0), t.get("stop"), t.get("target_px")
    qty = float(t.get("qty") or 0) if str(t.get("qty") or "").replace(".", "").isdigit() else 0
    d = -1 if t.get("side") == "SHORT" else 1
    data = [f"Entry {entry:,.2f}" + (f", stop {float(stop):,.2f}" if stop else "") + (f", target {float(tgt):,.2f}" if tgt else "") + f"; {int(qty)} shares worth {inr(entry * qty)}." if qty else f"Entry {entry:,.2f}."]
    numbers = []
    if stop and qty:
        risk = abs(entry - float(stop)) * qty
        numbers += [["Risk if the stop is hit", inr(risk), f"{risk / acct * 100:.2f}% of the account"]]
        if tgt:
            rew = abs(float(tgt) - entry) * qty
            numbers += [["Reward at the target", inr(rew), f"{rew / risk:.1f} to 1 against the risk" if risk else ""]]
    tone = (env or {}).get("tone") or {}
    news = list((env or {}).get("news") or [])[:3]
    why = [rule[2]] if rule else []
    if t.get("reason"):
        why.append(f"Signal: {t['reason']}")
    if tone.get("label"):
        data.append(f"Market tone this morning: {tone['label']}. " + " ".join((tone.get("notes") or [])[:2]))
    return pack(t.get("opened") if t.get("opened") in ("swing", "signal") else "intraday", t.get("label", ""), news, data, rule[1] if rule else "", why, numbers,
                "Exit at the stop, the target or the time stop in the rule.", f"Paid for in cash: {inr(entry * qty)}." if qty else "")
