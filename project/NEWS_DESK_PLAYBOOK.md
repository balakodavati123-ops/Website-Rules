# News desk runbook (for the Claude session that runs it)

Goal: during NSE hours, react to market-moving news with instant intraday PAPER trades, using as little
of the CEO's Claude plan as possible. No real order is ever placed. Every trade is closed by ~15:10.

## Daily loop (a self-renewing chain of send_later wake-ups)
1. 09:10 IST wake: arm Monitor with `cd /home/user/Website-Rules && python dashboard/news_watch.py`
   (timeout 1800000, description "high-impact market news"). It prints nothing except events.
2. Each 30-minute expiry notice before 15:10: re-arm the same Monitor. Nothing else.
3. On an EVENT line (these are rare: index-level news or a watchlist filing, max 6 a day):
   a. Decide direction from the headline text. Good news = LONG lean, bad = SHORT lean. RBI/macro: pick the
      NIFTY or BANKNIFTY option side only if the headline is clearly one-directional; if not, record NO TRADE.
   b. Get ONE live INDmoney quote (get_indian_stocks_details; ind_key via lookup_ind_keys if unknown).
      If the price already moved more than 3% on the news, skip: record nothing.
   c. Book: `python dashboard/news_desk.py book stock SYMBOL LONG|SHORT PRICE "headline"`, or for an index event,
      get_indian_stocks_option_chain (strikes_around_atm 3) and book the ATM call or put:
      `... book option NIFTY LONG|SHORT STRIKE CE|PE PREMIUM_ASK LOT EXPIRY "headline"` (use the ask).
   d. Publish only dashboard/data/news_feed.json and news_ledger.json (see Publishing).
4. 15:10 IST: for every OPEN trade get a live quote (stock price, or the option's current bid from a fresh chain),
   run `news_desk.py close ID PRICE`, publish both files, then arm the next morning's wake with send_later.
   If a stop was hit earlier you cannot know without a quote: close at the quote you get at 15:10.
5. Tell the CEO in at most five lines. No PushNotification unless a trade closed at a loss above Rs 2,000.

## Publishing (the dashboard shows what was last saved)
Artifact tool publish asset for the file, ArtifactData update datasets/<id> with the new source.url, updated, edit
stamps (pin if_version), then delete the old blob. Datasets: news_feed, news_ledger.

## Credit discipline
Never poll or sleep. No analysis beyond the steps above. Six events a day is the ceiling; the watcher enforces it.
If the CEO's usage warning appears, stop re-arming and say so.
