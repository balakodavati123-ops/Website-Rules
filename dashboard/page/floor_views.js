/* Floor panels: the status bar, the desk cards, the speaker, the rules and score panels, the paper
   book and the log. The engine says what happened; these drawings show it. */
(function () {
  const { el, inr, num, pct, cls, mk, need, tag, PAL } = CD; const E = CD.ENG, AG = CD.AGENTS, PORTS = CD.PORTS;
  const TONES = ['info', 'ok', 'bull', 'bear', 'kill', 'warn', 'ask'];
  const COL = { info: PAL.cyan, ok: PAL.green, bull: PAL.green, bear: PAL.red, kill: PAL.red, warn: PAL.amber, ask: '#ffffff' };
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const tone = (n, t) => TONES.forEach((x) => n.classList.toggle(x, x === t));
  const nm = (id) => (AG[id] ? AG[id].name : PORTS[id] || id);
  const stats = () => { const d = dash.data('floor_stats'); return d.status === 'ok' && d.data.length ? d.data[0] : null; };
  const where = (r) => 'symbol=' + CD.enc(r.symbol);
  const MAXP = {}, BAR = {}; let typing = null, typed = null;

  /* ---------- status bar ---------- */
  dash.draw('fl_mode', (c) => {
    const d = dash.data('floor_stats'); const lab = (kind, text) => { ['live', 'wait', 'off'].forEach((k) => c.classList.toggle(k, k === kind)); c.replaceChildren(el('i'), document.createTextNode(text)); };
    if (d.status !== 'ok' || !d.data.length) { lab(d.status === 'error' ? 'off' : 'wait', d.status === 'connect' || d.status === 'declined' ? 'Connect INDmoney to wake the desks' : d.status === 'error' ? 'Prices failed to load' : 'Waking the desks'); return; }
    const age = CD.ageSec(d.data[0].quote_time);
    if (CD.session().key !== 'open') lab('wait', 'REVIEW · market closed · last session\'s tape');
    else if (E.live.on) lab('live', 'LIVE · re-reading prices each minute');
    else if (age !== null && age < 240) lab('live', 'LIVE PRICES · ' + CD.ago(age));
    else lab('wait', 'SNAPSHOT · prices ' + CD.ago(age));
  });
  dash.draw('fl_num', (b) => { const k = b.dataset.k; if (k === 'loop' || k === 'total') { b.textContent = E[k] ? String(E[k]) : '—'; return; } const s = stats(); b.textContent = s && s[k] != null ? String(s[k]) : '—'; });
  dash.draw('fl_asof', (b) => { const s = stats(); const m = s && String(s.quote_time).match(/-(\d{2})-(\d{2})[T ](\d{2}:\d{2})/); b.textContent = m ? `${m[3]} · ${Number(m[2])} ${MON[Number(m[1]) - 1]}` : '—'; });
  dash.draw('fl_note', (p) => { const s = E.cur; if (!s) { p.textContent = '—'; return; } const h = s.hops[s.hops.length - 1]; p.textContent = `${nm(h[0])} → ${nm(h[1])} · step ${E.i + 1} of ${E.steps.length} · loop ${E.loop}`; });

  /* ---------- the speaker: who is talking, to whom, typed out ---------- */
  dash.draw('fl_say', (box) => {
    clearInterval(typing); const s = E.cur;
    if (!s) { const d = dash.data('floor_stats'); box.replaceChildren(el('p', 'fl-wait', d.status === 'connect' || d.status === 'declined' ? 'Connect INDmoney and the desks start working.' : d.status === 'error' ? 'The live lists failed to load. Press "Pull prices now".' : 'Waking the desks…')); return; }
    const a = AG[s.agent]; const h = s.hops[s.hops.length - 1]; const head = el('div', 'fl-say-h'); const av = el('i', 'orb', a.init); av.style.background = a.c; av.style.color = a.fg;
    const st = el('span', 'st', s.state); tone(st, s.tone); head.append(av, el('b', '', a.name), st, el('span', 'to', s.ceo ? 'to you, CEO' : 'from ' + nm(h[0])), el('time', 'num', s.t));
    const p = el('p', 'fl-say-t'); box.replaceChildren(head, p);
    if (E.reduce) { p.textContent = s.text; return; }
    if (typed === s) { p.textContent = s.text; return; }
    let i = 0; const jump = Math.max(1, Math.ceil(s.text.length / 42)); const caret = el('i', 'caret');
    typing = setInterval(() => { i = Math.min(s.text.length, i + jump); p.textContent = s.text.slice(0, i); if (i >= s.text.length) { clearInterval(typing); typed = s; } else p.appendChild(caret); }, 28);
  });

  /* ---------- desk cards ---------- */
  dash.draw('desk_chip', (c) => { const d = E.desk[c.dataset.agent]; c.textContent = d ? d.chip : '—'; tone(c, d ? d.tone : ''); });
  dash.draw('desk_n', (b) => { const d = E.desk[b.dataset.agent]; b.textContent = d ? String(d.n) : '—'; });
  dash.draw('desk_now', (p) => { const d = E.desk[p.dataset.agent]; p.textContent = d ? d.now : '—'; });
  dash.draw('fl_flow', (box) => {
    if (!E.flow.length) { box.textContent = '—'; return; }
    box.replaceChildren(...E.flow.map((f) => { const c = el('span', 'fchip ' + f.st); c.appendChild(el('b', '', f.label.length > 20 ? f.label.slice(0, 19) + '…' : f.label)); if (f.st === 'kill') c.appendChild(el('small', '', 'rule ' + f.rule)); else if (f.score != null) c.appendChild(el('small', '', String(f.score))); return c; }));
  });

  /* ---------- Chartist's 8 rules ---------- */
  dash.draw('rule_lim', (b) => { const d = dash.data('floor_rules'); const r = d.status === 'ok' ? d.data.find((x) => x.n === Number(b.dataset.k)) : null; b.textContent = r ? r.show : '—'; });
  dash.draw('rule_val', (b) => { const r = E.focus, k = 'v' + b.dataset.k; if (!r) { b.textContent = '—'; b.removeAttribute('data-where'); return; } b.textContent = r[k] || '·'; CD.mark(b, 'floor_rows', k, where(r)); });
  dash.draw('rule_note', (p) => { const r = E.focus; p.textContent = !r ? '—' : r.failed ? `${r.label} · out at rule ${r.failed} of 8` : `${r.label} · 8 of 8 clear`; p.classList.toggle('down', !!(r && r.failed)); p.classList.toggle('up', !!(r && !r.failed)); });

  /* ---------- the screen score ---------- */
  dash.draw('sc_max', (b) => { const d = dash.data('floor_rules'); if (d.status !== 'ok') { b.textContent = '—'; return; }
    d.data.forEach((x) => { if (x.kind === 'part') MAXP[x.key] = x.limit; if (x.kind === 'bar') BAR[x.key] = x.limit; }); const r = d.data.find((x) => x.key === 'f' + b.dataset.k); b.textContent = r ? r.show : '—'; });
  dash.draw('sc_val', (b) => { const r = E.scored, k = 'f' + b.dataset.k; if (!r) { b.textContent = '—'; b.removeAttribute('data-where'); return; } b.textContent = String(r[k]); CD.mark(b, 'floor_rows', k, where(r)); });
  dash.draw('sc_name', (em) => { em.textContent = E.scored ? `${E.scored.label} · ${E.scored.lists}` : 'waiting for a name to clear the rules'; });
  dash.draw('sc_gauge', (box) => {
    const r = E.scored; box.replaceChildren(); const W = 240, H = 146; const s = CD.svg(box, W, H, r ? `Screen score for ${r.label}: ${r.score} out of 100` : 'Screen score gauge, waiting for a name');
    const g = s.append('g').attr('transform', `translate(${W / 2},${H - 26})`); const A = (v) => -Math.PI / 2 + (Math.max(0, Math.min(100, v)) / 100) * Math.PI; const arc = d3.arc().innerRadius(74).outerRadius(88).cornerRadius(3);
    g.append('path').attr('d', arc({ startAngle: A(0), endAngle: A(100) })).attr('fill', '#14233f');
    const col = !r ? PAL.dim : r.score >= BAR.setup ? PAL.green : r.score >= BAR.watch ? PAL.amber : PAL.mut;
    if (r) g.append('path').attr('d', arc({ startAngle: A(0), endAngle: A(r.score) })).attr('fill', col);
    ['watch', 'setup'].forEach((k) => { if (BAR[k] == null) return; const a = A(BAR[k]) - Math.PI / 2; g.append('line').attr('x1', Math.cos(a) * 70).attr('y1', Math.sin(a) * 70).attr('x2', Math.cos(a) * 93).attr('y2', Math.sin(a) * 93).attr('stroke', '#e8eef9').attr('stroke-width', 1.5);
      g.append('text').attr('x', Math.cos(a) * 104).attr('y', Math.sin(a) * 104 + 3).attr('text-anchor', 'middle').style('fill', PAL.mut).style('font', '10px ui-monospace, Menlo, monospace').text(String(BAR[k])); });
    const big = g.append('text').attr('text-anchor', 'middle').attr('y', -14).style('fill', '#fff').style('font', '650 34px ui-monospace, Menlo, monospace').text(r ? String(r.score) : '—'); if (r) CD.mark(big.node(), 'floor_rows', 'score', where(r));
    g.append('text').attr('text-anchor', 'middle').attr('y', 6).style('fill', col).style('font', '700 11px ui-monospace, Menlo, monospace').style('letter-spacing', '1px').text(r ? (r.verdict === 'PASS' ? 'DROPPED' : r.verdict) : 'NO NAME YET');
  });

  /* ---------- paper book, decisions, Warden's ladder ---------- */
  const PS = { equity: (v) => inr(v), pnl: (v) => (v > 0 ? '+' : '') + inr(v), confidence: (v) => pct(v, 0, false), drawdown: (v) => pct(v, 1, false), win_rate: (v) => pct(v, 0, false) };
  dash.draw('fl_ps', (b) => { const d = dash.data('paper_stats'), k = b.dataset.k; if (d.status !== 'ok' || !d.data.length) { b.textContent = '—'; return; } const v = d.data[0][k]; b.textContent = PS[k] ? PS[k](v) : String(v);
    if (k === 'pnl') { b.classList.toggle('up', v > 0); b.classList.toggle('down', v < 0); } });
  dash.draw('fl_spark', (box) => { const r = need(box, ['paper_equity']); if (!r) return; box.replaceChildren(); const v = r[0].map((e) => e.equity);
    if (v.length < 2) { box.appendChild(el('p', 'note', 'The equity line starts once there are two days of paper trading.')); return; } CD.spark(box, v, v[v.length - 1] >= v[0] ? PAL.green : PAL.red, 260, 46); });
  dash.draw('fl_decide', (box) => {
    const r = need(box, ['paper_live', 'floor_rows']); if (!r) return; const out = [];
    r[0].forEach((p) => { const w = 'id=' + p.id; const c = el('div', 'dec'), h = el('div', 'dec-h'); h.append(el('b', '', `${p.symbol} · paper ${p.status === 'OPEN' ? 'position' : 'order'}`), tag(p.status === 'OPEN' ? 'OPEN' : 'FILLS AT THE OPEN', p.status === 'OPEN' ? 'g' : 'a'));
      const t = el('p', 'sub num'); t.append('entry ', mk(num(p.entry, 2), '', 'paper_live', 'entry', w), ' · stop ', mk(num(p.stop, 2), '', 'paper_live', 'stop', w)); if (p.target !== null) t.append(' · target ', mk(num(p.target, 2), '', 'paper_live', 'target', w));
      if (p.live !== null) t.append(' · now ', mk(num(p.live, 2), '', 'paper_live', 'live', w), ' (', mk(pct(p.move_pct, 1), cls(p.move_pct), 'paper_live', 'move_pct', w), ')'); c.append(h, t); out.push(c); });
    r[1].filter((x) => x.verdict === 'SETUP').sort((a, b) => b.score - a.score).slice(0, 3).forEach((x) => { const c = el('div', 'dec'), h = el('div', 'dec-h'), b = el('b'); b.append(`${x.label} · setup, score `, mk(String(x.score), '', 'floor_rows', 'score', where(x))); h.append(b, tag('WATCH ONLY', 'b'));
      c.append(h, el('p', 'sub', x.blocked ? `Too big for the paper account: ${x.blocked}.` : `Would be ${x.qty} shares on paper. It goes through the morning research run first.`)); out.push(c); });
    if (!out.length) out.push(el('div', 'empty', 'Nothing needs you right now. The desks keep looking.')); box.replaceChildren(...out);
  });
  dash.draw('fl_ladder', (box) => {
    const r = E.sized; box.replaceChildren(); if (!r) { box.appendChild(el('div', 'empty', 'Warden draws the entry, stop and target here when a name reaches the watch bar.')); return; }
    const W = Math.max(220, box.clientWidth), H = 138, x0 = 8, x1 = W - 8; const s = CD.svg(box, W, H, `Paper entry, stop and target for ${r.label}`); const y = d3.scaleLinear([r.stop, r.target_px], [H - 16, 16]);
    s.append('rect').attr('x', x0).attr('width', x1 - x0).attr('y', y(r.target_px)).attr('height', y(r.price) - y(r.target_px)).attr('fill', PAL.green).attr('opacity', 0.1);
    s.append('rect').attr('x', x0).attr('width', x1 - x0).attr('y', y(r.price)).attr('height', y(r.stop) - y(r.price)).attr('fill', PAL.red).attr('opacity', 0.17);
    [['Target', r.target_px, PAL.green, 'target_px'], ['Entry now', r.price, '#e8eef9', 'price'], ['Stop', r.stop, PAL.red, 'stop']].forEach(([lab, v, c, f]) => { const d = Math.round((v / r.price - 1) * 100);
      s.append('line').attr('x1', x0).attr('x2', x1).attr('y1', y(v)).attr('y2', y(v)).attr('stroke', c).attr('stroke-width', 1.4);
      s.append('text').attr('x', x0 + 4).attr('y', y(v) - 4).style('fill', c).text(d ? `${lab} ${pct(d, 0)}` : lab);
      CD.mark(s.append('text').attr('x', x1 - 4).attr('y', y(v) - 4).attr('text-anchor', 'end').style('fill', c).text(num(v, 2)).node(), 'floor_rows', f, where(r)); });
    const cap = el('p', 'sub'); cap.style.marginTop = '6px'; cap.textContent = r.blocked ? `${r.label}: ${r.blocked}.` : `${r.label} on paper: ${r.qty} shares, ${inr(r.value)}, risk ${inr(r.risk_rs)}.`; box.appendChild(cap);
  });

  /* ---------- the log and the activity strip ---------- */
  dash.draw('fl_log', (box) => {
    const rows = E.log.slice(-14); if (!rows.length) { box.textContent = '—'; return; }
    box.replaceChildren(...rows.map((l) => { const p = el('p', 'ln ' + l.tone); p.append(el('time', '', l.t), el('b', '', l.name.toUpperCase()), el('span', '', l.text)); return p; })); box.scrollTop = box.scrollHeight;
  });
  dash.draw('fl_timeline', (box) => {
    const h = E.hist.slice(-80); box.replaceChildren(); if (!h.length) { box.textContent = '—'; return; }
    const W = Math.max(260, box.clientWidth), H = 88, mid = 46, bw = (W - 8) / 80;
    const s = CD.svg(box, W, H, 'Desk activity over the last steps, newest on the right. Red marks are names killed by a rule; green and amber marks are names that were scored.');
    s.append('line').attr('x1', 4).attr('x2', W - 4).attr('y1', mid).attr('y2', mid).attr('stroke', '#1c2c48'); let lastLab = -99;
    h.forEach((e, i) => { const x = W - 4 - (h.length - i) * bw + bw / 2, a = 4 + Math.min(24, e.len / 7), c = COL[e.tone] || PAL.cyan, key = e.kill || e.verdict;
      s.append('rect').attr('x', x - Math.max(1, bw * 0.3)).attr('width', Math.max(2, bw * 0.6)).attr('y', mid - a).attr('height', a * 2).attr('rx', 1.5).attr('fill', c).attr('opacity', key ? 0.95 : 0.45);
      if (key && i - lastLab >= 6) { lastLab = i; s.append('text').attr('x', Math.min(W - 34, Math.max(34, x))).attr('y', e.kill ? H - 3 : 10).attr('text-anchor', 'middle').style('fill', c).style('font-size', '9.5px').text(e.kill ? '✗ ' + e.sym : `${e.sym} ${e.score}`); } });
  });

  /* ---------- what the engine changes outside the drawings: classes and bar widths only ---------- */
  const last = { focus: null, scored: null, sized: null };
  const paintRules = (flash) => document.querySelectorAll('#rules-list li').forEach((li) => { const k = Number(li.dataset.rule), v = E.focus ? E.focus['r' + k] : '';
    li.classList.remove('pass', 'fail', 'skip'); if (flash) void li.offsetWidth; if (v) li.classList.add(v); li.style.setProperty('--i', String(k - 1)); });
  const paintScore = () => document.querySelectorAll('.fbar').forEach((b) => { const k = 'f' + b.dataset.f, r = E.scored; b.style.width = r && MAXP[k] ? Math.round((r[k] / MAXP[k]) * 100) + '%' : '0%'; });
  E.on((s) => {
    if (s) { document.querySelectorAll('.desk').forEach((n) => n.classList.toggle('on', n.dataset.agent === s.agent || (!!s.ceo && n.dataset.agent === 'CEO')));
      document.querySelectorAll('#floor-phases [data-ph]').forEach((n) => n.classList.toggle('on', Number(n.dataset.ph) === AG[s.agent].ph)); }
    ['fl_num', 'fl_note', 'desk_chip', 'desk_n', 'desk_now', 'fl_flow'].forEach((n) => dash.draw(n));
    if (s) ['fl_say', 'fl_log', 'fl_timeline'].forEach((n) => dash.draw(n));
    if (!s || E.focus !== last.focus) { paintRules(!!s); last.focus = E.focus; dash.draw('rule_val'); dash.draw('rule_note'); }
    if (!s || E.scored !== last.scored) { last.scored = E.scored; paintScore(); ['sc_val', 'sc_name', 'sc_gauge'].forEach((n) => dash.draw(n)); }
    if (!s || E.sized !== last.sized) { last.sized = E.sized; dash.draw('fl_ladder'); }
  });

  /* ---------- controls ---------- */
  const press = (id, fn) => document.querySelectorAll('#' + id).forEach((b) => b.addEventListener('click', () => fn(b)));
  press('btn-live', () => E.setLive(!E.live.on));
  press('btn-pull', () => E.pull());
  press('btn-pause', (b) => { E.pause(!E.paused); b.setAttribute('aria-pressed', String(E.paused)); });
})();
