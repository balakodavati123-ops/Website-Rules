/* Loaders reshape each live answer into rows. Calcs work out every derived figure. */

/* ---------- loaders (each is self-contained: readers see its code) ---------- */
dash.loader('snapshot', { description: 'Net worth, asset classes and loans from the INDmoney account.',
  fn: ({ answer }) => {
    const a = typeof answer === 'string' ? JSON.parse(answer) : answer; const rows = [];
    rows.push({ kind: 'total', name: 'Net worth', invested: null, current: a.total_networth, share_pct: null });
    rows.push({ kind: 'total', name: 'Assets', invested: a.total_invested, current: a.total_current_value, share_pct: null });
    (a.investments || []).forEach((x) => rows.push({ kind: 'asset', name: x.asset_type, invested: x.invested_value, current: x.current_value, pnl: x.return, pnl_pct: x.return_percentage, share_pct: x.progress_value_percentage }));
    ((a.liabilities && a.liabilities.loans) || []).forEach((l) => rows.push({ kind: 'debt', name: (l.lender || 'Loan') + ' ' + (l.loan_type || ''), invested: null, current: l.current_balance, share_pct: null }));
    return rows;
  } });

dash.loader('mf_holdings', { description: 'Mutual fund holdings with profit and loss.',
  fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    return (a.holdings || []).map((h) => ({ name: h.investment, class: h.assetclass_l2, invested: h.invested_amount, value: h.market_value, pnl: h.total_pnl, pnl_pct: h.pnl_per, units: h.total_units, nav: h.unit_price, day_change: h.one_day_change, day_pct: h.one_day_change_percentage, share: h.holding_percent })); } });

dash.loader('stock_holdings', { description: 'Direct Indian stock holdings with profit and loss.',
  fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    return (a.holdings || []).map((h) => ({ name: h.investment, symbol: h.investment_code, invested: h.invested_amount, value: h.market_value, pnl: h.total_pnl, pnl_pct: h.pnl_per, qty: h.total_units, price: h.unit_price, day_change: h.one_day_change, day_pct: h.one_day_change_percentage })); } });

dash.loader('gold_rows', { description: 'Your gold holdings (coins, jewellery, digital).',
  fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer; const me = (a.family_asset_holdings || []).find((m) => m.is_you) || {};
    return (me.holdings || []).map((h) => ({ metal: 'Gold', name: h.name, qty: h.quantity, invested: h.invested_amount, value: h.current_value, pnl: h.absolute_change, pnl_pct: h.absolute_change_percentage, avg_price: h.avg_buy_price, price: h.unit_price })); } });

dash.loader('silver_rows', { description: 'Your silver holdings.',
  fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer; const me = (a.family_asset_holdings || []).find((m) => m.is_you) || {};
    return (me.holdings || []).map((h) => ({ metal: 'Silver', name: h.name, qty: h.quantity, invested: h.invested_amount, value: h.current_value, pnl: h.absolute_change, pnl_pct: h.absolute_change_percentage, avg_price: h.avg_buy_price, price: h.unit_price })); } });

['indices', 'watch_live', 'comm_live'].forEach((id) => {
  dash.loader(id, { description: 'Live quotes, day range, circuits and analyst targets, one row per instrument.',
    fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
      return Object.keys(a || {}).filter((k) => a[k] && a[k].entity_stats).map((k) => { const v = a[k]; const s = v.entity_stats; const b = v.entity_basic || {}; const f = v.analyst_forecast || {}; const t = f.target_price || {}; const c = f.consensus || {};
        return { key: k, name: b.display_name || b.name, symbol: b.symbol || b.display_name, live: s.live_price, chg: s.day_change, chg_pct: s.day_change_percentage, open: s.day_open, high: s.day_high, low: s.day_low, prev: s.prev_close, w52_high: s['52week_high'], w52_low: s['52week_low'], upper: s.upper_circuit, lower: s.lower_circuit, volume: s.volume, oi: s.open_interest, oi_chg: s.open_interest_change, expiry: b.expiry_date, time: s.price_updated_at_ist, target: t.mean, upside: t.upside_per, sentiment: c.sentiment, buy_pct: c.buy_per, analysts: c.num_analysts, cap: b.market_cap }; }); } });
});

