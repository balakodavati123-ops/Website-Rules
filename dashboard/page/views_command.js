/* Header chips and the Command tab. */
(function () {
  const { inr, num, pct, cls, el, tag, mk, need } = CD;
  const COLORS = { GOLD: '#ffb64a', SILVER: '#c9d6ea', MF: '#4f8cff', SA: '#2de3a5', CRYPTO: '#a184ff' };

  dash.draw('chip_session', {
    mount: () => ({ t: setInterval(() => dash.draw('chip_session'), 30000) }),
    update: (box) => { const s = CD.session(); box.className = 'chip ' + (s.key === 'open' ? 'live' : s.key === 'pre' ? 'wait' : 'off');
      box.replaceChildren(el('i'), document.createTextNode(` ${s.label} · ${s.hhmm} IST`)); },
    unmount: (box, made) => clearInterval(made && made.t) });

  dash.draw('chip_data', (box) => { const d = dash.data('indices');
    if (d.status === 'connect' || d.status === 'declined') { box.className = 'chip off'; box.replaceChildren(el('i'), document.createTextNode(' Connect INDmoney for live data')); return; }
    if (d.status !== 'ok' || !d.data.length) { box.className = 'chip'; box.textContent = '—'; return; }
    const t = d.data[0].time; box.className = 'chip live'; box.replaceChildren(el('i'), document.createTextNode(` INDmoney live · quote ${t ? t.slice(11, 19) : '—'} IST`)); });

  dash.draw('chip_agents', (box) => { const d = dash.data('agent_feed'); if (d.status !== 'ok' || !d.data.length) { box.textContent = '—'; return; }
    const agents = new Set(d.data.map((r) => r.agent)).size; box.replaceChildren(el('i'), document.createTextNode(` ${agents} agents · last run ${d.data[0].run_date}`)); });

  const greet = () => { const k = CD.session().key; return k === 'early' || k === 'pre' ? 'Good morning' : k === 'open' ? 'Markets are open' : 'Good evening'; };

  dash.draw('lead_command', (p) => { const r = need(p, ['kpi_rows']); if (!r) return; const [k] = r; const g = (key) => k.find((x) => x.key === key) || {};
    const net = g('net'), met = g('metals'), liq = g('liquid'), gate = g('gate');
    p.replaceChildren(document.createTextNode(`${greet()}, CEO. Your net worth is `), mk(inr(net.value), '', 'kpi_rows', 'value', 'key=net'),
      document.createTextNode(', which is '), mk(inr(net.delta), net.delta >= 0 ? 'up' : 'down', 'kpi_rows', 'delta', 'key=net'),
      document.createTextNode(' against what you put in. '), mk(num(met.delta_pct, 0) + '%', '', 'kpi_rows', 'delta_pct', 'key=metals'),
      document.createTextNode(' of your assets sit in gold and silver and '), mk(num(liq.delta_pct, 0) + '%', '', 'kpi_rows', 'delta_pct', 'key=liquid'),
      document.createTextNode(' is liquid savings. The paper desk has closed '), mk(String(gate.value), '', 'kpi_rows', 'value', 'key=gate'),
      document.createTextNode(' trades so far. Real money stays off until the gate on the Algo lab tab passes.')); });

  dash.draw('kpis', (box) => { const r = need(box, ['kpi_rows']); if (!r) return; const rows = r[0];
    const fmt = {
      net: (x) => [inr(x.value), `${inr(x.delta)} (${pct(x.delta_pct)}) ${x.note}`, cls(x.delta)],
      mfday: (x) => [(x.value > 0 ? '+' : '') + inr(x.value), `${pct(x.delta_pct)} of ${inr(x.delta)}`, cls(x.value)],
      metals: (x) => [inr(x.value), `${num(x.delta_pct, 1)}% ${x.note.split(' · ')[0]} · est. ${(x.delta > 0 ? '+' : '') + inr(x.delta)} today`, cls(x.delta)],
      liquid: (x) => [inr(x.value), `${num(x.delta_pct, 1)}% ${x.note}`, ''],
      paper: (x) => [inr(x.value), `${(x.delta > 0 ? '+' : '') + inr(x.delta)} (${pct(x.delta_pct)}) ${x.note}`, cls(x.delta)],
      gate: (x) => [String(x.value), `${x.delta} needed · confidence ${num(x.delta_pct, 0)}%`, ''] };
    box.replaceChildren(...rows.map((x) => { const [v, d, c] = fmt[x.key](x); const t = el('div', 'kpi'); t.appendChild(el('div', 'l', x.label));
      const vv = el('div', 'v ' + (x.key === 'mfday' ? c : '')); vv.textContent = v; CD.mark(vv, 'kpi_rows', 'value', 'key=' + x.key); t.appendChild(vv);
      const dd = el('div', 'd ' + (x.key === 'mfday' ? '' : c)); dd.textContent = d; if (x.delta !== null && x.delta !== undefined) CD.mark(dd, 'kpi_rows', 'delta', 'key=' + x.key); t.appendChild(dd); return t; })); });

  dash.draw('alloc_chart', (box) => { const r = need(box, ['alloc_rows']); if (!r) return; const rows = r[0]; d3.select(box).selectAll('*').remove();
    if (!rows.length) { box.appendChild(el('div', 'empty', 'No assets found in the account.')); return; }
    const tot = rows.reduce((s, x) => s + x.value, 0); CD.donut(box, rows.map((x) => ({ label: x.label, value: x.value, share: x.share, color: COLORS[x.name] || '#8ea3c4' })), inr(tot), 'total assets'); });

  dash.draw('alloc_legend', (box) => { const r = need(box, ['alloc_rows']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const row = el('div', 'legend'); row.style.justifyContent = 'space-between'; const l = el('span'); const dot = el('i'); dot.style.background = COLORS[x.name] || '#8ea3c4'; dot.style.height = '8px'; dot.style.width = '8px'; dot.style.borderRadius = '50%'; l.append(dot, document.createTextNode(x.label)); const v = el('span', 'num');
      v.append(mk(num(x.share, 1) + '%', '', 'alloc_rows', 'share', 'name=' + CD.enc(x.name)), document.createTextNode(' · ' + inr(x.value))); row.append(l, v); return row; })); });

  const money = (v) => el('span', 'num ' + cls(v), v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + inr(v));
  dash.draw('mf_body', (body) => { const r = need(body, ['mf_holdings']); if (!r) return;
    CD.fillTable(body, r[0], [{ k: 'name' }, { cls: 'hs', render: (d) => tag(CD.cap(d.class), d.class === 'gold' ? 'a' : d.class === 'equity' ? 'b' : '') }, { cls: 'num r hs', render: (d) => inr(d.invested) }, { cls: 'num r', render: (d) => inr(d.value) },
      { cls: 'num r', render: (d) => money(d.pnl) }, { cls: 'num r', render: (d) => { const s = el('span', cls(d.pnl_pct), pct(d.pnl_pct)); return s; } }, { cls: 'num r', render: (d) => el('span', cls(d.day_pct), pct(d.day_pct)) }], 'name'); });

  dash.draw('metals_body', (body) => { const r = need(body, ['metals_rows']); if (!r) return;
    CD.fillTable(body, r[0], [{ k: 'metal', render: (d) => tag(d.metal, d.metal === 'Gold' ? 'a' : '') }, { k: 'name' }, { cls: 'num r hs', render: (d) => num(d.qty, 0) }, { cls: 'num r hs', render: (d) => inr(d.invested) }, { cls: 'num r', render: (d) => inr(d.value) },
      { cls: 'num r', render: (d) => money(d.pnl) }, { cls: 'num r', render: (d) => el('span', cls(d.pnl_pct), pct(d.pnl_pct)) }], 'key'); });

  dash.draw('stock_body', (body) => { const r = need(body, ['stock_holdings']); if (!r) return;
    CD.fillTable(body, r[0], [{ k: 'name' }, { cls: 'num r', render: (d) => num(d.qty, 0) }, { cls: 'num r', render: (d) => inr(d.value) }, { cls: 'num r', render: (d) => money(d.pnl) }, { cls: 'num r', render: (d) => el('span', cls(d.pnl_pct), pct(d.pnl_pct)) }], 'name'); });

  dash.draw('stock_empty', (box) => { const r = need(box, ['stock_holdings']); if (!r) return;
    box.replaceChildren(...(r[0].length ? [] : [el('div', 'empty', 'No direct stocks in INDmoney. The agents trade on pretend money until the real-money gate passes.')])); });

  dash.draw('debt_note', (box) => { const r = need(box, ['snapshot']); if (!r) return; const debts = r[0].filter((x) => x.kind === 'debt');
    box.replaceChildren(...debts.map((d) => { const p = el('p', 'note'); p.append(document.createTextNode('Loan outstanding: '), mk(inr(d.current), 'warn', 'snapshot', 'current', 'kind=debt&name=' + CD.enc(d.name)), document.createTextNode(' · ' + d.name)); return p; })); });

  dash.draw('inbox', (box) => { const r = need(box, ['ticket_view']); if (!r) return; const rows = r[0];
    if (!rows.length) { box.replaceChildren(el('div', 'empty', 'Nothing waiting. The agents will put a decision here when they have one.')); return; }
    box.replaceChildren(...rows.map((t) => { const w = el('div', 'ticket'); const top = el('div'); top.style.cssText = 'display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center';
      const b = el('div', 'big'); b.textContent = 'BUY ' + t.symbol + ' (paper)'; const st = tag(t.status, 'a'); top.append(b, st);
      const sub = el('p', 'sub'); sub.style.marginTop = '6px'; sub.append(document.createTextNode(`${t.strategy}. Reference close `), mk(num(t.entry, 2), 'num', 'ticket_view', 'entry', 'id=' + t.id), document.createTextNode(`. Stop ${num(t.stop, 2)}, target ${num(t.target, 2)}.`));
      const btn = el('button', 'cd-btn pri', 'Open the ticket'); btn.type = 'button'; btn.style.marginTop = '10px'; btn.addEventListener('click', () => CD.goto('room')); w.append(top, sub, btn); return w; })); });

  dash.draw('mini_feed', (box) => { const r = need(box, ['agent_feed']); if (!r) return; const rows = r[0].slice(-4);
    box.replaceChildren(...rows.map((m) => { const row = el('div', 'row'); const t = el('span', 'tag v', m.name); const body = el('div'); const h = el('div', 'h', m.role); const w = el('div', 'w', m.text.length > 190 ? m.text.slice(0, 187) + '…' : m.text); body.append(h, w); row.append(t, body, el('span')); return row; })); });
})();
