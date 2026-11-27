// Trade signals (entry and exit times, direction) for option pricing on real option data: the multi-day strategies that held up in
// every period, and the CEO's intraday EMA crossovers.  node quant/export_signals.js DATA_DIR  ->  quant/results/signals.json
const fs = require('fs'), path = require('path'), zlib = require('zlib'), BT = require('../docs/bt.js');
const dir = process.argv[2] || 'data', FROM = '2024-10-01';
const D = BT.concat(fs.readdirSync(dir).filter((f) => /^nifty50_1m_\d{4}\.bin\.gz$/.test(f)).sort().map((f) => { const b = zlib.gunzipSync(fs.readFileSync(path.join(dir, f))); return BT.decode(b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); }));
const sw = JSON.parse(fs.readFileSync('quant/results/swing_factory.json')), out = [];
for (const r of sw.top) {
  const R = BT.runSwing(D, r.spec);
  out.push({ id: r.id, label: r.label, kind: 'multi-day', trades: R.trades.filter((t) => t.day >= FROM && t.why !== 'still open').map((t) => ({ day: t.day, inT: t.inT, exitDay: t.exitDay, outT: t.outT, side: t.side, pts: +t.pts.toFixed(2), why: t.why })) });
}
for (const [label, tf, f, s, ex] of [['EMA 9/21 crossover, 5-min, intraday (stop 1 ATR, target 2R)', 5, 9, 21, { stopAtr: 1, targetR: 2 }],
  ['EMA 9/21 crossover, 15-min, intraday (trail 1 ATR)', 15, 9, 21, { stopAtr: 1, trail: 1, trailAfter: 1 }], ['EMA 20/50 crossover, 15-min, intraday (trail 1 ATR)', 15, 20, 50, { stopAtr: 1, trail: 1, trailAfter: 1 }]]) {
  const R = BT.run(D, BT.compose({ id: label, family: 'ema_cross', tf, entry: { fast: f, slow: s }, exits: ex }), { mode: 'index', money: { costPts: 0 } });
  out.push({ id: label, label, kind: 'intraday', trades: R.trades.filter((t) => t.day >= FROM).map((t) => ({ day: t.day, inT: t.inT, exitDay: t.day, outT: t.outT, side: t.side, pts: +t.pts.toFixed(2), why: t.why })) });
}
fs.writeFileSync('quant/results/signals.json', JSON.stringify(out));
out.forEach((x) => console.log(`${x.kind.padEnd(9)} ${String(x.trades.length).padStart(4)} trades  ${x.label}`));
