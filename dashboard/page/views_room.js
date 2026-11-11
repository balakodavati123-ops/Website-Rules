/* Morning briefing: the research run replayed message by message, and the CEO's ticket. */
(function () {
  const { inr, num, pct, cls, el, tag, mk, need } = CD;
  const COLOR = { DATA: ['#29d3ee', '#04101c'], TECH: ['#4f8cff', '#fff'], FUND: ['#a184ff', '#fff'], SENT: ['#ff7ac6', '#fff'], CALL: ['#ffb64a', '#2a1a00'], BULL: ['#2de3a5', '#04201a'], BEAR: ['#ff5f75', '#fff'], RISK: ['#ffb64a', '#2a1a00'], PM: ['#4f8cff', '#fff'], LEDGER: ['#5b7093', '#fff'] };
  const INIT = { DATA: 'DA', TECH: 'TE', FUND: 'FU', SENT: 'SE', CALL: 'CA', BULL: 'BU', BEAR: 'BE', RISK: 'WA', PM: 'CH', LEDGER: 'SC' };
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ST = { shown: 0, timer: null, rows: [], key: '' };

  const setActive = (agent) => { document.querySelectorAll('#card-team [data-agent]').forEach((n) => n.classList.toggle('active', n.getAttribute('data-agent') === agent));
    document.querySelectorAll('#card-team [data-edge]').forEach((n) => n.classList.toggle('active', n.getAttribute('data-edge') === agent)); };
  const stop = () => { if (ST.timer) { clearInterval(ST.timer); ST.timer = null; } };
  const step = () => { if (ST.shown >= ST.rows.length - 1) { stop(); ST.shown = ST.rows.length - 1; setActive(null); dash.draw('feed'); return; } ST.shown += 1; dash.draw('feed'); };
  const play = () => { stop(); ST.shown = 0; if (reduce) { ST.shown = ST.rows.length - 1; dash.draw('feed'); return; } ST.timer = setInterval(step, 1700); dash.draw('feed'); };

  document.getElementById('btn-replay').addEventListener('click', play);
  document.getElementById('btn-skip').addEventListener('click', () => { stop(); ST.shown = ST.rows.length - 1; setActive(null); dash.draw('feed'); });

  dash.draw('room_stamp', (box) => { const d = dash.data('agent_feed'); box.textContent = d.status === 'ok' && d.data.length ? `${d.data.length} messages · run of ${d.data[0].run_date}` : '—'; });

  dash.draw('feed', (box) => { const r = need(box, ['agent_feed']); if (!r) return; ST.rows = r[0]; const key = ST.rows.length + ':' + (ST.rows[0] ? ST.rows[0].run_date : '');
    if (ST.key !== key) { ST.key = key; play(); return; }
    const shown = ST.rows.slice(0, ST.shown + 1); const last = ST.shown;
    box.replaceChildren(...shown.map((m, i) => { const [bg, fg] = COLOR[m.agent] || ['#5b7093', '#fff']; const row = el('div', 'msg' + (i === last && ST.timer ? ' new' : '')); const av = el('div', 'avatar', INIT[m.agent] || '··'); av.style.background = bg; av.style.color = fg;
      const bub = el('div', 'bubble ' + (m.tone === 'bull' ? 'bull' : m.tone === 'bear' ? 'bear' : m.tone === 'warn' ? 'warn' : m.kind === 'ask' ? 'ask' : '')); const who = el('div', 'who'); who.append(el('b', '', m.name), el('span', '', m.role));
      if (m.ticker) who.appendChild(tag(m.ticker, m.tone === 'bull' ? 'g' : m.tone === 'bear' ? 'r' : '')); bub.append(who, el('p', '', m.text)); row.append(av, bub); return row; }));
    box.scrollTop = box.scrollHeight; setActive(ST.timer && ST.rows[ST.shown] ? ST.rows[ST.shown].agent : null); });

  dash.draw('ticket_panel', (box) => { const r = need(box, ['ticket_view']); if (!r) return; const rows = r[0];
    if (!rows.length) { box.replaceChildren(el('div', 'empty', 'Nothing is waiting for you. The Chief will bring the next decision here.')); return; }
    box.replaceChildren(...rows.map((t) => { const open = CD.session().key === 'open'; const age = CD.ageSec(t.live_time); const why = []; let status = 'READY';
      if (!open) { status = 'WAIT'; why.push('The market is closed. The ticket re-checks at 09:20 when live prices flow.'); }
      else if (t.live === null) { status = 'WAIT'; why.push('No live price yet.'); }
      else if (age > 180) { status = 'WAIT'; why.push('The price is ' + CD.ago(age) + ', too old to act on.'); }
      else if (Math.abs(t.ref_gap_pct) > 3) { status = 'STOP'; why.push(`The price moved ${pct(t.ref_gap_pct)} from the signal close. The reason for the trade has changed: skip it.`); }
      else why.push('Price is fresh and within 3% of the signal close.');
      const w = el('div', 'ticket'); const top = el('div'); top.style.cssText = 'display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center';
      const big = el('div', 'big'); big.textContent = `BUY ${t.symbol}  ·  paper`; const stamp = el('span', 'stamp ' + (status === 'READY' ? 'ready' : status === 'STOP' ? 'stop' : 'wait'), status); top.append(big, stamp);
      const dl = el('dl'); const add = (k, vNode) => { dl.appendChild(el('dt', '', k)); const dd = el('dd'); dd.append(vNode); dl.appendChild(dd); };
      add('Strategy', document.createTextNode(t.strategy)); add('Signal close', mk(num(t.entry, 2), '', 'ticket_view', 'entry', 'id=' + t.id));
      add('Live price', document.createTextNode(t.live === null ? '—' : `${num(t.live, 2)} (${pct(t.ref_gap_pct)} vs signal)`));
      add('Entry limit', document.createTextNode(num(t.t_entry, 2))); add('Stop (5% below)', document.createTextNode(num(t.t_stop, 2))); add('Target (20% above)', document.createTextNode(num(t.t_target, 2)));
      add('Quantity', document.createTextNode(String(t.t_qty))); add('Rupees at risk', document.createTextNode(inr(t.t_risk))); add('Position value', document.createTextNode(inr(t.t_value)));
      const ex = el('p', 'note', why.join(' ')); const how = el('p', 'note', 'This is a paper order. The Scribe fills it by itself at the next open, in the morning run, if the gap is within 3%. For real money, later, the order is always yours to place in INDmoney.');
      const text = [`PAPER TICKET: BUY ${t.symbol} (${t.strategy})`, `Entry LIMIT ${num(t.t_entry, 2)}  Qty ${t.t_qty}`, `Stop ${num(t.t_stop, 2)}  Target ${num(t.t_target, 2)}`, `Risk ${inr(t.t_risk)}  Value ${inr(t.t_value)}`, `Status ${status}: ${why.join(' ')}`].join('\n');
      const btn = el('button', 'cd-btn pri', 'Copy ticket'); btn.type = 'button'; btn.dataset.label = 'Copy ticket'; btn.style.marginTop = '8px'; btn.addEventListener('click', () => CD.copy(text, btn));
      w.append(top, dl, ex, how, btn); return w; })); });
})();
