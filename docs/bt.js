/*! bt.js - NIFTY 50 intraday strategy backtester on 1-minute candles. Works in the browser (window.BT) and in Node (module.exports).
 *
 *  Data: nifty50_1m_YYYY.bin.gz from the charts branch (int32 x5 per candle: Unix seconds, open, high, low, close in paise).
 *  Honest by construction: a signal is read at a candle's close and the trade enters at the NEXT candle's open; a stop and a target
 *  inside the same candle count as the stop; a gap through a level fills at the open; every trade is out by the exit time or the close.
 *  The index has no volume, so "VWAP" here is the session's average typical price (equal weight per minute).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(); else root.BT = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var IST = 19800, OPEN = 555, LAST = 929;           // 09:15 and 15:29 in minutes of the day

  function decode(buf) {
    var a = new Int32Array(buf), n = a.length / 5, D = { n: n, ts: new Int32Array(n), o: new Float64Array(n), h: new Float64Array(n), l: new Float64Array(n), c: new Float64Array(n) };
    for (var i = 0, j = 0; i < n; i++, j += 5) { D.ts[i] = a[j]; D.o[i] = a[j + 1] / 100; D.h[i] = a[j + 2] / 100; D.l[i] = a[j + 3] / 100; D.c[i] = a[j + 4] / 100; }
    return D;
  }
  function concat(parts) {
    parts = parts.filter(Boolean).sort(function (x, y) { return x.ts[0] - y.ts[0]; });
    var n = parts.reduce(function (s, p) { return s + p.n; }, 0), D = { n: n, ts: new Int32Array(n), o: new Float64Array(n), h: new Float64Array(n), l: new Float64Array(n), c: new Float64Array(n) }, k = 0;
    parts.forEach(function (p) { ['ts', 'o', 'h', 'l', 'c'].forEach(function (f) { D[f].set(p[f], k); }); k += p.n; });
    return D;
  }
  var dayNo = function (ts) { return Math.floor((ts + IST) / 86400); };
  var minOf = function (ts) { return Math.floor(((ts + IST) % 86400) / 60); };
  var dayStr = function (dn) { return new Date(dn * 86400000).toISOString().slice(0, 10); };
  var hhmm = function (m) { return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0'); };
  var toMin = function (s) { var p = String(s).split(':'); return +p[0] * 60 + +p[1]; };

  /* ---------- bars of tf minutes from 09:15, sessions with at least minCandles regular minutes ---------- */
  function bars(D, tf, minCandles) {
    tf = tf || 5; minCandles = minCandles == null ? 300 : minCandles;
    var t = [], o = [], h = [], l = [], c = [], m = [], days = [], i = 0;
    while (i < D.n) {
      var dn = dayNo(D.ts[i]), j = i, reg = 0;
      while (j < D.n && dayNo(D.ts[j]) === dn) { var mm = minOf(D.ts[j]); if (mm >= OPEN && mm <= LAST) reg++; j++; }
      if (reg >= minCandles) {
        var start = t.length, cur = -1, d = new Date(dn * 86400000);
        for (var k = i; k < j; k++) {
          var mo = minOf(D.ts[k]); if (mo < OPEN || mo > LAST) continue;
          var b = Math.floor((mo - OPEN) / tf);
          if (b !== cur) { cur = b; t.push(D.ts[k] - ((mo - OPEN) % tf) * 60); m.push(OPEN + b * tf); o.push(D.o[k]); h.push(D.h[k]); l.push(D.l[k]); c.push(D.c[k]); }
          else { var q = t.length - 1; if (D.h[k] > h[q]) h[q] = D.h[k]; if (D.l[k] < l[q]) l[q] = D.l[k]; c[q] = D.c[k]; }
        }
        days.push({ day: dayStr(dn), dow: d.getUTCDay(), a: start, b: t.length });
      }
      i = j;
    }
    var F = function (x) { return Float64Array.from(x); };
    return { tf: tf, n: t.length, t: Int32Array.from(t), o: F(o), h: F(h), l: F(l), c: F(c), m: Int32Array.from(m), days: days };
  }

  /* ---------- indicators (continuous across sessions unless said) ---------- */
  function ema(x, n) { var out = new Float64Array(x.length), k = 2 / (n + 1), e = x[0]; for (var i = 0; i < x.length; i++) { e = i ? e + k * (x[i] - e) : x[0]; out[i] = e; } return out; }
  function sma(x, n) { var out = new Float64Array(x.length), s = 0; for (var i = 0; i < x.length; i++) { s += x[i]; if (i >= n) s -= x[i - n]; out[i] = s / Math.min(i + 1, n); } return out; }
  function stdev(x, n, mean) { var out = new Float64Array(x.length); for (var i = 0; i < x.length; i++) { var a = Math.max(0, i - n + 1), s = 0; for (var j = a; j <= i; j++) s += (x[j] - mean[i]) * (x[j] - mean[i]); out[i] = Math.sqrt(s / (i - a + 1)); } return out; }
  function rsi(c, n) {
    var out = new Float64Array(c.length), g = 0, ls = 0; out[0] = 50;
    for (var i = 1; i < c.length; i++) {
      var d = c[i] - c[i - 1], up = d > 0 ? d : 0, dn = d < 0 ? -d : 0;
      if (i <= n) { g += up / n; ls += dn / n; } else { g = (g * (n - 1) + up) / n; ls = (ls * (n - 1) + dn) / n; }
      out[i] = ls === 0 ? 100 : 100 - 100 / (1 + g / ls);
    }
    return out;
  }
  function atr(B, n) {
    var out = new Float64Array(B.n), a = 0;
    for (var i = 0; i < B.n; i++) {
      var tr = i ? Math.max(B.h[i] - B.l[i], Math.abs(B.h[i] - B.c[i - 1]), Math.abs(B.l[i] - B.c[i - 1])) : B.h[i] - B.l[i];
      a = i < n ? (a * i + tr) / (i + 1) : (a * (n - 1) + tr) / n; out[i] = a;
    }
    return out;
  }
  function adx(B, n) {
    var out = new Float64Array(B.n), tr = 0, pd = 0, md = 0, ax = 0;
    for (var i = 1; i < B.n; i++) {
      var up = B.h[i] - B.h[i - 1], dn = B.l[i - 1] - B.l[i], p = up > dn && up > 0 ? up : 0, q = dn > up && dn > 0 ? dn : 0;
      var t = Math.max(B.h[i] - B.l[i], Math.abs(B.h[i] - B.c[i - 1]), Math.abs(B.l[i] - B.c[i - 1]));
      tr = tr - tr / n + t; pd = pd - pd / n + p; md = md - md / n + q;
      var pdi = tr ? 100 * pd / tr : 0, mdi = tr ? 100 * md / tr : 0, dx = pdi + mdi ? 100 * Math.abs(pdi - mdi) / (pdi + mdi) : 0;
      ax = i < 2 * n ? (ax * (i - 1) + dx) / i : (ax * (n - 1) + dx) / n; out[i] = ax;
    }
    return out;
  }
  function supertrend(B, n, mult, A) {
    var dir = new Int8Array(B.n), line = new Float64Array(B.n), fu = 0, fl = 0;
    for (var i = 0; i < B.n; i++) {
      var mid = (B.h[i] + B.l[i]) / 2, bu = mid + mult * A[i], bl = mid - mult * A[i];
      if (!i) { fu = bu; fl = bl; dir[i] = 1; line[i] = fl; continue; }
      fu = bu < fu || B.c[i - 1] > fu ? bu : fu; fl = bl > fl || B.c[i - 1] < fl ? bl : fl;
      dir[i] = dir[i - 1] === 1 ? (B.c[i] < fl ? -1 : 1) : (B.c[i] > fu ? 1 : -1);
      line[i] = dir[i] === 1 ? fl : fu;
    }
    return { dir: dir, line: line };
  }
  /* per-session values: VWAP (equal-weight typical price), day open, opening range, previous session's close/high/low, high/low so far */
  function session(B, orMin) {
    var n = B.n, vw = new Float64Array(n), dOpen = new Float64Array(n), orH = new Float64Array(n), orL = new Float64Array(n), orDone = new Uint8Array(n),
      pc = new Float64Array(n), ph = new Float64Array(n), pl = new Float64Array(n), hi = new Float64Array(n), lo = new Float64Array(n), di = new Int32Array(n), prev = null;
    B.days.forEach(function (d, k) {
      var s = 0, cnt = 0, H = -Infinity, L = Infinity, oh = -Infinity, ol = Infinity;
      for (var i = d.a; i < d.b; i++) {
        s += (B.h[i] + B.l[i] + B.c[i]) / 3; cnt++; vw[i] = s / cnt; dOpen[i] = B.o[d.a]; di[i] = k;
        if (B.h[i] > H) H = B.h[i]; if (B.l[i] < L) L = B.l[i]; hi[i] = H; lo[i] = L;
        if (B.m[i] < OPEN + orMin) { if (B.h[i] > oh) oh = B.h[i]; if (B.l[i] < ol) ol = B.l[i]; }
        orH[i] = oh; orL[i] = ol; orDone[i] = B.m[i] + B.tf >= OPEN + orMin ? 1 : 0;
        pc[i] = prev ? prev.c : NaN; ph[i] = prev ? prev.h : NaN; pl[i] = prev ? prev.l : NaN;
      }
      prev = { c: B.c[d.b - 1], h: H, l: L };
    });
    return { vwap: vw, dOpen: dOpen, orH: orH, orL: orL, orDone: orDone, pc: pc, ph: ph, pl: pl, hi: hi, lo: lo, di: di };
  }

  /* ---------- the five strategies: plain words, parameters, entry rule (side, target, stop) and optional early-exit rule ---------- */
  var COMMON = [
    { k: 'from', label: 'First entry', v: '09:45', type: 'time' }, { k: 'to', label: 'Last entry', v: '14:30', type: 'time' },
    { k: 'exit', label: 'Exit by', v: '15:15', type: 'time' }, { k: 'maxTrades', label: 'Trades a day (max)', v: 2, min: 1, max: 10, step: 1 }];
  var STRATS = [
    { id: 'trend_pullback', grid: ['tgt', [0.3, 0.5, 0.75, 1, 1.5, 2, 3], 'stp', [0.5, 1, 1.5, 2, 3, 4]], name: 'Trend pullback', tf: 5,
      about: 'Buy dips in an up-trend, sell rallies in a down-trend. Trend: EMA 20 above EMA 50 and price above VWAP (or both below). Entry: RSI(14) pulls back under the dip line within the last few candles, then crosses back above 50 (mirror for shorts). Target and stop are set in ATRs, the market\'s typical bar size.',
      params: [{ k: 'fast', label: 'EMA fast', v: 20, min: 3, max: 100, step: 1 }, { k: 'slow', label: 'EMA slow', v: 50, min: 5, max: 200, step: 1 },
        { k: 'rsiLow', label: 'RSI dip below', v: 45, min: 10, max: 50, step: 1 }, { k: 'tgt', label: 'Target (ATR)', v: 1.0, min: 0.2, max: 6, step: 0.1 }, { k: 'stp', label: 'Stop (ATR)', v: 1.5, min: 0.2, max: 6, step: 0.1 }],
      prep: function (B, P, X) { X.ef = ema(B.c, P.fast); X.es = ema(B.c, P.slow); X.r = rsi(B.c, 14); },
      entry: function (B, X, i, P) {
        var up = X.ef[i] > X.es[i] && B.c[i] > X.S.vwap[i], dn = X.ef[i] < X.es[i] && B.c[i] < X.S.vwap[i], a = X.A[i];
        var lo = Math.min(X.r[i - 1], X.r[i - 2], X.r[i - 3], X.r[i - 4]), hi = Math.max(X.r[i - 1], X.r[i - 2], X.r[i - 3], X.r[i - 4]);
        if (up && lo < P.rsiLow && X.r[i - 1] < 50 && X.r[i] >= 50) return { side: 1, tgt: P.tgt * a, stp: P.stp * a };
        if (dn && hi > 100 - P.rsiLow && X.r[i - 1] > 50 && X.r[i] <= 50) return { side: -1, tgt: P.tgt * a, stp: P.stp * a };
        return null;
      } },
    { id: 'orb_trend', grid: ['tgt', [0.25, 0.5, 0.75, 1, 1.5, 2], 'stpFrac', [0.25, 0.5, 0.75, 1, 1.5]], name: 'Opening-range breakout', tf: 5,
      about: 'The first 15 minutes set a range. Buy the first candle that closes above its high when EMA 9 is above EMA 21 and ADX(14) shows a trend (or sell the first close below its low, mirror). Stop at the middle of the range, target a multiple of the range.',
      params: [{ k: 'orMin', label: 'Opening range (min)', v: 15, min: 5, max: 60, step: 5 }, { k: 'adxMin', label: 'ADX at least', v: 20, min: 0, max: 50, step: 1 },
        { k: 'tgt', label: 'Target (x range)', v: 1.0, min: 0.2, max: 4, step: 0.1 }, { k: 'stpFrac', label: 'Stop (fraction of range from the edge)', v: 0.5, min: 0.1, max: 1.5, step: 0.05 }],
      fixed: { from: '09:30', to: '13:00', maxTrades: 1 },
      prep: function (B, P, X) { X.e9 = ema(B.c, 9); X.e21 = ema(B.c, 21); X.ad = adx(B, 14); X.S = session(B, P.orMin); },
      entry: function (B, X, i, P) {
        var S = X.S; if (!S.orDone[i - 1]) return null; var r = S.orH[i] - S.orL[i]; if (!(r > 0)) return null;
        if (B.c[i] > S.orH[i] && B.c[i - 1] <= S.orH[i] && X.e9[i] > X.e21[i] && X.ad[i] >= P.adxMin) return { side: 1, tgt: P.tgt * r, stp: (B.c[i] - S.orH[i]) + P.stpFrac * r };
        if (B.c[i] < S.orL[i] && B.c[i - 1] >= S.orL[i] && X.e9[i] < X.e21[i] && X.ad[i] >= P.adxMin) return { side: -1, tgt: P.tgt * r, stp: (S.orL[i] - B.c[i]) + P.stpFrac * r };
        return null;
      } },
    { id: 'vwap_snapback', grid: ['tgtFrac', [0.3, 0.5, 0.75, 1], 'stp', [0.5, 1, 1.5, 2, 3, 4]], name: 'VWAP snap-back', tf: 5,
      about: 'On a quiet, range-bound day (ADX low), a stretch outside the Bollinger band with RSI at an extreme tends to snap back towards VWAP. Buy below the lower band with RSI under the low line (sell above the upper band, mirror); target VWAP, stop in ATRs.',
      params: [{ k: 'bbN', label: 'Bollinger length', v: 20, min: 5, max: 60, step: 1 }, { k: 'bbK', label: 'Bollinger width (SD)', v: 2.0, min: 1, max: 4, step: 0.1 },
        { k: 'rsiLow', label: 'RSI below', v: 30, min: 5, max: 45, step: 1 }, { k: 'adxMax', label: 'ADX at most', v: 25, min: 5, max: 60, step: 1 },
        { k: 'tgtFrac', label: 'Target (share of the way to VWAP)', v: 1.0, min: 0.2, max: 1.5, step: 0.1 }, { k: 'stp', label: 'Stop (ATR)', v: 2.0, min: 0.2, max: 6, step: 0.1 }],
      prep: function (B, P, X) { X.mid = sma(B.c, P.bbN); X.sd = stdev(B.c, P.bbN, X.mid); X.r = rsi(B.c, 14); X.ad = adx(B, 14); },
      entry: function (B, X, i, P) {
        var lo = X.mid[i] - P.bbK * X.sd[i], hi = X.mid[i] + P.bbK * X.sd[i], v = X.S.vwap[i], c = B.c[i], a = X.A[i];
        if (X.ad[i] > P.adxMax) return null;
        if (c < lo && X.r[i] < P.rsiLow && v - c > 0.3 * a) return { side: 1, tgt: P.tgtFrac * (v - c), stp: P.stp * a };
        if (c > hi && X.r[i] > 100 - P.rsiLow && c - v > 0.3 * a) return { side: -1, tgt: P.tgtFrac * (c - v), stp: P.stp * a };
        return null;
      } },
    { id: 'gap_fill', grid: ['fill', [0.2, 0.35, 0.5, 0.75, 1], 'buf', [0, 0.25, 0.5, 1, 2]], name: 'Gap fill', tf: 5,
      about: 'When NIFTY opens with a gap and the first 15 minutes move against the gap, trade back towards yesterday\'s close. Gap up + red first 15 minutes + price below VWAP: sell (gap down: mirror). Target: part of the gap, stop above the day\'s high (below the low) plus a buffer.',
      params: [{ k: 'gapMin', label: 'Gap at least (%)', v: 0.3, min: 0.1, max: 2, step: 0.05 }, { k: 'fill', label: 'Target (share of the gap)', v: 0.5, min: 0.1, max: 1.2, step: 0.05 },
        { k: 'buf', label: 'Stop buffer (ATR)', v: 0.5, min: 0, max: 3, step: 0.1 }],
      fixed: { from: '09:30', to: '11:00', maxTrades: 1 },
      entry: function (B, X, i, P) {
        var S = X.S, pc = S.pc[i], op = S.dOpen[i]; if (!(pc > 0) || B.m[i] + B.tf < OPEN + 15) return null;
        var gap = (op / pc - 1) * 100, c = B.c[i], a = X.A[i], first = X.first[S.di[i]];
        if (gap >= P.gapMin && first < op && c < S.vwap[i] && c > pc) return { side: -1, tgt: P.fill * (op - pc) - (op - c), stp: S.hi[i] - c + P.buf * a };
        if (gap <= -P.gapMin && first > op && c > S.vwap[i] && c < pc) return { side: 1, tgt: P.fill * (pc - op) - (c - op), stp: c - S.lo[i] + P.buf * a };
        return null;
      } },
    { id: 'ema_st_adx', grid: ['tgt', [0.5, 1, 1.5, 2, 3, 4], 'stp', [0.5, 0.75, 1, 1.5, 2, 3]], name: 'EMA crossover + Supertrend', tf: 5,
      about: 'Trend following with three checks: EMA fast crosses EMA slow, Supertrend(10, 3) points the same way, ADX(14) confirms a trend, and price is on the right side of VWAP. Target and stop in ATRs; also out when price closes back across the slow EMA.',
      params: [{ k: 'fast', label: 'EMA fast', v: 9, min: 2, max: 50, step: 1 }, { k: 'slow', label: 'EMA slow', v: 21, min: 5, max: 100, step: 1 },
        { k: 'adxMin', label: 'ADX at least', v: 20, min: 0, max: 50, step: 1 }, { k: 'tgt', label: 'Target (ATR)', v: 2.0, min: 0.2, max: 8, step: 0.1 }, { k: 'stp', label: 'Stop (ATR)', v: 1.0, min: 0.2, max: 6, step: 0.1 }],
      prep: function (B, P, X) { X.ef = ema(B.c, P.fast); X.es = ema(B.c, P.slow); X.ad = adx(B, 14); X.st = supertrend(B, 10, 3, X.A); },
      entry: function (B, X, i, P) {
        var a = X.A[i], up = X.ef[i - 1] <= X.es[i - 1] && X.ef[i] > X.es[i], dn = X.ef[i - 1] >= X.es[i - 1] && X.ef[i] < X.es[i];
        if (X.ad[i] < P.adxMin) return null;
        if (up && X.st.dir[i] === 1 && B.c[i] > X.S.vwap[i]) return { side: 1, tgt: P.tgt * a, stp: P.stp * a };
        if (dn && X.st.dir[i] === -1 && B.c[i] < X.S.vwap[i]) return { side: -1, tgt: P.tgt * a, stp: P.stp * a };
        return null;
      },
      out: function (B, X, j, side) { return side === 1 ? B.c[j] < X.es[j] : B.c[j] > X.es[j]; } }];
  STRATS.forEach(function (s) { s.params = s.params.concat(COMMON.filter(function (c) { return !(s.fixed && c.k in s.fixed); })); });

  function defaults(s) { var P = {}; s.params.forEach(function (p) { P[p.k] = p.v; }); return Object.assign(P, s.fixed || {}); }

  /* ---------- money: index points, NIFTY futures, or an at-the-money option (estimate) ---------- */
  var MODES = {
    index: { label: 'Index points', unit: 'pts', defaults: { costPts: 1 } },
    futures: { label: 'NIFTY futures, 1 lot', unit: '₹', defaults: { lot: 65, slipPts: 1 } },
    option: { label: 'ATM option buy, 1 lot (estimate)', unit: '₹', defaults: { lot: 65, delta: 0.5, thetaPtsHr: 3, slipPts: 1, feesRs: 60 } } };
  /* NSE charges on one futures round trip: Rs 20 an order, STT 0.02% of the sell value, exchange 0.00173% and SEBI 0.0001% of turnover,
     stamp duty 0.002% of the buy value, GST 18% on brokerage + exchange + SEBI */
  function futFees(buy, sell) { var turn = buy + sell, brk = 40, ex = 0.0000173 * turn, sebi = 0.000001 * turn; return brk + 0.0002 * sell + ex + sebi + 0.00002 * buy + 0.18 * (brk + ex + sebi); }
  function money(tr, mode, M) {
    if (mode === 'futures') { var bv = (tr.side === 1 ? tr.entry : tr.exit) * M.lot, sv = (tr.side === 1 ? tr.exit : tr.entry) * M.lot; tr.fees = futFees(bv, sv); return (tr.pts - M.slipPts) * M.lot - tr.fees; }
    if (mode === 'option') { var side = tr.side === 1 ? 'call' : 'put'; tr.opt = side; return (M.delta * tr.pts - M.thetaPtsHr * tr.holdMin / 60 - M.slipPts) * M.lot - M.feesRs; }
    return tr.pts - M.costPts;
  }

  /* ---------- the engine ---------- */
  function prepare(D, strat, P, tf) {
    var C = D._bars || (D._bars = {}), B = C[tf] || (C[tf] = bars(D, tf));          // cached on this dataset only
    var X = { A: atr(B, 14), S: session(B, 15) };
    if (strat.prep) strat.prep(B, P, X);
    if (strat.id === 'gap_fill') { X.first = B.days.map(function (d) { var i = d.a; while (i < d.b - 1 && B.m[i] + B.tf < OPEN + 15) i++; return B.c[i]; }); }
    return { B: B, X: X };
  }
  function run(D, sid, opts) {
    opts = opts || {};
    var strat = STRATS.filter(function (s) { return s.id === sid; })[0]; if (!strat) throw new Error('unknown strategy ' + sid);
    var P = Object.assign(defaults(strat), opts.params || {}), tf = +(opts.tf || strat.tf), F = opts.filters || {}, mode = opts.mode || 'index';
    var M = Object.assign({}, MODES[mode].defaults, opts.money || {}), pr = opts.pre || prepare(D, strat, P, tf), B = pr.B, X = pr.X;
    var from = toMin(P.from), to = toMin(P.to), ex = toMin(P.exit), d0 = opts.start || '0000', d1 = opts.end || '9999', trades = [], sessions = 0;
    B.days.forEach(function (d) {
      if (d.day < d0 || d.day > d1) return;
      sessions++;
      if (F.days && F.days.indexOf(d.dow) < 0) return;
      var pos = null, n = 0;
      for (var i = Math.max(d.a, 4); i < d.b; i++) {
        if (pos) {
          var s = pos.side, o = B.o[i], hit = null, px;
          if (s * (o - pos.stop) <= 0) { hit = 'stop'; px = o; } else if (s * (o - pos.tgt) >= 0) { hit = 'target'; px = o; }
          else if (s === 1 ? B.l[i] <= pos.stop : B.h[i] >= pos.stop) { hit = 'stop'; px = pos.stop; }
          else if (s === 1 ? B.h[i] >= pos.tgt : B.l[i] <= pos.tgt) { hit = 'target'; px = pos.tgt; }
          else if (B.m[i] + B.tf >= ex) { hit = 'time'; px = B.c[i]; }
          else if (strat.out && strat.out(B, X, i, s)) { hit = 'trend broke'; px = B.c[i]; }
          else if (i === d.b - 1) { hit = 'close'; px = B.c[i]; }
          if (hit) {
            var tr = { day: d.day, dow: d.dow, side: s, inT: hhmm(pos.m), outT: hhmm(Math.min(B.m[i] + (hit === 'stop' || hit === 'target' ? 0 : B.tf), 930)), entry: pos.entry, exit: px,
              pts: s * (px - pos.entry), why: hit, holdMin: Math.max(1, B.m[i] + B.tf - pos.m) };
            tr.net = money(tr, mode, M); trades.push(tr); pos = null;
          }
          continue;
        }
        if (n >= P.maxTrades || i >= d.b - 1) continue;
        var end = B.m[i] + B.tf; if (end < from || end > to) continue;
        var sig = strat.entry(B, X, i, P); if (!sig || !(sig.tgt > 0) || !(sig.stp > 0)) continue;
        if (F.vwapSide && sig.side * (B.c[i] - X.S.vwap[i]) < 0) continue;
        if (F.adxMin && (X.adxF || (X.adxF = adx(B, 14)))[i] < F.adxMin) continue;
        if (F.skipExpiry && isExpiry(d.day, d.dow)) continue;
        if (F.onlyExpiry && !isExpiry(d.day, d.dow)) continue;
        var e = B.o[i + 1];
        pos = { side: sig.side, entry: e, m: B.m[i + 1], tgt: e + sig.side * sig.tgt, stop: e - sig.side * sig.stp }; n++;
      }
    });
    return { strategy: strat.id, name: strat.name, params: P, tf: tf, mode: mode, unit: MODES[mode].unit, money: M, filters: F, sessions: sessions, trades: trades, stats: stats(trades, sessions) };
  }
  /* NIFTY weekly expiry: Thursday until August 2025, Tuesday from September 2025 (holidays move it a day earlier; not modelled) */
  function isExpiry(day, dow) { return day < '2025-09-01' ? dow === 4 : dow === 2; }

  function stats(T, sessions) {
    var w = T.filter(function (t) { return t.net > 0; }), L = T.filter(function (t) { return t.net <= 0; }), gp = 0, gl = 0, eq = 0, pk = 0, dd = 0, days = {};
    w.forEach(function (t) { gp += t.net; }); L.forEach(function (t) { gl -= t.net; });
    T.forEach(function (t) { eq += t.net; if (eq > pk) pk = eq; if (pk - eq > dd) dd = pk - eq; days[t.day] = 1; });
    var n = T.length, mean = n ? (gp - gl) / n : 0, sd = 0; T.forEach(function (t) { sd += (t.net - mean) * (t.net - mean); }); sd = n > 1 ? Math.sqrt(sd / (n - 1)) : 0;
    return { trades: n, wins: w.length, winRate: n ? 100 * w.length / n : null, profitFactor: gl ? gp / gl : (gp ? Infinity : null), net: gp - gl, avgWin: w.length ? gp / w.length : null,
      avgLoss: L.length ? -gl / L.length : null, payoff: w.length && L.length ? (gp / w.length) / (gl / L.length) : null, expectancy: mean, maxDD: dd, tStat: sd ? mean / (sd / Math.sqrt(n)) : null,
      sessions: sessions, signalDays: Object.keys(days).length, signalDayPct: sessions ? 100 * Object.keys(days).length / sessions : null, perWeek: sessions ? n / (sessions / 5) : null,
      avgHold: n ? T.reduce(function (s, t) { return s + t.holdMin; }, 0) / n : null };
  }
  function group(T, key) { var g = {}; T.forEach(function (t) { var k = key(t); (g[k] = g[k] || []).push(t); }); var out = {}; Object.keys(g).sort().forEach(function (k) { out[k] = stats(g[k], 0); }); return out; }
  function breakdown(R) {
    var T = R.trades, DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return { byYear: group(T, function (t) { return t.day.slice(0, 4); }), byMonth: group(T, function (t) { return t.day.slice(0, 7); }), byDow: group(T, function (t) { return t.dow + ' ' + DOW[t.dow]; }),
      byHour: group(T, function (t) { return t.inT.slice(0, 2) + ':00'; }), byExit: group(T, function (t) { return t.why; }), bySide: group(T, function (t) { return t.side === 1 ? 'long / call' : 'short / put'; }),
      expiry: group(T, function (t) { return isExpiry(t.day, t.dow) ? 'expiry day' : 'other days'; }) };
  }
  /* grid over two parameters; picks are judged on the training years and shown on the later ones */
  function grid(D, sid, opts, kx, xs, ky, ys, split) {
    var strat = STRATS.filter(function (s) { return s.id === sid; })[0], P0 = Object.assign(defaults(strat), (opts && opts.params) || {}), rows = [], tf = +((opts && opts.tf) || strat.tf);
    var pre = null;
    xs.forEach(function (x) { ys.forEach(function (y) {
      var P = Object.assign({}, P0); P[kx] = x; P[ky] = y;
      if (!pre || strat.prep) pre = prepare(D, strat, P, tf);
      var R = run(D, sid, Object.assign({}, opts, { params: P, pre: pre }));
      var a = R.trades.filter(function (t) { return t.day < split; }), b = R.trades.filter(function (t) { return t.day >= split; });
      rows.push({ x: x, y: y, train: stats(a, 0), test: stats(b, 0), all: R.stats });
    }); });
    return rows;
  }

  /* ---------- patterns that repeat: day, week and month, straight from the 1-minute candles ---------- */
  function patterns(D) {
    var B = bars(D, 1, 300), out = [], prev = null, DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    B.days.forEach(function (d) {
      var o = B.o[d.a], c = B.c[d.b - 1], H = -Infinity, L = Infinity, tH = 0, tL = 0, c15 = null, c60 = null;
      for (var i = d.a; i < d.b; i++) { if (B.h[i] > H) { H = B.h[i]; tH = B.m[i]; } if (B.l[i] < L) { L = B.l[i]; tL = B.m[i]; } if (B.m[i] === OPEN + 14) c15 = B.c[i]; if (B.m[i] === OPEN + 59) c60 = B.c[i]; }
      var r = { day: d.day, dow: d.dow, o: o, c: c, H: H, L: L, tH: tH, tL: tL, c15: c15, c60: c60, pc: prev ? prev.c : null, dom: +d.day.slice(8) };
      out.push(r); prev = r;
    });
    var pct = function (a, b) { return b ? Math.round(1000 * a / b) / 10 : null; }, avg = function (a) { return a.length ? a.reduce(function (s, x) { return s + x; }, 0) / a.length : null; };
    var D2 = out.filter(function (r) { return r.pc; }), res = { sessions: D2.length, from: D2.length ? D2[0].day : null, to: D2.length ? D2[D2.length - 1].day : null };
    res.gaps = [[0.2, 0.5], [0.5, 1], [1, 99]].map(function (b) {
      var up = D2.filter(function (r) { var g = (r.o / r.pc - 1) * 100; return g >= b[0] && g < b[1]; }), dn = D2.filter(function (r) { var g = (1 - r.o / r.pc) * 100; return g >= b[0] && g < b[1]; });
      return { band: b[1] > 50 ? 'over ' + b[0] + '%' : b[0] + '–' + b[1] + '%', up: up.length, upFilled: pct(up.filter(function (r) { return r.L <= r.pc; }).length, up.length),
        down: dn.length, downFilled: pct(dn.filter(function (r) { return r.H >= r.pc; }).length, dn.length) };
    });
    var fh = D2.filter(function (r) { return r.c60 != null && Math.abs(r.c60 - r.o) / r.o >= 0.002; });
    res.firstHour = { days: fh.length, sameDirectionAtClose: pct(fh.filter(function (r) { return (r.c60 - r.o) * (r.c - r.o) > 0; }).length, fh.length),
      closesBeyondFirstHour: pct(fh.filter(function (r) { return (r.c60 - r.o) * (r.c - r.c60) > 0; }).length, fh.length) };
    res.extremes = { highOrLowInFirstHour: pct(D2.filter(function (r) { return r.tH < OPEN + 60 || r.tL < OPEN + 60; }).length, D2.length),
      highOrLowInLastHour: pct(D2.filter(function (r) { return r.tH >= LAST - 59 || r.tL >= LAST - 59; }).length, D2.length) };
    res.byDow = [1, 2, 3, 4, 5].map(function (k) {
      var a = D2.filter(function (r) { return r.dow === k; });
      return { day: DOW[k], sessions: a.length, upPct: pct(a.filter(function (r) { return r.c > r.pc; }).length, a.length), avgMovePct: a.length ? +avg(a.map(function (r) { return (r.c / r.pc - 1) * 100; })).toFixed(3) : null,
        avgRangePct: a.length ? +avg(a.map(function (r) { return (r.H - r.L) / r.o * 100; })).toFixed(2) : null };
    });
    var ex = D2.filter(function (r) { return isExpiry(r.day, r.dow); }), nx = D2.filter(function (r) { return !isExpiry(r.day, r.dow); }), rg = function (a) { return a.length ? +avg(a.map(function (r) { return (r.H - r.L) / r.o * 100; })).toFixed(2) : null; };
    res.expiry = { expiryDays: ex.length, expiryRangePct: rg(ex), otherRangePct: rg(nx), expiryBigMovePct: pct(ex.filter(function (r) { return (r.H - r.L) / r.o >= 0.01; }).length, ex.length),
      otherBigMovePct: pct(nx.filter(function (r) { return (r.H - r.L) / r.o >= 0.01; }).length, nx.length) };
    var tom = D2.filter(function (r) { return r.dom <= 5; }), mid = D2.filter(function (r) { return r.dom > 5 && r.dom <= 24; }), eom = D2.filter(function (r) { return r.dom > 24; }), mv = function (a) { return a.length ? { days: a.length, upPct: pct(a.filter(function (r) { return r.c > r.pc; }).length, a.length), avgMovePct: +avg(a.map(function (r) { return (r.c / r.pc - 1) * 100; })).toFixed(3) } : null; };
    res.month = { firstFiveDays: mv(tom), middle: mv(mid), lastDays: mv(eom) };
    return res;
  }

  return { decode: decode, concat: concat, bars: bars, ema: ema, rsi: rsi, atr: atr, adx: adx, supertrend: supertrend, session: session, STRATS: STRATS, MODES: MODES,
    defaults: defaults, futFees: futFees, run: run, stats: stats, breakdown: breakdown, grid: grid, patterns: patterns, isExpiry: isExpiry, hhmm: hhmm };
});
