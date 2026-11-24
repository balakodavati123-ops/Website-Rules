# Regime strategy (buying only), walk-forward on real option prices

Out of sample 2025-04 to 2026-11: 401 days tested, 253 traded, 58 skipped.
Profit-ranked: 253 trades, 45.5% won, average Rs 19.9, net Rs 5041, profit factor 1.01, max drawdown Rs -47835, t 0.1.
Win-rate-ranked: 252 trades, 50.4% won, average Rs 39.5, net Rs 9964.

| Cell (09:20) | Rule with all data today |
|---|---|
| MODE_1_QUIET | DTE 0 | dir_with|12:45|TP50|SL25 {'n': 40, 'avg': 272.2, 'pf': 1.63, 'win': 47.5} |
| MODE_1_QUIET | DTE 1-2 | dir_with|09:20|TP30|SL50 {'n': 50, 'avg': 441.9, 'pf': 1.6, 'win': 62.0} |
| MODE_1_QUIET | DTE 3-4 | dir_with|09:20|TP30|SL50 {'n': 46, 'avg': 500.7, 'pf': 1.43, 'win': 58.7} |
| MODE_2_VOLATILE | DTE 0 | lean_100|10:30|TP50|SL35 {'n': 39, 'avg': 1362.5, 'pf': 2.19, 'win': 48.7} |
| MODE_2_VOLATILE | DTE 1-2 | dir_with|09:20|TP30|SL35 {'n': 52, 'avg': 570.9, 'pf': 1.45, 'win': 59.6} |
| MODE_2_VOLATILE | DTE 3-4 | dir_against|11:00|TP30|SL35 {'n': 65, 'avg': 194.5, 'pf': 1.17, 'win': 43.1} |
| MODE_3_HIGH_VOLATILITY | DTE 0 | dir_against|11:00|TP80|SL25 {'n': 18, 'avg': 985.6, 'pf': 2.06, 'win': 38.9} |
| MODE_3_HIGH_VOLATILITY | DTE 1-2 | dir_against|11:00|TP80|SL25 {'n': 36, 'avg': 2041.8, 'pf': 3.03, 'win': 47.2} |
| MODE_3_HIGH_VOLATILITY | DTE 3-4 | dir_against|11:00|TP80|SL50 {'n': 23, 'avg': 1036.7, 'pf': 1.81, 'win': 52.2} |
