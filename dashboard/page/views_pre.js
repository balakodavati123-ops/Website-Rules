/* Pre-market 08:45 tab: indices, the day's plan with reasons, analyst targets, long-term options. */
(function () {
  const { inr, num, pct, cls, el, tag, mk, need } = CD;
  const KIND = { 'Algo signal': 'b', Screened: '', Event: 'a', Earnings: 'v' };
  const greet = () => { const k = CD.session().key; return k === 'early' || k === 'pre' ? 'Good morning' : k === 'open' ? 'Markets are open' : 'Good evening'; };

  dash.draw('lead_pre', (p) => { const r = need(p, ['plan_today']); if (!r) return; const n = r[0].length; const idx = dash.data('indices');
    const find = (re) => (idx.status === 'ok' ? idx.data.find((x) => re.test(x.name || '')) : null); const nifty = find(/nifty 50/i), vix = find(/vix/i);
    const nodes = [document.createTextNode(`${greet()}, CEO. ${n} names are on today's plan, built from the last agent run and the day's company filings. `)];
    if (nifty) nodes.push(document.createTextNode('Nifty 50 is '), mk(num(nifty.live, 2), '', 'indices', 'live', 'key=' + nifty.key), document.createTextNode(' ('), mk(pct(nifty.chg_pct), cls(nifty.chg_pct), 'indices', 'chg_pct', 'key=' + nifty.key), document.createTextNode('). '));
    if (vix) nodes.push(document.createTextNode('India VIX is '), mk(num(vix.live, 2), '', 'indices', 'live', 'key=' + vix.key), document.createTextNode(vix.live > 20 ? ': the desk stays in cash above 20.' : vix.live >= 16 ? ': caution, so the desk takes half-size risk.' : ': calm.'));
    p.replaceChildren(...nodes); });

  dash.draw('idx_cards', (box) => { const r = need(box, ['indices']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const c = el('div', 'mcx-card'); const nm = el('div', 'sub', x.name); const v = el('div', 'num'); v.style.cssText = 'font-size:20px;font-weight:650;margin-top:2px';
      v.appendChild(mk(num(x.live, 2), '', 'indices', 'live', 'key=' + x.key)); const d = el('div', 'num ' + cls(x.chg_pct)); d.append(mk(pct(x.chg_pct), '', 'indices', 'chg_pct', 'key=' + x.key), document.createTextNode(' · prev ' + num(x.prev, 2)));
      const rb = el('div', 'rangebar'); rb.style.marginTop = '10px'; const span = x.high - x.low; const pos = span > 0 ? Math.min(100, Math.max(0, ((x.live - x.low) / span) * 100)) : 50; const m = el('i'); m.style.left = pos + '%'; rb.appendChild(m);
      const lh = CD.lohi(num(x.low, 2), 'day range', num(x.high, 2));
      c.append(nm, v, d, rb, lh); return c; })); });

  dash.draw('plan_list', (box) => { const r = need(box, ['plan_join']); if (!r) return; const rows = r[0];
    if (!rows.length) { box.replaceChildren(el('div', 'empty', 'No plan yet. The agents publish it after each run.')); return; }
    box.replaceChildren(...rows.map((p) => { const row = el('div', 'row' + (p.kind === 'Algo signal' ? ' sev-up' : p.kind === 'Event' ? ' sev-hi' : '')); const left = el('div'); left.append(tag(p.kind, KIND[p.kind] || ''));
      const mid = el('div'); const h = el('div', 'h'); h.append(document.createTextNode(p.symbol + ' · '), document.createTextNode(p.headline)); const w = el('div', 'w', p.why);
      const meta = el('div', 'sub'); meta.style.marginTop = '4px'; meta.textContent = p.source + (p.next_results ? ` · next results ${p.next_results} (projected)` : ''); mid.append(h, w, meta);
      const right = el('div', 'num'); right.style.textAlign = 'right';
      if (p.live !== null && p.live !== undefined) { const a = el('div'); a.appendChild(mk(num(p.live, 2), '', 'plan_join', 'live', 'rank=' + p.rank)); const b = el('div', cls(p.chg_pct)); b.appendChild(mk(pct(p.chg_pct), '', 'plan_join', 'chg_pct', 'rank=' + p.rank)); right.append(a, b); }
      row.append(left, mid, right); return row; })); });

  dash.draw('analyst_body', (body) => { const r = need(body, ['watch_live']); if (!r) return;
    CD.fillTable(body, r[0], [{ render: (d) => d.symbol }, { cls: 'num r', render: (d) => num(d.live, 2) }, { cls: 'num r', render: (d) => el('span', cls(d.chg_pct), pct(d.chg_pct)) }, { cls: 'num r', render: (d) => (d.target ? num(d.target, 0) : '—') },
      { cls: 'num r', render: (d) => (d.upside === null || d.upside === undefined ? '—' : el('span', cls(d.upside), pct(d.upside, 1))) }, { render: (d) => (d.sentiment ? tag(d.sentiment, d.sentiment === 'BUY' ? 'g' : d.sentiment === 'SELL' ? 'r' : 'a') : '—') }], 'symbol'); });

  dash.draw('ideas_body', (body) => { const r = need(body, ['mf_ideas']); if (!r) return;
    CD.fillTable(body, r[0], [{ k: 'name' }, { render: (d) => tag(d.category) }, { render: (d) => d.rank || '—' }, { cls: 'num r', render: (d) => (d.ret_1y ? pct(d.ret_1y, 1, false) : '—') }, { cls: 'num r', render: (d) => (d.ret_3y ? pct(d.ret_3y, 1, false) : '—') },
      { cls: 'num r', render: (d) => (d.ret_5y ? pct(d.ret_5y, 1, false) : '—') }, { cls: 'num r', render: (d) => (d.expense ? pct(d.expense, 2, false) : '—') }, { render: (d) => d.risk }, { cls: 'num r', render: (d) => inr(d.min_sip) }], 'name'); });
})();
