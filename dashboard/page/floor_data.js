/* Floor pipeline. Every limit lives in floor_rules, and every sentence a desk says is a cell of
   floor_rows, floor_stats or floor_side. These are fixed rules on live prices, not predictions. */

dash.calc('floor_rules', {
  inputs: ['desk_rules'],
  title: 'Floor limits and score parts',
  description: 'The eight limits each name is checked against, the points each part of the screen score can give, and the paper sizing caps. Set by the desk, not fitted to history.',
  fn: (deskRules) => {
    const R = (k, d) => { const r = deskRules.find((x) => x.key === k); return r ? Number(r.value) : d; };
    const L = { traded: 10, price: 20, circuit: 0.5, chase: 8, green: 0, dayhigh: 3, yearhigh: 3, vix: 20 };
    const P = { f1: 30, f2: 25, f3: 15, f4: 20, f5: 10 };
    const row = (n, kind, key, limit, show) => ({ n, kind, key, limit, show });
    return [
      row(1, 'rule', 'traded', L.traded, `₹${L.traded} cr or more`), row(2, 'rule', 'price', L.price, `₹${L.price} or more`),
      row(3, 'rule', 'circuit', L.circuit, 'not locked'), row(4, 'rule', 'chase', L.chase, `up ${L.chase}% at most`),
      row(5, 'rule', 'green', L.green, 'not down'), row(6, 'rule', 'dayhigh', L.dayhigh, `within ${L.dayhigh}%`),
      row(7, 'rule', 'yearhigh', L.yearhigh, `within ${L.yearhigh}%`), row(8, 'rule', 'vix', L.vix, `${L.vix} or below`),
      ...Object.keys(P).map((k, i) => row(11 + i, 'part', k, P[k], `of ${P[k]}`)),
      row(21, 'bar', 'setup', 70, 'setup'), row(22, 'bar', 'watch', 50, 'watch'),
      row(31, 'size', 'caution', 16, 'India VIX from which size is halved'), row(32, 'size', 'pos_cap', 30, '% of the account in one position, at most'),
      row(33, 'size', 'open_risk', 4, '% of the account at risk in total, at most'), row(34, 'size', 'max_pos', 4, 'positions at once, at most'),
      row(35, 'size', 'risk_normal', R('risk_normal', 1), '% of the account risked on a trade'), row(36, 'size', 'risk_caution', R('risk_caution', 0.5), '% risked on a trade in a caution market'),
      row(37, 'size', 'stop_pct', R('stop_pct', 5), '% stop under the entry'), row(38, 'size', 'reward_r', 2, 'times the risk: a marker on the ladder, not a prediction'),
      row(39, 'size', 'paper_start', R('paper_start', 0), 'rupees the paper account started with')];
  } });

