# Balaji's Trading Desk

An algorithmic trading desk for **NSE Equity and NIFTY F&O**, run by AI agents on GitHub. It researches strategies, trades them on paper, shows everything on one dashboard, and sends real orders only after you approve.

**Dashboard:** https://balakodavati123-ops.github.io/Website-Rules/ (tabs open directly by link, for example `#bt` for Backtest and `#audit` for Audit).

---

## 1. The dashboard

**At the top**
- **Index cards:** NIFTY 50, Bank Nifty, Sensex and India VIX.
- **Ticker:** index moves and the latest market headlines run continuously. Hover over it to pause.
- **Status chips:** whether prices are live, and whether each market is open.
- **⚡ Live prices on this device:** paste a read-only Upstox token to get tick-by-tick prices in your own browser. The token stays on your device.

| Tab | What it shows |
|---|---|
| **Company floor** (front page) | The live office: every desk, its agents, the trades flowing through, the COO and your CEO desk. Below it, the research agents and the share of the strategy search each one ran. |
| **Overview** | **Broker account**: wallet, holdings and today's positions from your Upstox account, refreshed every minute; the paper account until a broker token is connected. Also today's P/L, NIFTY today, agent ranking, open positions and **Close now** buttons. |
| **Equity** | Equity desk P/L, open positions and trades (Open / Today / All days); top gainers, losers and most active; headlines; results filed; world markets; **Fundamentals** for any stock from TradingView (financials and a daily chart, BSE listing). |
| **F&O** | **NIFTY today**: the mode (Quiet / Volatile / Highly volatile, from India VIX), the desk's call (up / down / no clear direction), the likely range, today's trade, the reasons in plain words. The NIFTY chart with the call drawn on it, the **live option chain** (21 strikes, best buyer and seller with quantities, volume, open contracts, a five-level order book), open trades by Today / Weekly / Monthly, and trade history per book. |
| **Charts** | Live 1-minute charts for F&O and Equity with EMA 20/50, VWAP, opening range, entries, stops, targets, expected exits and the order book; plus a chart for any NSE stock with your trades on it. |
| **Backtest** | The **strategy research** results and the **approval queue**; the **backtester** (any of the strategies, any years, your own settings, exits that protect profit, the search for settings, patterns by day / week / month); the **NIFTY 1-minute database** (download). |
| **Audit** | Every Equity and F&O trade with its planned **risk** (₹ to the stop), **reward** (₹ to the target), **R:R**, capital, order route (paper / practice / live), status and P/L. Filter by desk, status, period or text; tap a row for the trade's full reasoning. |

## 2. Connectors: only three are needed

They are stored as GitHub secrets: repository **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | What it is | What it unlocks |
|---|---|---|
| `UPSTOX_TOKEN` | Upstox **Analytics** token (read-only, long-lived) | All market data: prices, candles, option chains, the 1-minute database. *Already set.* |
| `UPSTOX_EXEC_TOKEN` | Upstox **trading** access token for your own account (from the Upstox developer app; it expires daily at 03:30 IST) | Your wallet, holdings and positions on the Overview. Orders too, but only once execution is switched on (section 3). |
| `CLAUDE_CODE_OAUTH_TOKEN` | From `claude setup-token` on your Claude plan (no API bill) | The AI market brief, the plain-words thesis and the analyst rounds. |

GitHub itself is the fourth piece. It is already in place: it hosts the dashboard, runs the engine every market day, and carries your approvals. Approval buttons open a GitHub issue with the instruction already written; the engine obeys only issues opened by you.

## 3. From research to real money: the gates

Nothing places a real order until every step below is done, in order.

1. **Research.** Every Saturday five quant agents split the strategy search equally (workflow `research`). A sixth runs the multi-day strategies. A risk agent runs random-entry strategies through the same rules, to measure luck.
2. **Approval queue** (Backtest tab). Only strategies that held up in **all three periods** are listed:
   - chosen on 2022–23,
   - confirmed on 2024,
   - shown once on 2025–26.

   **Approve** means paper trading. **Reject** removes the strategy.
