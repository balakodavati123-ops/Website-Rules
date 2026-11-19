# Running the execution gateway on a machine with a static IP

The paper desk runs on GitHub and stays in **dry-run**: INDstocks only accepts orders from an IP address you have
whitelisted (dashboard, Access Tokens, Static IP), and GitHub's servers change address. To send real orders, run the same engine on
a computer that has a static IP (a home connection with a fixed IP, or a small always-on server).

```
pip install yfinance pandas numpy
export UPSTOX_TOKEN=...            # read-only market data (the desk's prices)
export INDSTOCKS_TOKEN=...         # from the INDstocks Access Tokens page; valid 24 hours, replace it each morning
export EXEC_ALLOWED_IP=203.0.113.7 # the static IP you whitelisted
export EXEC_MODE=live
export EXEC_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY
export LOOP_SECONDS=22000
python backend/engine.py
```

Do not run this and the GitHub live run for orders at the same time; the GitHub run cannot send orders (wrong IP) and only mirrors in dry-run.

What the gateway enforces (see `backend/gateway.py`): a stop-loss on every order (attached as a broker-side GTT leg), risk and order-value caps,
one position per instrument, trade-count and daily-loss limits, entry window and end-of-day exit, charges against target, and the agent's
paper-record gate. Defaults are small (Rs 250 risk, Rs 40,000 order value); lower them for the first sessions with `EXEC_RISK_PER_TRADE_RS` and `EXEC_MAX_ORDER_RS`.
Kill switch: `EXEC_KILL=1`, or create a file named `KILL` in `docs/data/`.
Gate: `EXEC_GATE=normal` (verdict WORKING and 30+ closed paper trades), `strict` (READY FOR REVIEW), or `off` (needs `EXEC_GATE_OFF_CONFIRM=I-ACCEPT-UNVALIDATED-STRATEGY`).
Nothing was tested against the live broker: start with a tiny size and watch the first orders in the INDmoney app.
