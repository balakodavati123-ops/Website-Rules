# Keeping the CEO Trading Desk dashboard alive

The dashboard is a Claude Artifact (https://claude.ai/artifact/4zc7CfzQEu6AiXdKt5Qp3N). Its numbers come two ways:

- **Live, in the viewer's own browser:** holdings, net worth, quotes, movers, candles, MCX futures
  (INDmoney connector) and crypto (Gemini connector). Nothing to do: it refreshes when the page opens.
- **Saved by the desk after each run:** agent notes, today's plan, filing alerts, the paper ledger,
  strategy tests. These are nine JSON datasets that the daily session must refresh.

## Automatic refresh

A scheduled task, "CEO Desk Daily Refresh", runs weekdays at 08:15 IST in a fresh cloud session. It
clones this branch, runs the desk, the crypto and commodity signals, the filing alerts and the paper
engine, then publishes seven datasets (agent feed, plan, filing alerts, crypto/commodity strategy tests,
breakout signals, paper ledger, paper equity). It reads the dashboard's current paper ledger first, so
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

## When the CEO says "approve SYMBOL"

Append a row to `paper_ledger` (status OPEN with the actual entry, stop, target, qty and risk) and
re-upload that one file. When a stop or target is hit, close the row (WIN, LOSS or TIME STOP, with
`exit`, `pnl_rs` and `r_mult`) and add a point to `paper_equity`. The dashboard computes the
confidence figure and the real-money gate from those rows by itself. Never approve on the CEO's
behalf and never place an order.

## Contract rolls (MCX futures)

MCX contracts expire (crude 19 Nov, natural gas 24 Nov, copper 30 Nov, gold and silver 4 Dec 2026).
Before expiry, look up the next contract with `lookup_ind_keys` (`filter_type: IN_COMMODITY`), then
update `datasets/comm_live` (`source.args.ind_keys`) and the enum for `sym` in `datasets/candles`
(`source.rules.sym.enum`), and the matching entries in `dashboard/pack.py`.

## Changing the page

Edit `dashboard/page/*`, test with `D3=<path to d3.min.js> node dashboard/test/harness.js OUTDIR`
(a headless smoke test with a mock of the platform), run `python dashboard/pack.py dashboard/assets.json`,
then write the changed documents with ArtifactData `set` (pin `if_version`).