3. **Paper record.** An approved strategy trades on paper. Every trade appears in Audit, with its risk and reward worked out before entry.
4. **Live.** Real orders need, together:
   - a separate live approval;
   - the secret `EXEC_MODE=live` plus `EXEC_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY`;
   - a valid `UPSTOX_EXEC_TOKEN`;
   - a strategy verdict of READY FOR REVIEW (100+ paper trades, 98% confidence).

   Hard limits always apply: `EXEC_MAX_ORDER_RS`, `EXEC_MAX_DAY_LOSS_RS`, and the kill switch `EXEC_KILL=1`. `EXEC_MODE=sandbox` sends practice orders to Upstox's practice exchange first.

Commodities and crypto no longer open new trades (`DESKS_OFF`, default `COMMODITY,CRYPTO`).

## 4. What the research found (data: 3 Jan 2022 to 26 Nov 2026, real NIFTY 1-minute candles)

### Intraday: 2,112 strategies
- **How they were built:** 44 entry setups (EMA crossovers 5/13 … 20/50 on 3, 5 and 15-minute candles, RSI, VWAP, opening range, Supertrend, Bollinger, MACD, previous-day high/low, first 5-minute candle), each with 6 exit plans and 4 filters, and each also **faded** (the opposite trade, to profit where the taught version fails).

| Priced as | Picked on 2022–23 | Held in 2024 | Profitable 2025–26 |
|---|---|---|---|
| ATM option buy (your instrument) | 0 | 0 | 0 |
| Futures, NSE charges | 8 | 2 | 0 |
| Before any costs | 457 | 311 | 253 (random entries: 11 of 200) |

- **The edge before costs is real but small**, about 3–12 NIFTY points a trade. Costs are about 8–10 points a trade (option spread, time decay, ₹470 of futures charges), so intraday trading of these signals loses money.
- **No setting of any strategy reached 80% wins with a profit factor of 2** in any period.

### Your EMA crossover
- **Last 5 sessions:** EMA 9/21 on 5-minute NIFTY made money, 5 trades with 60% won and +₹3,354. This matches your experience.
- **Over 5 years:** 2,037 trades, 34% won, −₹3.67 lakh.
- **How often it wins:** it was profitable in 11 of 59 months and 82 of 257 weeks, so a good week like yours comes about one week in three.

### Multi-day: held across sessions until the opposite signal or a stop

| | Picked 2022–23 | Held 2024 | Profitable 2025–26 | Profitable in every period |
|---|---|---|---|---|
| 162 real strategies | 75 | 34 | **31** | 53 (33%) |
| 100 random-entry controls | 31 | 14 | 6 | 12 (12%) |

The best, traded as a deep in-the-money NIFTY option (estimate: 0.8 of the index move, about 4 points of time value a day):

| Strategy | Capital per lot | 2024–26, compounded | Worst drawdown | Won |
|---|---|---|---|---|
| EMA 9/21, hourly, trail 3 ATR | ₹3.5 L | ×2.15 | 20% | 42% |
| EMA 9/26, hourly, trail 3 ATR | ₹4 L | ×1.97 | 26% | 43% |
| MACD, 2-hourly, ATR stop | ₹4 L | ×1.80 | 23% | 44% |
| EMA 9/21 + ADX 20+, hourly | ₹4 L | ×1.76 | 22% | 44% |

- **"Capital per lot"** is 3.3 times the worst one-lot drawdown of 2022–23, so a bad streak costs about 30% of the account. One NIFTY lot swings more than ₹1 lakh in a bad streak; at ₹1 lakh per lot, accounts were wiped out in the test.
- **Compounding:** the account adds a lot for each multiple of that capital, so profits are reinvested every day instead of sitting idle.
- **Realistic return:** about 25–30% a year, with about a 20% drawdown. Not 70–80%.
- **The option figures are an estimate.** They must be checked on real option prices before any money goes in.

### Real option prices with your 2-lot rule (Oct 2024 to Nov 2026, every NIFTY weekly option, 1-minute candles)

Each trade buys at most 2 lots: calls on up signals, puts on down signals. Each trade uses the nearest weekly expiry with 3 or more trading days left, rolled before expiry day. The figures include slippage and full charges, and the account starts at ₹1,00,000.

