/* Commodities and crypto tab. MCX futures come from INDmoney, crypto from Gemini. */
(function () {
  const { inr, num, pct, cls, el, tag, mk, need } = CD;
  const STATUS = { APPROVED: 'g', PROBATION: 'a', REJECTED: 'r' };
  const CSYMS = [['BTCUSD', 'Bitcoin'], ['ETHUSD', 'Ethereum'], ['SOLUSD', 'Solana']]; const CTFS = [['1day', 'Daily'], ['6hr', '6-hour'], ['1hr', 'Hourly']];
  const rangeBar = (live, lo, hi) => { const rb = el('div', 'rangebar'); const span = hi - lo; const i = el('i'); i.style.left = (span > 0 ? Math.min(100, Math.max(0, ((live - lo) / span) * 100)) : 50) + '%'; rb.appendChild(i); return rb; };

  dash.draw('lead_markets', (p) => { const r = need(p, ['metals_est']); if (!r) return; const rows = r[0]; const g = rows.find((x) => x.metal === 'Gold') || {}, s = rows.find((x) => x.metal === 'Silver') || {}, b = rows.find((x) => x.metal === 'Both') || {};
    p.replaceChildren(document.createTextNode('CEO, today MCX gold futures are '), mk(pct(g.fut_chg_pct), cls(g.fut_chg_pct), 'metals_est', 'fut_chg_pct', 'metal=Gold'), document.createTextNode(' and silver '), mk(pct(s.fut_chg_pct), cls(s.fut_chg_pct), 'metals_est', 'fut_chg_pct', 'metal=Silver'),
      document.createTextNode('. On your '), mk(inr(b.held), '', 'metals_est', 'held', 'metal=Both'), document.createTextNode(' of gold and silver that is an estimated '), mk((b.est_move > 0 ? '+' : '') + inr(b.est_move), cls(b.est_move), 'metals_est', 'est_move', 'metal=Both'),
      document.createTextNode(' move. Crypto and commodity strategies are on paper only until they pass the same gate as stocks.')); });

  dash.draw('mcx_cards', (box) => { const r = need(box, ['comm_live']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const c = el('div', 'mcx-card'); c.appendChild(el('div', 'sub', (x.name || '').replace(' Fut', ' futures'))); const v = el('div', 'num'); v.style.cssText = 'font-size:20px;font-weight:650;margin-top:2px';
      v.append(document.createTextNode('₹'), mk(num(x.live, x.live < 1000 ? 2 : 0), '', 'comm_live', 'live', 'key=' + x.key)); const d = el('div', 'num ' + cls(x.chg_pct)); d.append(mk(pct(x.chg_pct), '', 'comm_live', 'chg_pct', 'key=' + x.key), document.createTextNode(' today'));
      const lh = CD.lohi(num(x.low, x.low < 1000 ? 2 : 0), 'day range', num(x.high, x.high < 1000 ? 2 : 0));
      const meta = el('div', 'sub'); meta.style.marginTop = '6px'; meta.textContent = `Open interest ${num(x.oi, 0)} (${pct(x.oi_chg, 1)}) · expires ${String(x.expiry || '').slice(0, 10)}`; c.append(v, d, rangeBar(x.live, x.low, x.high), lh, meta); return c; })); });

  dash.draw('crypto_cards', (box) => { const r = need(box, ['crypto_all']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const c = el('div', 'crypto-card'); c.appendChild(el('div', 'sub', `${x.name} · ${x.symbol}`)); const v = el('div', 'num'); v.style.cssText = 'font-size:20px;font-weight:650;margin-top:2px';
      v.append(document.createTextNode('$'), mk(num(x.close, 2), '', 'crypto_all', 'close', 'symbol=' + x.symbol)); const d = el('div', 'num ' + cls(x.chg_pct)); d.append(mk(pct(x.chg_pct), '', 'crypto_all', 'chg_pct', 'symbol=' + x.symbol), document.createTextNode(' since the 24-hour open'));
      const sp = el('div'); sp.style.marginTop = '6px'; let arr = []; try { arr = JSON.parse(x.spark); } catch (e) { arr = []; } CD.spark(sp, arr, (x.chg_pct || 0) >= 0 ? CD.PAL.green : CD.PAL.red, 200, 40);
      const lh = CD.lohi('$' + num(x.low, 2), '24h range', '$' + num(x.high, 2)); c.append(v, d, sp, rangeBar(x.close, x.low, x.high), lh); return c; })); });

  dash.draw('sel_csym', (sel) => { sel.replaceChildren(...CSYMS.map(([k, n]) => new Option(n, k))); sel.value = dash.params().csym || 'BTCUSD'; sel.onchange = () => dash.setParams({ csym: sel.value }); });
  dash.draw('sel_ctf', (sel) => { sel.replaceChildren(...CTFS.map(([k, n]) => new Option(n, k))); sel.value = dash.params().ctf || '1day'; sel.onchange = () => dash.setParams({ ctf: sel.value }); });
  dash.draw('candle_crypto', (box) => { const r = need(box, ['crypto_candles']); if (!r) return; const rows = r[0].map((x) => ({ t: new Date(x.t), o: x.o, h: x.h, l: x.l, c: x.c, v: x.v })); CD.candleChart(box, rows, { iv: dash.params().ctf, label: 'Crypto candlestick chart with moving averages and a projection line' }); });

  dash.draw('metals_panel', (box) => { const r = need(box, ['metals_est']); if (!r) return; const t = el('table'); const tb = el('tbody');
    r[0].forEach((x) => { const tr = el('tr'); const a = el('td', '', x.metal); const b = el('td', 'num r', inr(x.held)); const c = el('td', 'num r ' + cls(x.fut_chg_pct), x.fut_chg_pct === null ? '' : pct(x.fut_chg_pct)); const d = el('td', 'num r ' + cls(x.est_move));
      d.appendChild(mk((x.est_move > 0 ? '+' : '') + inr(x.est_move), '', 'metals_est', 'est_move', 'metal=' + x.metal)); tr.append(a, b, c, d); tb.appendChild(tr); });
    const th = el('thead'); const hr = el('tr'); ['Metal', 'You hold', 'Futures', 'Est. move'].forEach((h, i) => hr.appendChild(el('th', i ? 'r' : '', h))); th.appendChild(hr); t.append(th, tb); box.replaceChildren(t); });

  dash.draw('macro_body', (body) => { const r = need(body, ['strategies_macro']); if (!r) return;
    CD.fillTable(body, r[0], [{ render: (d) => d.strategy }, { render: (d) => d.market }, { render: (d) => tag(d.status, STATUS[d.status] || '') }, { cls: 'num r', render: (d) => String(d.trades) }, { cls: 'num r', render: (d) => el('span', cls(d.avg_R), num(d.avg_R, 2)) },
      { cls: 'num r', render: (d) => pct(d.conf_cluster * 100, 0, false) }, { cls: 'num r', render: (d) => pct(d.conf_adjusted * 100, 0, false) }], ['strategy', 'market']); });

  dash.draw('macrosig_body', (body) => { const r = need(body, ['macro_signals']); if (!r) return;
    CD.fillTable(body, r[0], [{ render: (d) => d.symbol }, { render: (d) => d.name }, { render: (d) => tag(d.entry_signal_today === 'YES' ? 'BREAKOUT' : 'none', d.entry_signal_today === 'YES' ? 'g' : '') }, { cls: 'num r', render: (d) => num(d.last_close, 2) }, { cls: 'num r', render: (d) => pct(d.buy_hold_pa, 1, false) }], 'symbol'); });
})();
