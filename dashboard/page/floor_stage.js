/* The stage. The desks ride a tilted ring round the CEO; whoever speaks is brought to the front,
   and their words are typed in the bubble under them. A column of light turns in the middle,
   feed dots run down from the sources, and packets carry each name from desk to desk.
   Everything here lives inside one drawing. */
(function () {
  const { el } = CD; const AG = CD.AGENTS, E = CD.ENG, reduce = E.reduce;
  const ORDER = ['DATA', 'TECH', 'SENT', 'FUND', 'CALL', 'BULL', 'BEAR', 'RISK', 'PM', 'LEDGER', 'COO'];
  const PORTS = [['S1', 'INDmoney', 'movers'], ['S2', 'INDmoney', 'quotes'], ['S3', 'NSE', 'filings'], ['S4', 'CoinDCX', 'crypto'], ['S5', 'Ledger', 'paper']];
  const TONE = { info: '#29d3ee', ok: '#2de3a5', bull: '#2de3a5', bear: '#ff5f75', kill: '#ff5f75', warn: '#ffb64a', ask: '#ffffff' };
  const TAU = Math.PI * 2; const bez = (a, m, b, u) => (1 - u) * (1 - u) * a + 2 * (1 - u) * u * m + u * u * b;
  const BASE = ORDER.map((_, i) => (i / ORDER.length) * TAU);

  dash.draw('floor_stage', {
    mount(box) {
      const cv = el('canvas', 'fl-cv'); cv.setAttribute('role', 'img');
      cv.setAttribute('aria-label', 'The floor. The desks circle the CEO; the desk that is speaking comes to the front while data packets travel between desks.');
      const layer = el('div', 'fl-layer'); const bub = el('div', 'fl-bubble'); const bh = el('div', 'fl-bubble-h'), bp = el('p', 'fl-bubble-t', 'Waking the desks…'); bub.append(bh, bp);
      box.replaceChildren(cv, layer, bub); const N = {};
      PORTS.forEach(([id, a, b]) => { const n = el('div', 'fl-port'); n.append(el('b', '', a), el('small', '', b)); layer.appendChild(n); N[id] = { el: n }; });
      ORDER.concat(['CEO']).forEach((id) => { const a = AG[id]; const n = el('div', 'fl-node' + (id === 'CEO' ? ' ceo' : '')); n.style.setProperty('--c', a.c);
        const orb = el('i', 'orb', a.init); orb.style.color = a.fg; const st = el('small', '', E.desk[id].chip); n.append(orb, el('b', '', id === 'CEO' ? 'You' : a.short), st); layer.appendChild(n); N[id] = { el: n, st, x: 0, y: 0 }; });
      const M = { cv, ctx: cv.getContext('2d'), N, W: 0, H: 0, rot: -Math.PI / 2, rotT: -Math.PI / 2, stars: [], pk: [], sparks: [], rings: [], edge: null, raf: 0, last: 0, typing: null };

      M.layout = () => {
        const W = Math.max(280, box.clientWidth); const wide = W >= 560; const top = wide ? 56 : 50;
        const rx = W / 2 - (wide ? 86 : 46), ry = wide ? Math.max(92, Math.min(128, W * 0.17)) : Math.max(64, Math.min(84, W * 0.2));
        const cy = top + ry + (wide ? 50 : 42); const H = Math.round(cy + ry + (wide ? 84 : 70) + (wide ? 96 : 118)); if (W === M.W && H === M.H) return;
        Object.assign(M, { W, H, rx, ry, cx: W / 2, cy, wide }); box.style.height = H + 'px'; box.classList.toggle('narrow', !wide);
        const dpr = Math.min(2, window.devicePixelRatio || 1); cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); M.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        PORTS.forEach(([id], i) => { const n = N[id]; n.x = W * (0.1 + 0.2 * i); n.y = 22; n.el.style.left = n.x + 'px'; n.el.style.top = n.y + 'px'; });
        Object.assign(N.CEO, { x: M.cx, y: cy }); N.CEO.el.style.left = M.cx + 'px'; N.CEO.el.style.top = cy + 'px';
        M.stars = d3.range(wide ? 70 : 40).map(() => ({ x: Math.random() * W, y: Math.random() * (cy + ry + 60), r: 0.5 + Math.random() * 1.1, p: Math.random() * TAU }));
        M.pk = []; M.sparks = []; M.rings = []; M.place(); if (reduce) M.still(E.cur);
      };
      /* where each desk stands now: the front of the ring is nearer, so it is larger and brighter */
      M.place = () => ORDER.forEach((id, i) => { const n = N[id], th = BASE[i] + M.rot, d = (Math.sin(th) + 1) / 2;
        n.x = M.cx + M.rx * Math.cos(th); n.y = M.cy + M.ry * Math.sin(th); n.d = d;
        n.el.style.left = n.x + 'px'; n.el.style.top = n.y + 'px'; n.el.style.transform = `scale(${(0.7 + 0.42 * d).toFixed(3)})`; n.el.style.zIndex = String(10 + Math.round(d * 20)); n.el.style.opacity = (0.5 + 0.5 * d).toFixed(2); });
      const mid = (a, b, from) => { const sx = (a.x + b.x) / 2, sy = (a.y + b.y) / 2, pull = CD.PORTS[from] ? 0 : 0.4; return [sx + (M.cx - sx) * pull, sy + (M.cy - 30 - sy) * pull]; };

      M.base = (ctx, t) => {
        const { W, H, cx, cy, rx, ry } = M; ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = '#bcd2ff'; M.stars.forEach((s) => { ctx.globalAlpha = 0.18 + 0.3 * (0.5 + 0.5 * Math.sin(s.p + t * 0.0012)); ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, TAU); ctx.fill(); });
        ctx.globalAlpha = 1; ctx.lineWidth = 1.2; const g = ctx.createLinearGradient(0, cy - ry, 0, cy + ry); g.addColorStop(0, 'rgba(96,140,220,0.12)'); g.addColorStop(1, 'rgba(120,180,255,0.6)');
        ctx.strokeStyle = g; ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, TAU); ctx.stroke();
        ctx.strokeStyle = 'rgba(96,140,220,0.10)'; ctx.beginPath(); ctx.ellipse(cx, cy, rx * 0.62, ry * 0.62, 0, 0, TAU); ctx.stroke();
        ORDER.forEach((id) => { const n = N[id]; ctx.strokeStyle = `rgba(120,170,255,${(0.05 + 0.13 * n.d).toFixed(3)})`; ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(cx, cy); ctx.stroke(); });
      };
      M.still = (s) => { const ctx = M.ctx; M.rot = M.rotT; M.place(); M.base(ctx, 0); if (!s) return; ctx.strokeStyle = TONE[s.tone] || TONE.info; ctx.lineWidth = 2;
        s.hops.forEach((h) => { const a = N[h[0]], b = N[h[1]]; if (!a || !b) return; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }); };

      M.frame = (t) => {
        M.raf = 0; if (document.hidden || !E.shown || !box.isConnected) return;
        const ctx = M.ctx, { cx, cy, rx, ry } = M; const dt = Math.min(60, t - (M.last || t)); M.last = t;
        M.rot += (M.rotT - M.rot) * Math.min(1, dt * 0.0045); M.place(); M.base(ctx, t); ctx.globalCompositeOperation = 'lighter';
        /* the column of light: strands that pinch at the CEO and fan out above and below */
        const hh = ry * 1.35; for (let k = 0; k < 14; k++) { ctx.beginPath(); for (let j = 0; j <= 36; j++) { const u = j / 18 - 1, amp = (0.1 + 0.9 * u * u) * rx * 0.36;
            const x = cx + amp * Math.sin(u * 3.4 + k * TAU / 14 + t * 0.0011), y = cy + u * hh; if (j) ctx.lineTo(x, y); else ctx.moveTo(x, y); }
          ctx.strokeStyle = ['#29d3ee', '#4f8cff', '#a184ff', '#7fa8ff'][k % 4]; ctx.globalAlpha = 0.2 + 0.14 * Math.sin(t * 0.002 + k); ctx.lineWidth = 1.3; ctx.stroke(); }
        ctx.globalAlpha = 1; const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, ry * 1.1); g.addColorStop(0, `rgba(150,190,255,${0.36 + 0.1 * Math.sin(t * 0.003)})`); g.addColorStop(1, 'rgba(150,190,255,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, ry * 1.1, 0, TAU); ctx.fill();
        /* feed dots from every source down to the Market Data desk, and a current round the ring */
        ctx.fillStyle = '#29d3ee'; PORTS.forEach(([id], i) => { const a = N[id], b = N.DATA; for (let j = 0; j < 4; j++) { const u = (t * 0.0004 + i * 0.17 + j / 4) % 1; ctx.globalAlpha = 0.2 + 0.6 * u; ctx.beginPath(); ctx.arc(a.x + (b.x - a.x) * u, a.y + 14 + (b.y - a.y - 14) * u, 1.8, 0, TAU); ctx.fill(); } });
        ctx.fillStyle = '#9fc0ff'; for (let j = 0; j < 28; j++) { const a = t * 0.0003 + (j / 28) * TAU, d = (Math.sin(a) + 1) / 2; ctx.globalAlpha = 0.15 + 0.6 * d; ctx.beginPath(); ctx.arc(cx + rx * Math.cos(a), cy + ry * Math.sin(a), 1 + 1.4 * d, 0, TAU); ctx.fill(); }
        /* the hand-off being played */
        if (M.edge && t - M.edge.t0 < 3200) { ctx.setLineDash([6, 7]); ctx.lineDashOffset = -t * 0.05; ctx.strokeStyle = M.edge.c; ctx.lineWidth = 2.2; ctx.globalAlpha = 0.9 * Math.max(0, 1 - (t - M.edge.t0) / 3200);
          M.edge.hops.forEach((h) => { const a = N[h[0]], b = N[h[1]]; if (!a || !b) return; const m = mid(a, b, h[0]); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(m[0], m[1], b.x, b.y); ctx.stroke(); }); ctx.setLineDash([]); }
        M.pk = M.pk.filter((k) => { const u = (t - k.t0) / k.dur; if (u < 0) return true; if (u >= 1) { if (k.hit) k.hit(t); return false; }
          const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2, m = mid(k.a, k.b, k.from); let x = 0, y = 0; ctx.fillStyle = k.c;
          for (let j = 8; j >= 0; j--) { const uu = Math.max(0, e - j * 0.026); x = bez(k.a.x, m[0], k.b.x, uu); y = bez(k.a.y, m[1], k.b.y, uu); ctx.globalAlpha = 0.95 - j * 0.1; ctx.beginPath(); ctx.arc(x, y, 5.5 - j * 0.5, 0, TAU); ctx.fill(); }
          ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.arc(x, y, 15, 0, TAU); ctx.fill();
          if (k.label) { ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.font = '600 10px ui-monospace, Menlo, Consolas, monospace'; const w = ctx.measureText(k.label).width, lx = Math.max(4, Math.min(M.W - w - 12, x + 9));
            ctx.fillStyle = 'rgba(7,12,24,0.9)'; ctx.fillRect(lx, y - 17, w + 8, 14); ctx.fillStyle = '#e8eef9'; ctx.fillText(k.label, lx + 4, y - 6.5); ctx.globalCompositeOperation = 'lighter'; }
          return true; });
        M.rings = M.rings.filter((r) => { const u = (t - r.t0) / 700; if (u >= 1) return false; ctx.globalAlpha = 0.9 * (1 - u); ctx.strokeStyle = r.c; ctx.lineWidth = 2.4; ctx.beginPath(); ctx.arc(r.n.x, r.n.y, (r.n === N.CEO ? 36 : 24) + 34 * u, 0, TAU); ctx.stroke(); return true; });
        M.sparks = M.sparks.filter((s) => { const u = (t - s.t0) / 700; if (u < 0) return true; if (u >= 1) return false; ctx.globalAlpha = 1 - u; ctx.strokeStyle = s.c; ctx.lineWidth = 1.8;
          ctx.beginPath(); ctx.moveTo(s.n.x + s.vx * u * 0.5, s.n.y + s.vy * u * 0.5); ctx.lineTo(s.n.x + s.vx * u, s.n.y + s.vy * u); ctx.stroke(); return true; });
        ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; M.raf = requestAnimationFrame(M.frame);
      };
      M.run = () => { if (!reduce && !M.raf) { M.last = 0; M.raf = requestAnimationFrame(M.frame); } };
      M.send = (from, to, c, label, delay, hit) => { const a = N[from], b = N[to]; if (a && b) M.pk.push({ a, b, from, c, label, t0: performance.now() + delay, dur: 1000, hit }); };
      M.burst = (n, c, t) => { for (let i = 0; i < 18; i++) { const a = (i / 18) * TAU + Math.random() * 0.4, v = 26 + Math.random() * 34; M.sparks.push({ n, vx: Math.cos(a) * v, vy: Math.sin(a) * v, t0: t, c }); } };
      M.sync = () => Object.keys(N).forEach((id) => { if (N[id].st) N[id].st.textContent = E.desk[id].chip; });
      M.say = (s) => { clearInterval(M.typing); const a = AG[s.agent], c = TONE[s.tone] || TONE.info; bub.style.setProperty('--t', c);
        const av = el('i', 'orb', a.init); av.style.background = a.c; av.style.color = a.fg; bh.replaceChildren(av, el('b', '', a.name), el('span', 'st', s.state), el('time', 'num', s.t));
        if (reduce) { bp.textContent = s.text; return; } let i = 0; const jump = Math.max(1, Math.ceil(s.text.length / 40)), caret = el('i', 'caret');
        M.typing = setInterval(() => { i = Math.min(s.text.length, i + jump); bp.textContent = s.text.slice(0, i); if (i >= s.text.length) clearInterval(M.typing); else bp.appendChild(caret); }, 28); };

      M.step = (s) => {
        const c = TONE[s.tone] || TONE.info, ports = {}; s.hops.forEach((h) => { ports[h[0]] = 1; });
        Object.keys(N).forEach((id) => N[id].el.classList.toggle('on', id === s.agent || (!!s.ceo && id === 'CEO') || !!(CD.PORTS[id] && ports[id]))); M.sync(); M.say(s);
        const want = Math.PI / 2 - BASE[ORDER.indexOf(s.agent)]; M.rotT = want + TAU * Math.round((M.rot - want) / TAU);   /* bring the speaker to the front the short way round */
        if (reduce) { M.still(s); return; }
        M.edge = { hops: s.hops, c, t0: performance.now() };
        s.hops.forEach((h, i) => { const lastHop = i === s.hops.length - 1, chained = i > 0 && s.hops[i - 1][1] === h[0], at = chained ? 820 : i * 170;
          const land = (t) => { M.rings.push({ n: N[h[1]], c, t0: t }); if (lastHop && s.kill) M.burst(N[h[1]], c, t); };
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
    unmount(box, M) { cancelAnimationFrame(M.raf); M.raf = 0; clearInterval(M.typing); if (M.off) M.off(); document.removeEventListener('visibilitychange', M.vis); },
  });
})();
