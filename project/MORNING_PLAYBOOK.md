# Morning playbook: from analysis to a ticket you can place in a few taps

For the daily Claude session. It needs: this repo (`trading-desk/`), the `claude` command
logged in, and the INDmoney connector enabled. **Nothing here places an order. The last tap
is always the user's.**

## When
Weekdays, 09:20 to 09:30 IST. The opening auction is done and one-minute prices are live.
Skip NSE holidays and weekends: do a ledger review instead (`python -m trading_team settle`).

## Steps

1. **Settle yesterday.** `python -m trading_team settle`, then `python -m trading_team stats`.
2. **Analyse.** `python -m trading_team run --watchlist watchlists/nifty200_plus_etfs.txt`
   Writes `reports/YYYY-MM-DD.json` and a PDF. Signals come from the last completed close
   (the backtest's rule: signal at the close, enter at the next open).
3. **If the file says NO_TRADE:** run `python -m trading_team ticket --from-json reports/YYYY-MM-DD.json --equity <equity>`
   to print the reason, show the market board (step 6), and stop. No trade is a valid result.
4. **If BUY: get the live price in one go.** With the INDmoney connector:
   `lookup_ind_keys` for the ticker, then `get_indian_stocks_details` (it returns
   `live_price`, `price_updated_at_ist`, circuit limits). Note the price and its time.
   Do this immediately before step 5: prices older than 2 minutes are refused.
5. **Build the ticket right away:**
   `python -m trading_team ticket --from-json reports/YYYY-MM-DD.json --mode open --live-price <P> --price-time <HH:MM:SS> --equity <equity> --open-risk <rupees at risk in open trades> --vix <India VIX>`
   - `--mode open` enters at the live price with the strategy's own stop and target
     percentages, exactly as backtested. It refuses if the price has gapped more than 3% away
     from the analysed close.
   - Equity and open risk come from the ledger (`stats`) or the user's INDmoney positions.
     Read positions only if the user has agreed to it.
6. **Context board (optional, one call each):** `get_indian_stocks_movers` for `top-gainers`
   and `52-week-high`. Save each result to a file and run
   `python -m trading_team board gainers.json high.json --ticker <TICKER>`.
   Treat movers as context only: do not trade a stock because it is on a list.
7. **Present** the ticket exactly as printed, with its status:
   READY (price near entry), WAITING (price ran away: the limit rests, do not raise it) or
   DO NOT TRADE (a check failed: say which).
8. **Never** place, modify or cancel orders, never raise a limit to chase, and never save
   anything to the user's INDmoney account unless they ask.

## Always state
- The strategy and its status. Today none is validated; the live ones are on PROBATION.
- Data Unverified items from the report.
- "Research output on a simulated portfolio. Not investment advice."