| Strategy · structure | Trades | Won | PF | Net | Without the 5 best trades | Worst drawdown | Lowest account |
|---|---|---|---|---|---|---|---|
| MACD 2-hourly · **debit spread** (buy 1, sell 1 lot 200 out) | 103 | 38% | 1.58 | +₹92k | **+₹8.5k** | ₹23k | ₹88.8k |
| EMA 13/34 hourly · **debit spread** | 95 | 41% | 1.34 | +₹46k | −₹11k | ₹38k | ₹98.6k |
| EMA 9/21 + ADX hourly · **debit spread** | 90 | 38% | 1.35 | +₹44k | −₹17k | ₹26k | ₹93.8k |
| EMA 13/34 hourly · **1 lot + 1 opposite lot 200 out** (hedged pair) | 95 | 35% | 1.71 | +₹2.15 L | −₹98k | ₹69k | ₹64k |
| EMA 9/26 hourly · **2 lots at the money** | 132 | 34% | 1.68 | +₹6.18 L | −₹1.37 L | ₹1.87 L | ₹95k |
| EMA 13/34 hourly · **2 lots at the money** | 95 | 37% | 1.84 | +₹5.77 L | −₹1.54 L | ₹1.61 L | ₹87k |

- **Debit spreads fit ₹1 lakh.** About ₹5,500 is at risk per trade (at most ₹9,500), and the worst drawdown was ₹23–38k. The edge is modest: roughly ₹20–45k a year.
- **2 lots of bought options made the most**, ₹4–7 lakh in two years. But the drawdowns (₹1.6–2.2 lakh) exceed a ₹1 lakh account, and the profit came from a handful of big trend moves. Without the 5 best trades, every one of them loses. With ₹1 lakh, use 1 lot or a spread.
- **Your intraday EMA crossover on real prices** (5- and 15-minute, every structure): profit factor 0.36–0.98. It lost money in every version.
- **Both directions (1 call + 1 put):**

  | Entered | Profit factor |
  |---|---|
  | Every day | 0.52–0.63 |
  | After a narrowest-range day | 0.67–1.00 |
  | After a quiet first hour | 0.54–0.61 |

  There is no edge: time decay wins unless a big move is known in advance.
- **Hedging pays on multi-day trends, not intraday.** The opposite protective option helped the multi-day trades (smaller drawdowns), but made intraday trades much worse (profit factor 0.48–0.65), because over a few hours the protection only costs time value.

### The "EMA VWAP" reel (3-minute candles), on real option prices with 2 lots

