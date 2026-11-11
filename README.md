# Trading Desk: a multi-agent daily research team

A Python system where a team of LLM agents reviews a watchlist each day and
produces **one** recommendation (or "stay in cash") plus a one-page PDF. It
never places orders. Output is research, not investment advice.

## The team

| Agent | What it does | Implementation |
|---|---|---|
| Data agent | Prices, index levels, fundamentals, flows, news. Anything it cannot confirm is marked `UNVERIFIED`. | `trading_team/data.py` |
| Screen | Ranks the watchlist with a transparent score so only the top few get LLM analysis. | `indicators.screen_score` |
| Technical analyst | Trend, support/resistance, RSI(14), MACD, volatility. Indicators are computed in code. | `agents.run_analyst` |
| Fundamentals analyst | Valuation and earnings from provider fields. | `agents.run_analyst` |
| News/sentiment analyst | Headlines and FII/DII flows. Neutral when unverified. | `agents.run_analyst` |
| Bull vs Bear | Two independent arguments for and against each candidate. | `agents.run_debate` |
| Portfolio manager | Chooses at most one idea or NO_TRADE, with a proposed stop and target. Sees the track record. | `agents.run_portfolio_manager` |
| Risk manager | Enforces the house rules. Can veto anything. | `risk.py` |
| Ledger agent | Logs every decision, settles open trades against later prices, feeds win/loss stats into the next run. | `ledger.py` |
| Report | One-page PDF of the day's decision. | `report.py` |

Pipeline per run: data → screen → analysts → debate → portfolio manager →
risk manager → ledger → PDF.

## Risk rules (`trading_team/config.py`)

- Stop-loss 3–5% below entry. Out-of-range proposals are clamped and the change is noted.
- Target 15–30% above entry. Clamped the same way.
- At most one idea per day.
- **Stay in cash** when:
  - India VIX is above 20 (configurable), or **unavailable** (conservative default),
  - the stock's 20-day realised volatility is above 60%,
  - the stock's price history is unverified.
- The risk manager's veto is final. The portfolio manager cannot override it.

Entry is the reference close of the run date. The ledger settles from the
following session onward. If both stop and target fall in one bar, the stop
is assumed first. A gap through a level fills at the open.

## Strategy lab: what the desk is allowed to trade

`python backtest/strategy_lab.py` replays every entry strategy in
`trading_team/strategies.py` over 5 years on the wide universe
(`watchlists/nifty200_plus_etfs.txt`: 215 stocks plus gold and silver ETFs), under the
desk's portfolio rules and after costs. Results go to `backtest/approved_strategies.json`.

- **APPROVED**: at least 100 trades, positive average result per trade with t-stat of 2 or
  more, positive in both parts of the period, drawdown of 20% or less, positive return.
  These criteria were fixed before the results were seen.
- **PROBATION**: failed approval, but positive per trade and ahead of the Nifty. Tradable
  only as a labelled experiment, so forward results build up in the ledger by strategy.
- **REJECTED**: not traded.

The daily run analyses only tickers with an entry signal from a tradable strategy whose
stop and target fit the risk rules, and trades it with the tested stop and target. If
nothing signals, the day is NO_TRADE and no model calls are made.
`--no-strategy-gate` turns this off.

Current verdicts (11 Nov 2021 to 11 Nov 2026), eight strategies tested: none APPROVED;
`breakout_52w` and `trend_ride` on PROBATION (`trend_ride` has no fixed target, so it is outside the risk
rules and is reported as watch-only); the rest REJECTED. The universe is today's index
members, so every result is flattered by survivorship bias.

## Company results and concalls

For each analysed candidate the desk also fetches:

- **Quarterly results** (Yahoo Finance): revenue, net profit and operating margin for the
  latest quarter against the same quarter a year earlier, EPS against the consensus
  estimate, and days to the next result. Growth is computed in code. If the year-ago
  quarter is missing, growth is reported as unverified.
- **The latest concall transcript**: located on the company's screener.in page and
  downloaded from BSE, the official filing. A concall analyst summarises demand, margins,
  guidance and risks. Each point must carry a verbatim quote; quotes not found in the
  transcript are deleted, as are statements with figures the transcript does not contain.
  With no verified quote, the concall view is set to neutral.

These inputs cannot be backtested (no history of past transcripts), so their value is
measured only going forward, in the ledger. The newest transcript can be a quarter old
when a company has reported but not yet filed its transcript; the report states its month.

## Sudden jumps: study and live watcher

`python backtest/spike_study.py CACHE_DIR` studies every NSE EQ stock (2,108 listed today)
over 5 years: how often 10%+ jumps happen, what was filed before them, how the day
unfolded, whether price moved before the filing, and how often a scheduled results
announcement ends in a jump. Results are in `backtest/spike_study_results.json`.

