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

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...          # for the LLM agents
cp watchlist.example.txt watchlist.txt  # edit with your tickers (NSE uses .NS)
```

## Usage

```bash
python -m trading_team run --watchlist watchlist.txt   # daily run, writes reports/YYYY-MM-DD.pdf
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
