/* Money flow through the desks. Every line is one stock on the live INDmoney lists. It streams in
   from the left, is squeezed through the chain of desks in the middle, and leaves upward in cyan if
   it cleared all eight rules or downward in orange if a rule killed it, ending at the ranked lists
   on the right. The desk that is working now is lit, and so is the line of the stock it is working
   on. Tap a name to open its chart. One drawing; nothing here is a forecast. */
(function () {
  const { el } = CD; const AG = CD.AGENTS, E = CD.ENG, TAU = Math.PI * 2;
  const CHAIN = ['DATA', 'TECH', 'SENT', 'FUND', 'CALL', 'BULL', 'BEAR', 'RISK', 'PM', 'LEDGER', 'COO'];
  const bz = (a, b, c, d, u) => { const v = 1 - u; return v * v * v * a + 3 * v * v * u * b + 3 * v * u * u * c + u * u * u * d; };
  const UP = '41,211,238', DN = '255,140,80', RAW = '120,160,235';
  const pc = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2) + '%';
  const fit = (ctx, s, w) => { if (ctx.measureText(s).width <= w) return s; let t = s; while (t.length > 3 && ctx.measureText(t + '…').width > w) t = t.slice(0, -1); return t + '…'; };

  dash.draw('flow_stage', {
    mount(box) {
      const cv = el('canvas', 'fl-cv'); cv.setAttribute('role', 'img');
      cv.setAttribute('aria-label', 'Flow of stocks through the desks: lines enter from the left, pass the chain of desks, and leave upward to the list of names that cleared the rules or downward to the list a rule removed.');
      box.replaceChildren(cv);
      const M = { cv, ctx: cv.getContext('2d'), lines: [], top: [], bot: [], slots: [], ph: {}, raf: 0, W: 0, H: 0, st: null };

      M.pos = (L, u) => { const g = M.g; if (u < 0.42) { const k = u / 0.42; return [bz(0, g.xa * 0.55, g.xa * 0.72, g.xa, k), bz(L.y0, L.y0, g.cy, g.cy, k)]; }
        if (u < 0.58) return [g.xa + (g.xb - g.xa) * ((u - 0.42) / 0.16), g.cy];
        const k = (u - 0.58) / 0.42, dx = g.xl - g.xb; return [bz(g.xb, g.xb + dx * 0.45, g.xb + dx * 0.55, g.xl, k), bz(g.cy, g.cy, L.yt, L.yt, k)]; };

      M.paint = (t, moving) => {
        const ctx = M.ctx, g = M.g, cur = E.cur, hotSym = cur && cur.row ? cur.row.symbol : '', wide = g.wide; ctx.clearRect(0, 0, M.W, M.H);
        /* the wires: grey-blue until the desks have judged the name, then its colour */
        M.lines.forEach((L) => { const hot = L.r.symbol === hotSym, dx = g.xl - g.xb;
          ctx.lineWidth = hot ? 2.2 : 1; ctx.strokeStyle = `rgba(${RAW},${hot ? 0.95 : 0.2})`; ctx.beginPath(); ctx.moveTo(0, L.y0); ctx.bezierCurveTo(g.xa * 0.55, L.y0, g.xa * 0.72, g.cy, g.xa, g.cy); ctx.stroke();
          ctx.strokeStyle = `rgba(${L.ok ? UP : DN},${hot ? 1 : 0.3})`; ctx.beginPath(); ctx.moveTo(g.xb, g.cy); ctx.bezierCurveTo(g.xb + dx * 0.45, g.cy, g.xb + dx * 0.55, L.yt, g.xl, L.yt); ctx.stroke(); });
        ctx.strokeStyle = 'rgba(160,190,255,0.5)'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(g.xa, g.cy); ctx.lineTo(g.xb, g.cy); ctx.stroke();
        /* data packets riding the wires */
        if (moving) { ctx.globalCompositeOperation = 'lighter'; M.lines.forEach((L) => { const hot = L.r.symbol === hotSym, u = (t * L.sp + L.ph) % 1, p = M.pos(L, u);
            ctx.fillStyle = `rgba(${u < 0.58 ? '190,215,255' : L.ok ? UP : DN},${hot ? 1 : 0.85})`; ctx.beginPath(); ctx.arc(p[0], p[1], hot ? 3.6 : 1.9, 0, TAU); ctx.fill();
            if (hot) { ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.arc(p[0], p[1], 10, 0, TAU); ctx.fill(); ctx.globalAlpha = 1; } }); ctx.globalCompositeOperation = 'source-over'; }
        /* the desks, in the order a name passes them */
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; const step = (g.xb - g.xa) / CHAIN.length, r = wide ? 10 : 5.5;
        CHAIN.forEach((id, i) => { const a = AG[id], x = g.xa + (i + 0.5) * step, on = cur && cur.agent === id;
          if (on) { ctx.fillStyle = a.c; ctx.globalAlpha = 0.25 + (moving ? 0.12 * Math.sin(t * 0.008) : 0); ctx.beginPath(); ctx.arc(x, g.cy, r + 9, 0, TAU); ctx.fill(); ctx.globalAlpha = 1; }
          ctx.fillStyle = a.c; ctx.beginPath(); ctx.arc(x, g.cy, on ? r + 3 : r, 0, TAU); ctx.fill(); ctx.strokeStyle = '#070c18'; ctx.lineWidth = 1.5; ctx.stroke();
          if (wide) { ctx.fillStyle = a.fg; ctx.font = '700 7px ui-sans-serif, system-ui, sans-serif'; ctx.fillText(a.init, x, g.cy + 0.5); }
          if (on) { ctx.font = '600 11px ui-sans-serif, system-ui, sans-serif'; const lab = fit(ctx, `${a.short} · ${cur.state}`, 200), w = ctx.measureText(lab).width + 12, lx = Math.max(w / 2 + 4, Math.min(M.W - g.listW - w / 2 - 12, x));
            ctx.fillStyle = 'rgba(7,12,24,0.92)'; ctx.fillRect(lx - w / 2, g.cy - r - 30, w, 18); ctx.strokeStyle = a.c; ctx.lineWidth = 1; ctx.strokeRect(lx - w / 2, g.cy - r - 30, w, 18); ctx.fillStyle = '#e8eef9'; ctx.fillText(lab, lx, g.cy - r - 21); } });
        ctx.fillStyle = 'rgba(142,163,196,0.9)'; ctx.font = '600 9px ui-monospace, Menlo, monospace'; ctx.fillText('YOUR DESKS', (g.xa + g.xb) / 2, g.cy + r + 16);
        /* the index at the pinch, and the two counts */
        const st = M.st; ctx.textAlign = 'left';
        if (st) { ctx.font = '650 12px ui-monospace, Menlo, monospace'; if (st.nifty != null) { ctx.fillStyle = st.nifty_chg >= 0 ? `rgb(${UP})` : `rgb(${DN})`;
            ctx.fillText(`NIFTY ${Number(st.nifty).toLocaleString('en-IN', { maximumFractionDigits: 1 })}  ${pc(st.nifty_chg || 0)}`, Math.max(6, g.xa - 4), g.cy - r - 46); }
          ctx.font = '700 10.5px ui-monospace, Menlo, monospace'; const lab = (txt, c, x, y) => { const w = ctx.measureText(txt).width; ctx.fillStyle = 'rgba(7,12,24,0.88)'; ctx.fillRect(x - 5, y - 9, w + 10, 18); ctx.fillStyle = `rgb(${c})`; ctx.fillText(txt, x, y); };
          if (wide) { lab(`▲ CLEARED ${st.survivors}`, UP, g.xb + 12, g.cy - 24); lab(`▼ KILLED ${st.killed}`, DN, g.xb + 12, g.cy + 26); } else { lab(`▲ CLEARED ${st.survivors}`, UP, 8, M.H - 32); lab(`▼ KILLED ${st.killed}`, DN, 8, M.H - 13); }
          const m = String(st.quote_time).match(/[T ](\d{2}:\d{2})/); ctx.strokeStyle = 'rgba(120,160,235,0.35)'; ctx.setLineDash([3, 5]); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(g.xa * 0.5, 22); ctx.lineTo(g.xa * 0.5, M.H - 10); ctx.stroke(); ctx.setLineDash([]);
          ctx.fillStyle = 'rgba(160,190,255,0.9)'; ctx.font = '600 9.5px ui-monospace, Menlo, monospace'; ctx.textAlign = 'center'; ctx.fillText(m ? `PRICES ${m[1]}` : 'PRICES', Math.max(40, g.xa * 0.5), 12); ctx.textAlign = 'left'; }
        /* the ranked lists the wires end at */
        M.slots.forEach((s) => { const hot = s.r.symbol === hotSym, c = s.ok ? UP : DN;
          ctx.fillStyle = hot ? `rgba(${c},0.22)` : 'rgba(8,14,28,0.9)'; ctx.fillRect(s.x, s.y, s.w, s.h); ctx.strokeStyle = `rgba(${c},${hot ? 1 : 0.55})`; ctx.lineWidth = hot ? 1.8 : 1; ctx.strokeRect(s.x + 0.5, s.y + 0.5, s.w - 1, s.h - 1);
          const chg = pc(s.r.chg_pct); ctx.font = '700 10.5px ui-monospace, Menlo, monospace'; ctx.textAlign = 'right'; ctx.fillStyle = s.r.chg_pct >= 0 ? '#2de3a5' : '#ff5f75'; const y1 = wide ? s.y + 10 : s.y + s.h / 2; ctx.fillText(chg, s.x + s.w - 6, y1);
          ctx.textAlign = 'left'; ctx.fillStyle = '#e8eef9'; ctx.fillText(fit(ctx, s.r.label, s.w - ctx.measureText(chg).width - 16), s.x + 6, y1);
          if (wide) { ctx.font = '9px ui-monospace, Menlo, monospace'; ctx.fillStyle = `rgba(${c},0.95)`; ctx.fillText(fit(ctx, s.ok ? `#${s.k} · SCORE ${s.r.score}${s.r.horizon ? ' · ' + s.r.horizon.toUpperCase() : ''}` : `#${s.k} · OUT AT RULE ${s.r.failed}`, s.w - 12), s.x + 6, s.y + 22); } });
        ctx.font = '9.5px ui-monospace, Menlo, monospace'; ctx.fillStyle = 'rgba(142,163,196,0.9)'; ctx.textAlign = 'right';
        if (g.moreTop > 0) ctx.fillText(`+${g.moreTop} more cleared`, M.W - 8, g.topEnd + 8); if (g.moreBot > 0) ctx.fillText(`+${g.moreBot} more killed`, M.W - 8, g.botEnd + 8);
        if (!M.lines.length) { ctx.textAlign = 'center'; ctx.font = '12px ui-sans-serif, system-ui, sans-serif'; ctx.fillStyle = 'rgba(142,163,196,0.9)'; ctx.fillText('Waiting for the live lists…', M.W / 2, g.cy + 60); }
      };
      M.frame = (t) => { M.raf = 0; if (document.hidden || !E.shown || !box.isConnected || box.offsetParent === null) return; M.paint(t, true); M.raf = requestAnimationFrame(M.frame); };
      M.run = () => { if (E.reduce) { if (M.g) M.paint(0, false); return; } if (!M.raf && M.g) M.raf = requestAnimationFrame(M.frame); };
      cv.addEventListener('click', (ev) => { const b = cv.getBoundingClientRect(), x = ev.clientX - b.left, y = ev.clientY - b.top; const s = M.slots.find((q) => x >= q.x && x <= q.x + q.w && y >= q.y && y <= q.y + q.h);
        if (!s || !s.r.key) return; CD.pickName = s.r.label; dash.setParams({ sym: s.r.key, iv: '1day', lb: '1y' }); CD.goto('algo'); dash.draw('algo_pick'); dash.draw('candle_algo');
        document.querySelectorAll('#card-algochart').forEach((n) => n.scrollIntoView({ behavior: 'smooth', block: 'start' })); });
      M.off = E.on(() => M.run()); M.vis = () => M.run(); document.addEventListener('visibilitychange', M.vis);
      return M;
    },
    update(box, M) {
      const d = dash.data('floor_rows'), s = dash.data('floor_stats'); const rows = d.status === 'ok' ? d.data : []; M.st = s.status === 'ok' && s.data.length ? s.data[0] : null;
      const W = Math.max(300, box.clientWidth), wide = W >= 640, H = wide ? 510 : 400, dpr = Math.min(2, window.devicePixelRatio || 1);
      if (W !== M.W || H !== M.H) { M.W = W; M.H = H; box.style.height = H + 'px'; M.cv.width = Math.round(W * dpr); M.cv.height = Math.round(H * dpr); M.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); }
      const listW = wide ? 176 : 118, slotH = wide ? 29 : 21, gap = 3, n = wide ? 7 : 6, cy = H / 2, xl = W - listW - 6;
      const top = rows.filter((r) => !r.failed).sort((a, b) => b.score - a.score), bot = rows.filter((r) => r.failed).sort((a, b) => Math.abs(b.chg_pct) - Math.abs(a.chg_pct));
      M.top = top.slice(0, n); M.bot = bot.slice(0, n); const y = { t: 8, b: cy + (wide ? 10 : 12) }; M.slots = [];
      M.top.forEach((r, k) => M.slots.push({ r, ok: true, k: k + 1, x: xl, y: y.t + k * (slotH + gap), w: listW, h: slotH }));
      M.bot.forEach((r, k) => M.slots.push({ r, ok: false, k: k + 1, x: xl, y: y.b + k * (slotH + gap), w: listW, h: slotH }));
      const topEnd = y.t + M.top.length * (slotH + gap), botEnd = y.b + M.bot.length * (slotH + gap);
      M.g = { wide, cy, xa: W * (wide ? 0.24 : 0.15), xb: W * (wide ? 0.5 : 0.48), xl, listW, topEnd, botEnd, moreTop: top.length - M.top.length, moreBot: bot.length - M.bot.length };
      const where = {}; M.slots.forEach((q) => { where[q.r.symbol] = q.y + q.h / 2; }); const use = rows.slice(0, 70), pad = 26;
      M.lines = use.map((r, i) => { if (M.ph[r.symbol] === undefined) M.ph[r.symbol] = Math.random();
        return { r, ok: !r.failed, y0: use.length > 1 ? pad + (i * (H - 2 * pad)) / (use.length - 1) : cy, yt: where[r.symbol] !== undefined ? where[r.symbol] : r.failed ? botEnd + 8 : topEnd + 8, ph: M.ph[r.symbol], sp: 0.00006 + (M.ph[r.symbol] % 0.1) * 0.0004 }; });
      if (rows.length && M.st) { const o = ['floor_side', 'paper_live'].map((id) => dash.data(id)); E.feed({ rows, stats: M.st, side: o[0].status === 'ok' ? o[0].data : [], paper: o[1].status === 'ok' ? o[1].data : [] }); }
      if (E.reduce) M.paint(0, false); else M.run();
    },
    unmount(box, M) { cancelAnimationFrame(M.raf); M.raf = 0; if (M.off) M.off(); document.removeEventListener('visibilitychange', M.vis); },
  });
})();
