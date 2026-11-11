/* The floor engine. It puts the desks' sentences in order and plays them one hand-off at a time.
   It works out no market numbers of its own: each sentence is a cell of floor_rows, floor_stats
   or floor_side. The stage and the panels listen with CD.ENG.on(fn). */
(function () {
  const AG = (CD.AGENTS = {
    DATA: { name: 'Scout', init: 'DA', c: '#29d3ee', fg: '#04101c', ph: 0 }, TECH: { name: 'Chartist', init: 'TE', c: '#4f8cff', fg: '#fff', ph: 1 },
    SENT: { name: 'Pulse', init: 'SE', c: '#ff7ac6', fg: '#fff', ph: 2 }, FUND: { name: 'Ledgerhand', init: 'FU', c: '#a184ff', fg: '#fff', ph: 3 },
    CALL: { name: 'Echo', init: 'CA', c: '#ffb64a', fg: '#2a1a00', ph: 4 }, BULL: { name: 'Bull', init: 'BU', c: '#2de3a5', fg: '#04201a', ph: 5 },
    BEAR: { name: 'Bear', init: 'BE', c: '#ff5f75', fg: '#fff', ph: 5 }, RISK: { name: 'Warden', init: 'WA', c: '#ffb64a', fg: '#2a1a00', ph: 6 },
    PM: { name: 'Chief', init: 'CH', c: '#4f8cff', fg: '#fff', ph: 7 }, LEDGER: { name: 'Scribe', init: 'SC', c: '#8ea3c4', fg: '#04101c', ph: 8 },
    CEO: { name: 'CEO', init: 'CEO', c: '#cfe0ff', fg: '#04101c', ph: 7 } });
  CD.PORTS = { S1: 'INDmoney movers', S2: 'INDmoney quotes', S3: 'NSE filings', S4: 'CoinDCX crypto', S5: 'Paper ledger' };
  CD.hms = (d = new Date()) => { const t = CD.istParts(d); return [t.h, t.m, t.s].map((x) => String(x).padStart(2, '0')).join(':'); };

  const reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const inr = CD.inr; const pc = (v, d = 1) => CD.pct(v, d);
  const BATCH = 6; const SIDES = ['crypto', 'filings', 'metals', 'book', 'breakouts', 'gate', 'pending']; const DIRECT = { S3: 1, S5: 1 };
  const E = (CD.ENG = { loop: 0, total: 0, i: -1, steps: [], cur: null, paused: false, shown: false, D: null, key: '', cut: false, offset: 0, sideAt: 0, batch: [], doneBi: -1,
    desk: {}, log: [], hist: [], flow: [], focus: null, scored: null, sized: null, timer: null, subs: [], live: { on: false, n: 0, timer: null, since: 0 }, reduce });
  Object.keys(AG).forEach((k) => { E.desk[k] = { chip: k === 'CEO' ? 'WATCHING' : 'IDLE', tone: '', now: k === 'CEO' ? 'Waiting for the Chief\'s report.' : 'Waiting for the first prices.', n: 0, live: false }; });
  E.on = (fn) => { E.subs.push(fn); return () => { E.subs = E.subs.filter((f) => f !== fn); }; };
  const tell = (s) => E.subs.forEach((fn) => { try { fn(s); } catch (e) { setTimeout(() => { throw e; }, 0); } });

  /* One name's trip across the desks. A kill is one step; a survivor visits every desk. */
  const chain = (r, bi, S) => {
    const port = /watch/.test(r.src) ? 'S2' : 'S1'; const say = (o) => S.push(Object.assign({ row: r, bi }, o));
    if (r.failed) { say({ hops: [[port, 'DATA'], ['DATA', 'TECH']], agent: 'TECH', state: 'KILL', tone: 'kill', kill: true, text: `${r.label}, from ${r.src}, is out at rule ${r.failed} of 8: ${r.fail_reason}.` }); return; }
    say({ hops: [[port, 'DATA'], ['DATA', 'TECH']], agent: 'TECH', state: 'CLEAR', tone: 'ok', text: `${r.label}, from ${r.src}, clears all 8 rules at ${inr(r.price, 2)}, ${pc(r.chg_pct)} today. Over to Pulse.` });
    say({ hops: [['TECH', 'SENT']], agent: 'SENT', state: 'CROWD', tone: 'info', text: r.crowd_txt });
    say({ hops: [['SENT', 'FUND']], agent: 'FUND', state: 'SCORING', tone: 'info', score: true, text: r.fund_txt });
    say({ hops: [['S3', 'CALL']], agent: 'CALL', state: 'FILINGS', tone: 'info', text: r.echo_txt });
    say({ hops: [['FUND', 'BULL'], ['CALL', 'BULL']], agent: 'BULL', state: 'CASE', tone: 'bull', text: r.bull });
    say({ hops: [['BULL', 'BEAR']], agent: 'BEAR', state: 'COUNTER', tone: 'bear', text: r.bear });
    if (r.size_note) say({ hops: [['BEAR', 'RISK']], agent: 'RISK', state: r.blocked ? 'BLOCKED' : 'SIZING', tone: 'warn', size: true, text: r.size_note });
    say({ hops: [[r.size_note ? 'RISK' : 'BEAR', 'PM']], agent: 'PM', state: r.verdict, tone: r.verdict === 'SETUP' ? 'bull' : r.verdict === 'WATCH' ? 'warn' : 'info', verdict: r.verdict, text: r.chief_txt });
    say({ hops: [['PM', 'LEDGER']], agent: 'LEDGER', state: 'WRITE', tone: 'info', text: `Logged ${r.label}: ${r.verdict === 'PASS' ? 'dropped' : r.verdict.toLowerCase()}, score ${r.score}.` + (r.verdict === 'SETUP' ? ' It is on the CEO\'s board.' : '') });
  };

  /* The rest of a loop for the given names, always from the newest data: chains, side reports, the Chief's report. */
  const tail = (syms, bi0) => {
    const D = E.D, S = []; const by = {}; D.rows.forEach((r) => { by[r.symbol] = r; }); const side = {}; (D.side || []).forEach((r) => { side[r.key] = r; });
    const sideStep = () => { for (let k = 0; k < SIDES.length; k++) { const r = side[SIDES[(E.sideAt + k) % SIDES.length]]; if (!r || !AG[r.agent]) continue;
      E.sideAt = (E.sideAt + k + 1) % SIDES.length;
      S.push({ hops: DIRECT[r.port] || r.agent === 'DATA' ? [[r.port, r.agent]] : [[r.port, 'DATA'], ['DATA', r.agent]], agent: r.agent, state: r.state, tone: r.tone, text: r.text }); return; } };
    syms.forEach((sym, k) => { if (by[sym]) chain(by[sym], bi0 + k, S); if ((bi0 + k) % 3 === 1) sideStep(); });
    const seen = E.batch.map((s) => by[s]).filter(Boolean); const surv = seen.filter((r) => !r.failed); const best = surv.slice().sort((a, b) => b.score - a.score)[0];
    sideStep();
    if (D.stats.kill_txt && E.loop % 2 === 0) S.push({ hops: [['TECH', 'PM']], agent: 'TECH', state: 'TALLY', tone: 'info', text: D.stats.kill_txt });
    S.push({ hops: [['PM', 'CEO']], agent: 'PM', state: 'REPORT', tone: 'ask', ceo: true,
      text: `CEO, loop ${E.loop} is done. ${seen.length} names checked, ${seen.length - surv.length} killed by a rule, ${surv.length} scored.` + (best ? ` Best of the batch: ${best.label} at ${best.score}.` : ' Nothing in this batch is worth your time.') + ' Nothing is placed without you.' });
    return S;
  };

  const build = () => {
    const D = E.D; if (!D) return false; const st = D.stats, rows = D.rows; E.loop += 1; E.cut = false; E.doneBi = -1; const S = [];
    const n = Math.min(rows.length, BATCH); const batch = []; for (let k = 0; k < n; k++) batch.push(rows[(E.offset + k) % rows.length]);
    /* Keep every desk busy: if the whole batch dies at the rules, swap the last name for the next survivor. */
    if (n && batch.every((r) => r.failed)) { for (let k = 0; k < rows.length; k++) { const r = rows[(E.offset + n + k) % rows.length]; if (!r.failed && !batch.includes(r)) { batch[n - 1] = r; break; } } }
    E.offset = rows.length ? (E.offset + n) % rows.length : 0; E.batch = batch.map((r) => r.symbol);
    E.flow = batch.map((r) => ({ symbol: r.symbol, label: r.label, st: 'queue', score: null, rule: null }));
    S.push({ hops: [['S1', 'DATA'], ['S2', 'DATA']], agent: 'DATA', state: 'PULL', tone: 'info', text: `Loop ${E.loop}. ${st.scout_txt}` });
    S.push({ hops: [['DATA', 'RISK']], agent: 'RISK', state: st.regime, tone: st.regime === 'NORMAL' ? 'ok' : 'warn', text: st.regime_txt });
    if (st.idx_n) S.push({ hops: [['DATA', 'SENT']], agent: 'SENT', state: 'BREADTH', tone: st.idx_up * 2 >= st.idx_n ? 'bull' : 'bear', text: st.breadth_txt });
    E.steps = S.concat(tail(E.batch, 0)); E.i = -1; return true;
  };

  const apply = (s) => {
    s.t = CD.hms(); const d = E.desk;
    Object.keys(d).forEach((k) => { if (d[k].live) { d[k].live = false; d[k].chip = k === 'CEO' ? 'WATCHING' : 'READY'; d[k].tone = ''; } });
    const me = d[s.agent]; Object.assign(me, { chip: s.state, tone: s.tone, now: s.text, live: true }); me.n += 1;
    if (s.ceo) { Object.assign(d.CEO, { chip: 'YOUR CALL', tone: 'ask', now: s.text, live: true }); d.CEO.n += 1; }
    E.total += 1;
    if (s.bi !== undefined) { E.doneBi = Math.max(E.doneBi, s.bi); const f = E.flow[s.bi];
      if (f) { if (s.kill) { f.st = 'kill'; f.rule = s.row.failed; } else if (s.verdict) f.st = s.verdict; else if (f.st === 'queue') f.st = 'work'; if (s.score) f.score = s.row.score; } }
    if (s.agent === 'TECH' && s.row) E.focus = s.row; if (s.score) E.scored = s.row; if (s.size) E.sized = s.row;
    E.log.push({ t: s.t, agent: s.agent, name: AG[s.agent].name, text: s.text, tone: s.tone }); if (E.log.length > 80) E.log.shift();
    E.hist.push({ tone: s.tone, len: s.text.length, kill: !!s.kill, verdict: s.verdict || '', sym: s.row ? s.row.label : '', score: s.verdict ? s.row.score : null }); if (E.hist.length > 120) E.hist.shift();
    tell(s);
  };

  const dur = (s) => (reduce ? 3200 : Math.max(1500, Math.min(4600, 900 + s.text.length * 22)));
  const kick = (ms) => { clearTimeout(E.timer); E.timer = null; if (E.paused || !E.shown || !E.D) return; E.timer = setTimeout(play, ms); };
  const play = () => {
    E.timer = null; if (E.paused || !E.shown || document.hidden) return;
    const cur = E.steps[E.i], nx = E.steps[E.i + 1];
    /* Fresh prices arrived: at the next change of name, rebuild what is left of the loop from them. */
    if (E.cut && cur && (!nx || nx.bi === undefined || nx.bi !== cur.bi)) { E.steps = E.steps.slice(0, E.i + 1).concat(tail(E.batch.slice(E.doneBi + 1), E.doneBi + 1)); E.cut = false; }
    E.i += 1; if (E.i >= E.steps.length) { if (!build()) return; E.i = 0; }
    const s = (E.cur = E.steps[E.i]); if (!s) return; apply(s); kick(dur(s));
  };

  /* Called by the stage drawing each time the data or the width changes. */
  E.feed = (D) => {
    const key = [D.stats.quote_time, D.rows.length, D.rows.slice(0, 6).map((r) => r.price).join(','), (D.side || []).map((r) => r.text.length).join(',')].join('|');
    const first = !E.D; E.D = D; if (key === E.key) return; E.key = key;
    if (first || !E.steps.length) { if (build()) kick(400); return; }
    E.cut = true; const by = {}; D.rows.forEach((r) => { by[r.symbol] = r; });
    ['focus', 'scored', 'sized'].forEach((f) => { if (E[f] && by[E[f].symbol]) E[f] = by[E[f].symbol]; });
    setTimeout(() => tell(null), 0);
  };
  E.show = (on) => { E.shown = !!on; if (on) kick(300); else { clearTimeout(E.timer); E.timer = null; } };
  E.pause = (on) => { E.paused = !!on; if (on) { clearTimeout(E.timer); E.timer = null; } else kick(120); };
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !E.timer) kick(300); });

  /* Live refresh: re-reads prices from INDmoney while the market is open. Started by a press, never by itself. */
  const QUOTES = ['indices', 'watch_live'], MOVERS = ['m_gainers', 'm_52high', 'm_active', 'm_losers', 'm_upper', 'comm_live'];
  const refresh = (ids) => ids.forEach((id) => { try { dash.refresh(id); } catch (e) { /* that list keeps its last answer */ } });
  E.pull = () => refresh(QUOTES.concat(MOVERS));
  const liveTick = () => {
    const L = E.live; if (Date.now() - L.since > 30 * 60000) { E.setLive(false); return; }
    if (!E.shown || document.hidden || CD.session().key !== 'open') return;
    L.n += 1; refresh(QUOTES); if (L.n % 2 === 0) refresh(MOVERS);
  };
  E.setLive = (on) => {
    const L = E.live; clearInterval(L.timer); L.timer = null; L.on = !!on;
    if (on) { L.since = Date.now(); L.n = 0; E.pull(); L.timer = setInterval(liveTick, 60000); }
    document.querySelectorAll('#btn-live').forEach((b) => b.setAttribute('aria-pressed', String(L.on))); dash.draw('fl_mode');
  };
})();
