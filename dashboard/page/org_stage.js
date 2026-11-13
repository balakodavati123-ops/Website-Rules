/* The organisation. The CEO in the middle, a COO for each strategy, three trading managers under
   each COO and nine analysts under them: over a hundred desks. Each desk is a rule program, not a
   separate AI; a COO's colour is its strategy's paper profit, and a manager lights up when it is
   handling trades. Pulses show reports travelling up to the CEO. One drawing. */
(function () {
  const { el, inr, PAL } = CD; const E = CD.ENG, TAU = Math.PI * 2;
  const TEAMS = [['breakout_52w', '52-week Breakout'], ['breakout_52w_trail', 'Breakout, Trailing Exit'], ['trend_ride', 'Trend Following'], ['momentum_screen', 'Momentum'],
    ['pullback_in_uptrend', 'Pullback'], ['rsi2_dip', 'Dip Buying'], ['results_reaction', 'Results Reaction'], ['donchian_20_10', 'Crypto and Commodities']];
  const ROLES = ['Market data', 'Price action', 'Volume', 'Trend', 'Fundamentals', 'Filings', 'Sentiment', 'Noise filter', 'Risk'];

  dash.draw('org_stage', {
    mount(box) {
      const cv = el('canvas', 'fl-cv'); cv.setAttribute('role', 'img'); cv.setAttribute('aria-label', 'Organisation chart: the CEO, a chief operating officer for each strategy, their trading managers and analysts, with reports pulsing towards the CEO.');
      const tip = el('div', 'tip'); tip.style.display = 'none'; box.replaceChildren(cv, tip);
      const M = { cv, ctx: cv.getContext('2d'), tip, nodes: [], pulses: [], raf: 0, W: 0, H: 0, hot: null, last: 0 };
      const at = (n, rot) => { const a = n.a + rot * n.spin; return [M.cx + n.r * Math.cos(a), M.cy + n.r * Math.sin(a) * M.sq]; };
      M.frame = (t) => { M.raf = 0; if (document.hidden || !E.shown || !box.isConnected || !M.nodes.length) return; const ctx = M.ctx, rot = E.reduce ? 0 : t * 0.00004; ctx.clearRect(0, 0, M.W, M.H);
        M.nodes.forEach((n) => { [n.x, n.y] = at(n, rot); });
        ctx.lineWidth = 1; M.nodes.forEach((n) => { if (!n.up) return; ctx.strokeStyle = n.kind === 'coo' ? 'rgba(140,180,255,0.35)' : n.kind === 'mgr' ? 'rgba(120,160,240,0.22)' : 'rgba(90,130,210,0.12)'; ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(n.up.x, n.up.y); ctx.stroke(); });
        if (!E.reduce && t - M.last > 90) { M.last = t; const leaf = M.leaves[Math.floor(Math.random() * M.leaves.length)]; M.pulses.push({ n: leaf, t0: t }); }
        ctx.globalCompositeOperation = 'lighter'; M.pulses = M.pulses.filter((p) => { let u = (t - p.t0) / 520, n = p.n; while (u >= 1 && n.up) { u -= 1; n = n.up; } if (!n.up) return false;
          ctx.fillStyle = n.col; ctx.globalAlpha = 0.9; ctx.beginPath(); ctx.arc(n.x + (n.up.x - n.x) * u, n.y + (n.up.y - n.y) * u, n.kind === 'coo' ? 3.4 : 2.2, 0, TAU); ctx.fill(); return true; });
        ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
        M.nodes.forEach((n) => { const hot = n === M.hot; if (n.glow || hot) { ctx.globalAlpha = 0.25 + 0.15 * Math.sin(t * 0.004 + n.a); ctx.fillStyle = n.col; ctx.beginPath(); ctx.arc(n.x, n.y, n.size + 7, 0, TAU); ctx.fill(); ctx.globalAlpha = 1; }
          ctx.fillStyle = n.col; ctx.beginPath(); ctx.arc(n.x, n.y, n.size + (hot ? 2 : 0), 0, TAU); ctx.fill(); ctx.strokeStyle = '#0a1226'; ctx.lineWidth = 1.5; ctx.stroke();
          if (n.kind === 'ceo' || (n.kind === 'coo' && M.W >= 520)) { ctx.font = (n.kind === 'ceo' ? '800 12px ' : '600 10.5px ') + 'ui-sans-serif, system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.fillStyle = n.kind === 'ceo' ? '#04101c' : '#e8eef9';
            ctx.fillText(n.kind === 'ceo' ? 'CEO' : n.short, n.x, n.kind === 'ceo' ? n.y + 4 : n.y - n.size - 6); } });
        M.raf = requestAnimationFrame(M.frame); };
      M.run = () => { if (!M.raf) M.raf = requestAnimationFrame(M.frame); };
      const pick = (ev) => { const b = cv.getBoundingClientRect(), x = ev.clientX - b.left, y = ev.clientY - b.top; let best = null, bd = 18; M.nodes.forEach((n) => { const d = Math.hypot(n.x - x, n.y - y) - n.size; if (d < bd) { bd = d; best = n; } });
        M.hot = best; if (!best) { tip.style.display = 'none'; return; } tip.textContent = best.tip; tip.style.display = 'block'; tip.style.whiteSpace = 'normal'; tip.style.maxWidth = '240px';
        tip.style.left = Math.max(4, Math.min(M.W - 250, x + 12)) + 'px'; tip.style.top = Math.max(0, y - 10) + 'px'; };
      cv.addEventListener('pointermove', pick); cv.addEventListener('pointerdown', pick); cv.addEventListener('pointerleave', () => { M.hot = null; tip.style.display = 'none'; });
      cv.addEventListener('click', () => { if (M.hot && M.hot.kind !== 'ana') CD.goto('trades'); });
      M.off = E.on(() => M.run()); return M;
    },
    update(box, M) {
      const W = Math.max(280, box.clientWidth), R = Math.min(W / 2 - 8, 340), sq = W >= 560 ? 0.62 : 0.9, H = Math.round(2 * R * sq + 30);
      Object.assign(M, { W, H, cx: W / 2, cy: H / 2, sq }); box.style.height = H + 'px'; const dpr = Math.min(2, window.devicePixelRatio || 1); M.cv.width = Math.round(W * dpr); M.cv.height = Math.round(H * dpr); M.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const sb = dash.data('strategy_board'), tb = dash.data('trade_book'); const stats = {}; if (sb.status === 'ok') sb.data.forEach((s) => { stats[s.strategy] = s; }); const book = tb.status === 'ok' ? tb.data : [];
      const ceo = { kind: 'ceo', a: 0, r: 0, spin: 0, size: 17, col: '#cfe0ff', tip: 'You, the CEO. Every COO reports here, and nothing is placed without you.' }; const nodes = [ceo], leaves = [];
      TEAMS.forEach(([key, title], i) => { const s = stats[key] || {}, mine = book.filter((t) => t.strategy === key && (t.status === 'OPEN' || t.status === 'PENDING')), a0 = (i / TEAMS.length) * TAU - Math.PI / 2, span = (TAU / TEAMS.length) * 0.84;
        const pnl = Number(s.pnl) || 0, col = pnl > 0 ? PAL.green : pnl < 0 ? PAL.red : PAL.blue;
        const coo = { kind: 'coo', a: a0, r: R * 0.4, spin: 1, size: 10, col, up: ceo, short: title, glow: mine.length > 0,
          tip: `COO, ${title}. ${s.closed || 0} closed paper trades, ${mine.length} live, paper profit or loss ${inr(pnl, 0)}.` + (s.closed > 1 ? ` Confidence ${Number(s.confidence).toFixed(0)}%.` : ' Too few closed trades to judge.') };
        nodes.push(coo);
        for (let j = 0; j < 3; j++) { const has = mine.filter((_, k) => k % 3 === j); const m = { kind: 'mgr', a: a0 + (j - 1) * span / 3, r: R * 0.68, spin: 1, size: 5.5, col: has.length ? PAL.amber : '#5d7fc4', up: coo, glow: has.length > 0,
            tip: `Trading manager ${j + 1}, ${title}. ` + (has.length ? 'Handling ' + has.map((t) => `${t.symbol} (${t.status.toLowerCase()})`).join(', ') + '.' : 'No trade on this desk right now.') };
          nodes.push(m); for (let k = 0; k < 3; k++) { const idx = j * 3 + k; const an = { kind: 'ana', a: a0 + (idx - 4) * span / 9, r: R * (0.9 + 0.08 * (idx % 2)), spin: 1, size: 3, col: '#29d3ee', up: m, tip: `${ROLES[idx]} analyst, ${title}. Feeds trading manager ${j + 1}.` }; nodes.push(an); leaves.push(an); } } });
      M.nodes = nodes; M.leaves = leaves; M.pulses = []; CD.orgCount = nodes.length; if (E.reduce) { E.shown = E.shown; } M.run();
    },
    unmount(box, M) { cancelAnimationFrame(M.raf); M.raf = 0; if (M.off) M.off(); },
  });
  dash.draw('org_count', (b) => { b.textContent = CD.orgCount ? String(CD.orgCount) : '—'; });
})();
