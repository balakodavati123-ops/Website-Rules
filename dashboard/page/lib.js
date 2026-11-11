/* CEO Trading Desk helpers. Pure functions and chart painters; no data lives here. */
(function () {
  const CD = (window.CD = {});
  const PAL = { blue: '#4f8cff', cyan: '#29d3ee', green: '#2de3a5', red: '#ff5f75', amber: '#ffb64a',
    violet: '#a184ff', pink: '#ff7ac6', mut: '#8ea3c4', dim: '#5b7093', line: '#1c2c48', fg: '#e8eef9' };
  CD.PAL = PAL;

  /* ---------- formatting ---------- */
  const n = (x) => (x === null || x === undefined || x === '' || Number.isNaN(Number(x)) ? null : Number(x));
  CD.n = n;
  CD.inr = (x, d = 0) => { const v = n(x); return v === null ? '—' : (v < 0 ? '−₹' : '₹') + Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }); };
  CD.num = (x, d = 2) => { const v = n(x); return v === null ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }); };
  CD.pct = (x, d = 2, sign = true) => { const v = n(x); return v === null ? '—' : (sign && v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + '%'; };
  CD.cls = (x) => { const v = n(x); return v === null || v === 0 ? '' : v > 0 ? 'up' : 'down'; };
  CD.price = (x) => { const v = n(x); if (v === null) return '—'; return v >= 1000 ? CD.num(v, 2) : v >= 1 ? CD.num(v, 2) : v.toFixed(5); };
  CD.cap = (s) => String(s || '').replace(/^./, (c) => c.toUpperCase());

  /* ---------- IST clock and session ---------- */
  CD.istParts = (d = new Date()) => {
    const f = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).formatToParts(d);
    const o = {}; f.forEach((p) => { o[p.type] = p.value; });
    return { wd: o.weekday, h: +o.hour % 24, m: +o.minute, s: +o.second };
  };
  CD.session = () => {
    const t = CD.istParts(); const mins = t.h * 60 + t.m; const wk = !['Sat', 'Sun'].includes(t.wd);
    const hhmm = String(t.h).padStart(2, '0') + ':' + String(t.m).padStart(2, '0');
    if (!wk) return { key: 'closed', label: 'Weekend. NSE is closed', hhmm };
    if (mins < 8 * 60 + 45) return { key: 'early', label: 'Before the 08:45 briefing', hhmm };
    if (mins < 9 * 60 + 15) return { key: 'pre', label: 'Pre-market. Plan the day', hhmm };
    if (mins < 15 * 60 + 30) return { key: 'open', label: 'Market open. Alerts live', hhmm };
    return { key: 'closed', label: 'Market closed. Review and learn', hhmm };
  };
  CD.ageSec = (iso) => (iso ? (Date.now() - new Date(iso).getTime()) / 1000 : null);
  CD.ago = (s) => (s === null ? 'unknown' : s < 90 ? Math.round(s) + 's ago' : s < 5400 ? Math.round(s / 60) + ' min ago' : s < 129600 ? Math.round(s / 3600) + ' h ago' : Math.round(s / 86400) + ' d ago');

  /* ---------- marks (so a number can be traced to its source) ---------- */
  CD.mark = (el, source, field, where) => {
    el.setAttribute('data-source', source);
    if (field) el.setAttribute('data-field', field);
    if (where) el.setAttribute('data-where', where);
    return el;
  };

  /* ---------- small DOM helpers ---------- */
  CD.el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
  CD.tag = (text, kind) => CD.el('span', 'tag' + (kind ? ' ' + kind : ''), text);
  CD.copy = async (text, btn) => {
    try { await navigator.clipboard.writeText(text); btn.textContent = 'Copied'; }
    catch (e) { btn.textContent = 'Select and copy'; }
    setTimeout(() => { btn.textContent = btn.dataset.label || 'Copy'; }, 1600);
  };
  CD.enc = (v) => String(v).replace(/[%&=]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase());
  /* Returns the datasets' rows, or paints a short message and returns null while any is not ready. */
  CD.need = (el, ids) => {
    const out = [];
    for (const id of ids) {
      const d = dash.data(id);
      if (d.status === 'ok') { out.push(d.data); continue; }
      const msg = d.status === 'error' ? 'Failed to load' : d.status === 'connect' || d.status === 'declined' ? 'Connect the account to see this' : '—';
      el.replaceChildren(document.createTextNode(msg)); return null;
    }
    return out;
  };
  CD.mk = (text, cls, source, field, where) => { const b = CD.el('b', cls, text); CD.mark(b, source, field, where); return b; };
  CD.fillTable = (tbody, rows, cols, keyCol) => {
    const sel = d3.select(tbody); sel.selectAll('*').remove();
    const tr = sel.selectAll('tr').data(rows).join('tr');
    if (keyCol) tr.attr('data-key', (d) => (Array.isArray(keyCol) ? keyCol.map((k) => CD.enc(d[k])).join(',') : d[keyCol]));
    cols.forEach((c) => {
      tr.append('td').attr('class', (d) => (c.cls ? (typeof c.cls === 'function' ? c.cls(d) : c.cls) : '')).each(function (d) {
        const v = c.render ? c.render(d) : d[c.k];
        if (v instanceof Node) this.appendChild(v); else this.textContent = v === null || v === undefined ? '—' : v;
      });
    });
  };

  /* ---------- indicators ---------- */
  CD.ema = (v, p) => { const k = 2 / (p + 1); const o = []; let e = null; v.forEach((x) => { e = e === null ? x : x * k + e * (1 - k); o.push(e); }); return o; };
  CD.sma = (v, p) => v.map((_, i) => (i + 1 < p ? null : d3.mean(v.slice(i + 1 - p, i + 1))));
  CD.rsi = (c, p = 14) => {
    if (c.length < p + 1) return null; let g = 0, l = 0;
    for (let i = 1; i <= p; i++) { const d = c[i] - c[i - 1]; if (d >= 0) g += d; else l -= d; }
    g /= p; l /= p;
    for (let i = p + 1; i < c.length; i++) { const d = c[i] - c[i - 1]; g = (g * (p - 1) + Math.max(d, 0)) / p; l = (l * (p - 1) + Math.max(-d, 0)) / p; }
    return l === 0 ? 100 : 100 - 100 / (1 + g / l);
  };
  CD.atr = (rows, p = 14) => {
    if (rows.length < p + 1) return null; const tr = [];
    for (let i = 1; i < rows.length; i++) tr.push(Math.max(rows[i].h - rows[i].l, Math.abs(rows[i].h - rows[i - 1].c), Math.abs(rows[i].l - rows[i - 1].c)));
    let a = d3.mean(tr.slice(0, p)); for (let i = p; i < tr.length; i++) a = (a * (p - 1) + tr[i]) / p; return a;
  };
  CD.linreg = (y) => {
    const m = y.length; const xm = (m - 1) / 2; const ym = d3.mean(y); let sxy = 0, sxx = 0;
    y.forEach((v, i) => { sxy += (i - xm) * (v - ym); sxx += (i - xm) ** 2; });
    const b = sxx ? sxy / sxx : 0; const a = ym - b * xm;
    const sd = Math.sqrt(d3.sum(y, (v, i) => (v - (a + b * i)) ** 2) / Math.max(m - 2, 1));
    return { a, b, sd, m };
  };
  /* normal CDF, used for the confidence of a mean being above zero */
  CD.ncdf = (x) => { const t = 1 / (1 + 0.2316419 * Math.abs(x)); const d = 0.3989423 * Math.exp(-x * x / 2);
    const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return x > 0 ? 1 - p : p; };

  /* ---------- charts ---------- */
  CD.svg = (el, w, h, label) => d3.select(el).append('svg').attr('viewBox', `0 0 ${w} ${h}`).attr('width', '100%').attr('role', 'img').attr('aria-label', label);
  CD.tooltip = (box) => {
    const t = d3.select(box).append('div').attr('class', 'tip').style('display', 'none');
    return { show(html, x, y) { const W = box.clientWidth; t.style('display', 'block').html(html); const tw = t.node().offsetWidth;
      t.style('left', Math.min(Math.max(4, x + 12), W - tw - 4) + 'px').style('top', Math.max(0, y - 10) + 'px'); }, hide() { t.style('display', 'none'); } };
  };
  /* Times are shown in IST for every viewer: shift by 5:30 and format as UTC. */
  CD.ist = (d) => new Date(d.getTime() + 330 * 60000);
  CD.fmtTime = (iv) => { const f = iv === '1day' || iv === '1d' ? d3.utcFormat('%d %b') : iv === '60minute' || iv === '1hr' || iv === '6hr' ? d3.utcFormat('%d %b %H:%M') : d3.utcFormat('%d %H:%M'); return (d) => f(CD.ist(d)); };
  CD.lohi = (lo, mid, hi) => { const d = CD.el('div', 'sub num'); d.style.cssText = 'display:flex;justify-content:space-between;gap:8px;margin-top:5px'; [lo, mid, hi].forEach((t) => d.appendChild(CD.el('span', '', t))); return d; };

  CD.spark = (el, values, color, w = 120, h = 34) => {
    const s = CD.svg(el, w, h, 'Sparkline of recent prices'); const v = values.filter((x) => n(x) !== null);
    if (v.length < 2) return; const x = d3.scaleLinear([0, v.length - 1], [2, w - 2]); const y = d3.scaleLinear(d3.extent(v), [h - 3, 3]);
    const line = d3.line().x((_, i) => x(i)).y((d) => y(d));
    const area = d3.area().x((_, i) => x(i)).y0(h).y1((d) => y(d));
    const id = 'g' + Math.random().toString(36).slice(2, 7);
    const g = s.append('defs').append('linearGradient').attr('id', id).attr('x1', 0).attr('x2', 0).attr('y1', 0).attr('y2', 1);
    g.append('stop').attr('offset', '0').attr('stop-color', color).attr('stop-opacity', .35); g.append('stop').attr('offset', '1').attr('stop-color', color).attr('stop-opacity', 0);
    s.append('path').attr('d', area(v)).attr('fill', `url(#${id})`); s.append('path').attr('d', line(v)).attr('fill', 'none').attr('stroke', color).attr('stroke-width', 1.6);
    s.append('circle').attr('cx', x(v.length - 1)).attr('cy', y(v[v.length - 1])).attr('r', 2.6).attr('fill', color);
  };

  CD.donut = (el, items, centerTop, centerSub) => {
    const W = 260, H = 260; const s = CD.svg(el, W, H, 'Allocation by asset class'); const g = s.append('g').attr('transform', `translate(${W / 2},${H / 2})`);
    const pie = d3.pie().value((d) => Math.max(d.value, 0)).sort(null).padAngle(0.02)(items);
    const arc = d3.arc().innerRadius(78).outerRadius(112).cornerRadius(4);
    const tip = CD.tooltip(el);
    g.selectAll('path').data(pie).join('path').attr('d', arc).attr('fill', (d) => d.data.color).attr('stroke', '#060a13').attr('stroke-width', 2)
      .on('pointermove', (ev, d) => { const r = el.getBoundingClientRect(); tip.show(`${d.data.label}<br>${CD.inr(d.data.value)} (${d.data.share.toFixed(1)}%)`, ev.clientX - r.left, ev.clientY - r.top); })
      .on('pointerleave', () => tip.hide());
    g.append('text').attr('text-anchor', 'middle').attr('y', -2).style('fill', '#fff').style('font-size', '19px').style('font-weight', 650).text(centerTop);
    g.append('text').attr('text-anchor', 'middle').attr('y', 18).text(centerSub);
  };

  /* Candles with volume, EMA 20 and 50, support and resistance, and a statistical projection.
     rows: [{t:Date,o,h,l,c,v}]. The projection is a straight-line fit of recent closes extended
     forward with a widening band: it shows where the recent drift points, not a forecast. */
  CD.candleChart = (el, rows, opt) => {
    opt = opt || {};
    d3.select(el).selectAll('*').remove();
    if (!rows || rows.length < 8) { el.appendChild(CD.el('div', 'empty', 'Not enough candles yet. This fills when the market is trading.')); return null; }
    const W = Math.max(320, el.clientWidth || 640); const H = Math.round(Math.min(430, Math.max(280, W * 0.5))); const volH = 58; const m = { l: 8, r: 54, t: 10, b: 22 };
    const s = CD.svg(el, W, H + volH, opt.label || 'Candlestick chart with moving averages and projection');
    const N = rows.length; const closes = rows.map((r) => r.c); const e20 = CD.ema(closes, 20); const e50 = CD.ema(closes, 50);
    const fit = CD.linreg(closes.slice(-Math.min(40, N))); const P = Math.max(6, Math.round(N * 0.16)); const base = N - Math.min(40, N);
    const proj = d3.range(0, P + 1).map((k) => { const x = Math.min(40, N) - 1 + k; const mid = fit.a + fit.b * x; const w = 1.5 * fit.sd * Math.sqrt(1 + k / Math.min(40, N)); return { i: N - 1 + k, mid, up: mid + w, lo: mid - w }; });
    const lastWin = rows.slice(-Math.min(40, N)); const sup = d3.min(lastWin, (r) => r.l); const res = d3.max(lastWin, (r) => r.h);
    const x = d3.scaleLinear([-0.5, N + P - 0.5], [m.l, W - m.r]); const bw = Math.max(1.5, (x(1) - x(0)) * 0.7);
    const lo = d3.min([d3.min(rows, (r) => r.l), d3.min(proj, (p) => p.lo)]); const hi = d3.max([d3.max(rows, (r) => r.h), d3.max(proj, (p) => p.up)]);
    const pad = (hi - lo) * 0.06; const y = d3.scaleLinear([lo - pad, hi + pad], [H - m.b, m.t]);
    const vy = d3.scaleLinear([0, d3.max(rows, (r) => r.v) || 1], [H + volH - 2, H + 8]);
    y.ticks(5).forEach((t) => { s.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(t)).attr('y2', y(t)).attr('stroke', '#12223d'); s.append('text').attr('x', W - m.r + 6).attr('y', y(t) + 3).text(CD.price(t)); });
    const tf = CD.fmtTime(opt.iv || '1day'); const stepX = Math.max(1, Math.floor(N / 6));
    rows.forEach((r, i) => { if (i % stepX === 0) s.append('text').attr('x', x(i)).attr('y', H - 4).attr('text-anchor', 'middle').text(tf(r.t)); });
    [['Support', sup, PAL.green], ['Resistance', res, PAL.red]].forEach(([nm, v, c]) => {
      s.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(v)).attr('y2', y(v)).attr('stroke', c).attr('stroke-dasharray', '4 4').attr('opacity', .55);
      s.append('text').attr('x', m.l + 4).attr('y', y(v) - 3).style('fill', c).text(`${nm} ${CD.price(v)}`); });
    s.append('path').attr('d', d3.area().x((p) => x(p.i)).y0((p) => y(p.lo)).y1((p) => y(p.up))(proj)).attr('fill', PAL.violet).attr('opacity', .13);
    s.append('path').attr('d', d3.line().x((p) => x(p.i)).y((p) => y(p.mid))(proj)).attr('fill', 'none').attr('stroke', PAL.violet).attr('stroke-width', 1.8).attr('stroke-dasharray', '6 4');
    s.append('text').attr('x', x(N + P / 2)).attr('y', m.t + 8).attr('text-anchor', 'middle').style('fill', PAL.violet).text('projection');
    rows.forEach((r, i) => { const up = r.c >= r.o; const col = up ? PAL.green : PAL.red;
      s.append('line').attr('x1', x(i)).attr('x2', x(i)).attr('y1', y(r.h)).attr('y2', y(r.l)).attr('stroke', col).attr('stroke-width', 1);
      s.append('rect').attr('x', x(i) - bw / 2).attr('width', bw).attr('y', y(Math.max(r.o, r.c))).attr('height', Math.max(1, Math.abs(y(r.o) - y(r.c)))).attr('fill', col);
      s.append('rect').attr('x', x(i) - bw / 2).attr('width', bw).attr('y', vy(r.v)).attr('height', Math.max(0, H + volH - 2 - vy(r.v))).attr('fill', col).attr('opacity', .35); });
    [[e20, PAL.cyan], [e50, PAL.amber]].forEach(([e, c]) => s.append('path').attr('d', d3.line().defined((d, i) => i >= 1).x((_, i) => x(i)).y((d) => y(d))(e)).attr('fill', 'none').attr('stroke', c).attr('stroke-width', 1.4));
    const last = rows[N - 1]; s.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(last.c)).attr('y2', y(last.c)).attr('stroke', '#fff').attr('stroke-width', .6).attr('stroke-dasharray', '2 3').attr('opacity', .6);
    s.append('rect').attr('x', W - m.r + 1).attr('y', y(last.c) - 8).attr('width', m.r - 1).attr('height', 16).attr('rx', 3).attr('fill', last.c >= last.o ? PAL.green : PAL.red);
    s.append('text').attr('x', W - m.r + 5).attr('y', y(last.c) + 3).style('fill', '#04101c').style('font-weight', 700).text(CD.price(last.c));
    const tip = CD.tooltip(el); const cross = s.append('line').attr('y1', m.t).attr('y2', H).attr('stroke', '#fff').attr('opacity', 0).attr('stroke-width', .6);
    s.append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H + volH - m.t).attr('fill', 'transparent')
      .on('pointermove', (ev) => { const r = el.getBoundingClientRect(); const px = (ev.clientX - r.left) * (W / r.width); const i = Math.max(0, Math.min(N - 1, Math.round(x.invert(px))));
        const d = rows[i]; cross.attr('x1', x(i)).attr('x2', x(i)).attr('opacity', .5);
        tip.show(`${d3.utcFormat('%d %b %H:%M')(CD.ist(d.t))} IST<br>O ${CD.price(d.o)} H ${CD.price(d.h)}<br>L ${CD.price(d.l)} C ${CD.price(d.c)}<br>Vol ${CD.num(d.v, 0)}<br>EMA20 ${CD.price(e20[i])} EMA50 ${CD.price(e50[i])}`, ev.clientX - r.left, ev.clientY - r.top); })
      .on('pointerleave', () => { tip.hide(); cross.attr('opacity', 0); });
    return { rsi: CD.rsi(closes), atr: CD.atr(rows), slope: fit.b, sd: fit.sd, support: sup, resistance: res, last: last.c, e20: e20[N - 1], e50: e50[N - 1], projEnd: proj[proj.length - 1].mid, steps: P };
  };
})();