| Rule | Trades | Per day | Won | PF | Net | Account low |
|---|---|---|---|---|---|---|
| Wick into VWAP rejected, with the trend (the reel's images) | 1,282 | 3.2 | 24% | 0.83 | −₹1.75 L | wiped |
| Wick into EMA9 or VWAP, with the trend | 5,993 | 12.2 | 23% | 0.75 | −₹10.8 L | wiped |
| VWAP wick → puts, EMA9 break → calls (as written) | 5,917 | 12.0 | 23% | 0.74 | −₹10.6 L | wiped |
| EMA9 × VWAP crossover | 1,167 | 2.6 | 30% | 0.86 | −₹1.53 L | −₹53k |

- **No edge even before costs.** On the futures, these entries lost 0.7–1.0 points per trade, so there is nothing for option costs to eat into.
- **The exit cuts most trades.** About 95% of trades end at the first 3-minute close back across EMA9, mostly as small losses. The rare trades that run to 15:20 are the only big winners.
- **Every variant loses.** The stop, skipping expiry day, the call side, the put side, and each year from 2024 to 2026 all lost money.
- **A 5-year check on the index (2022–2026) agrees.** The profit factor before costs is 0.97–1.10.
- **Why the reel looks convincing:** a reel shows chosen examples, while a backtest counts every signal.
- **Try it yourself:** both rules are in the Backtest tab as "EMA9 / VWAP wick rejection (reel)" and "VWAP wick puts / EMA9 break calls".

### About "70–80% profits" on social media
- Posts show winners and leave out the losers.
- SEBI's study: **91% of individual F&O traders lost money in FY24**, and 93% over FY22–FY24.
- The desk's aim is a measured edge with controlled risk, not screenshots.

## 5. Strategies traders teach, where they fail, and the fix

From public sources (Zerodha Varsity, Zerodha's *In The Money*, TradingView, Groww, StockCharts, and Quantsapp's public one-year NIFTY futures backtests with costs).

| Strategy | Where it loses | What helps (to test) |
|---|---|---|
| First 5-minute candle break (2R) | Quiet days, gap-ups of 0.4%+; negative without its 25 best trades | Skip big gap-ups; reverse once after a failed break before 11:00 |
| 15-min opening range breakout | Choppy days that break and swing back (−₹2.5 L); net −₹55.8k | Fade a close back inside the range within 30 minutes |
| Long-window ORB (9:15–11:15, 3-min) | The short side; option buying in 2025 | Long-only on spot; shorts only below the previous day's low |
| Previous day high/low break | Choppy and quiet days, gap-ups | Fade a failed break (15-min close back inside) |
| Gap-and-go | Big gap-downs, VIX above 14.5 | Fade the gap instead: **full-gap fade was net positive (+₹47.7k)** |
| CPR narrow / wide | Quiet days, whipsaws | Narrow CPR: trade the break; wide: fade it |
| EMA 9/21 crossover | Sideways markets, quiet days | 15-min with an ATR buffer and the 200-SMA filter (**+₹32.4k net**); stop crossovers after 3 before noon |
| 9 EMA × VWAP | Quiet days, weekly expiry | VWAP slope filter (needs futures volume) |
| VWAP + RSI fade | Trend days (−₹2 L) | After two stopped fades, trade with the move |
| Supertrend (10,3) intraday | Quiet days, expiry | The slower Heikin-Ashi version held overnight was net positive (+₹84k) |
| 5 EMA alert candle | Trend days; the worst result reviewed (−₹3.95 L) | Reverse when stopped |
| Inside bar / NR7 | False breaks, high VIX | Fade the failed break |
| Bollinger squeeze / re-entry | Choppy (squeeze) and trend (re-entry) days | Wider stops; skip expanding bands |
| MACD 1-min scalp | Costs on quiet days (−₹1.68 L) | 15-min with ADX 25+ |
| 9:20 short straddle | Choppy days stop both legs | Move the other leg's stop to cost (the only net-positive straddle version) |
| 3 PM breakout | No verifiable record | Only in the day's direction |

**Common lessons**
- **Quiet days kill breakouts; trend days kill fades.** No live rule reliably tells them apart in advance. The ADX "switch regimes" router lost money in its public test.
- **Costs turn many systems negative**, so trade less often and hold for bigger moves.
- **Validate every filter out of sample.** Most public results cover one year only.

## 6. Risk on every trade

- **Before entry,** each trade has a stop and a target. The Audit tab shows risk (₹ to the stop), reward (₹ to the target), R:R and capital.
- **Position size** comes from the account, not from a guess: capital per lot (above), the desk's money limits, and daily loss caps.
- **Exits protect profit:** trailing stops, breakeven moves, momentum exits and time stops, all tested in the backtester.

## 7. Data and schedule

- **NIFTY 50 1-minute database:** every minute since 3 Jan 2022, in one SQLite file (`nifty50_1m.sqlite` on the `charts` branch), updated after every close.
  - The view `nifty50_1m` has day, time, open, high, low and close.
  - The table `days` has one row per session, with NSE's official close.
- **Engine:** runs through market hours on GitHub Actions and publishes to the dashboard about every 15 seconds. It skips exchange holidays.
- **Research:** every Saturday (workflow `research`), or on demand from GitHub → Actions → research → Run workflow.

## 8. Words used on the dashboard

| Term | Meaning |
|---|---|
| **Profit factor (PF)** | Money won ÷ money lost; above 1 makes money. |
| **Win rate** | Share of trades that made money. |
| **Drawdown** | The fall from the account's high point. |
| **R:R** | Reward ÷ risk planned at entry. |
| **ATR** | The market's typical candle size; used to set stops. |
| **EMA** | Exponential moving average. |
| **VWAP** | Session average price. |
| **ITM option** | An option already in profit at the strike: it moves almost like the index and loses less time value. |
| **Paper** | Simulated trades with real prices, no money. |
| **Practice (sandbox)** | Upstox's practice exchange. |
| **Live** | Real orders. |

---

*Research and paper trading. Not investment advice. Past results do not promise future returns.*

Older documentation of the research-team tools: [docs/legacy-research-team.md](docs/legacy-research-team.md).