`python -m trading_team.spike_watch` watches NSE's public announcements feed during
market hours. For each price-sensitive filing it prints what was filed, how long ago, and
how far the price has already moved (Yahoo one-minute prices, about 30 seconds behind).
It reacts to public filings; it does not and cannot know about them in advance.
No model calls are used, so it costs nothing on your subscription. It needs a computer
that stays on during market hours (09:15 to 15:30 IST).

## Order tickets (no orders are placed)

`python -m trading_team ticket --ticker BEL --entry 393 --stop 376 --target 470 --equity 102797
--live-price 396.45 --price-time 15:15:12` prints exact numbers for a manual trade: quantity,
limit price, stop trigger and limit, target, rupees at risk and to gain, a checklist, and the
steps to place it in the INDmoney app. No tool available to Claude can place orders, so
the last step is always yours.

The ticket refuses (DO NOT TRADE) when the stop is not below the entry, reward to risk is
under 3, the position would exceed 30% of equity or total open risk 4%, India VIX is above 20,
the price is older than 2 minutes, or the price is at or below the stop. It shows WAITING
when price has run more than 0.5% above the entry: the limit rests, and you do not raise it.
The sizing reproduces the daily report's BEL numbers exactly (see `tests/test_ticket.py`).

## How sure are we that a strategy works?

`python backtest/confidence.py` measures how likely each strategy's true average result per
trade is above zero. "99% confidence" does not mean a 99% win rate. Results (5 years):

| Strategy | Trades | Avg R | Naive | Month-clustered | After correcting for 8 tries |
|---|---|---|---|---|---|
| breakout_52w | 289 | +0.24 | 97.3% | 97.4% | 81.0% |
| trend_ride | 179 | +0.50 | 92.9% | 90.9% | 46.5% |
| earnings_drift | 111 | +0.24 | 91.7% | 88.3% | 36.9% |
| breakout_52w_trail | 174 | +0.23 | 84.2% | 83.9% | 24.6% |
| others | | | below 70% | | below 5% |

The best strategy would need about 424 trades at its current average to reach 99%, and that
assumes its edge is real. None is validated. They stay on probation or rejected.

## Guardrails against bad data and hallucination

These run in code, after each model reply:

- **Freshness:** price history whose last bar is more than 4 calendar days old is
  treated as unverified. No trade can rest on stale prices.
- **Grounding:** every figure quoted in an analyst summary, a bull or bear argument,
  or the PM rationale must match a value in the data the agent was given. A figure
  that matches nothing is removed (analysts, debate) or voids the trade (PM).
- **Schema:** the PM reply must be valid JSON with a known action, a candidate ticker,
  numeric stop and target, and confidence between 0 and 1. Anything else becomes NO_TRADE.
- **Unverified fields:** every missing or unconfirmed value is labelled and listed on
  the report.

Limits: these checks catch invented numbers and malformed output. They cannot verify
that the source data itself is correct. The data is end-of-day, not live. See
`project/PORTFOLIO_MANAGER_INSTRUCTIONS.md` for the instructions to use with the agents.

## Setup

```bash
pip install -r requirements.txt
cp watchlist.example.txt watchlist.txt  # edit with your tickers (NSE uses .NS)
```

The agents need Claude. There are two ways to provide it:

- **Claude subscription (default, no extra cost).** If the `claude` command (Claude Code)
  is installed and logged in, the agents run through it. Calls count against your
  subscription's usage limits. A run of five candidates is 26 calls and takes about 80 seconds.
- **API key (pay per use).** Set `ANTHROPIC_API_KEY` and the agents use the API instead.

`--llm cli` or `--llm api` forces one or the other.

## Usage

```bash
python -m trading_team run --watchlist watchlist.txt   # daily run, writes reports/YYYY-MM-DD.pdf
python -m trading_team screen --watchlist watchlist.txt  # verified prices + indicators as JSON, no API key
python -m trading_team settle                          # check open trades against later prices
python -m trading_team stats                           # win rate, average return, counts
```

Run `settle` before `run` each day so the portfolio manager sees current results.
Schedule both with cron or a scheduled task.

## Data honesty

- Price history and fundamentals come from Yahoo Finance via `yfinance`. These are
  free and unofficial. They can be delayed, incomplete, or change without notice.
- **FII/DII flows have no verified free source configured.** They are always reported as
  `Data Unverified` until you add a provider that implements `flows()`.
- News headlines are best-effort. Missing headlines are reported as unverified.
- Every report lists the Data Unverified items it used.

## Tests

```bash
python -m pytest -q tests
```

The suite uses a synthetic data provider and a fake LLM, so it runs offline. It
covers the indicators, data validation, each risk rule, ledger settlement (target,
stop, gap, stop-first, still open) and the end-to-end pipeline.

## Extending

- Add a data source: implement the `DataProvider` protocol in `data.py`.
- Change the team: each agent is a prompt plus a function in `agents.py`.
  Agents are independent and easy to swap or add.
- Change the model: `--model` on the CLI, or `Settings.model`.

## Disclaimer

Research output from an automated process. Not investment advice. Markets can
move against any recommendation, and the stop-loss does not guarantee a fill
price. Verify every figure before acting.