dash.calc('floor_rows', {
  inputs: ['m_gainers', 'm_52high', 'm_active', 'watch_live', 'indices', 'floor_rules', 'paper_stats', 'paper_ledger', 'alerts_log', 'strategies_eq'],
  title: 'Floor pipeline, name by name',
  description: 'Top gainers, 52-week highs, most active and watchlist names, each put through 8 hard rules, a 0 to 100 screen score and paper position sizing. A ranking for attention, not a forecast, and not backtested.',
  fn: (gainers, highs, active, watch, indices, limits, paper, ledger, alerts, strategies) => {
    const L = (k) => { const r = limits.find((x) => x.key === k); return r ? Number(r.limit) : NaN; };
    const inr = (v, d = 0) => '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
    const pc = (v, d = 1) => (v > 0 ? '+' : '') + Number(v).toFixed(d) + '%';
    const clamp = (x) => Math.max(0, Math.min(1, x));
    const vixRow = indices.find((x) => /vix/i.test(x.name || ''));
    const vix = vixRow && vixRow.live != null ? Number(vixRow.live) : null;
    const equity = (paper[0] && Number(paper[0].equity)) || L('paper_start');
    const half = vix !== null && vix >= L('caution');
    const riskPct = half ? L('risk_caution') : L('risk_normal');
    const stopPct = L('stop_pct'), rewardR = L('reward_r');
    const openRisk = ledger.filter((r) => r.status === 'OPEN').reduce((s, r) => s + (Number(r.risk_rs) || 0), 0);
    const busy = ledger.filter((r) => r.status === 'OPEN' || r.status === 'PENDING').length;
    const bo = strategies.find((s) => s.strategy === 'breakout_52w');
    const winPct = bo ? Math.round(bo.win_rate * 100) : null;
    const sectorN = {}; gainers.forEach((g) => { if (g.sector) sectorN[g.sector] = (sectorN[g.sector] || 0) + 1; });

    /* One row per name, taking turns between the lists so the flow is mixed. */
    const by = new Map(); const order = [];
    const take = (s, tag) => {
      if (!s || !s.symbol) return; const k = String(s.symbol); let o = by.get(k);
      if (!o) { o = { symbol: k, tags: [] }; by.set(k, o); order.push(k); }
      o.tags.push(tag); if (!o.key && s.key) o.key = s.key;
      if (tag === 'your watchlist') {
        o.name = o.name || s.name;
        if (o.price == null) Object.assign(o, { price: s.live, chg_pct: s.chg_pct, day_high: s.high, volume: s.volume, w52_high: s.w52_high, circ_up: s.upper, cap: s.cap });
        Object.assign(o, { target: s.target, upside: s.upside, buy_pct: s.buy_pct, analysts: s.analysts });
      } else if (!o.src) {
        Object.assign(o, { name: s.name, price: s.price, chg_pct: s.chg_pct, day_high: s.day_high, volume: s.volume, w52_high: s.w52_high, circ_up: s.circ_up, cap: s.cap || o.cap, sector: s.sector, src: tag });
      }
    };
    const lists = [[highs, '52-week highs'], [gainers, 'top gainers'], [active, 'most active'], [watch, 'your watchlist']];
    const longest = Math.max(0, ...lists.map((l) => l[0].length));
    for (let i = 0; i < longest; i++) lists.forEach(([l, tag]) => take(l[i], tag));

    return order.map((k, idx) => {
      const o = by.get(k); const price = Number(o.price) || 0; const chg = Number(o.chg_pct) || 0;
      const traded = price * (Number(o.volume) || 0) / 1e7;
      const offHigh = o.w52_high ? Math.max(0, (o.w52_high - price) / o.w52_high * 100) : null;
      const offDay = o.day_high ? Math.max(0, (o.day_high - price) / o.day_high * 100) : null;
      const cap = (String(o.cap || '').match(/large|mid|small/i) || [''])[0].toLowerCase();
      const capName = cap ? cap.charAt(0).toUpperCase() + cap.slice(1) + ' cap' : 'Company size not given';
      const atCirc = o.circ_up ? price >= (1 - L('circuit') / 100) * o.circ_up : false;
      const cr = (v) => inr(v, v < 100 ? 1 : 0) + ' cr';
      /* BSE-only names come with a number for a symbol: say the company's name instead. */
      const tick = /^\d+$/.test(o.symbol) ? String(o.name || o.symbol).replace(/\s+(Ltd|Limited)\.?$/i, '') : o.symbol;
      /* The 8 hard rules, in order. Each: [passes, measured value, reason when it fails]. */
      const checks = [
        [traded >= L('traded'), cr(traded), `only ${cr(traded)} traded, too thin to get out of`],
        [price >= L('price'), inr(price, 2), `priced at ${inr(price, 2)}, penny-stock territory`],
        [!atCirc, atCirc ? 'locked' : 'free', 'locked at its upper circuit, so buyers cannot get filled'],
        [chg <= L('chase'), pc(chg), `already up ${chg.toFixed(1)}% today, and buying that is chasing`],
        [chg >= L('green'), pc(chg), `down ${Math.abs(chg).toFixed(1)}% today`],
        [offDay !== null && offDay <= L('dayhigh'), offDay === null ? 'no data' : offDay.toFixed(1) + '% off', offDay === null ? 'no day range on the feed' : `fading, ${offDay.toFixed(1)}% below the day's high`],
        [offHigh !== null && offHigh <= L('yearhigh'), offHigh === null ? 'no data' : offHigh.toFixed(1) + '% below', offHigh === null ? 'no 52-week high on the feed' : `${offHigh.toFixed(1)}% below its 52-week high, so not a breakout`],
        [vix !== null && vix <= L('vix'), vix === null ? 'no data' : 'VIX ' + vix.toFixed(1), vix === null ? 'India VIX is unavailable, so the desk stays in cash' : `India VIX ${vix.toFixed(1)} is above ${L('vix')}, cash only`]];
      const failAt = checks.findIndex((c) => !c[0]);
      const row = { order: idx + 1, symbol: o.symbol, label: tick, name: o.name || o.symbol, lists: o.tags.join(', '), src: o.src || 'your watchlist', price, chg_pct: chg,
        traded_cr: Math.round(traded * 10) / 10, cap: capName, sector: o.sector || '', failed: failAt + 1, fail_reason: failAt >= 0 ? checks[failAt][2] : '' };
      checks.forEach((c, i) => { const reached = failAt < 0 || i <= failAt; row['r' + (i + 1)] = reached ? (c[0] ? 'pass' : 'fail') : 'skip'; row['v' + (i + 1)] = reached ? c[1] : ''; });

      /* Screen score for names that cleared every rule: six parts that add to 100. */
      const share = [
        offHigh === null ? 0 : clamp(1 - offHigh / L('yearhigh')),
        offDay === null ? 0 : clamp(1 - offDay / L('dayhigh')),
        chg < 1.5 ? 0.4 + 0.4 * chg / 1.5 : chg <= 5 ? 1 : clamp(1 - 0.22 * (chg - 5)),
        traded > 0 ? clamp(Math.log10(traded / L('traded')) / 2) : 0,
        cap === 'large' ? 1 : cap === 'mid' ? 0.7 : cap === 'small' ? 0.4 : 0.5];
      const parts = share.map((x, i) => Math.round(Math.max(0, x) * L('f' + (i + 1))));
      const score = failAt >= 0 ? null : parts.reduce((a, b) => a + b, 0);
      parts.forEach((v, i) => { row['f' + (i + 1)] = failAt >= 0 ? null : v; });
      row.score = score;
      row.verdict = failAt >= 0 ? 'KILLED' : score >= L('setup') ? 'SETUP' : score >= L('watch') ? 'WATCH' : 'PASS';

      row.key = o.key || ''; row.horizon = failAt >= 0 ? '' : score >= 81 ? 'Day' : score >= 61 ? 'Week' : score >= 50 ? 'Month' : '';
      /* What each desk says about it. */
      const secN = o.sector ? sectorN[o.sector] || 0 : 0;
      row.crowd_txt = `${tick}: ${cr(traded)} traded today.` + (secN >= 3 ? ` ${o.sector} has ${secN} of the top gainers, so the move is not alone.` : ' No cluster of gainers in its sector.');
      row.fund_txt = `${capName}` + (o.sector ? `, ${o.sector}` : '') + '.' + (score !== null ? ` Screen score ${score} of 100: ${parts[0]} for the 52-week high, ${parts[1]} for holding gains, ${parts[3]} for money traded.` : '');
      const al = alerts.find((a) => a.symbol === o.symbol);
      row.echo_txt = al ? `${tick} filed "${String(al.type).toLowerCase()}" at ${al.time}. The price was ${pc(al.at_filing)} at the filing and moved ${pc(al.since_filing)} after it.` : `No filing from ${tick} in the last alert log. Nothing to read into.`;
      row.bull = `${tick} is ${offHigh !== null && offHigh < 0.3 ? 'at its 52-week high' : (offHigh || 0).toFixed(1) + '% below its 52-week high'}, ${pc(chg)} today on ${cr(traded)}, and within ${(offDay || 0).toFixed(1)}% of the day's high.`;
      row.bear = chg >= 5 ? `It is already ${pc(chg)} today. Late entries on big up days often give the gain back.`
          : cap === 'small' ? 'Small cap: the exit gets thin when a breakout fails.'
            : winPct !== null ? `Only ${winPct}% of breakout trades won in the 5-year test. Most breakouts fail and the stop does the work.` : 'Most breakouts fail and the stop does the work.';

      /* Warden's paper sizing for anything that reaches the watch bar. */
      const per = price * stopPct / 100; let qty = 0, blocked = ''; const sized = failAt < 0 && score >= L('watch');
      if (sized) {
        const budget = Math.min(equity * riskPct / 100, Math.max(0, equity * L('open_risk') / 100 - openRisk));
        qty = per > 0 ? Math.floor(budget / per) : 0; qty = Math.min(qty, Math.floor(equity * L('pos_cap') / 100 / price));
        if (busy >= L('max_pos')) { blocked = `${L('max_pos')} paper positions are already open or pending`; qty = 0; }
        else if (qty < 1) blocked = price > equity * L('pos_cap') / 100 ? `one share costs ${inr(price, 0)}, more than ${L('pos_cap')}% of the paper account` : `one share risks ${inr(per, 0)}, more than the ${inr(budget, 0)} risk budget`;
      }
      row.qty = qty; row.value = Math.round(qty * price); row.risk_rs = Math.round(qty * per); row.blocked = blocked;
      row.stop = Math.round(price * (1 - stopPct / 100) * 100) / 100; row.target_px = Math.round((price + rewardR * price * stopPct / 100) * 100) / 100;
      row.size_note = !sized ? '' : blocked ? `${tick} is blocked: ${blocked}.`
        : `${tick} on paper: ${qty} shares, ${inr(row.value)}, risking ${inr(row.risk_rs)} down to a stop at ${inr(row.stop, 2)}.` + (half ? ` Half size because India VIX is ${vix.toFixed(1)}.` : '');
      row.chief_txt = row.verdict === 'SETUP' ? `${tick} scores ${score}: a setup. If it holds into the close, the morning research run reads its filings and results before anything goes on paper.` + (blocked ? ' Too big for the paper account, so watch only.' : '')
        : row.verdict === 'WATCH' ? `${tick} scores ${score}: on the watch board, under the ${L('setup')} needed for a setup.`
          : row.verdict === 'PASS' ? `${tick} scores ${score}: it cleared the rules but is too weak. Dropped.` : '';
      return row;
    });
  } });