['m_gainers', 'm_losers', 'm_52high', 'm_active', 'm_upper'].forEach((id) => {
  dash.loader(id, { description: 'Market movers list: price, change, volume, 52-week range and circuit limits.',
    fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
      return (a.stocks || []).map((s) => ({ symbol: s.symbol, name: s.name, key: s.ind_key, price: s.price, chg_pct: s.change_pct, prev: s.previous_close, day_low: s.day_low, day_high: s.day_high, volume: s.volume, mcap_cr: s.mcap_cr, w52_high: s['52_week_high'], w52_low: s['52_week_low'], circ_up: s.circuit_upper_limit, circ_lo: s.circuit_lower_limit, sector: s.sector, cap: s.market_cap_category })); } });
});

dash.loader('candles', { description: 'Candles for the chosen instrument and timeframe.',
  fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    return (a.candles || []).map((c) => ({ t: c.datetime_ist, o: c.open, h: c.high, l: c.low, c: c.close, v: c.volume })); } });

dash.loader('crypto_live', { description: 'Live global dollar prices from CoinGecko, one row per coin.',
  fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    return (a.coins || []).map((c) => ({ symbol: String(c.symbol || '').toUpperCase(), name: c.name, price_usd: c.currentPrice, chg_24h_pct: c.priceChangePercentage24h, market_cap: c.marketCap, volume_24h: c.totalVolume, rank: c.marketCapRank, spark: JSON.stringify((c.sparkline7d || []).map((x) => Math.round(x * 100) / 100)) })); } });

dash.loader('mf_ideas', { description: 'Top-ranked mutual funds in three long-term categories, from INDmoney.',
  fn: ({ answer }) => { const a = typeof answer === 'string' ? JSON.parse(answer) : answer;
    return (a.data || []).map((f) => ({ name: f.name, category: f.category, rank: f.ind_ranking && f.ind_ranking.rank, ret_1y: f.return_1yr, ret_3y: f.return_3yr, ret_5y: f.return_5yr, expense: f.expense_ratio, risk: f.risk, nav: f.nav, aum: f.aum, min_sip: f.min_sip, rating: f.rating })); } });

/* ---------- calcs ---------- */
dash.calc('alloc_rows', { inputs: ['snapshot'], title: 'Allocation by asset class', description: 'Each asset class as a share of assets.',
  fn: (snapshot) => { const lab = { GOLD: 'Gold', SILVER: 'Silver', MF: 'Mutual funds', SA: 'Savings (liquid)', CRYPTO: 'Crypto' };
    const rows = snapshot.filter((r) => r.kind === 'asset' && r.current > 0); const tot = rows.reduce((s, r) => s + r.current, 0);
    return rows.map((r) => ({ name: r.name, label: lab[r.name] || r.name, value: r.current, share: tot ? (r.current / tot) * 100 : 0 })); } });

dash.calc('metals_rows', { inputs: ['gold_rows', 'silver_rows'], title: 'Gold and silver lines', description: 'Gold and silver holdings in one list.',
  fn: (gold, silver) => gold.concat(silver).map((r) => ({ key: r.metal + ' ' + r.name, ...r })) });

dash.calc('metals_est', { inputs: ['snapshot', 'comm_live'], title: 'Estimated metals move today', description: 'Your gold and silver value times today\'s MCX futures change. An estimate: your holdings track spot, not futures.',
  fn: (snapshot, comm) => { const cur = (n) => (snapshot.find((r) => r.kind === 'asset' && r.name === n) || {}).current || 0;
    const fut = (re) => comm.find((r) => re.test(r.name || '')) || {}; const g = fut(/^GOLD /i), s = fut(/^SILVER/i);
    const rows = [{ metal: 'Gold', held: cur('GOLD'), fut_chg_pct: g.chg_pct ?? null, est_move: g.chg_pct == null ? null : (cur('GOLD') * g.chg_pct) / 100 },
      { metal: 'Silver', held: cur('SILVER'), fut_chg_pct: s.chg_pct ?? null, est_move: s.chg_pct == null ? null : (cur('SILVER') * s.chg_pct) / 100 }];
    rows.push({ metal: 'Both', held: rows[0].held + rows[1].held, fut_chg_pct: null, est_move: (rows[0].est_move || 0) + (rows[1].est_move || 0) }); return rows; } });

