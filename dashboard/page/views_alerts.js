/* Live alerts tab: chart explorer, rule-based signals from the movers lists, filing alerts. */
(function () {
  const { inr, num, pct, cls, el, tag, mk, need } = CD;
  const SYMS = [['INDI00012', 'NIFTY 50'], ['INDI00024', 'BANK NIFTY'], ['INDS02423', 'BEL'], ['INDS01104', 'KOTAKBANK'], ['INDS01992', 'HDFCBANK'], ['INDS04037', 'ETERNAL'],
    ['INDS00972', 'ITC'], ['INDS01995', 'ICICIBANK'], ['INDS01620', 'PNB'], ['INDCF5UV5U5G', 'Gold futures (MCX)'], ['INDCF4KF275C', 'Silver futures (MCX)'],
    ['INDCF66J0IAV', 'Crude oil futures (MCX)'], ['INDCFCC1F0V8', 'Natural gas futures (MCX)'], ['INDCF5MMIWLR', 'Copper futures (MCX)']];
  const VIEWS = [['5minute|1d', 'Today, 5-minute'], ['15minute|7d', 'Week, 15-minute'], ['60minute|14d', 'Two weeks, hourly'], ['1day|1y', 'Year, daily']];
  const toRows = (rows) => rows.map((r) => ({ t: new Date(String(r.t).replace(' ', 'T') + '+05:30'), o: r.o, h: r.h, l: r.l, c: r.c, v: r.v })).filter((r) => !Number.isNaN(r.t.getTime()));

  dash.draw('sel_sym', (sel) => { sel.replaceChildren(...SYMS.map(([k, n]) => new Option(n, k))); const cur = dash.params().sym || SYMS[0][0]; if (!SYMS.some((x) => x[0] === cur)) sel.appendChild(new Option(CD.pickName || 'Picked on the Algo tab', cur)); sel.value = cur; sel.onchange = () => dash.setParams({ sym: sel.value }); });
  dash.draw('sel_view', (sel) => { sel.replaceChildren(...VIEWS.map(([k, n]) => new Option(n, k))); const p = dash.params(); sel.value = (p.iv || '15minute') + '|' + (p.lb || '7d');
    sel.onchange = () => { const [iv, lb] = sel.value.split('|'); dash.setParams({ iv, lb }); }; });

  dash.draw('chart_stamp', (box) => { const d = dash.data('candles'); if (d.status !== 'ok' || !d.data.length) { box.textContent = '—'; return; }
    const last = d.data[d.data.length - 1]; box.className = 'chip live'; box.replaceChildren(el('i'), document.createTextNode(` ${d.data.length} candles · last ${String(last.t).slice(5, 16)} IST`)); });

  dash.draw('candle_main', (box) => { const r = need(box, ['candles']); if (!r) return; const rows = toRows(r[0]); CD.candleChart(box, rows, { iv: dash.params().iv, label: 'Candlestick chart with moving averages and a projection line' }); });

  dash.draw('tech_stats', (box) => { const r = need(box, ['candles']); if (!r) return; const rows = toRows(r[0]); box.replaceChildren(); if (rows.length < 20) return;
    const c = rows.map((x) => x.c); const rsi = CD.rsi(c), atr = CD.atr(rows), e20 = CD.ema(c, 20).pop(), e50 = CD.ema(c, 50).pop(); const fit = CD.linreg(c.slice(-40)); const last = c[c.length - 1];
    const add = (txt, kind) => box.appendChild(tag(txt, kind));
    add(`RSI ${num(rsi, 0)}: ${rsi >= 70 ? 'stretched up' : rsi <= 30 ? 'stretched down' : 'neutral'}`, rsi >= 70 ? 'a' : rsi <= 30 ? 'a' : '');
    add(`EMA 20 is ${e20 >= e50 ? 'above' : 'below'} EMA 50: ${e20 >= e50 ? 'uptrend bias' : 'downtrend bias'}`, e20 >= e50 ? 'g' : 'r');
    add(`Typical candle move ${num((atr / last) * 100, 2)}%`, 'b'); add(`Recent drift ${fit.b >= 0 ? 'up' : 'down'} ${num(Math.abs(fit.b / last) * 100, 3)}% per candle`, fit.b >= 0 ? 'g' : 'r');
    const hint = el('span', 'sub', 'Computed in the page from the candles above.'); box.appendChild(hint); });

  dash.draw('alerts_live_list', (box) => { const r = need(box, ['alerts_live']); if (!r) return; const rows = r[0];
    if (!rows.length) { box.replaceChildren(el('div', 'empty', 'No signals right now. They appear while the market is trading and a stock meets a rule.')); return; }
    box.replaceChildren(...rows.map((a) => { const row = el('div', 'row sev-' + a.sev); const left = el('div'); left.appendChild(tag(a.kind, a.sev === 'up' ? 'g' : a.sev === 'dn' ? 'r' : 'a'));
      const mid = el('div'); const h = el('div', 'h', a.symbol); const w = el('div', 'w', a.detail); mid.append(h, w);
      const right = el('div', 'num'); right.style.textAlign = 'right'; const p1 = el('div'); p1.appendChild(mk(num(a.price, 2), '', 'alerts_live', 'price', 'id=' + CD.enc(a.id))); const p2 = el('div', cls(a.chg_pct)); p2.appendChild(mk(pct(a.chg_pct), '', 'alerts_live', 'chg_pct', 'id=' + CD.enc(a.id)));
      const p3 = el('div', 'sub', 'traded ' + inr(a.traded_cr, 0) + ' cr'); right.append(p1, p2, p3); row.append(left, mid, right); return row; })); });

  dash.draw('alerts_date', (box) => { const d = dash.data('alerts_log'); box.textContent = d.status === 'ok' && d.data.length ? `${d.data.length} filings, with the price when each appeared` : '—'; });

  dash.draw('alerts_log_list', (box) => { const r = need(box, ['alerts_log']); if (!r) return;
    box.replaceChildren(...r[0].slice().reverse().map((a) => { const before = a.at_filing >= 5 || a.at_filing <= -5; const row = el('div', 'row' + (a.day_high >= 10 ? ' sev-hi' : '')); const left = el('div', 't', a.time);
      const mid = el('div'); const h = el('div', 'h'); h.append(document.createTextNode(a.symbol + ' '), tag(a.type, a.type === 'Results' ? 'v' : 'a')); const w = el('div', 'w', a.headline);
      const read = el('div', 'sub'); read.style.marginTop = '4px'; read.append(document.createTextNode(`${a.read} · at filing `), mk(pct(a.at_filing, 1), cls(a.at_filing), 'alerts_log', 'at_filing', 'symbol=' + CD.enc(a.symbol)),
        document.createTextNode(', since filing '), mk(pct(a.since_filing, 1), cls(a.since_filing), 'alerts_log', 'since_filing', 'symbol=' + CD.enc(a.symbol)), document.createTextNode(before ? ' · moved before the filing' : ''));
      mid.append(h, w, read); const right = el('div', 'num'); right.style.textAlign = 'right'; const d1 = el('div'); d1.appendChild(mk(pct(a.day_pct, 1), cls(a.day_pct), 'alerts_log', 'day_pct', 'symbol=' + CD.enc(a.symbol))); const d2 = el('div', 'sub');
      d2.append(document.createTextNode('high '), mk(pct(a.day_high, 1), '', 'alerts_log', 'day_high', 'symbol=' + CD.enc(a.symbol))); right.append(d1, d2); row.append(left, mid, right); return row; })); });

  const mover = (id) => (body) => { const r = need(body, [id]); if (!r) return;
    CD.fillTable(body, r[0].slice(0, 10), [{ render: (d) => d.symbol }, { cls: 'num r', render: (d) => num(d.price, 2) }, { cls: 'num r', render: (d) => el('span', cls(d.chg_pct), pct(d.chg_pct)) }, { cls: 'num r', render: (d) => num(d.volume / 100000, 1) + ' L' }], 'symbol'); };
  dash.draw('gainers_body', mover('m_gainers')); dash.draw('high_body', mover('m_52high')); dash.draw('active_body', mover('m_active'));
})();
