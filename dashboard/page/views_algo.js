/* Algo lab tab: the real-money gate, the paper account, the ledger and the evidence. */
(function () {
  const { inr, num, pct, cls, el, tag, mk, need } = CD;
  const STATUS = { APPROVED: 'g', PROBATION: 'a', REJECTED: 'r', WIN: 'g', LOSS: 'r', OPEN: 'b', PENDING: 'a', 'TIME STOP': '' };
  const P = (rows) => (rows && rows[0]) || {};

  dash.draw('lead_algo', (p) => { const r = need(p, ['paper_stats']); if (!r) return; const s = P(r[0]);
    p.replaceChildren(document.createTextNode('The paper desk started with '), mk(inr(s.start), '', 'paper_stats', 'start'), document.createTextNode(' and holds '), mk(inr(s.equity), cls(s.pnl), 'paper_stats', 'equity'),
      document.createTextNode('. '), mk(String(s.trades), '', 'paper_stats', 'trades'), document.createTextNode(` trades are closed. The gate needs `), mk(String(s.need_trades), '', 'paper_stats', 'need_trades'),
      document.createTextNode(' trades and '), mk(num(s.need_conf, 0) + '%', '', 'paper_stats', 'need_conf'), document.createTextNode(' confidence that the average trade makes money. Confidence stands at '),
      mk(num(s.confidence, 0) + '%', '', 'paper_stats', 'confidence'), document.createTextNode(', so every order stays on paper. A 98% confidence is not a 98% win rate.')); });

  dash.draw('gate_panel', (box) => { const r = need(box, ['paper_stats']); if (!r) return; const s = P(r[0]);
    const tests = [
      { label: 'Paper trades closed', val: `${s.trades} of ${s.need_trades}`, frac: s.trades / s.need_trades, ok: s.trades_ok, field: 'trades' },
      { label: 'Confidence the average trade makes money', val: `${num(s.confidence, 0)}% of ${num(s.need_conf, 0)}%`, frac: s.confidence / 100, mark: s.need_conf / 100, ok: s.conf_ok, field: 'confidence' },
      { label: 'Worst drawdown stays under the limit', val: s.trades ? `${num(s.drawdown, 1)}% (limit ${num(s.need_dd, 0)}%)` : 'No trades yet', frac: s.trades ? Math.min(1, s.drawdown / s.need_dd) : 0, ok: s.dd_ok, field: 'drawdown', invert: true },
      { label: 'Both halves of the record are profitable', val: s.trades >= 4 ? (s.halves_ok ? 'Yes' : 'No') : 'Needs 4 closed trades', frac: s.halves_ok ? 1 : 0, ok: s.halves_ok, field: 'halves_ok' }];
    const ul = el('ul'); ul.style.padding = '0'; ul.style.margin = '0';
    tests.forEach((t) => { const li = el('li'); li.style.cssText = 'list-style:none;margin:0 0 14px'; const top = el('div'); top.style.cssText = 'display:flex;justify-content:space-between;gap:10px;font-size:12.5px';
      const lab = el('span', '', t.label); const val = el('span', 'num'); val.appendChild(CD.mark(el('b', '', t.val), 'paper_stats', t.field)); top.append(el('span'), val); top.firstChild.append(tag(t.ok ? 'PASS' : 'NOT YET', t.ok ? 'g' : 'a'), document.createTextNode(' '), lab);
      const m = el('div', 'meter'); m.style.marginTop = '6px'; const b = el('b'); b.style.width = Math.max(0, Math.min(100, t.frac * 100)) + '%'; if (t.invert) b.style.background = t.ok ? 'var(--green)' : 'var(--red)'; m.appendChild(b);
      if (t.mark) { const s2 = el('s'); s2.style.left = t.mark * 100 + '%'; m.appendChild(s2); } li.append(top, m); ul.appendChild(li); });
    const stamp = el('div'); stamp.style.marginTop = '4px'; const st = el('span', 'stamp ' + (s.ready ? 'ready' : 'stop'), s.ready ? 'REAL MONEY: UNLOCKED' : 'REAL MONEY: LOCKED'); stamp.appendChild(st);
    const why = el('p', 'note', s.ready ? 'All four tests pass. You still decide, and you still start small.' : 'The desk keeps trading on pretend money until all four tests pass.');
    box.replaceChildren(ul, stamp, why); });

  dash.draw('equity_chart', (box) => { const r = need(box, ['paper_equity']); if (!r) return; const rows = r[0].slice().sort((a, b) => (a.date < b.date ? -1 : 1)); d3.select(box).selectAll('*').remove();
    if (!rows.length) { box.appendChild(el('div', 'empty', 'The curve starts with the first paper trade.')); return; }
    const ps = dash.data('paper_stats'); const start = ps.status === 'ok' && ps.data[0] ? ps.data[0].start : rows[0].equity;
    const W = Math.max(320, box.clientWidth || 600), H = 230, m = { l: 56, r: 16, t: 14, b: 26 }; const s = CD.svg(box, W, H, 'Paper account equity over time');
    const vals = rows.map((x) => x.equity).concat([start]); const lo = Math.min(...vals), hi = Math.max(...vals); const padv = Math.max((hi - lo) * 0.2, start * 0.02);
    const y = d3.scaleLinear([lo - padv, hi + padv], [H - m.b, m.t]); const n = rows.length; const x = (i) => (n === 1 ? (W + m.l - m.r) / 2 : m.l + (i * (W - m.l - m.r)) / (n - 1));
    y.ticks(4).forEach((t) => { s.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(t)).attr('y2', y(t)).attr('stroke', '#12223d'); s.append('text').attr('x', m.l - 6).attr('y', y(t) + 3).attr('text-anchor', 'end').text(inr(t)); });
    s.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(start)).attr('y2', y(start)).attr('stroke', CD.PAL.amber).attr('stroke-dasharray', '4 4').attr('opacity', .6);
    s.append('text').attr('x', W - m.r).attr('y', y(start) - 5).attr('text-anchor', 'end').style('fill', CD.PAL.amber).text('start ' + inr(start));
    if (n > 1) { s.append('path').attr('d', d3.area().x((d, i) => x(i)).y0(H - m.b).y1((d) => y(d.equity))(rows)).attr('fill', CD.PAL.blue).attr('opacity', .15);
      s.append('path').attr('d', d3.line().x((d, i) => x(i)).y((d) => y(d.equity))(rows)).attr('fill', 'none').attr('stroke', CD.PAL.cyan).attr('stroke-width', 2); }
    const tip = CD.tooltip(box); s.selectAll('circle.pt').data(rows).join('circle').attr('class', 'pt').attr('cx', (d, i) => x(i)).attr('cy', (d) => y(d.equity)).attr('r', 4.5).attr('fill', CD.PAL.cyan).attr('stroke', '#060a13').attr('stroke-width', 2)
      .on('pointermove', (ev, d) => { const rc = box.getBoundingClientRect(); tip.show(`${d.date}<br>${inr(d.equity)}`, ev.clientX - rc.left, ev.clientY - rc.top); }).on('pointerleave', () => tip.hide());
    s.selectAll('text.dt').data(rows.length > 8 ? rows.filter((_, i) => i % Math.ceil(rows.length / 6) === 0) : rows).join('text').attr('class', 'dt').attr('x', (d) => x(rows.indexOf(d))).attr('y', H - 6).attr('text-anchor', 'middle').text((d) => d.date.slice(5)); });

  dash.draw('ledger_body', (body) => { const r = need(body, ['paper_ledger']); if (!r) return;
    CD.fillTable(body, r[0], [{ render: (d) => String(d.id) }, { render: (d) => d.market }, { render: (d) => d.symbol }, { render: (d) => d.strategy || '—' }, { render: (d) => tag(d.status, STATUS[d.status] || '') },
      { cls: 'num r', render: (d) => num(d.entry, 2) }, { cls: 'num r', render: (d) => num(d.stop, 2) }, { cls: 'num r', render: (d) => num(d.target, 2) }, { cls: 'num r', render: (d) => String(d.qty) }, { cls: 'num r', render: (d) => inr(d.risk_rs) },
      { cls: 'num r', render: (d) => el('span', cls(d.pnl_rs), inr(d.pnl_rs)) }, { cls: 'num r', render: (d) => num(d.r_mult, 2) }], 'id'); });

  dash.draw('conf_chart', (box) => { const r = need(box, ['strategies_eq', 'strategies_macro']); if (!r) return; d3.select(box).selectAll('*').remove();
    const rows = r[0].map((d) => ({ name: d.strategy.replace(/_/g, ' '), market: 'stocks', naive: d.conf_cluster, adj: d.conf_adjusted, trades: d.trades, avg: d.avg_R }))
      .concat(r[1].map((d) => ({ name: d.strategy.replace(/_/g, ' '), market: d.market, naive: d.conf_cluster, adj: d.conf_adjusted, trades: d.trades, avg: d.avg_R }))).sort((a, b) => b.adj - a.adj);
    const W = Math.max(320, box.clientWidth || 640), rowH = 24, left = Math.min(210, W * 0.38), m = { t: 22, r: 40, b: 8 }; const H = m.t + rows.length * rowH + m.b; const s = CD.svg(box, W, H, 'Confidence that each strategy truly makes money, naive and corrected');
    const x = d3.scaleLinear([0, 100], [left, W - m.r]); [0, 25, 50, 75, 100].forEach((t) => { s.append('line').attr('x1', x(t)).attr('x2', x(t)).attr('y1', m.t - 4).attr('y2', H - m.b).attr('stroke', '#12223d'); s.append('text').attr('x', x(t)).attr('y', 11).attr('text-anchor', 'middle').text(t + '%'); });
    s.append('line').attr('x1', x(98)).attr('x2', x(98)).attr('y1', m.t - 4).attr('y2', H - m.b).attr('stroke', CD.PAL.amber).attr('stroke-width', 1.6);
    s.append('text').attr('x', x(98) - 5).attr('y', m.t + 8).attr('text-anchor', 'end').style('fill', CD.PAL.amber).text('98% gate');
    const tip = CD.tooltip(box); rows.forEach((d, i) => { const yy = m.t + i * rowH + rowH / 2; const g = s.append('g');
      g.append('text').attr('x', left - 8).attr('y', yy + 3).attr('text-anchor', 'end').style('fill', '#cfd9ec').text(`${d.name} · ${d.market}`.slice(0, 34));
      g.append('rect').attr('x', left).attr('y', yy - 4).attr('width', Math.max(0, x(d.naive * 100) - left)).attr('height', 8).attr('rx', 4).attr('fill', CD.PAL.blue).attr('opacity', .55);
      g.append('path').attr('transform', `translate(${x(d.adj * 100)},${yy})`).attr('d', d3.symbol(d3.symbolDiamond, 90)()).attr('fill', d.adj >= 0.98 ? CD.PAL.green : '#fff').attr('stroke', '#060a13');
      g.append('rect').attr('x', 0).attr('y', yy - rowH / 2).attr('width', W).attr('height', rowH).attr('fill', 'transparent')
        .on('pointermove', (ev) => { const rc = box.getBoundingClientRect(); tip.show(`${d.name} (${d.market})<br>${d.trades} trades, avg ${num(d.avg, 2)} R<br>naive ${num(d.naive * 100, 0)}% · corrected ${num(d.adj * 100, 0)}%`, ev.clientX - rc.left, ev.clientY - rc.top); }).on('pointerleave', () => tip.hide()); }); });

  dash.draw('eq_body', (body) => { const r = need(body, ['strategies_eq']); if (!r) return;
    CD.fillTable(body, r[0].slice().sort((a, b) => b.conf_adjusted - a.conf_adjusted), [{ render: (d) => d.strategy }, { render: (d) => tag(d.status, STATUS[d.status] || '') }, { cls: 'num r', render: (d) => String(d.trades) },
      { cls: 'num r', render: (d) => el('span', cls(d.avg_R), num(d.avg_R, 2)) }, { cls: 'num r', render: (d) => pct(d.conf_adjusted * 100, 0, false) }], 'strategy'); });
})();