dash.calc('paper_stats', { inputs: ['paper_ledger', 'paper_equity', 'desk_rules'], title: 'Paper desk statistics and real-money gate', description: 'Closed paper trades, the chance their true average is above zero, drawdown, and each gate test.',
  fn: (ledger, equity, rules) => { const rule = (k) => (rules.find((r) => r.key === k) || {}).value; const done = ledger.filter((r) => ['WIN', 'LOSS', 'TIME STOP'].includes(r.status));
    const R = done.map((r) => Number(r.r_mult)); const n = R.length; const mean = n ? R.reduce((a, b) => a + b, 0) / n : 0;
    const sd = n > 1 ? Math.sqrt(R.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0; const t = n > 1 && sd > 0 ? mean / (sd / Math.sqrt(n)) : 0;
    const ncdf = (x) => { const k = 1 / (1 + 0.2316419 * Math.abs(x)); const d = 0.3989423 * Math.exp(-x * x / 2); const p = d * k * (0.3193815 + k * (-0.3565638 + k * (1.781478 + k * (-1.821256 + k * 1.330274)))); return x > 0 ? 1 - p : p; };
    const conf = n > 1 && sd > 0 ? ncdf(t) * 100 : 0; let peak = 0, dd = 0; equity.forEach((e) => { peak = Math.max(peak, e.equity); if (peak) dd = Math.max(dd, (1 - e.equity / peak) * 100); });
    const half = Math.floor(n / 2); const h1 = R.slice(0, half), h2 = R.slice(half); const avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    const last = equity.length ? equity[equity.length - 1].equity : rule('paper_start'); const start = rule('paper_start');
    const need = { trades: rule('gate_trades'), conf: rule('gate_conf'), dd: rule('gate_dd') };
    const tests = { trades_ok: n >= need.trades, conf_ok: conf >= need.conf, dd_ok: dd <= need.dd && n > 0, halves_ok: n >= 4 && avg(h1) > 0 && avg(h2) > 0 };
    return [{ trades: n, wins: R.filter((r) => r > 0).length, win_rate: n ? (R.filter((r) => r > 0).length / n) * 100 : 0, avg_r: mean, t_stat: t, confidence: conf, drawdown: dd, equity: last, start, pnl: last - start, pnl_pct: start ? ((last - start) / start) * 100 : 0, need_trades: need.trades, need_conf: need.conf, need_dd: need.dd, ...tests,
      open_positions: ledger.filter((r) => r.status === 'OPEN').length, pending: ledger.filter((r) => r.status === 'PENDING').length, ready: Object.values(tests).every(Boolean) }]; } });

dash.calc('strategy_board', { inputs: ['paper_ledger', 'strategies_eq', 'strategies_macro', 'desk_rules'], title: 'Strategy league', description: 'Each strategy judged on its own closed paper trades: win rate, average R, the chance its true average is above zero, and whether it has earned real money.',
  fn: (ledger, eq, macro, rules) => { const rule = (k) => (rules.find((r) => r.key === k) || {}).value; const names = [];
    const add = (n) => { if (n && !names.includes(n)) names.push(n); }; ledger.forEach((r) => add(r.strategy)); eq.forEach((s) => add(s.strategy));
    const ncdf = (x) => { const k = 1 / (1 + 0.2316419 * Math.abs(x)); const d = 0.3989423 * Math.exp(-x * x / 2); const p = d * k * (0.3193815 + k * (-0.3565638 + k * (1.781478 + k * (-1.821256 + k * 1.330274)))); return x > 0 ? 1 - p : p; };
    const rows = names.map((name) => { const mine = ledger.filter((r) => r.strategy === name); const R = mine.filter((r) => ['WIN', 'LOSS', 'TIME STOP'].includes(r.status)).map((r) => Number(r.r_mult));
      const n = R.length, mean = n ? R.reduce((a, b) => a + b, 0) / n : 0, sd = n > 1 ? Math.sqrt(R.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0;
      const conf = n > 1 && sd > 0 ? ncdf(mean / (sd / Math.sqrt(n))) * 100 : 0; const bt = eq.find((s) => s.strategy === name) || macro.find((s) => s.strategy === name);
      return { strategy: name, closed: n, open: mine.filter((r) => r.status === 'OPEN' || r.status === 'PENDING').length, win_rate: n ? (R.filter((x) => x > 0).length / n) * 100 : 0, avg_r: mean, confidence: conf,
        pnl: mine.reduce((s, r) => s + (Number(r.pnl_rs) || 0) + (r.status === 'OPEN' ? Number(r.unrealized_rs) || 0 : 0), 0), backtest: bt ? bt.status : '', need_trades: rule('gate_trades'), need_conf: rule('gate_conf'),
        ready: n >= rule('gate_trades') && conf >= rule('gate_conf') && mean > 0 }; });
    rows.sort((a, b) => b.confidence - a.confidence || b.avg_r - a.avg_r || b.closed - a.closed); rows.forEach((r, i) => { r.rank = i + 1; }); return rows; } });

dash.calc('trade_book', { inputs: ['paper_ledger', 'paper_live'], title: 'Trade book', description: 'Every paper trade the desks booked, newest first, with its strategy, where the price stands between stop and target, and its profit or loss. Open trades use the live price when the stock is on a live list, else the last close.',
  fn: (ledger, live) => { const latest = ledger.reduce((m, r) => (String(r.signal_date) > m ? String(r.signal_date) : m), ''); const lv = {}; live.forEach((r) => { lv[r.id] = r.live; });
    return ledger.map((r) => { const entry = Number(r.entry), qty = r.qty === '' || r.qty == null ? null : Number(r.qty); const closed = ['WIN', 'LOSS', 'TIME STOP'].includes(r.status); const open = r.status === 'OPEN';
      const last = closed ? Number(r.exit) : open ? (lv[r.id] != null ? lv[r.id] : r.last_close != null ? Number(r.last_close) : null) : null;
      const pnl = closed ? Number(r.pnl_rs) || 0 : open ? (lv[r.id] != null && qty !== null ? Math.round(qty * (lv[r.id] - entry) * 100) / 100 : Number(r.unrealized_rs) || 0) : 0;
      return { id: r.id, booked: String(r.signal_date), today: String(r.signal_date) === latest ? 'yes' : 'no', strategy: r.strategy, market: r.market, symbol: r.symbol, status: r.status, entry, stop: Number(r.stop),
        target: r.target === '' || r.target == null ? null : Number(r.target), qty, last, move_pct: last !== null && entry ? Math.round((last / entry - 1) * 1000) / 10 : null, pnl,
        deployed: (open || closed) && qty !== null ? Math.round(qty * entry) : 0, r_mult: closed || open ? Number(r.r_mult) || 0 : null, note: r.note || '' }; }).sort((a, b) => b.id - a.id); } });

dash.calc('strategy_pnl', { inputs: ['trade_book'], title: 'Profit and loss by strategy', description: 'Per strategy: trades booked on the latest day, pending, open and closed counts, wins, rupees deployed, profit or loss, and that profit as a percent of the rupees deployed.',
  fn: (book) => { const by = {}; book.forEach((t) => { const s = by[t.strategy] || (by[t.strategy] = { strategy: t.strategy, booked_today: 0, pending: 0, open: 0, closed: 0, wins: 0, skipped: 0, deployed: 0, pnl: 0 });
      if (t.today === 'yes') s.booked_today += 1; if (t.status === 'PENDING') s.pending += 1; else if (t.status === 'OPEN') s.open += 1; else if (t.status === 'SKIPPED') s.skipped += 1; else { s.closed += 1; if (t.pnl > 0) s.wins += 1; }
      s.deployed += t.deployed; s.pnl += t.pnl; });
    return Object.values(by).map((s) => ({ ...s, pnl: Math.round(s.pnl * 100) / 100, return_pct: s.deployed ? Math.round((s.pnl / s.deployed) * 10000) / 100 : null })).sort((a, b) => b.pnl - a.pnl); } });

dash.calc('kpi_rows', { inputs: ['snapshot', 'mf_holdings', 'metals_est', 'paper_stats'], title: 'Headline figures', description: 'The six figures at the top of the Command tab.',
  fn: (snap, mf, est, paper) => { const get = (k, n) => snap.find((r) => r.kind === k && r.name === n) || {}; const net = get('total', 'Net worth').current, as = get('total', 'Assets');
    const gold = get('asset', 'GOLD').current || 0, silver = get('asset', 'SILVER').current || 0, sa = get('asset', 'SA').current;
    const mfDay = mf.reduce((s, r) => s + (r.day_change || 0), 0), mfVal = mf.reduce((s, r) => s + (r.value || 0), 0);
    const metals = gold + silver; const p = paper[0] || {}; const e = est.find((r) => r.metal === 'Both') || {};
    return [
      { key: 'net', label: 'Net worth', value: net, delta: as.current - as.invested, delta_pct: as.invested ? ((as.current - as.invested) / as.invested) * 100 : null, note: 'since invested' },
      { key: 'mfday', label: 'Mutual funds today', value: mfDay, delta: mfVal, delta_pct: mfVal - mfDay ? (mfDay / (mfVal - mfDay)) * 100 : null, note: 'fund value' },
      { key: 'metals', label: 'Gold and silver', value: metals, delta: e.est_move, delta_pct: as.current ? (metals / as.current) * 100 : null, note: 'of assets · est. move today' },
      { key: 'liquid', label: 'Liquid savings', value: sa, delta: null, delta_pct: as.current ? (sa / as.current) * 100 : null, note: 'of assets' },
      { key: 'paper', label: 'Paper desk equity', value: p.equity, delta: p.pnl, delta_pct: p.pnl_pct, note: 'since start' },
      { key: 'gate', label: 'Paper trades closed', value: p.trades, delta: p.need_trades, delta_pct: p.confidence, note: 'needed · confidence %' }]; } });

dash.calc('alerts_live', { inputs: ['m_gainers', 'm_losers', 'm_52high', 'm_upper', 'm_active'], title: 'Live signals from the movers lists', description: 'Rules applied to today\'s gainers, losers, 52-week highs, upper circuits and most active stocks.',
  fn: (gain, lose, high, upper, active) => { const out = []; const seen = new Set(); const cr = (s) => ((s.price || 0) * (s.volume || 0)) / 1e7;
    const push = (kind, s, detail, sev) => { const id = kind + s.symbol; if (seen.has(id)) return; seen.add(id); const hp = s.prev ? ((s.day_high / s.prev) - 1) * 100 : null; out.push({ id, kind, symbol: s.symbol, price: s.price, chg_pct: s.chg_pct, high_pct: hp, traded_cr: cr(s), detail, sev }); };
    high.forEach((s) => { if (s.w52_high && s.price >= 0.995 * s.w52_high && cr(s) >= 10) push('52-week high', s, 'Trading at its 52-week high on strong turnover. This is the setup the breakout strategy looks for.', 'up'); });
    gain.forEach((s) => { const hp = s.prev ? ((s.day_high / s.prev) - 1) * 100 : 0; if (s.circ_up && s.price >= 0.995 * s.circ_up) push('Upper circuit', s, 'Stuck at its upper circuit: buyers cannot get filled. Do not chase.', 'hi');
      else if (s.chg_pct >= 5 && cr(s) >= 10) { if (hp >= 5 && (s.day_high - s.price) / s.day_high >= 0.03) push('Fading', s, 'Up strongly but already 3% or more below the day high. Late buyers are being sold into.', 'hi'); else push('Momentum', s, 'Up 5% or more on turnover above Rs 10 crore. Most of a spike is usually made by the time it shows here.', 'up'); } });
    lose.forEach((s) => { if (s.chg_pct <= -5 && cr(s) >= 10) push('Heavy selling', s, 'Down 5% or more on heavy turnover. Check the news before touching it.', 'dn'); });
    active.forEach((s) => { if (Math.abs(s.chg_pct) >= 3 && cr(s) >= 100) push('High turnover', s, 'Among the most traded names with a move of 3% or more.', s.chg_pct >= 0 ? 'up' : 'dn'); });
    return out.sort((a, b) => b.traded_cr - a.traded_cr).slice(0, 14); } });

dash.calc('plan_join', { inputs: ['plan_today', 'watch_live'], title: 'Today\'s plan with live prices', description: 'The pre-market watchlist joined to live quotes where the stock is on the live list.',
  fn: (plan, live) => plan.map((p) => { const l = live.find((x) => x.symbol === p.symbol) || {}; return { ...p, live: l.live ?? null, chg_pct: l.chg_pct ?? null, target: l.target ?? null, upside: l.upside ?? null }; }) });

dash.calc('ticket_view', { inputs: ['paper_ledger', 'watch_live', 'desk_rules', 'paper_stats'], title: 'Pending paper tickets', description: 'Each pending or open paper order with its live price and the size it would take today.',
  fn: (ledger, live, rules, paper) => { const rule = (k) => (rules.find((r) => r.key === k) || {}).value; const eq = (paper[0] || {}).equity || rule('paper_start');
    return ledger.filter((r) => ['PENDING', 'OPEN'].includes(r.status)).map((r) => { const l = live.find((x) => x.symbol === r.symbol) || {};
      const px = l.live ?? null; const entry = r.status === 'PENDING' && px ? px : r.entry; const stopPct = rule('stop_pct'), tgtPct = rule('target_pct');
      const stop = entry * (1 - stopPct / 100), target = entry * (1 + tgtPct / 100); const risk = (eq * rule('risk_caution')) / 100; const qty = Math.floor(risk / (entry - stop));
      return { ...r, live: px, live_time: l.time ?? null, ref_gap_pct: px && r.entry ? ((px / r.entry) - 1) * 100 : null, t_entry: entry, t_stop: stop, t_target: target, t_qty: qty, t_risk: qty * (entry - stop), t_value: qty * entry, rr: tgtPct / stopPct }; }); } });
