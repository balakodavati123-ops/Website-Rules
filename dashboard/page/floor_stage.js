/* The stage: the data sources along the top, ten desks on a ring, the CEO in the middle. Packets of
   data travel along each hand-off the engine plays. Everything here lives inside one drawing. */
(function () {
  const { el } = CD; const AG = CD.AGENTS, E = CD.ENG, reduce = E.reduce;
  const ORDER = ['DATA', 'TECH', 'SENT', 'FUND', 'CALL', 'BULL', 'BEAR', 'RISK', 'PM', 'LEDGER', 'COO'];
  const PORTS = [['S1', 'INDmoney', 'movers'], ['S2', 'INDmoney', 'quotes'], ['S3', 'NSE', 'filings'], ['S4', 'CoinDCX', 'crypto'], ['S5', 'Ledger', 'paper']];
  const TONE = { info: '#29d3ee', ok: '#2de3a5', bull: '#2de3a5', bear: '#ff5f75', kill: '#ff5f75', warn: '#ffb64a', ask: '#ffffff' };
  const TAU = Math.PI * 2; const bez = (a, m, b, u) => (1 - u) * (1 - u) * a + 2 * (1 - u) * u * m + u * u * b;

  dash.draw('floor_stage', {
    mount(box) {
      const cv = el('canvas', 'fl-cv'); cv.setAttribute('role', 'img');
      cv.setAttribute('aria-label', 'The floor. Data moves from five sources to the Market Data Analyst, around the ring of desks, and from the Trading Officer and the COO to the CEO in the middle.');
      const layer = el('div', 'fl-layer'); box.replaceChildren(cv, layer); const N = {};
      PORTS.forEach(([id, a, b]) => { const n = el('div', 'fl-port'); n.append(el('b', '', a), el('small', '', b)); layer.appendChild(n); N[id] = { el: n }; });
      ORDER.concat(['CEO']).forEach((id) => { const a = AG[id]; const n = el('div', 'fl-node' + (id === 'CEO' ? ' ceo' : '')); n.style.setProperty('--c', a.c);
        const orb = el('i', 'orb', a.init); orb.style.color = a.fg; const st = el('small', '', E.desk[id].chip); n.append(orb, el('b', '', id === 'CEO' ? 'You' : a.short), st); layer.appendChild(n); N[id] = { el: n, st }; });
      const M = { cv, ctx: cv.getContext('2d'), N, W: 0, H: 0, parts: [], pk: [], sparks: [], rings: [], edge: null, raf: 0, last: 0 };

      M.layout = () => {
        const W = Math.max(280, box.clientWidth); const wide = W >= 560; const top = wide ? 54 : 48;
        const ry = wide ? Math.min(170, Math.max(120, W * 0.25)) : Math.min(150, Math.max(104, W * 0.34)); const rx = W / 2 - (wide ? 70 : 42);
        const H = Math.round(top + 2 * ry + (wide ? 112 : 96)); if (W === M.W && H === M.H) return;
        Object.assign(M, { W, H, rx, ry, cx: W / 2, cy: top + ry + (wide ? 38 : 34) }); box.style.height = H + 'px'; box.classList.toggle('narrow', !wide);
        const dpr = Math.min(2, window.devicePixelRatio || 1); cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); M.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const put = (id, x, y) => { Object.assign(N[id], { x, y }); N[id].el.style.left = x + 'px'; N[id].el.style.top = y + 'px'; };
        PORTS.forEach(([id], i) => put(id, W * (0.1 + 0.2 * i), 22));
        ORDER.forEach((id, i) => { const a = -Math.PI / 2 + (i / ORDER.length) * TAU; put(id, M.cx + rx * Math.cos(a), M.cy + ry * Math.sin(a)); });
        put('CEO', M.cx, M.cy); M.pk = []; M.sparks = []; M.rings = [];
        M.parts = reduce ? [] : d3.range(wide ? 120 : 64).map((i) => ({ a: Math.random() * TAU, r: 0.14 + Math.random() * 0.86, w: 0.5 + Math.random() * 0.9, z: Math.random() * TAU, c: ['#29d3ee', '#4f8cff', '#a184ff'][i % 3] }));
        if (reduce) M.still(E.cur);
      };

      /* The fixed wiring: the ring, a spoke from each desk to the CEO, a feed line from each source to Scout. */
      M.base = (ctx) => {
        const { W, H, cx, cy, rx, ry } = M; ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H); ctx.lineWidth = 1; ctx.setLineDash([2, 6]);
        ctx.strokeStyle = 'rgba(96,140,220,0.32)'; ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, TAU); ctx.stroke();
        ctx.strokeStyle = 'rgba(96,140,220,0.14)'; ORDER.forEach((id) => { ctx.beginPath(); ctx.moveTo(N[id].x, N[id].y); ctx.lineTo(cx, cy); ctx.stroke(); });
        ctx.strokeStyle = 'rgba(41,211,238,0.17)'; PORTS.forEach(([id]) => { ctx.beginPath(); ctx.moveTo(N[id].x, N[id].y + 14); ctx.lineTo(N.DATA.x, N.DATA.y); ctx.stroke(); });
        ctx.setLineDash([]);
      };
      const mid = (a, b, from) => { const sx = (a.x + b.x) / 2, sy = (a.y + b.y) / 2; const pull = CD.PORTS[from] ? 0 : 0.35; return [sx + (M.cx - sx) * pull, sy + (M.cy - sy) * pull]; };
      M.still = (s) => { const ctx = M.ctx; M.base(ctx); if (!s) return; ctx.strokeStyle = TONE[s.tone] || TONE.info; ctx.lineWidth = 2;
        s.hops.forEach((h) => { const a = N[h[0]], b = N[h[1]]; if (!a || !b) return; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }); };

      M.frame = (t) => {
        M.raf = 0; if (document.hidden || !E.shown || !box.isConnected) return;
        const ctx = M.ctx, { cx, cy, rx, ry } = M; const dt = Math.min(60, t - (M.last || t)); M.last = t; M.base(ctx); ctx.globalCompositeOperation = 'lighter';
        /* the vortex: arcs of light turning round the CEO, faster and brighter near the middle */
        M.parts.forEach((p) => { p.a += dt * 0.00055 * p.w / (0.3 + p.r); const k = 0.62 * p.r; ctx.beginPath(); ctx.ellipse(cx, cy + Math.sin(p.z + t * 0.0005) * 5, rx * k, ry * k, 0, p.a - (0.75 - 0.5 * p.r), p.a);
          ctx.strokeStyle = p.c; ctx.globalAlpha = 0.08 + 0.5 * (1 - p.r); ctx.lineWidth = 0.7 + 1.8 * (1 - p.r); ctx.stroke(); });
        ctx.globalAlpha = 1; const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, ry * 0.8); g.addColorStop(0, 'rgba(140,180,255,0.34)'); g.addColorStop(1, 'rgba(140,180,255,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, ry * 0.8, 0, TAU); ctx.fill();
        /* always-on streams: feed dots running from each source down to Scout, and a slow current round the ring */
        ctx.fillStyle = '#29d3ee'; PORTS.forEach(([id], i) => { const a = N[id], b = N.DATA; for (let j = 0; j < 3; j++) { const u = (t * 0.00042 + i * 0.17 + j / 3) % 1; ctx.globalAlpha = 0.25 + 0.5 * u; ctx.beginPath(); ctx.arc(a.x + (b.x - a.x) * u, a.y + 14 + (b.y - a.y - 14) * u, 1.7, 0, TAU); ctx.fill(); } });
        ctx.fillStyle = '#7fa8ff'; for (let j = 0; j < 20; j++) { const a = t * 0.00022 + (j / 20) * TAU; ctx.globalAlpha = 0.5; ctx.beginPath(); ctx.arc(cx + rx * Math.cos(a), cy + ry * Math.sin(a), 1.5, 0, TAU); ctx.fill(); }
        ctx.globalAlpha = 1;
        /* the hand-off being played: a lit, moving line */
        if (M.edge && t - M.edge.t0 < 3200) { ctx.setLineDash([5, 7]); ctx.lineDashOffset = -t * 0.045; ctx.strokeStyle = M.edge.c; ctx.lineWidth = 2; ctx.globalAlpha = 0.85 * Math.max(0, 1 - (t - M.edge.t0) / 3200);
          M.edge.hops.forEach((h) => { const a = N[h[0]], b = N[h[1]]; if (!a || !b) return; const m = mid(a, b, h[0]); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(m[0], m[1], b.x, b.y); ctx.stroke(); }); ctx.setLineDash([]); }
        /* packets: a bright head with a short tail, carrying the name being worked on */
        M.pk = M.pk.filter((k) => { const u = (t - k.t0) / k.dur; if (u < 0) return true; if (u >= 1) { if (k.hit) k.hit(t); return false; }
          const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2; let x = 0, y = 0; ctx.fillStyle = k.c;
          for (let j = 7; j >= 0; j--) { const uu = Math.max(0, e - j * 0.028); x = bez(k.a.x, k.mx, k.b.x, uu); y = bez(k.a.y, k.my, k.b.y, uu); ctx.globalAlpha = 0.95 - j * 0.12; ctx.beginPath(); ctx.arc(x, y, 5 - j * 0.5, 0, TAU); ctx.fill(); }
          ctx.globalAlpha = 0.22; ctx.beginPath(); ctx.arc(x, y, 13, 0, TAU); ctx.fill();
          if (k.label) { ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.font = '600 10px ui-monospace, Menlo, Consolas, monospace'; const w = ctx.measureText(k.label).width; const lx = Math.min(M.W - w - 12, x + 8);
            ctx.fillStyle = 'rgba(7,12,24,0.88)'; ctx.fillRect(lx, y - 16, w + 8, 14); ctx.fillStyle = '#e8eef9'; ctx.fillText(k.label, lx + 4, y - 5.5); ctx.globalCompositeOperation = 'lighter'; }
          return true; });
        M.rings = M.rings.filter((r) => { const u = (t - r.t0) / 620; if (u >= 1) return false; ctx.globalAlpha = 0.9 * (1 - u); ctx.strokeStyle = r.c; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.arc(r.x, r.y, (r.big ? 34 : 24) + 26 * u, 0, TAU); ctx.stroke(); return true; });
        M.sparks = M.sparks.filter((s) => { const u = (t - s.t0) / 650; if (u < 0) return true; if (u >= 1) return false; ctx.globalAlpha = 1 - u; ctx.strokeStyle = s.c; ctx.lineWidth = 1.6;
          ctx.beginPath(); ctx.moveTo(s.x + s.vx * u * 0.55, s.y + s.vy * u * 0.55); ctx.lineTo(s.x + s.vx * u, s.y + s.vy * u); ctx.stroke(); return true; });
        ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; M.raf = requestAnimationFrame(M.frame);
      };
      M.run = () => { if (!reduce && !M.raf) { M.last = 0; M.raf = requestAnimationFrame(M.frame); } };
      M.send = (from, to, c, label, delay, hit) => { const a = N[from], b = N[to]; if (!a || !b) return; const m = mid(a, b, from); M.pk.push({ a, b, mx: m[0], my: m[1], c, label, t0: performance.now() + delay, dur: 980, hit }); };
      M.burst = (id, c, t) => { const n = N[id]; for (let i = 0; i < 14; i++) { const a = (i / 14) * TAU + Math.random() * 0.4, v = 24 + Math.random() * 28; M.sparks.push({ x: n.x, y: n.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, t0: t, c }); } };
      M.sync = () => Object.keys(N).forEach((id) => { if (N[id].st) N[id].st.textContent = E.desk[id].chip; });

      M.step = (s) => {
        const c = TONE[s.tone] || TONE.info; const ports = {}; s.hops.forEach((h) => { ports[h[0]] = 1; });
        Object.keys(N).forEach((id) => N[id].el.classList.toggle('on', id === s.agent || (!!s.ceo && id === 'CEO') || !!(CD.PORTS[id] && ports[id]))); M.sync();
        if (reduce) { M.still(s); return; }
        M.edge = { hops: s.hops, c, t0: performance.now() };
        s.hops.forEach((h, i) => { const lastHop = i === s.hops.length - 1; const chained = i > 0 && s.hops[i - 1][1] === h[0];
          const at = chained ? 820 : i * 170; const land = (t) => { M.rings.push({ x: N[h[1]].x, y: N[h[1]].y, c, t0: t, big: h[1] === 'CEO' }); if (lastHop && s.kill) M.burst(h[1], c, t); };
          [0, 130, 260].forEach((d, j) => M.send(h[0], h[1], c, j === 0 && lastHop && s.row ? s.row.label : '', at + d, j === 0 ? land : null)); });
        M.run();
      };
      M.off = E.on((s) => { if (s) M.step(s); }); M.vis = () => M.run(); document.addEventListener('visibilitychange', M.vis);
      return M;
    },
    update(box, M) {
      M.layout();
      const req = ['floor_rows', 'floor_stats'].map((id) => dash.data(id)), opt = ['floor_side', 'paper_live'].map((id) => dash.data(id));
      const ok = req.every((d) => d.status === 'ok') && req[1].data.length > 0; box.classList.toggle('wait', !ok);
      if (ok) E.feed({ rows: req[0].data, stats: req[1].data[0], side: opt[0].status === 'ok' ? opt[0].data : [], paper: opt[1].status === 'ok' ? opt[1].data : [] });
      M.sync(); if (reduce) M.still(E.cur); M.run();
    },
    unmount(box, M) { cancelAnimationFrame(M.raf); M.raf = 0; if (M.off) M.off(); document.removeEventListener('visibilitychange', M.vis); },
  });
})();