dash.calc('floor_stats', {
  inputs: ['floor_rows', 'floor_rules', 'm_gainers', 'm_losers', 'm_upper', 'indices'],
  title: 'Floor totals',
  description: 'Totals for the prices now on the page: names seen, killed by a rule, setups, market breadth and the volatility regime, with the sentences the desks open each loop with.',
  fn: (rows, limits, gainers, losers, upper, indices) => {
    const L = (k) => { const r = limits.find((x) => x.key === k); return r ? Number(r.limit) : NaN; };
    const pc = (v, d = 1) => (v > 0 ? '+' : '') + Number(v).toFixed(d) + '%';
    const avg = (a, k) => (a.length ? Math.round(a.reduce((s, r) => s + (Number(r[k]) || 0), 0) / a.length * 10) / 10 : null);
    const surv = rows.filter((r) => !r.failed); const top = surv.slice().sort((a, b) => b.score - a.score);
    const vixRow = indices.find((x) => /vix/i.test(x.name || '')); const nifty = indices.find((x) => /nifty 50/i.test(x.name || ''));
    const vix = vixRow && vixRow.live != null ? Number(vixRow.live) : null;
    const eq = indices.filter((x) => !/vix/i.test(x.name || '')); const idxUp = eq.filter((x) => x.chg_pct > 0).length;
    const times = indices.map((x) => x.time).filter(Boolean).sort(); const quoteTime = times.length ? times[times.length - 1] : '';
    const sec = {}; gainers.forEach((g) => { if (g.sector) sec[g.sector] = (sec[g.sector] || 0) + 1; });
    const lead = Object.entries(sec).sort((a, b) => b[1] - a[1])[0];
    const why = {}; rows.filter((r) => r.failed).forEach((r) => { why[r.failed] = (why[r.failed] || 0) + 1; });
    const topKill = Object.entries(why).sort((a, b) => b[1] - a[1])[0];
    const smallN = gainers.filter((g) => /small/i.test(g.cap || '')).length; const avgGain = avg(gainers, 'chg_pct'), avgLoss = avg(losers, 'chg_pct');
    const regime = vix === null ? 'UNKNOWN' : vix > L('vix') ? 'CASH' : vix >= L('caution') ? 'CAUTION' : 'NORMAL';
    const tm = String(quoteTime).match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    const asOf = tm ? `${tm[4]}:${tm[5]} on ${Number(tm[3])} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(tm[2]) - 1]}` : 'an unknown time';
    return [{ seen: rows.length, killed: rows.length - surv.length, survivors: surv.length,
      setups: surv.filter((r) => r.verdict === 'SETUP').length, watch: surv.filter((r) => r.verdict === 'WATCH').length,
      top_symbol: top[0] ? top[0].symbol : '', top_score: top[0] ? top[0].score : null, board: top.slice(0, 3).map((r) => r.label + ' ' + r.score).join(', '),
      top_kill_rule: topKill ? Number(topKill[0]) : null, top_kill_n: topKill ? topKill[1] : 0,
      avg_gain: avgGain, avg_loss: avgLoss, gainers_n: gainers.length, small_n: smallN,
      lead_sector: lead ? lead[0] : '', lead_sector_n: lead ? lead[1] : 0, upper_n: upper.length,
      vix, vix_chg: vixRow ? vixRow.chg_pct : null, regime,
      nifty: nifty ? nifty.live : null, nifty_chg: nifty ? nifty.chg_pct : null, idx_up: idxUp, idx_n: eq.length, quote_time: quoteTime,
      scout_txt: rows.length ? `${rows.length} names are on the tape from INDmoney: top gainers, 52-week highs, most active and your watchlist. Prices as of ${asOf}.` : 'The INDmoney lists are empty right now, so there is nothing to check. Data Unverified.',
      regime_txt: vix === null ? 'India VIX is unavailable. Data Unverified, so no new paper positions.'
        : regime === 'CASH' ? `India VIX is ${vix.toFixed(1)}, above ${L('vix')}: cash regime. No new paper positions.`
          : regime === 'CAUTION' ? `India VIX is ${vix.toFixed(1)}: caution regime. Any new paper position takes half size.` : `India VIX is ${vix.toFixed(1)}: normal regime. Full paper size.`,
      breadth_txt: `${idxUp} of ${eq.length} indices are up` + (nifty && nifty.chg_pct != null ? `, Nifty 50 ${pc(nifty.chg_pct, 2)}` : '') + '.'
        + (gainers.length ? ` The top ${gainers.length} gainers average ${pc(avgGain)}` + (smallN ? `, ${smallN} of them small caps` : '') + '.' : '')
        + (lead && lead[1] >= 3 ? ` ${lead[0]} leads with ${lead[1]} of them.` : '') + (upper.length ? ` ${upper.length} stocks are locked at upper circuit, where nobody can buy.` : ''),
      kill_txt: topKill ? `Across the whole tape, rule ${topKill[0]} removes the most names: ${topKill[1]} of ${rows.length}.` : '' }];
  } });

