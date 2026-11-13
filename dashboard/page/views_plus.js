/* Pre-market world view, the strategy league and the chart inside the Algo tab. */
(function () {
  const { el, inr, num, pct, cls, mk, need, tag, PAL } = CD; const STATUS = { APPROVED: 'g', PROBATION: 'a', REJECTED: 'r' };

  dash.draw('world_cards', (box) => { const r = need(box, ['world_markets']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const c = el('div', 'mcx-card'), w = 'symbol=' + CD.enc(x.symbol); c.appendChild(el('div', 'sub', `${x.group} · ${x.name}`));
      const v = el('div', 'num'); v.style.cssText = 'font-size:18px;font-weight:650;margin-top:2px'; v.append(x.last === null ? 'Data Unverified' : mk(num(x.last, 2), '', 'world_markets', 'last', w));
      const d = el('div', 'num ' + cls(x.chg_pct)); if (x.chg_pct !== null) d.append(mk(pct(x.chg_pct), '', 'world_markets', 'chg_pct', w), ` · close of ${x.as_of}`);
      const sp = el('div'); sp.style.marginTop = '4px'; let arr = []; try { arr = JSON.parse(x.spark); } catch (e) { arr = []; } CD.spark(sp, arr, (x.chg_pct || 0) >= 0 ? PAL.green : PAL.red, 180, 30);
      c.append(v, d, sp, el('div', 'sub', x.why)); return c; })); });
  dash.draw('events_body', (body) => { const r = need(body, ['events_today']); if (!r) return;
    CD.fillTable(body, r[0], [{ cls: 'num', render: (d) => d.date.slice(5) }, { render: (d) => (d.watchlist === 'yes' ? tag(d.symbol, 'b') : d.symbol) }, { render: (d) => d.kind }, { cls: 'hs', render: (d) => d.detail }], ['date', 'symbol', 'kind']); });
  dash.draw('news_list', (box) => { const r = need(box, ['world_news']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const row = el('div', 'row'); row.style.gridTemplateColumns = 'auto 1fr'; const b = el('div'); b.append(el('div', 'h', x.title), el('div', 'w', `${x.publisher} · ${String(x.time).replace('T', ' ').slice(0, 16)} UTC`)); row.append(tag(x.market, 'v'), b); return row; }));
    if (!r[0].length) box.replaceChildren(el('div', 'empty', 'No headlines were saved this morning.')); });

  dash.draw('league_body', (body) => { const r = need(body, ['strategy_board']); if (!r) return;
    CD.fillTable(body, r[0], [{ cls: 'num', render: (d) => String(d.rank) }, { render: (d) => d.strategy }, { cls: 'num r', render: (d) => `${d.closed} / ${d.need_trades}` }, { cls: 'num r', render: (d) => String(d.open) },
      { cls: 'num r', render: (d) => (d.closed ? pct(d.win_rate, 0, false) : '—') }, { cls: 'num r', render: (d) => (d.closed ? el('span', cls(d.avg_r), num(d.avg_r, 2)) : '—') },
      { cls: 'num r', render: (d) => (d.closed > 1 ? pct(d.confidence, 0, false) : '—') }, { cls: 'num r', render: (d) => el('span', cls(d.pnl), inr(d.pnl)) },
      { cls: 'hs', render: (d) => (d.backtest ? tag(d.backtest, STATUS[d.backtest] || '') : '—') }, { render: (d) => tag(d.ready ? 'READY FOR REAL MONEY' : 'PAPER ONLY', d.ready ? 'g' : '') }], 'strategy'); });

  /* ---------- Today's trades ---------- */
  const ST = { OPEN: 'b', PENDING: 'a', WIN: 'g', LOSS: 'r', 'TIME STOP': '', SKIPPED: '' }; const COLS = { pending: PAL.amber, open: PAL.blue, wins: PAL.green, losses: PAL.red, skipped: PAL.dim };
  dash.draw('tr_lead', (p) => { const r = need(p, ['strategy_pnl', 'trade_book']); if (!r) return; const [sp, book] = r; const tot = sp.reduce((a, s) => a + s.pnl, 0), today = book.filter((t) => t.today === 'yes'), best = sp.find((s) => s.open + s.closed > 0);
    p.replaceChildren(`The desks have booked ${book.length} paper trades across ${sp.length} strategies, ${today.length} of them on ${today.length ? today[0].booked : 'the last run'}. ${book.filter((t) => t.status === 'OPEN').length} are open and ${book.filter((t) => t.status === 'PENDING').length} wait for the next open. Paper profit so far is `,
      el('b', cls(tot), (tot > 0 ? '+' : '') + inr(tot, 2)), best && best.pnl > 0 ? `. ${best.strategy} leads.` : best ? '. No strategy is in profit yet.' : '. No strategy has a filled trade yet.', ' A day or two of trades proves nothing: judge a strategy on dozens of closed trades.'); });
  dash.draw('tr_pnl', (box) => { const r = need(box, ['strategy_pnl']); if (!r) return; const rows = r[0]; box.replaceChildren(); if (!rows.length) { box.appendChild(el('div', 'empty', 'No trades booked yet.')); return; }
    const W = Math.max(280, box.clientWidth), rh = 34, H = rows.length * rh + 26, left = Math.min(170, W * 0.36), s = CD.svg(box, W, H, 'Paper profit or loss by strategy'); const m = Math.max(1, d3.max(rows, (d) => Math.abs(d.pnl)));
    const x = d3.scaleLinear([-m, m], [left, W - 70]); s.append('line').attr('x1', x(0)).attr('x2', x(0)).attr('y1', 4).attr('y2', H - 18).attr('stroke', '#24385a'); const tip = CD.tooltip(box);
    rows.forEach((d, i) => { const y = 8 + i * rh; s.append('text').attr('x', 2).attr('y', y + 14).style('fill', '#e8eef9').style('font-size', '11.5px').text(d.strategy);
      s.append('rect').attr('x', Math.min(x(0), x(d.pnl))).attr('width', Math.max(2, Math.abs(x(d.pnl) - x(0)))).attr('y', y).attr('height', 20).attr('rx', 4).attr('fill', d.pnl >= 0 ? PAL.green : PAL.red).attr('opacity', d.open + d.closed ? 0.9 : 0.25)
        .on('pointermove', (ev) => { const b = box.getBoundingClientRect(); tip.show(`${d.strategy}<br>P/L ${inr(d.pnl, 2)} on ${inr(d.deployed)} deployed<br>${d.open} open · ${d.closed} closed · ${d.pending} pending`, ev.clientX - b.left, ev.clientY - b.top); }).on('pointerleave', () => tip.hide());
      s.append('text').attr('x', (d.pnl >= 0 ? x(d.pnl) : x(0)) + 6).attr('y', y + 14).style('fill', d.pnl > 0 ? PAL.green : d.pnl < 0 ? PAL.red : PAL.mut).text(d.open + d.closed ? (d.pnl > 0 ? '+' : '') + inr(d.pnl, 0) + (d.return_pct !== null ? ` (${pct(d.return_pct, 2)})` : '') : 'not filled yet'); }); });
  dash.draw('tr_mix', (box) => { const r = need(box, ['strategy_pnl']); if (!r) return; const rows = r[0].map((d) => ({ ...d, losses: d.closed - d.wins })); box.replaceChildren(); if (!rows.length) { box.appendChild(el('div', 'empty', 'No trades booked yet.')); return; }
    const keys = ['pending', 'open', 'wins', 'losses', 'skipped']; const W = Math.max(280, box.clientWidth), rh = 34, H = rows.length * rh + 26, left = Math.min(170, W * 0.36), s = CD.svg(box, W, H, 'Trades per strategy by status');
    const m = Math.max(1, d3.max(rows, (d) => d3.sum(keys, (k) => d[k]))); const x = d3.scaleLinear([0, m], [left, W - 30]);
    rows.forEach((d, i) => { const y = 8 + i * rh; let acc = 0; s.append('text').attr('x', 2).attr('y', y + 14).style('fill', '#e8eef9').style('font-size', '11.5px').text(d.strategy);
      keys.forEach((k) => { if (!d[k]) return; s.append('rect').attr('x', x(acc) + 1).attr('width', Math.max(2, x(acc + d[k]) - x(acc) - 2)).attr('y', y).attr('height', 20).attr('rx', 4).attr('fill', COLS[k]);
        s.append('text').attr('x', (x(acc) + x(acc + d[k])) / 2).attr('y', y + 14).attr('text-anchor', 'middle').style('fill', '#04101c').style('font-weight', 700).text(String(d[k])); acc += d[k]; }); }); });
  dash.draw('tr_body', (body) => { const r = need(body, ['trade_book']); if (!r) return;
    const track = (t) => { if (t.status !== 'OPEN' || t.last === null) return '—'; const hi = t.target !== null ? t.target : Math.max(t.entry * 1.1, t.last); const rb = el('div', 'rangebar'); rb.style.minWidth = '90px'; const mark = (v, c) => { const i = el('i'); i.style.left = Math.min(100, Math.max(0, ((v - t.stop) / (hi - t.stop)) * 100)) + '%'; if (c) { i.style.background = c; i.style.boxShadow = 'none'; i.style.opacity = '.6'; } rb.appendChild(i); }; mark(t.entry, PAL.mut); mark(t.last); return rb; };
    CD.fillTable(body, r[0], [{ cls: 'num', render: (d) => String(d.id) }, { cls: 'num hs', render: (d) => d.booked.slice(5) }, { render: (d) => d.strategy }, { render: (d) => el('b', '', d.symbol) }, { render: (d) => tag(d.status, ST[d.status] || '') },
      { cls: 'num r', render: (d) => num(d.entry, 2) }, { cls: 'num r hs', render: (d) => num(d.stop, 2) }, { cls: 'num r hs', render: (d) => (d.target === null ? 'by rule' : num(d.target, 2)) }, { cls: 'num r hs', render: (d) => (d.qty === null ? '—' : String(d.qty)) },
      { cls: 'num r', render: (d) => (d.last === null ? '—' : num(d.last, 2)) }, { cls: 'num r', render: (d) => (d.move_pct === null ? '—' : el('span', cls(d.move_pct), pct(d.move_pct, 1))) }, { cls: 'hs', render: track },
      { cls: 'num r', render: (d) => (d.status === 'PENDING' || d.status === 'SKIPPED' ? '—' : el('span', cls(d.pnl), (d.pnl > 0 ? '+' : '') + inr(d.pnl, 2))) }], 'id'); });
  dash.draw('tr_kpi', (b) => { const r = dash.data('trade_book'); if (r.status !== 'ok') { b.textContent = '—'; return; } const k = b.dataset.k, book = r.data; const pnl = book.reduce((a, t) => a + t.pnl, 0);
    b.textContent = k === 'today' ? String(book.filter((t) => t.today === 'yes').length) : k === 'open' ? String(book.filter((t) => t.status === 'OPEN').length) : k === 'pending' ? String(book.filter((t) => t.status === 'PENDING').length)
      : k === 'closed' ? String(book.filter((t) => ['WIN', 'LOSS', 'TIME STOP'].includes(t.status)).length) : k === 'deployed' ? inr(book.reduce((a, t) => a + (t.status === 'OPEN' ? t.deployed : 0), 0)) : (pnl > 0 ? '+' : '') + inr(pnl, 2);
    if (k === 'pnl') { b.classList.toggle('up', pnl > 0); b.classList.toggle('down', pnl < 0); } });

  /* ---------- paper / real switch: the CEO's own choice, with the facts beside it ---------- */
  const mode = () => (dash.params().mode === 'real' ? 'real' : 'paper');
  document.querySelectorAll('#btn-paper').forEach((b) => b.addEventListener('click', () => dash.setParams({ mode: 'paper' })));
  document.querySelectorAll('#btn-real').forEach((b) => b.addEventListener('click', () => dash.setParams({ mode: 'real' })));
  dash.draw('mode_note', (p) => { const real = mode() === 'real'; document.querySelectorAll('#btn-paper').forEach((b) => b.setAttribute('aria-pressed', String(!real))); document.querySelectorAll('#btn-real').forEach((b) => b.setAttribute('aria-pressed', String(real)));
    document.querySelectorAll('#card-real').forEach((n) => { n.hidden = !real; }); const d = dash.data('paper_stats'), s = d.status === 'ok' ? d.data[0] : null; p.classList.toggle('warn', real);
    p.textContent = !s ? '—' : !real ? `Paper mode. ${s.trades} of ${s.need_trades} paper trades are closed and confidence is ${Number(s.confidence).toFixed(0)}% against the ${s.need_conf}% the desk asks for before real money.`
      : s.ready ? 'Real-money mode. The tests have passed. The desk writes tickets; you place each order with your broker.'
        : `Real-money mode is on by your choice. The desk's own tests have NOT passed: ${s.trades} of ${s.need_trades} paper trades closed, confidence ${Number(s.confidence).toFixed(0)}% against ${s.need_conf}%. No strategy here has yet shown it makes money. Money you cannot afford to lose should not be used.`; });
  dash.draw('real_tickets', (box) => { const r = need(box, ['trade_book', 'strategy_board']); if (!r) return; const rank = {}; r[1].forEach((s) => { rank[s.strategy] = s; }); const rows = r[0].filter((t) => t.market === 'NSE' && (t.status === 'PENDING' || t.status === 'OPEN'));
    if (!rows.length) { box.replaceChildren(el('div', 'empty', 'The desks have no live paper order to turn into a ticket right now.')); return; }
    box.replaceChildren(...rows.map((t) => { const s = rank[t.strategy] || {}; const c = el('div', 'dec'), h = el('div', 'dec-h'); h.append(el('b', '', `BUY ${t.symbol} · ${t.strategy}`), tag(s.ready ? 'STRATEGY PROVEN' : 'STRATEGY UNPROVEN', s.ready ? 'g' : 'r'));
      const text = `BUY ${t.symbol}  limit near ${num(t.entry, 2)}  stop ${num(t.stop, 2)}  ${t.target === null ? 'exit by the strategy rule' : 'target ' + num(t.target, 2)}`; const b = el('button', 'cd-btn', 'Copy ticket'); b.type = 'button'; b.dataset.label = 'Copy ticket'; b.style.marginTop = '6px'; b.addEventListener('click', () => CD.copy(text, b));
      c.append(h, el('p', 'sub num', text), el('p', 'sub', `Paper record of this strategy: ${s.closed || 0} closed trades, confidence ${s.closed > 1 ? Number(s.confidence).toFixed(0) + '%' : 'not measurable yet'}. Size it yourself: risk at most 1% of your trading cash between entry and stop.`), b); return c; })); });

  dash.draw('results_body', (body) => { const r = need(body, ['results_filed']); if (!r) return; if (!r[0].length) { const tr = el('tr'), td = el('td', 'dim', 'No results were filed since the last close.'); td.colSpan = 3; tr.appendChild(td); body.replaceChildren(tr); return; }
    CD.fillTable(body, r[0], [{ cls: 'num', render: (d) => d.time }, { render: (d) => (d.watchlist === 'yes' ? tag(d.symbol, 'b') : d.symbol + ' · ' + d.company) }, { cls: 'hs', render: (d) => d.headline }], 'symbol'); });
  dash.draw('pf_advice', (box) => { const r = need(box, ['alloc_rows']); if (!r) return; const rows = r[0].slice().sort((a, b) => b.share - a.share); const share = (n) => { const x = rows.find((q) => q.name === n); return x ? x.share : 0; }; const out = [];
    const say = (sev, head, why) => { const row = el('div', 'row sev-' + sev); row.style.gridTemplateColumns = '1fr'; const b = el('div'); b.append(el('div', 'h', head), el('div', 'w', why)); row.appendChild(b); out.push(row); };
    const metals = share('GOLD') + share('SILVER'), top = rows[0];
    if (metals >= 50) say('hi', `Gold and silver are ${metals.toFixed(0)}% of your assets.`, 'One theme decides most of your result. Metals pay no income and can go sideways for years. A common rule of thumb keeps them at 10% to 20%; that is a rule of thumb, not a target for you.');
    else if (top && top.share >= 40) say('hi', `${top.label} is ${top.share.toFixed(0)}% of your assets.`, 'One asset class decides most of your result.');
    if (share('MF') < 30) say('up', `Mutual funds are ${share('MF').toFixed(0)}% of your assets.`, 'Diversified equity funds are the usual long-term growth engine. Yours is small beside the metals.');
    if (share('SA') < 10) say('dn', `Liquid savings are ${share('SA').toFixed(0)}% of your assets.`, 'With no salary coming in, an emergency reserve of six months or more of expenses comes before any trading money.');
    if (!out.length) say('up', 'No single asset class dominates.', 'Nothing stands out as concentrated.'); box.replaceChildren(...out); });
  dash.draw('idx_chart', (box) => { const id = box.dataset.id, r = need(box, [id]); if (!r) return;
    const rows = r[0].map((c) => ({ t: new Date(String(c.t).replace(' ', 'T') + '+05:30'), o: c.o, h: c.h, l: c.l, c: c.c, v: c.v || 0 })).filter((c) => !Number.isNaN(c.t.getTime()));
    const s = CD.candleChart(box, rows, { iv: '1day', label: 'Index candles for one year with moving averages and a projection band' });
    if (s) { const p = el('p', 'note'); p.textContent = `Last ${num(s.last, 2)}. Recent drift points to ${num(s.projEnd, 2)} in ${s.steps} sessions (${pct((s.projEnd / s.last - 1) * 100, 1)}); support near ${num(s.support, 2)}, resistance near ${num(s.resistance, 2)}. This is the slope of recent closes with a widening band, not a forecast.`; box.appendChild(p); } });

  const toRows = (rows) => rows.map((r) => ({ t: new Date(String(r.t).replace(' ', 'T') + '+05:30'), o: r.o, h: r.h, l: r.l, c: r.c, v: r.v })).filter((r) => !Number.isNaN(r.t.getTime()));
  dash.draw('algo_pick', (em) => { em.textContent = CD.pickName ? `${CD.pickName} · daily candles, one year` : 'press "Open chart" on a name above'; });
  dash.draw('candle_algo', (box) => { if (!CD.pickName) { box.replaceChildren(el('div', 'empty', 'Pick a name from the approved list to see its history, its moving averages and where the recent drift points.')); return; }
    const r = need(box, ['candles']); if (!r) return; const s = CD.candleChart(box, toRows(r[0]), { iv: dash.params().iv, label: `${CD.pickName}: candles with moving averages and a projection band` });
    if (s) { const p = el('p', 'note'); p.textContent = `Last ${num(s.last, 2)}. The straight-line fit of recent closes points to ${num(s.projEnd, 2)} in ${s.steps} sessions (${pct((s.projEnd / s.last - 1) * 100, 1)}), with support near ${num(s.support, 2)} and resistance near ${num(s.resistance, 2)}. A drift line is not a forecast.`; box.appendChild(p); } });
})();
