# NIFTY weekly long-straddle backtest (real Upstox option prices)

DATA_SOURCE_STATUS: option_prices: VERIFIED_HISTORICAL (Upstox expired-instrument candles); index: VERIFIED_HISTORICAL (Upstox v3 candles); macro: PARTIAL (Yahoo daily closes, point-in-time; JNIV replaced by Nikkei and TOPIX Banks moves); news_sentiment: SYNTHETIC_MOCK = 0 in the backtest (no historical headline archive); live only

Period: 112 weekly expiries, 2024-10-03 to 2026-11-17; 4-DTE to 0-DTE; entries 09:20, 10:30, 11:00, 12:45; strike policies at the money and lean 150/250; targets 30/50/80%, stops 25/35/50%; square-off 15:20; full charges and slippage; lot size as traded (25, 75 or 65).

| Config | Trades | Won | Expectancy | Net | Profit factor | Max drawdown | t |
|---|---|---|---|---|---|---|---|
| lean_150_250|09:20|TP80|SL25 | 515 | 35.3% | ₹-109.1 | ₹-56,179 | 0.94 | ₹-120,843 | -0.5 |
| lean_150_250|09:20|TP30|SL25 | 515 | 40.2% | ₹-163.4 | ₹-84,161 | 0.91 | ₹-97,959 | -0.92 |
| lean_150_250|09:20|TP50|SL25 | 515 | 36.7% | ₹-200.5 | ₹-103,269 | 0.89 | ₹-159,494 | -1.02 |
| lean_150_250|09:20|TP80|SL50 | 515 | 37.1% | ₹-222.0 | ₹-114,309 | 0.89 | ₹-164,377 | -0.96 |
| lean_150_250|09:20|TP80|SL35 | 515 | 36.1% | ₹-228.8 | ₹-117,829 | 0.89 | ₹-167,782 | -1.02 |
| lean_150_250|12:45|TP50|SL25 | 517 | 37.1% | ₹-240.9 | ₹-124,549 | 0.82 | ₹-146,303 | -1.71 |
| lean_150_250|12:45|TP30|SL25 | 517 | 38.1% | ₹-268.3 | ₹-138,697 | 0.79 | ₹-155,527 | -2.04 |
| lean_150_250|09:20|TP30|SL35 | 515 | 40.8% | ₹-278.1 | ₹-143,223 | 0.85 | ₹-151,974 | -1.49 |
| lean_150_250|09:20|TP30|SL50 | 515 | 41.7% | ₹-281.1 | ₹-144,744 | 0.85 | ₹-150,239 | -1.46 |
| lean_150_250|12:45|TP80|SL25 | 517 | 36.2% | ₹-292.3 | ₹-151,107 | 0.78 | ₹-176,243 | -2.02 |

All 72 configurations together: 37098 trades, 33.4% won, expectancy ₹-395.4, profit factor 0.73, t -22.05.

Selecting the best of 72 configurations inflates its result; no configuration is statistically different from zero after costs (best t = -0.5).

No agent has been trained and no order sent. Training needs APPROVE_AGENT_TRAINING; paper execution needs APPROVE_PAPER_EXECUTION (quant/src/agent/trainer.py).