dash.calc('floor_side', {
  inputs: ['crypto_quotes', 'macro_signals', 'alerts_log', 'paper_ledger', 'paper_stats', 'comm_live'],
  title: 'Side reports for the floor',
  description: 'One sentence each on crypto, breakout signals, MCX metals, the filing log and the paper book, as the desks say them between names.',
  fn: (crypto, signals, alerts, ledger, paper, mcx) => {
    const inr = (v, d = 0) => '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
    const pc = (v, d = 1) => (v > 0 ? '+' : '') + Number(v).toFixed(d) + '%';
    const out = [];
    if (crypto.length) {
      const prem = crypto.map((q) => q.premium_pct).filter((x) => x !== null && x !== undefined);
      const lone = crypto.filter((q) => q.verified !== 'yes').length;
      out.push({ key: 'crypto', agent: 'DATA', port: 'S4', state: 'CRYPTO', tone: 'info',
        text: `Crypto on CoinDCX, saved ${crypto[0].as_of_hm} IST: ` + crypto.map((q) => `${q.symbol} ${inr(q.price_inr)} (${pc(q.chg_24h_pct)} in 24 hours)`).join(', ') + '.'
          + (prem.length ? ` Rupee prices sit about ${(prem.reduce((a, b) => a + b, 0) / prem.length).toFixed(1)}% above the global dollar price.` : '')
          + (lone ? ` ${lone} of ${crypto.length} could not be cross-checked against Kraken: Data Unverified.` : ' All cross-checked against Kraken.') });
    }
    if (signals.length) {
      const yes = signals.filter((s) => s.entry_signal_today === 'YES');
      out.push({ key: 'breakouts', agent: 'TECH', port: 'S4', state: 'BREAKOUT', tone: yes.length ? 'bull' : 'info',
        text: `20-day breakout rule on ${signals.length} crypto and commodity markets at the ${signals[0].last_date} close: ` + (yes.length ? yes.map((s) => s.name).join(', ') + ' signalled. Paper orders only.' : 'no signal. Nothing to do.') });
    }
    const g = mcx.find((r) => /^GOLD /i.test(r.name || '')), s = mcx.find((r) => /^SILVER/i.test(r.name || ''));
    if (g && s && g.chg_pct != null && s.chg_pct != null) {
      out.push({ key: 'metals', agent: 'SENT', port: 'S2', state: 'METALS', tone: 'info', text: `MCX gold futures are ${pc(g.chg_pct, 2)} and silver ${pc(s.chg_pct, 2)} today. Gold and silver are the CEO's largest holdings.` });
    }
    if (alerts.length) {
      const before = alerts.filter((a) => /before/i.test(a.read || '')).length;
      out.push({ key: 'filings', agent: 'CALL', port: 'S3', state: 'FILINGS', tone: 'info', text: `The last filing log caught ${alerts.length} company filings. In ${before} of them the price had already moved before the filing appeared.` });
    }
    const p = paper[0];
    if (p) {
      out.push({ key: 'book', agent: 'LEDGER', port: 'S5', state: 'BOOK', tone: 'info', text: `Paper book: ${p.pending} pending, ${p.open_positions} open, ${p.trades} closed of the ${p.need_trades} needed. Paper equity ${inr(p.equity)}.` });
      out.push({ key: 'gate', agent: 'RISK', port: 'S5', state: 'GATE', tone: 'warn', text: p.ready ? 'All four real-money tests pass. Whether to use real money is still the CEO\'s decision.'
        : `The real-money gate is closed: confidence ${Number(p.confidence).toFixed(0)}% against the ${p.need_conf}% needed, and ${p.trades} of ${p.need_trades} paper trades.` });
    }
    const pend = ledger.filter((r) => r.status === 'PENDING');
    if (pend.length) out.push({ key: 'pending', agent: 'LEDGER', port: 'S5', state: 'PENDING', tone: 'info', text: `Pending paper order: ${pend.map((r) => r.symbol).join(', ')}. It fills at the next open if the gap from the signal close is within 3%.` });
    return out;
  } });

