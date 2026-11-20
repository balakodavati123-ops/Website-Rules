/*! candles.js - dependency-free live intraday candle charts (canvas).
 *  window.LiveCharts = { mount(el, opts) -> {update, tick, select, destroy} }
 */
(function () {
  'use strict';
  var MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
  var SANS = '-apple-system, "Segoe UI", Roboto, sans-serif';
  var C = { bg: '#060a13', panel: '#0c1424', grid: '#1c2c48', fg: '#e8eef9', muted: '#8ea3c4', dim: '#5b7093',
    blue: '#4f8cff', cyan: '#29d3ee', up: '#2de3a5', dn: '#ff5f75', e20: '#ffb64a', e50: '#a184ff', exit: '#ffb64a' };
  var SCOL = ['#4fd6ff', '#ff8ccf', '#f4f7ff', '#ffd27a', '#9dff9d'];
  var FCOL = ['#ffd27a', '#7ee8fa', '#ff8ccf', '#9dff9d'];
  var IST = 19800;

  var CSS = '.lc-root{position:relative;background:#060a13;color:#e8eef9;font:12px/1.2 ' + SANS + ';box-sizing:border-box;width:100%;-webkit-text-size-adjust:100%}' +
    '.lc-root *{box-sizing:border-box}' +
    '.lc-head{display:flex;align-items:center;gap:8px;padding:0 0 6px}' +
    '.lc-tabs{display:flex;gap:6px;overflow-x:auto;flex:1;min-width:0;scrollbar-width:none}.lc-tabs::-webkit-scrollbar{display:none}' +
    '.lc-tab{flex:none;display:flex;align-items:baseline;gap:7px;background:#0c1424;color:#8ea3c4;border:1px solid #1c2c48;border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit;white-space:nowrap}' +
    '.lc-tab:hover{border-color:#2b4268}.lc-tab.lc-on{border-color:#4f8cff;background:#101c33;color:#e8eef9}' +
    '.lc-tdesk{font-weight:700;color:#e8eef9}.lc-tsym{font-size:11px}.lc-tpx{font:600 12px ' + MONO + ';color:#e8eef9}' +
    '.lc-tchg{font:600 11px ' + MONO + '}.lc-up{color:#2de3a5}.lc-dn{color:#ff5f75}' +
    '.lc-gbtn{flex:none;display:none;background:#0c1424;color:#8ea3c4;border:1px solid #1c2c48;border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit}' +
    '.lc-gbtn.lc-show{display:block}.lc-gbtn.lc-on{border-color:#4f8cff;color:#e8eef9}' +
    '.lc-legend{display:flex;gap:6px;overflow-x:auto;padding:0 0 6px;scrollbar-width:none}.lc-legend::-webkit-scrollbar{display:none}' +
    '.lc-chip{flex:none;display:flex;align-items:center;gap:6px;background:transparent;color:#e8eef9;border:1px solid #1c2c48;border-radius:999px;padding:3px 10px;cursor:pointer;font:inherit;font-size:11px;white-space:nowrap}' +
    '.lc-chip i{display:block;width:14px;height:3px;border-radius:2px;background:currentColor}' +
    '.lc-chip.lc-off{opacity:.38;text-decoration:line-through}.lc-chip b{font-weight:700}' +
    '.lc-hint{display:none;align-items:center;justify-content:space-between;gap:8px;background:#101c33;border:1px solid #1c2c48;color:#8ea3c4;border-radius:8px;padding:6px 10px;margin-bottom:6px;font-size:12px}' +
    '.lc-hint.lc-show{display:flex}.lc-hint button{background:none;border:0;color:#8ea3c4;font-size:16px;line-height:1;cursor:pointer;padding:0 2px}' +
    '.lc-stage{display:block}.lc-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}' +
    '.lc-cell{min-width:0}.lc-cv{display:block;width:100%;background:#0c1424;border:1px solid #1c2c48;border-radius:10px;touch-action:pan-y;user-select:none;-webkit-user-select:none;cursor:crosshair}' +
    '.lc-cv.lc-drag{cursor:grabbing}';

  function isN(x) { return typeof x === 'number' && isFinite(x); }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  var nfc = {};
  function fmt(p, d) {
    if (!isN(p)) return '-';
    if (d == null) d = Math.abs(p) >= 1e5 ? 0 : Math.abs(p) >= 1 ? 2 : 4;
    var f = nfc[d] || (nfc[d] = new Intl.NumberFormat('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }));
    return f.format(p);
  }
  function fmtQ(q) {
    if (!isN(q)) return '-';
    if (q >= 1e7) return (q / 1e7).toFixed(1) + 'Cr';
    if (q >= 1e5) return (q / 1e5).toFixed(1) + 'L';
    if (q >= 1e3) return (q / 1e3).toFixed(1) + 'k';
    return String(Math.round(q));
  }
  function hm(t) {
    var s = (((Math.floor(t) + IST) % 86400) + 86400) % 86400, h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }
  function nice(range, n) {
    var raw = range / n, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), x = raw / mag;
    return (x < 1.5 ? 1 : x < 2.25 ? 2 : x < 3.5 ? 2.5 : x < 7 ? 5 : 10) * mag;
  }
  function decs(step) { var d = 0; while (d < 4 && Math.abs(step * Math.pow(10, d) - Math.round(step * Math.pow(10, d))) > 1e-7) d++; return d; }
  function lb(cs, t) { var lo = 0, hi = cs.length; while (lo < hi) { var m = (lo + hi) >> 1; if (cs[m][0] < t) lo = m + 1; else hi = m; } return lo; }
  function ema(cs, n) { var a = 2 / (n + 1), o = new Array(cs.length), p; for (var i = 0; i < cs.length; i++) { p = i ? a * cs[i][4] + (1 - a) * p : cs[i][4]; o[i] = p; } return o; }
  function rgba(hex, a) { var n = parseInt(hex.slice(1), 16); return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')'; }
  function pill(x, y, w, h, r, fill, c) {
    c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); c.fillStyle = fill; c.fill();
  }
  function resolve(items, lo, hi) {
    var i, k;
    for (i = 0; i < items.length; i++) items[i].q = items[i].p;
    for (var it = 0; it < 30; it++) {
      items.sort(function (a, b) { return a.q - b.q; });
      var moved = false;
      for (k = 1; k < items.length; k++) {
        var a = items[k - 1], b = items[k], need = (a.s + b.s) / 2 + 1 - (b.q - a.q);
        if (need > 0.01) {
          moved = true;
          if (a.fixed && !b.fixed) b.q += need; else if (b.fixed && !a.fixed) a.q -= need;
          else if (!a.fixed) { a.q -= need / 2; b.q += need / 2; }
        }
      }
      for (k = 0; k < items.length; k++) if (!items[k].fixed) items[k].q = clamp(items[k].q, lo, hi);
      if (!moved) break;
    }
  }
  function tfSec(tf, cs) {
    var m = /^(\d+)\s*([smhd])/i.exec(tf || '');
    if (m) return +m[1] * ({ s: 1, m: 60, h: 3600, d: 86400 })[m[2].toLowerCase()];
    if (cs.length > 1) { var d = []; for (var i = 1; i < cs.length && i < 50; i++) d.push(cs[i][0] - cs[i - 1][0]); d.sort(function (a, b) { return a - b; }); if (d[d.length >> 1] > 0) return d[d.length >> 1]; }
    return 60;
  }
  function slug(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

  /* ---------------- instance ---------------- */
  function Inst(el, opts) {
    opts = opts || {};
    this.el = el; this.opts = opts; this.charts = []; this.byId = {}; this.rt = {}; this.views = {};
    this.hidden = {}; this.sel = null; this.pending = opts.initial || null; this.grid = false; this.panes = [];
    this.raf = 0; this.dead = false; this.inView = true; this.hintOff = false; this.legSig = ''; this.tabSig = ''; this.lastPulse = 0;
    var self = this;
    if (!document.getElementById('lc-style')) { var st = document.createElement('style'); st.id = 'lc-style'; st.textContent = CSS; document.head.appendChild(st); }
    var r = this.root = document.createElement('div'); r.className = 'lc-root';
    r.innerHTML = '<div class="lc-head"><div class="lc-tabs" role="tablist"></div><button class="lc-gbtn" type="button" title="Show all four charts">2\u00d72 grid</button></div>' +
      '<div class="lc-legend"></div><div class="lc-hint"><span>Rotate your phone for the full chart</span><button type="button" aria-label="Dismiss">\u00d7</button></div><div class="lc-stage"></div>';
    this.tabsEl = r.querySelector('.lc-tabs'); this.gbtn = r.querySelector('.lc-gbtn'); this.legEl = r.querySelector('.lc-legend');
    this.hintEl = r.querySelector('.lc-hint'); this.stage = r.querySelector('.lc-stage');
    el.appendChild(r);
    this.gbtn.addEventListener('click', function () { self.grid = !self.grid; self.buildPanes(); });
    this.hintEl.querySelector('button').addEventListener('click', function () { self.hintOff = true; try { localStorage.setItem('lc-hint', '1'); } catch (e) {} self.layout(); });
    try { if (localStorage.getItem('lc-hint')) this.hintOff = true; } catch (e) {}
    this.onResize = function () { if (self.rz) return; self.rz = requestAnimationFrame(function () { self.rz = 0; self.layout(); }); };
    window.addEventListener('resize', this.onResize); window.addEventListener('orientationchange', this.onResize);
    this.onVis = function () { self.start(); };
    document.addEventListener('visibilitychange', this.onVis);
    if (typeof ResizeObserver !== 'undefined') { this.ro = new ResizeObserver(this.onResize); this.ro.observe(r); }
    if (typeof IntersectionObserver !== 'undefined') { this.io = new IntersectionObserver(function (e) { self.inView = e[e.length - 1].isIntersecting; self.start(); }); this.io.observe(r); }
    if (opts.data) this.update(opts.data);
    this.buildPanes();
  }
  var P = Inst.prototype;

  P.active = function () { return !this.dead && !document.hidden && this.inView; };
  P.start = function () { var s = this; if (!s.raf && s.active()) { s.dirtyAll(); s.raf = requestAnimationFrame(function (t) { s.frame(t); }); } };
  P.dirtyAll = function () { for (var i = 0; i < this.panes.length; i++) this.panes[i].dirty = true; };
  P.frame = function (ts) {
    var s = this, i, k;
    s.raf = 0; if (!s.active()) return;
    for (k in s.rt) {
      var r = s.rt[k];
      if (isN(r.tgt) && isN(r.disp) && r.disp !== r.tgt) {
        var d = r.tgt - r.disp;
        r.disp = Math.abs(d) < Math.abs(r.tgt) * 1e-7 + 1e-9 ? r.tgt : r.disp + d * 0.22;
        for (i = 0; i < s.panes.length; i++) if (s.panes[i].id === k) s.panes[i].dirty = true;
      }
    }
    if (ts - s.lastPulse > 66) { s.lastPulse = ts; s.dirtyAll(); }
    for (i = 0; i < s.panes.length; i++) if (s.panes[i].dirty) { s.panes[i].dirty = false; try { s.panes[i].draw(); } catch (e) { if (window.console) console.error('[LiveCharts]', e); } }
    if (s.tabsDirty) { s.tabsDirty = false; s.updateTabs(); }
    s.raf = requestAnimationFrame(function (t) { s.frame(t); });
  };

  function prep(I, src) {
    var ch = {}, k; for (k in src) ch[k] = src[k];
    var cs = [];
    (Array.isArray(src.candles) ? src.candles : []).forEach(function (c) {
      if (Array.isArray(c) && isN(+c[0]) && isN(+c[1]) && isN(+c[2]) && isN(+c[3]) && isN(+c[4]) && c[0] !== null && c[4] !== null)
        cs.push([+c[0], +c[1], +c[2], +c[3], +c[4], isN(+c[5]) ? +c[5] : 0]);
    });
    cs.sort(function (a, b) { return a[0] - b[0]; });
    ch.candles = cs;
    ch.strategies = (Array.isArray(src.strategies) ? src.strategies : []).map(function (s) {
      var o = {}; for (var k in s) o[k] = s[k];
      o.line = (Array.isArray(s.line) ? s.line : []).filter(function (p) { return Array.isArray(p) && isN(+p[0]) && isN(+p[1]) && p[1] !== null; }).map(function (p) { return [+p[0], +p[1]]; });
      return o;
    });
    ch.levels = (Array.isArray(src.levels) ? src.levels : []).filter(function (l) { return l && isN(l.px); });
    var r = I.rt[ch.id] || (I.rt[ch.id] = {});
    r.step = tfSec(ch.tf, cs);
    var tgt = isN(ch.last) ? ch.last : cs.length ? cs[cs.length - 1][4] : NaN;
    r.tgt = tgt; if (!isN(r.disp) || !cs.length) r.disp = tgt;
    r.e20 = ema(cs, 20); r.e50 = ema(cs, 50);
    return ch;
  }

  P.update = function (data) {
    if (typeof data === 'string') { try { data = JSON.parse(data); } catch (e) { return; } }
    if (!data || !Array.isArray(data.charts)) return;
    var self = this;
    data.charts.forEach(function (c) {
      if (!c || c.id == null) return;
      var ch = prep(self, c);
      if (!self.byId[ch.id]) self.charts.push(ch); else self.charts[self.charts.indexOf(self.byId[ch.id])] = ch;
      self.byId[ch.id] = ch;
    });
    if (this.pending) { var id = this.resolveId(this.pending); if (id) { this.sel = id; this.pending = null; } }
    if (!this.sel || !this.byId[this.sel]) this.sel = this.charts.length ? this.charts[0].id : null;
    var want = this.grid ? this.charts.slice(0, 4).map(function (c) { return c.id; }).join() : this.sel || '';
    if (this.panes.map(function (p) { return p.id; }).join() !== want) { this.buildPanes(); this.refreshUI(); } else this.refreshUI();
    this.dirtyAll(); this.start();
  };
  P.resolveId = function (x) {
    if (x == null) return null;
    if (this.byId[x]) return x;
    var s = slug(x);
    for (var i = 0; i < this.charts.length; i++) { var c = this.charts[i]; if (slug(c.id) === s || slug(c.desk) === s || slug(c.symbol) === s) return c.id; }
    return null;
  };
  P.select = function (id) {
    var r = this.resolveId(id);
    if (!r) { this.pending = id; return; }
    this.sel = r; this.pending = null;
    if (this.grid) { this.refreshUI(); return; }
    this.buildPanes(); this.refreshUI();
  };
  P.tick = function (id, price, epoch) {
    var rid = this.resolveId(id), ch = rid && this.byId[rid]; price = +price;
    if (!ch || !isN(price)) return;
    var r = this.rt[rid], cs = ch.candles, step = r.step; epoch = isN(+epoch) && epoch !== null ? +epoch : Date.now() / 1000;
    var b = Math.floor(epoch / step) * step, L = cs[cs.length - 1];
    if (!L || b > L[0]) { cs.push([b, price, price, price, price, 0]); r.disp = price; }
    else { L[4] = price; if (price > L[2]) L[2] = price; if (price < L[3]) L[3] = price; }
    ch.last = price; r.tgt = price; r.e20 = ema(cs, 20); r.e50 = ema(cs, 50);
    this.tabsDirty = true; this.dirtyAll(); this.start();
  };
  P.destroy = function () {
    this.dead = true; if (this.raf) cancelAnimationFrame(this.raf);
    window.removeEventListener('resize', this.onResize); window.removeEventListener('orientationchange', this.onResize);
    document.removeEventListener('visibilitychange', this.onVis);
    if (this.ro) this.ro.disconnect(); if (this.io) this.io.disconnect();
    if (this.root.parentNode) this.root.parentNode.removeChild(this.root);
    this.panes = []; this.charts = []; this.byId = {};
  };

  /* ---------------- DOM chrome ---------------- */
  function chgOf(ch) {
    var cs = ch.candles, last = isN(ch.last) ? ch.last : cs.length ? cs[cs.length - 1][4] : NaN, base = NaN;
    (ch.levels || []).forEach(function (l) { if (!isN(base) && (l.kind === 'ref' || /prev/i.test(l.label || ''))) base = l.px; });
    if (!isN(base) && cs.length) base = cs[0][1];
    return { last: last, pct: isN(base) && base ? (last - base) / base * 100 : NaN };
  }
  P.refreshUI = function () {
    var self = this, sig = this.charts.map(function (c) { return c.id; }).join('|');
    if (sig !== this.tabSig) {
      this.tabSig = sig; this.tabsEl.innerHTML = '';
      this.charts.forEach(function (c) {
        var b = document.createElement('button'); b.type = 'button'; b.className = 'lc-tab'; b.setAttribute('role', 'tab'); b.dataset.id = c.id;
        b.innerHTML = '<span class="lc-tdesk"></span><span class="lc-tsym"></span><span class="lc-tpx"></span><span class="lc-tchg"></span>';
        b.addEventListener('click', function () { if (self.grid) { self.grid = false; self.sel = c.id; self.buildPanes(); self.refreshUI(); } else self.select(c.id); });
        self.tabsEl.appendChild(b);
      });
    }
    this.updateTabs(); this.buildLegend(); this.layout(true);
  };
  P.updateTabs = function () {
    var tabs = this.tabsEl.children;
    for (var i = 0; i < tabs.length; i++) {
      var t = tabs[i], ch = this.byId[t.dataset.id]; if (!ch) continue;
      var m = chgOf(ch), up = !(m.pct < 0);
      var on = !this.grid && ch.id === this.sel; t.classList.toggle('lc-on', on);
      if (on && this.scrolled !== ch.id) { this.scrolled = ch.id; var tb = this.tabsEl; tb.scrollLeft = Math.max(0, t.offsetLeft - (tb.clientWidth - t.offsetWidth) / 2); }
      t.querySelector('.lc-tdesk').textContent = ch.desk || ch.id;
      t.querySelector('.lc-tsym').textContent = ch.symbol || '';
      t.querySelector('.lc-tpx').textContent = isN(m.last) ? fmt(m.last) : '-';
      var g = t.querySelector('.lc-tchg'); g.textContent = isN(m.pct) ? (up ? '\u25b2 ' : '\u25bc ') + Math.abs(m.pct).toFixed(2) + '%' : '';
      g.className = 'lc-tchg ' + (up ? 'lc-up' : 'lc-dn');
    }
  };
  P.buildLegend = function () {
    var self = this, items = [{ k: 'e20', n: 'EMA 20', c: C.e20 }, { k: 'e50', n: 'EMA 50', c: C.e50 }], seen = {};
    var list = this.grid ? this.charts : [this.byId[this.sel]];
    list.forEach(function (ch) {
      if (!ch) return;
      ch.strategies.forEach(function (s, i) {
        var k = 's:' + s.id; if (seen[k]) { if (s.chosen) seen[k].ch = true; return; }
        seen[k] = { k: k, n: s.name || s.id, c: SCOL[i % SCOL.length], ch: !!s.chosen }; items.push(seen[k]);
      });
    });
    items.push({ k: 'fc', n: 'Forecast', c: C.cyan }, { k: 'dp', n: 'Depth', c: C.up });
    var sig = items.map(function (i) { return i.k + i.ch + i.n; }).join('|');
    if (sig === this.legSig) return; this.legSig = sig;
    this.legEl.innerHTML = '';
    items.forEach(function (it) {
      var b = document.createElement('button'); b.type = 'button'; b.className = 'lc-chip' + (self.hidden[it.k] ? ' lc-off' : '');
      b.style.color = it.c; b.setAttribute('aria-pressed', self.hidden[it.k] ? 'false' : 'true');
      var lab = document.createElement(it.ch ? 'b' : 'span'); lab.textContent = it.n + (it.ch ? ' \u2605' : ''); lab.style.color = '#e8eef9';
      b.innerHTML = '<i></i>'; b.appendChild(lab);
      b.addEventListener('click', function () {
        self.hidden[it.k] = !self.hidden[it.k]; b.classList.toggle('lc-off', !!self.hidden[it.k]);
        b.setAttribute('aria-pressed', self.hidden[it.k] ? 'false' : 'true'); self.dirtyAll(); self.start();
      });
      self.legEl.appendChild(b);
    });
  };

  /* ---------------- layout ---------------- */
  P.buildPanes = function () {
    var self = this; this.stage.innerHTML = ''; this.panes = [];
    var ids = this.grid ? this.charts.slice(0, 4).map(function (c) { return c.id; }) : [this.sel || ''];
    this.stage.className = 'lc-stage' + (this.grid ? ' lc-grid' : '');
    ids.forEach(function (id) {
      var cell = document.createElement('div'); cell.className = 'lc-cell';
      var cv = document.createElement('canvas'); cv.className = 'lc-cv'; cell.appendChild(cv); self.stage.appendChild(cell);
      var p = new Pane(self, id, cv); self.panes.push(p); p.bind();
    });
    this.gbtn.classList.toggle('lc-on', this.grid);
    this.gbtn.textContent = this.grid ? 'Single' : '2\u00d72 grid';
    this.legSig = ''; this.buildLegend(); this.updateTabs(); this.layout(true); this.start();
  };
  P.layout = function (force) {
    var cw = this.root.clientWidth || this.el.clientWidth || 800, iw = window.innerWidth, ih = window.innerHeight;
    var wide = cw >= 1400; this.gbtn.classList.toggle('lc-show', wide && this.charts.length > 1);
    if (!wide && this.grid) { this.grid = false; this.buildPanes(); return; }
    var portrait = iw < 600 && ih > iw, land = iw > ih && ih <= 520, h;
    if (this.grid) h = 360; else if (land) h = Math.max(220, ih - 70); else if (portrait) h = Math.round(ih * 0.6); else h = cw < 760 ? 440 : 520;
    this.hintEl.classList.toggle('lc-show', portrait && !this.hintOff);
    for (var i = 0; i < this.panes.length; i++) this.panes[i].size(h);
    this.start();
  };

  /* ---------------- pane ---------------- */
  function Pane(I, id, cv) { this.I = I; this.id = id; this.cv = cv; this.c = cv.getContext('2d'); this.w = 0; this.h = 0; this.dpr = 1; this.hover = null; this.dirty = true; this.g = null; this.ptr = {}; }
  Pane.prototype.size = function (h) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2); this.cv.style.height = h + 'px';
    var w = Math.max(1, Math.round(this.cv.clientWidth));
    if (w !== this.w || h !== this.h || dpr !== this.dpr) { this.w = w; this.h = h; this.dpr = dpr; this.cv.width = Math.round(w * dpr); this.cv.height = Math.round(h * dpr); }
    this.dirty = true;
  };
  Pane.prototype.view = function () { var v = this.I.views; return v[this.id] || (v[this.id] = { win: null, off: 0 }); };

  Pane.prototype.bind = function () {
    var self = this, cv = this.cv, drag = null, lastTap = 0, tapX = 0, tapY = 0;
    function pos(e) { var r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
    function reset() { var v = self.view(); v.win = null; v.off = 0; self.hover = null; self.dirty = true; self.I.start(); }
    function zoom(f, ax) {
      var g = self.g, v = self.view(); if (!g) return;
      var nw = clamp(g.win * f, g.minWin, g.maxWin), fr = clamp((ax - g.x0) / g.pw, 0, 1), tA = g.tLeft + fr * g.win;
      var tl = tA - fr * nw, tr = tl + nw; v.win = nw; v.off = clamp(g.lastT + g.fut - tr, 0, g.maxOff); self.dirty = true; self.I.start();
    }
    function pan(dx) { var g = self.g, v = self.view(); if (!g) return; v.off = clamp(v.off + dx / g.pw * g.win, 0, g.maxOff); self.dirty = true; self.I.start(); }
    cv.addEventListener('wheel', function (e) {
      if (!self.g) return; e.preventDefault();
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) pan(-e.deltaX); else zoom(Math.exp(clamp(e.deltaY, -200, 200) * 0.0015), pos(e).x);
    }, { passive: false });
    cv.addEventListener('dblclick', reset);
    cv.addEventListener('pointerdown', function (e) {
      var p = pos(e); self.ptr[e.pointerId] = { x: p.x, y: p.y, sx: p.x, sy: p.y, t: e.pointerType, moved: false };
      try { cv.setPointerCapture(e.pointerId); } catch (x) {}
      var ids = Object.keys(self.ptr);
      if (ids.length === 2) { var a = self.ptr[ids[0]], b = self.ptr[ids[1]]; drag = { pinch: true, d: Math.hypot(a.x - b.x, a.y - b.y) || 1, win: self.g ? self.g.win : 1 }; }
      else drag = { pinch: false };
      if (e.pointerType === 'mouse') cv.classList.add('lc-drag');
    });
    cv.addEventListener('pointermove', function (e) {
      var p = pos(e), q = self.ptr[e.pointerId];
      if (!q) { if (e.pointerType === 'mouse') { self.hover = p; self.dirty = true; self.I.start(); } return; }
      var dx = p.x - q.x; q.x = p.x; q.y = p.y;
      if (Math.hypot(p.x - q.sx, p.y - q.sy) > 6) q.moved = true;
      var ids = Object.keys(self.ptr);
      if (ids.length === 2 && drag && drag.pinch && self.g) {
        var a = self.ptr[ids[0]], b = self.ptr[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y) || 1, g = self.g;
        var nw = clamp(drag.win * drag.d / d, g.minWin, g.maxWin); zoom(nw / g.win, (a.x + b.x) / 2);
      } else if (ids.length === 1 && (q.moved || q.t === 'mouse')) {
        if (q.t === 'mouse') self.hover = p; else self.hover = null;
        pan(dx);
      }
    });
    function up(e) {
      var q = self.ptr[e.pointerId]; if (!q) return;
      delete self.ptr[e.pointerId]; cv.classList.remove('lc-drag'); drag = null;
      if (q.t !== 'mouse' && !q.moved && !Object.keys(self.ptr).length) {
        var now = Date.now();
        if (now - lastTap < 320 && Math.hypot(q.x - tapX, q.y - tapY) < 30) { reset(); lastTap = 0; return; }
        lastTap = now; tapX = q.x; tapY = q.y; self.hover = { x: q.x, y: q.y }; self.dirty = true; self.I.start();
      }
    }
    cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
    cv.addEventListener('pointerleave', function (e) { if (e.pointerType === 'mouse') { self.hover = null; self.dirty = true; self.I.start(); } });
  };

  Pane.prototype.draw = function () {
    var I = this.I, ch = I.byId[this.id], c = this.c, W = this.w, H = this.h;
    if (!W || !H) return;
    c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    c.fillStyle = C.panel; c.fillRect(0, 0, W, H);
    var r = ch && I.rt[ch.id], cs = ch ? ch.candles : [];
    this.g = null;
    if (!ch || !cs.length) {
      c.fillStyle = C.muted; c.font = '13px ' + SANS; c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('Waiting for the first candles\u2026', W / 2, H / 2); return;
    }
    var hid = I.hidden, step = r.step, hs = step / 2, n = cs.length, lastC = cs[n - 1], lastT = lastC[0];
    var compact = W < 620 || H < 340, narrow = W < 480, fs = compact ? 10 : 11, fsS = compact ? 9 : 10;
    var disp = isN(r.disp) ? r.disp : lastC[4];

    // forecast horizon & window
    var tr = ch.trade && typeof ch.trade === 'object' ? ch.trade : null;
    var fc = tr && Array.isArray(tr.forecast) ? tr.forecast.filter(function (f) { return f && isN(f.t) && isN(f.px); }) : [];
    var horizon = 0; fc.forEach(function (f) { if (f.t - lastT > horizon) horizon = f.t - lastT; });
    var fut = fc.length ? horizon + 3 * step : 6 * step;
    var n0 = W < 500 ? 60 : W < 900 ? 90 : 110; n0 = Math.max(n0, fut / step * 0.7);
    var v = this.view(), win = v.win == null ? n0 * step + fut : v.win;
    var minWin = 12 * step, maxWin = (n + 20) * step + fut; win = clamp(win, minWin, maxWin);
    var maxOff = Math.max(0, lastT - cs[0][0] + fut - 10 * step); v.off = clamp(v.off, 0, maxOff);
    var tRight = lastT + fut - v.off, tLeft = tRight - win;

    // vertical layout
    var dp = ch.depth && typeof ch.depth === 'object' && Array.isArray(ch.depth.bids) && Array.isArray(ch.depth.asks) && !hid.dp ? ch.depth : null;
    var stripOn = dp && narrow, bandH = narrow ? (stripOn ? 68 : 52) : 24, axisH = compact ? 18 : 22;
    var plotT = bandH, plotB = H - axisH, plotH = plotB - plotT, volH = plotH * 0.13, yTop = plotT + 8, yBot = plotB - volH * 0.6;

    // y range
    var i0 = Math.max(0, lb(cs, tLeft - step * 2) - 1), i1 = Math.min(n, lb(cs, tRight + step)), hi = -Infinity, lo = Infinity, vmax = 0, i;
    for (i = i0; i < i1; i++) { var k = cs[i]; if (k[2] > hi) hi = k[2]; if (k[3] < lo) lo = k[3]; if (k[5] > vmax) vmax = k[5]; }
    if (!isFinite(hi)) { hi = lastC[2]; lo = lastC[3]; }
    if (disp > hi) hi = disp; if (disp < lo) lo = disp;
    function inc(p) { if (isN(p)) { if (p > hi) hi = p; if (p < lo) lo = p; } }
    var chosen = null; ch.strategies.forEach(function (s) { if (s.chosen) chosen = s; });
    if (chosen && !hid['s:' + chosen.id]) chosen.line.forEach(function (p) { if (p[0] >= tLeft && p[0] <= tRight) inc(p[1]); });
    if (!hid.fc) fc.forEach(function (f) { if (f.t <= tRight) inc(f.px); });
    if (tr && isN(+tr.stop) && isN(+tr.target) && tr.entry && tr.entry[0] >= tLeft - win) { inc(+tr.stop); inc(+tr.target); }
    var pad = (hi - lo || Math.abs(hi) * 0.01 || 1) * 0.07; hi += pad; lo -= pad;
    if (!isN(r.yHi) || !isN(r.yLo) || r.pane !== this.id) { r.yHi = hi; r.yLo = lo; r.pane = this.id; }
    else {
      var ay = (hi - lo) * 0.002;
      if (Math.abs(r.yHi - hi) > ay || Math.abs(r.yLo - lo) > ay) { r.yHi += (hi - r.yHi) * 0.3; r.yLo += (lo - r.yLo) * 0.3; this.dirty = true; } else { r.yHi = hi; r.yLo = lo; }
    }
    hi = r.yHi; lo = r.yLo;
    function Y(p) { return yTop + (hi - p) / (hi - lo) * (yBot - yTop); }

    // y ticks & axis width
    var tstep = nice((hi - lo), Math.max(3, Math.floor(plotH / (compact ? 38 : 46)))), td = decs(tstep), ticks = [];
    for (var tv = Math.ceil(lo / tstep) * tstep; tv <= hi; tv += tstep) ticks.push(tv);
    var pd = Math.abs(r.tgt) >= 1e5 ? 0 : Math.max(td, 2);
    c.font = '600 ' + fsS + 'px ' + MONO;
    var mw = c.measureText(fmt(r.tgt, pd)).width;
    ticks.forEach(function (t) { var w = c.measureText(fmt(t, td)).width; if (w > mw) mw = w; });
    var yAxW = Math.ceil(mw) + 14, depW = dp && !narrow ? (compact ? 94 : 114) : 0;
    var plotL = 6, plotR = W - yAxW - depW, pw = plotR - plotL;
    function X(t) { return plotL + (t + hs - tLeft) / win * pw; }
    var bw = Math.max(1, step / win * pw * 0.72);
    this.g = { x0: plotL, pw: pw, tLeft: tLeft, win: win, minWin: minWin, maxWin: maxWin, lastT: lastT, fut: fut, maxOff: maxOff, hs: hs };

    // grid
    c.save(); c.beginPath(); c.rect(plotL, plotT, pw, plotH); c.clip();
    c.strokeStyle = C.grid; c.lineWidth = 1; c.globalAlpha = 0.55; c.beginPath();
    ticks.forEach(function (t) { var y = Math.round(Y(t)) + 0.5; c.moveTo(plotL, y); c.lineTo(plotR, y); });
    var xs = [600, 1200, 1800, 3600, 7200, 14400, 21600, 43200], xstep = xs[xs.length - 1];
    for (i = 0; i < xs.length; i++) if (xs[i] / win * pw >= (compact ? 54 : 70)) { xstep = xs[i]; break; }
    var xt = [], t0 = Math.ceil((tLeft - hs + IST) / xstep) * xstep - IST;
    for (var tt = t0; tt <= tRight - hs; tt += xstep) { xt.push(tt); var x = Math.round(X(tt)) + 0.5; c.moveTo(x, plotT); c.lineTo(x, plotB); }
    c.stroke(); c.globalAlpha = 1;

    // levels
    var tags = [], fonts = fsS + 'px ' + SANS;
    var lastY = Y(disp);
    (ch.levels || []).forEach(function (l) {
      if (l.px > hi || l.px < lo) return;
      var col = l.kind === 'ref' ? C.muted : l.kind === 'breakeven' ? '#e6a8ff' : C.dim, y = Y(l.px);
      c.strokeStyle = rgba(col, 0.75); c.lineWidth = 1; c.setLineDash([1.5, 3.5]); c.beginPath(); c.moveTo(plotL, y); c.lineTo(plotR, y); c.stroke(); c.setLineDash([]);
      c.font = fonts; c.textAlign = 'left'; c.textBaseline = 'bottom'; c.fillStyle = rgba(col, 0.95); c.lineWidth = 3; c.strokeStyle = C.panel; c.strokeText(l.label || '', plotL + 6, y - 2); c.fillText(l.label || '', plotL + 6, y - 2);
      tags.push({ p: y, s: 15, bg: rgba(col, 0.28), fg: col, text: fmt(l.px, pd), pr: 1 });
    });

    // volume
    for (i = i0; i < i1; i++) {
      var q = cs[i], vh = vmax ? q[5] / vmax * volH : 0, vx = X(q[0]);
      c.fillStyle = rgba(q[4] >= q[1] ? C.up : C.dn, 0.2); c.fillRect(vx - bw / 2, plotB - vh, bw, vh);
    }

    // strategy lines (light), then EMAs
    var labels = [];
    function path(pts, w, col, alpha, lw) {
      c.beginPath(); var st = false;
      for (var j = 0; j < pts.length; j++) { var px = X(pts[j][0]), py = Y(pts[j][1]); if (!st) { c.moveTo(px, py); st = true; } else c.lineTo(px, py); }
      c.lineWidth = lw; c.strokeStyle = col; c.globalAlpha = alpha; c.lineJoin = 'round'; c.lineCap = 'round'; c.stroke(); c.globalAlpha = 1;
    }
    ch.strategies.forEach(function (s, si) {
      if (hid['s:' + s.id] || !s.line.length) return;
      var col = SCOL[si % SCOL.length]; if (!s.chosen) path(s.line, 0, col, 0.35, 1.2);
      var lp = s.line[s.line.length - 1]; labels.push({ p: Y(lp[1]), s: 13, text: s.name || s.id, col: col, ch: !!s.chosen, x: X(lp[0]) + 7 });
    });
    function emaPts(arr, tl) { var out = [], a = 2 / (tl + 1); for (var j = Math.max(0, i0 - 1); j < i1 && j < n; j++) out.push([cs[j][0], j === n - 1 ? (n > 1 ? a * disp + (1 - a) * arr[n - 2] : disp) : arr[j]]); return out; }
    if (!hid.e20) path(emaPts(r.e20, 20), 0, C.e20, 1, 1.4);
    if (!hid.e50) path(emaPts(r.e50, 50), 0, C.e50, 1, 1.4);

    // candles
    for (i = i0; i < i1; i++) {
      var k2 = cs[i], o = k2[1], h = k2[2], l = k2[3], cl = k2[4];
      if (i === n - 1) { cl = disp; if (cl > h) h = cl; if (cl < l) l = cl; }
      var col2 = cl >= o ? C.up : C.dn, cx = Math.round(X(k2[0])) + 0.5;
      c.strokeStyle = col2; c.fillStyle = col2; c.lineWidth = 1; c.beginPath(); c.moveTo(cx, Y(h)); c.lineTo(cx, Y(l)); c.stroke();
      var yo = Y(o), yc = Y(cl), top = Math.min(yo, yc), bh = Math.max(1, Math.abs(yo - yc));
      c.fillRect(Math.round(cx - bw / 2), Math.round(top), Math.max(1, Math.round(bw)), Math.round(bh));
    }

    // chosen strategy: dark halo + strong line
    var chosenOn = chosen && chosen.line.length && !hid['s:' + chosen.id];
    if (chosenOn) {
      var ccol = SCOL[ch.strategies.indexOf(chosen) % SCOL.length];
      path(chosen.line, 0, C.bg, 0.92, 7.5); path(chosen.line, 0, ccol, 1, 3.2);
    }

    // trade markers
    var dots = [];
    if (tr) {
      var en = Array.isArray(tr.entry) && isN(+tr.entry[0]) && isN(+tr.entry[1]) ? [+tr.entry[0], +tr.entry[1]] : null,
        ex = Array.isArray(tr.exit) && isN(+tr.exit[0]) && isN(+tr.exit[1]) ? [+tr.exit[0], +tr.exit[1]] : null,
        sl = isN(+tr.stop) && tr.stop !== null ? +tr.stop : null, tp = isN(+tr.target) && tr.target !== null ? +tr.target : null;
      if (en) {
        var ex0 = X(en[0]), endX = X(ex ? ex[0] : lastT);
        if (sl != null && tp != null) { c.strokeStyle = rgba(C.dim, 0.9); c.lineWidth = 1; c.beginPath(); c.moveTo(ex0, Y(tp)); c.lineTo(ex0, Y(sl)); c.stroke(); }
        [[sl, C.dn], [tp, C.up]].forEach(function (z) { if (z[0] == null) return; c.strokeStyle = rgba(z[1], 0.5); c.lineWidth = 1; c.setLineDash([5, 4]); c.beginPath(); c.moveTo(ex0, Y(z[0])); c.lineTo(endX, Y(z[0])); c.stroke(); c.setLineDash([]); });
        if (chosenOn) {
          var ly = interp(chosen.line, en[0]);
          if (isN(ly)) {
            c.strokeStyle = rgba(C.blue, 0.7); c.lineWidth = 1; c.setLineDash([2, 3]); c.beginPath(); c.moveTo(ex0, Y(en[1])); c.lineTo(ex0, Y(ly)); c.stroke(); c.setLineDash([]);
            c.beginPath(); c.arc(ex0, Y(ly), 3, 0, 6.3); c.strokeStyle = C.blue; c.lineWidth = 1.5; c.fillStyle = C.bg; c.fill(); c.stroke();
          }
        }
        dots.push({ x: ex0, y: Y(en[1]), col: C.blue, text: 'Entry ' + fmt(en[1], pd) });
        if (sl != null) dots.push({ x: ex0, y: Y(sl), col: C.dn, text: 'SL ' + fmt(sl, pd) });
        if (tp != null) dots.push({ x: ex0, y: Y(tp), col: C.up, text: 'Target ' + fmt(tp, pd) });
        tags.push({ p: Y(en[1]), s: 15, bg: C.blue, fg: '#fff', text: fmt(en[1], pd), pr: 3 });
      }
      if (ex) { dots.push({ x: X(ex[0]), y: Y(ex[1]), col: C.exit, text: 'Exit ' + fmt(ex[1], pd) }); tags.push({ p: Y(ex[1]), s: 15, bg: C.exit, fg: '#1a1204', text: fmt(ex[1], pd), pr: 3 }); }
    }

    // forecast
    var fx = [], lx = X(lastT);
    if (!hid.fc) fc.forEach(function (f, fi) {
      var col = /target|tp/i.test(f.label || '') ? C.up : /stop|sl/i.test(f.label || '') ? C.dn : /time|exit/i.test(f.label || '') ? '#e9edf7' : FCOL[fi % FCOL.length];
      var x = X(f.t), y = Y(f.px); if (f.t < lastT) return;
      c.strokeStyle = col; c.lineWidth = 1.6; c.setLineDash([6, 4]); c.beginPath(); c.moveTo(lx, lastY); c.lineTo(x, y); c.stroke();
      if (x <= plotR) {
        c.strokeStyle = rgba(col, 0.5); c.lineWidth = 1; c.setLineDash([2, 4]);
        c.beginPath(); c.moveTo(x, y); c.lineTo(plotR, y); c.moveTo(x, y); c.lineTo(x, plotB); c.stroke();
      }
      c.setLineDash([]);
      if (x <= plotR + 1) {
        c.beginPath(); c.arc(x, y, 4.5, 0, 6.3); c.fillStyle = C.bg; c.fill(); c.strokeStyle = col; c.lineWidth = 2; c.stroke();
        dots.push({ x: x, y: y, col: col, text: f.label || '', ring: true, up: f.px >= disp, right: false });
        tags.push({ p: y, s: 15, bg: col, fg: '#06101c', text: fmt(f.px, pd), pr: 2 });
        fx.push({ p: x, s: 0, col: col, text: hm(f.t) });
      }
    });
    c.restore();

    c.save(); c.beginPath(); c.rect(plotL, plotT, pw, plotH); c.clip();
    // strategy name labels
    labels.sort(function (a, b) { return a.p - b.p; }); labels.forEach(function (l) { l.fixed = false; });
    resolve(labels, plotT + 8, plotB - 8);
    labels.forEach(function (l) {
      c.font = (l.ch ? '700 ' : '') + fsS + 'px ' + SANS; var w = c.measureText(l.text).width + 8, lx2 = Math.min(l.x, plotR - w - 2);
      pill(lx2, l.q - 7, w, 14, 4, 'rgba(12,20,36,0.82)', c);
      c.fillStyle = l.ch ? l.col : rgba(l.col, 0.75); c.textAlign = 'left'; c.textBaseline = 'middle'; c.fillText(l.text, lx2 + 4, l.q + 0.5);
    });
    // dot labels (clipped to plot)
    dots.forEach(function (d) {
      if (d.x < plotL - 4 || d.x > plotR + 4) return;
      if (!d.ring) { c.beginPath(); c.arc(d.x, d.y, 7, 0, 6.3); c.fillStyle = C.bg; c.fill(); c.beginPath(); c.arc(d.x, d.y, 4.8, 0, 6.3); c.fillStyle = d.col; c.fill(); }
      c.font = '600 ' + fsS + 'px ' + SANS; c.lineWidth = 3; c.strokeStyle = C.panel; c.fillStyle = d.col;
      var tw = c.measureText(d.text).width, left = d.ring || d.x + tw + 14 > plotR;
      c.textAlign = left ? 'right' : 'left'; c.textBaseline = d.ring ? (d.up ? 'bottom' : 'top') : 'middle';
      var tx = left ? d.x - 8 : d.x + 9, ty = d.ring ? d.y + (d.up ? -6 : 6) : d.y;
      c.strokeText(d.text, tx, ty); c.fillText(d.text, tx, ty);
    });
    // last-price line
    c.strokeStyle = rgba(C.cyan, 0.7); c.lineWidth = 1; c.setLineDash([2, 3]); c.beginPath(); c.moveTo(plotL, lastY); c.lineTo(plotR, lastY); c.stroke(); c.setLineDash([]);
    var ph = (performance.now() % 1600) / 1600;
    c.beginPath(); c.arc(lx, lastY, 3, 0, 6.3); c.fillStyle = C.cyan; c.fill();
    c.beginPath(); c.arc(lx, lastY, 3 + ph * 9, 0, 6.3); c.strokeStyle = rgba(C.cyan, 0.8 * (1 - ph)); c.lineWidth = 1.5; c.stroke();
    c.restore();

    // crosshair
    var hv = this.hover, hcI = -1, hx = 0;
    if (hv && hv.x >= plotL && hv.x <= plotR && hv.y >= plotT && hv.y <= plotB) {
      var tq = tLeft + (hv.x - plotL) / pw * win - hs; hcI = clamp(lb(cs, tq), 0, n - 1);
      if (hcI > 0 && Math.abs(cs[hcI - 1][0] - tq) < Math.abs(cs[hcI][0] - tq)) hcI--;
      if (tq > lastT + step) hcI = -1;
    }
    if (hcI >= 0) {
      hx = X(cs[hcI][0]); c.strokeStyle = rgba(C.fg, 0.4); c.lineWidth = 1; c.setLineDash([4, 3]); c.beginPath();
      c.moveTo(Math.round(hx) + 0.5, plotT); c.lineTo(Math.round(hx) + 0.5, plotB); c.moveTo(plotL, Math.round(hv.y) + 0.5); c.lineTo(plotR, Math.round(hv.y) + 0.5); c.stroke(); c.setLineDash([]);
    }

    // ---- axes ----
    c.fillStyle = C.panel; c.fillRect(plotR, 0, W - plotR, H); c.fillRect(0, plotB, plotR, axisH);
    c.strokeStyle = C.grid; c.lineWidth = 1; c.beginPath(); c.moveTo(plotR + 0.5, plotT); c.lineTo(plotR + 0.5, plotB); c.moveTo(plotL, plotB + 0.5); c.lineTo(plotR, plotB + 0.5); c.stroke();
    // y tags
    var allTags = tags.slice(); allTags.push({ p: lastY, s: 16, bg: C.cyan, fg: '#04101c', text: fmt(r.tgt, pd), fixed: true, pr: 9, last: true });
    resolve(allTags, plotT + 8, plotB - 6);
    c.font = '600 ' + fsS + 'px ' + MONO; c.textAlign = 'left'; c.textBaseline = 'middle';
    ticks.forEach(function (t) {
      var y = Y(t); if (y < plotT + 6 || y > plotB - 4) return;
      for (var j = 0; j < allTags.length; j++) if (Math.abs(allTags[j].q - y) < 10) return;
      c.fillStyle = C.muted; c.fillText(fmt(t, td), plotR + 6, y);
    });
    allTags.sort(function (a, b) { return a.pr - b.pr; });
    allTags.forEach(function (t) {
      if (t.q < plotT - 2 || t.q > plotB + 2) return;
      var w = yAxW - 3, glow = 0;
      if (t.last) { glow = Math.sin(ph * 6.2832) * 0.5 + 0.5; c.shadowColor = C.cyan; c.shadowBlur = 4 + glow * 8; }
      c.beginPath(); c.moveTo(plotR, t.p); c.lineTo(plotR + 5, t.q - t.s / 2); c.lineTo(plotR + 5, t.q + t.s / 2); c.closePath(); c.fillStyle = t.bg; c.fill();
      pill(plotR + 4, t.q - t.s / 2, w - 1, t.s, 3, t.bg, c); c.shadowBlur = 0; c.shadowColor = 'transparent';
      c.font = '600 ' + fsS + 'px ' + MONO; c.fillStyle = t.fg; c.textAlign = 'left'; c.textBaseline = 'middle'; c.fillText(t.text, plotR + 8, t.q + 0.5);
    });
    // x ticks & tags
    var xtags = fx.map(function (f) { c.font = '600 ' + fsS + 'px ' + MONO; f.s = c.measureText(f.text).width + 10; return f; });
    resolve(xtags, plotL + 14, plotR - 14);
    c.textAlign = 'center'; c.textBaseline = 'middle'; c.font = fsS + 'px ' + MONO;
    xt.forEach(function (t) {
      var x = X(t); if (x < plotL + 12 || x > plotR - 12) return;
      for (var j = 0; j < xtags.length; j++) if (Math.abs(xtags[j].q - x) < xtags[j].s / 2 + 18) return;
      if (hcI >= 0 && Math.abs(hx - x) < 32) return;
      c.fillStyle = C.muted; c.fillText(hm(t), x, plotB + axisH / 2 + 1);
    });
    xtags.forEach(function (f) { pill(f.q - f.s / 2, plotB + 2, f.s, axisH - 3, 3, f.col, c); c.fillStyle = '#06101c'; c.font = '600 ' + fsS + 'px ' + MONO; c.textAlign = 'center'; c.fillText(f.text, f.q, plotB + axisH / 2 + 1); });
    if (hcI >= 0) {
      var tx = hm(cs[hcI][0]), tw2 = c.measureText(tx).width + 12;
      c.font = '600 ' + fsS + 'px ' + MONO; tw2 = c.measureText(tx).width + 12;
      var bx = clamp(hx - tw2 / 2, plotL, plotR - tw2); pill(bx, plotB + 2, tw2, axisH - 3, 3, C.fg, c); c.fillStyle = '#06101c'; c.textAlign = 'center'; c.fillText(tx, bx + tw2 / 2, plotB + axisH / 2 + 1);
      var hp = hi - (hv.y - yTop) / (yBot - yTop) * (hi - lo); pill(plotR + 4, hv.y - 8, yAxW - 4, 16, 3, C.fg, c);
      c.fillStyle = '#06101c'; c.textAlign = 'left'; c.fillText(fmt(hp, pd), plotR + 8, hv.y + 0.5);
    }

    // ---- header ----
    var hq = cs[hcI >= 0 ? hcI : n - 1], hl = hcI >= 0 || hq !== lastC ? hq[4] : disp, m = chgOf(ch);
    var sym = (ch.symbol || ch.label || ch.id) + ' \u00b7 ' + (ch.tf || ''), up = hl >= hq[1];
    var parts = [['O', hq[1]], ['H', hq[2]], ['L', hq[3]], ['C', hl]];
    c.textBaseline = 'middle'; c.textAlign = 'left';
    var hy = 12, hxp = plotL + 6, hf = '600 ' + (compact ? 10 : 11) + 'px ' + MONO;
    c.font = '700 ' + (compact ? 11 : 12) + 'px ' + SANS; c.fillStyle = C.fg; c.fillText(sym, hxp, hy); hxp += c.measureText(sym).width + 12;
    if (narrow) { hxp = plotL + 6; hy += 15; }
    c.font = hf;
    var items = parts.map(function (p) { return [p[0], fmt(p[1], pd)]; }); items.push(['V', fmtQ(hq[5])]);
    if (isN(m.pct) && hcI < 0) items.push(['', (m.pct >= 0 ? '+' : '') + m.pct.toFixed(2) + '%']);
    items.forEach(function (it) {
      var lw = c.measureText(it[0] ? it[0] + ' ' : '').width, vw = c.measureText(it[1]).width;
      if (hxp + lw + vw > plotR - 4) { hxp = plotL + 6; hy += 14; }
      c.fillStyle = C.dim; c.fillText(it[0] ? it[0] + ' ' : '', hxp, hy); c.fillStyle = it[0] === '' ? (m.pct >= 0 ? C.up : C.dn) : up ? C.up : C.dn;
      if (it[0] === 'V') c.fillStyle = C.muted; c.fillText(it[1], hxp + lw, hy); hxp += lw + vw + 10;
    });
    if (tr && tr.side) {
      var pn = isN(+tr.pnl_rs) && tr.pnl_rs !== null ? +tr.pnl_rs : null,
        ts = tr.side + ' ' + (tr.status || '') + (pn != null ? '  ' + (pn >= 0 ? '+' : '\u2212') + '\u20b9' + fmt(Math.abs(pn), 0) : '');
      c.font = '700 ' + fsS + 'px ' + MONO; var tw3 = c.measureText(ts).width;
      var rx = plotR - tw3 - 6, ry = 12;
      if (narrow ? c.measureText(sym).width + tw3 + 30 < pw : hxp < rx - 6) { c.fillStyle = pn != null && pn < 0 ? C.dn : pn != null ? C.up : C.muted; c.textAlign = 'left'; c.fillText(ts, rx, ry); }
    }
    // narrow buyers/sellers strip
    if (stripOn) { this.buySell(ch.depth, plotL + 6, bandH - 15, pw - 12, 11, fsS); }

    // ---- depth ladder ----
    if (dp && !narrow) this.ladder(dp, plotR + yAxW, plotT, plotB, W - plotR - yAxW, lastY, r.tgt, pd, fsS, up);
    c.lineWidth = 1;
  };

  function interp(line, t) {
    if (!line.length || t < line[0][0] || t > line[line.length - 1][0]) return NaN;
    var i = lb(line, t); if (i === 0) return line[0][1]; var a = line[i - 1], b = line[i];
    return b[0] === a[0] ? b[1] : a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0]);
  }
  Pane.prototype.buySell = function (d, x, y, w, h, fs, short) {
    var c = this.c, b = +d.buy_qty, s = +d.sell_qty; if (!isN(b) || !isN(s) || b + s <= 0) return;
    var pb = b / (b + s), bw = w * pb;
    pill(x, y, w, h, 3, rgba(C.dn, 0.85), c); c.save(); c.beginPath(); c.rect(x, y, bw, h); c.clip(); pill(x, y, w, h, 3, C.up, c); c.restore();
    c.font = '700 ' + (fs - 1) + 'px ' + SANS; c.textBaseline = 'middle'; c.fillStyle = '#04140e'; c.textAlign = 'left'; c.fillText((short ? '' : 'Buyers ') + Math.round(pb * 100) + '%', x + 4, y + h / 2 + 0.5);
    c.fillStyle = '#2a0710'; c.textAlign = 'right'; c.fillText((short ? '' : 'Sellers ') + Math.round((1 - pb) * 100) + '%', x + w - 4, y + h / 2 + 0.5);
  };
  Pane.prototype.ladder = function (d, x, y0, y1, w, midY, last, pd, fs) {
    var c = this.c, asks = d.asks.filter(function (a) { return a && isN(+a[0]) && isN(+a[1]); }).map(function (a) { return [+a[0], +a[1]]; }).sort(function (a, b) { return a[0] - b[0]; }).slice(0, 5),
      bids = d.bids.filter(function (a) { return a && isN(+a[0]) && isN(+a[1]); }).map(function (a) { return [+a[0], +a[1]]; }).sort(function (a, b) { return b[0] - a[0]; }).slice(0, 5);
    c.fillStyle = '#09111f'; c.fillRect(x, 0, w, this.h); c.strokeStyle = C.grid; c.beginPath(); c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, this.h); c.stroke();
    c.font = '700 ' + (fs - 1) + 'px ' + SANS; c.fillStyle = C.dim; c.textAlign = 'left'; c.textBaseline = 'middle'; c.fillText('MARKET DEPTH', x + 6, 12);
    var blockH = 38, rows = asks.length + bids.length + 1, avail = y1 - y0 - blockH - 6, rh = clamp(Math.floor(avail / Math.max(rows, 1)), 11, 18);
    var tot = rows * rh, top = clamp(midY - (asks.length + 0.5) * rh, y0 + 4, Math.max(y0 + 4, y1 - blockH - tot - 2));
    var mx = 1; asks.concat(bids).forEach(function (a) { if (a[1] > mx) mx = a[1]; });
    var bwid = w - 6, ry = top;
    function row(px, q, col, bar) {
      if (bar) { c.fillStyle = rgba(col, 0.26); c.fillRect(x + 3, ry + 1, Math.max(2, bwid * q / mx), rh - 2); }
      c.font = '600 ' + fs + 'px ' + MONO; c.textBaseline = 'middle'; c.textAlign = 'left'; c.fillStyle = col; c.fillText(fmt(px, pd), x + 6, ry + rh / 2 + 0.5);
      c.textAlign = 'right'; c.fillStyle = C.muted; c.fillText(fmtQ(q), x + w - 4, ry + rh / 2 + 0.5); ry += rh;
    }
    for (var i = asks.length - 1; i >= 0; i--) row(asks[i][0], asks[i][1], C.dn, true);
    c.fillStyle = rgba(C.cyan, 0.16); c.fillRect(x + 1, ry, w - 1, rh); c.font = '700 ' + fs + 'px ' + MONO; c.fillStyle = C.cyan; c.textAlign = 'left'; c.textBaseline = 'middle'; c.fillText(fmt(last, pd), x + 6, ry + rh / 2 + 0.5);
    c.textAlign = 'right'; c.fillStyle = C.muted; c.font = '600 ' + (fs - 1) + 'px ' + SANS; c.fillText('LTP', x + w - 4, ry + rh / 2 + 0.5); ry += rh;
    for (i = 0; i < bids.length; i++) row(bids[i][0], bids[i][1], C.up, true);
    this.buySell(d, x + 6, y1 - 20, w - 12, 12, fs, true);
    c.font = '700 ' + (fs - 1) + 'px ' + SANS; c.fillStyle = C.dim; c.textAlign = 'left'; c.fillText('BUYERS vs SELLERS', x + 6, y1 - 30);
  };

  window.LiveCharts = {
    mount: function (el, opts) {
      if (typeof el === 'string') el = document.querySelector(el);
      var I = new Inst(el, opts);
      return {
        update: function (d) { return I.update(d); },
        tick: function (id, p, t) { return I.tick(id, p, t); },
        select: function (id) { return I.select(id); },
        destroy: function () { return I.destroy(); }
      };
    }
  };
})();
