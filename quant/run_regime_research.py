"""Regime strategy research on the real-data ledger (quant/results/trades_ledger.json.gz). Writes quant/results/regime_strategy.json and
report_regime.md. Research only: no agent is trained and no order is sent (see quant/src/agent/trainer.py for the permission gate)."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.reports.report import metrics                 # noqa: E402
from src.research import regime_strategy as RS        # noqa: E402

OUT = Path("quant/results")


def main() -> None:
    rows = json.loads(gzip.decompress((OUT / "trades_ledger.json.gz").read_bytes()))
    wf = RS.walk_forward(rows, by="lcb")
    wf_win = RS.walk_forward(rows, by="win")
    start = wf["test_from"]
    base = {cid: RS.fixed(rows, cid, start) for cid in ("atm|11:00|TP50|SL35", "lean_100|10:30|TP50|SL35", "lean_150_250|09:20|TP80|SL25", "dir_with|09:20|TP50|SL35",
                                                        "dir_with|10:30|TP50|SL35", "dir_against|09:20|TP30|SL50")}
    by_policy = {}
    for pol in sorted({r["strike_policy"] for r in rows}):
        rr = [r for r in rows if r["strike_policy"] == pol]
        by_policy[pol] = metrics(rr)
    win_rate_kings = sorted(({"config_id": c, **metrics([r for r in rows if r["config_id"] == c])} for c in {r["config_id"] for r in rows}), key=lambda x: -x["win_rate_pct"])[:5]
    res = {"walk_forward_profit": wf, "walk_forward_win_rate": wf_win, "fixed_rules_same_period": base, "all_rows_by_structure": by_policy, "highest_win_rate_rules_in_sample": win_rate_kings}
    (OUT / "regime_strategy.json").write_text(json.dumps(res, indent=1, default=str))
    o = wf["out_of_sample"]
    L = ["# Regime strategy (buying only), walk-forward on real option prices", "",
         f"Out of sample {wf['test_from']} to {wf['test_to']}: {wf['days_tested']} days tested, {wf['days_traded']} traded, {wf['days_skipped']} skipped.",
         f"Profit-ranked: {o.get('trades')} trades, {o.get('win_rate_pct')}% won, average Rs {o.get('expectancy_inr')}, net Rs {o.get('net_pnl_inr')}, profit factor {o.get('profit_factor')}, "
         f"max drawdown Rs {o.get('max_drawdown_inr')}, t {o.get('t_stat')}.",
         f"Win-rate-ranked: {wf_win['out_of_sample'].get('trades')} trades, {wf_win['out_of_sample'].get('win_rate_pct')}% won, average Rs {wf_win['out_of_sample'].get('expectancy_inr')}, net Rs {wf_win['out_of_sample'].get('net_pnl_inr')}.", ""]
    L += ["| Cell (09:20) | Rule with all data today |", "|---|---|"] + [f"| {c} | {v['rule'] or 'SKIP'} {v['trained_on'] or ''} |" for c, v in wf["rules_today_from_all_data"].items()]
    (OUT / "report_regime.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