dash.calc('paper_live', {
  inputs: ['paper_ledger', 'watch_live', 'm_gainers', 'm_52high', 'm_active', 'm_losers'],
  title: 'Paper orders at live prices',
  description: 'Open and pending paper orders, marked to the latest INDmoney price where the stock is on one of the live lists.',
  fn: (ledger, watch, gainers, highs, active, losers) => {
    const px = {}; watch.forEach((r) => { if (r.symbol && r.live != null) px[r.symbol] = Number(r.live); });
    [gainers, highs, active, losers].forEach((list) => list.forEach((r) => { if (r.symbol && px[r.symbol] == null && r.price != null) px[r.symbol] = Number(r.price); }));
    return ledger.filter((r) => r.status === 'OPEN' || r.status === 'PENDING').map((r) => {
      const live = r.market === 'NSE' && px[r.symbol] != null ? px[r.symbol] : null; const entry = Number(r.entry); const open = r.status === 'OPEN';
      const qty = r.qty === '' || r.qty == null ? null : Number(r.qty);
      return { id: r.id, market: r.market, symbol: r.symbol, strategy: r.strategy, status: r.status, entry, stop: Number(r.stop),
        target: r.target === '' || r.target == null ? null : Number(r.target), qty, live,
        move_pct: live !== null && entry ? Math.round((live / entry - 1) * 1000) / 10 : null,
        unreal_rs: open && live !== null && qty !== null ? Math.round(qty * (live - entry)) : null };
    });
  } });
