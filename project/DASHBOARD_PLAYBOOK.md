# Keeping the CEO Trading Desk dashboard alive

The dashboard is a Claude Artifact (https://claude.ai/artifact/4zc7CfzQEu6AiXdKt5Qp3N). Its numbers come two ways:

- **Live, in the viewer's own browser:** holdings, net worth, quotes, movers, candles and MCX futures
  (INDmoney connector). Nothing to do: it refreshes when the page opens, and the Live floor's
  "Live refresh" button re-reads prices every minute while the market is open.
- **Saved by the desk after each run:** agent notes, today's plan, filing alerts, the paper ledger,
  strategy tests, and crypto prices and candles (CoinDCX in rupees, checked against Kraken; there is
  no crypto connector that works in India, so these are saved, not streamed). These are eleven JSON
  datasets; the daily session refreshes nine of them.

## The Live floor

The first tab. Ten desks and the CEO; the engine in `dashboard/page/floor_engine.js` plays one hand-off
at a time, and every sentence a desk says is a cell of the calcs in `floor_data.js` (`floor_rows`,
`floor_stats`, `floor_side`), so a reader can trace it. All limits live in one calc, `floor_rules`.
These desks are fixed rules on live prices, not Claude calls: they screen and rank, they do not
predict, and the screen is not backtested. The Claude agents' research is the morning run.

## Automatic refresh

A scheduled task, "CEO Desk Daily Refresh", runs weekdays at 08:15 IST in a fresh cloud session. It
clones this branch, runs the desk, the crypto and commodity signals, the filing alerts and the paper
engine, then publishes nine datasets (agent feed, plan, filing alerts, crypto/commodity strategy tests,
breakout signals, paper ledger, paper equity, crypto quotes, crypto candles). It reads the dashboard's current paper ledger first, so
trades carry over from day to day. If a step fails it leaves that dataset as it was and says so.
The paper engine (`dashboard/paper_engine.py`) fills pending orders at the next open, closes trades on
stop, target, exit signal or time stop, and writes the equity point. The dashboard turns the closed
trades into the confidence figure and the real-money gate.

## Daily refresh (after `python -m trading_team run ...`)

1. `python dashboard/build_seed.py` rebuilds `dashboard/data/*.json` from the newest
   `reports/*_agents.json`, the backtest results and `dashboard/inputs/*.json`.
2. For each file in `dashboard/data/`, upload it to the artifact as an asset
   (Artifact tool, `action: publish`, `url`, `asset: true`, `file_path`; JSON goes one file per call).
   Note the returned `/_blob/<id>` url.
3. Update the matching dataset document (ArtifactData `update`, collection `datasets`, doc id = file
   name without `.json`): set `source.url` to the new blob url, `updated: {at, by}` and `edit: {via: "claude", at}`.
4. Delete the previous upload of each file once nothing points at it.
5. Never write to `files/*` or the live-query datasets in this routine. The page code only changes
   when the page itself is changed.

## Paper orders and the CEO's approval

Paper orders need no approval: the paper engine opens and closes them by its own rules in the daily
refresh, so the record cannot be flattered by picking which signals to take. The CEO's approval is for
real money, and only after the gate passes. Even then the desk writes a ticket and the CEO places the
order in INDmoney. Never approve on the CEO's behalf and never place an order.

## Contract rolls (MCX futures)

MCX contracts expire (crude 19 Nov, natural gas 24 Nov, copper 30 Nov, gold and silver 4 Dec 2026).
Before expiry, look up the next contract with `lookup_ind_keys` (`filter_type: IN_COMMODITY`), then
update `datasets/comm_live` (`source.args.ind_keys`) and the enum for `sym` in `datasets/candles`
(`source.rules.sym.enum`), and the matching entries in `dashboard/pack.py`.

## Changing the page

Edit `dashboard/page/*`, test with `node dashboard/test/floor_calc_test.js` (the floor's rules) and
`D3=<path to d3.min.js> node dashboard/test/harness.js OUTDIR` (a headless smoke test with a mock of the platform), run `python dashboard/pack.py dashboard/assets.json`,
then write the changed documents with ArtifactData `set` (pin `if_version`).

## Rise and fall alerts

`dashboard/trend_alert.py` is run hourly through market hours (10:20 to 15:20 IST, weekdays) by the scheduled task
"Trend Alerts". It scans the watchlist on 15-minute Yahoo bars (NSE data is delayed about 15 minutes) and pushes a
phone notification only for names whose rise or fall condition is new since an hour earlier. It screens; it does not
forecast. Each run costs a fresh session, so keep the frequency low.

## F&O paper desk

`dashboard/fo_engine.py` paper trades NIFTY index option structures (short iron condor, bull put
spread, iron butterfly), one lot, held to expiry. `book CHAIN.json` needs a saved INDmoney option
chain (shorts at the bid, longs at the ask) and refuses credit structures with no credit and
expiries under 2 days. `settle` runs in the daily refresh and needs no option data: each leg is
worth its intrinsic value against the expiry-day index close from Yahoo, minus Rs 50 a leg, an
approximation of NSE's official settlement. Booking runs weekly by a send_later wake of the main
chat session, because scheduled tasks in this organisation carry no connectors and NSE's public
option-chain API refuses scripts. The fo_ledger dataset feeds the F&O card in the Algo lab.
