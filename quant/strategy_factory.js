// The strategy factory: about 2,100 NIFTY strategies built from parts (entry family x settings x exits x filters x as-taught / faded),
// run on the NIFTY 50 1-minute database with the dashboard's engine (docs/bt.js). Work is split into equal shards, one per research agent.
//   node quant/strategy_factory.js DATA_DIR [--shard K --of N] [--random 200]   ->  quant/results/factory/shard_K.json
const fs = require('fs'), path = require('path'), zlib = require('zlib'), BT = require('../docs/bt.js');
const args = process.argv.slice(2), dir = args[0] || 'data', opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? +args[i + 1] : d; };
const SHARD = opt('shard', 0), OF = opt('of', 1), RANDOM = opt('random', 0);
const PERIODS = { train: ['2022-01-01', '2023-12-31'], valid: ['2024-01-01', '2024-12-31'], test: ['2025-01-01', '2099-12-31'] };

const EXITS = { 'stop 1 ATR, target 1R': { stopAtr: 1, targetR: 1 }, 'stop 1 ATR, target 2R': { stopAtr: 1, targetR: 2 }, 'stop 1 ATR, target 3R': { stopAtr: 1, targetR: 3 },
  'stop 1.5 ATR, target 1R': { stopAtr: 1.5, targetR: 1 }, 'stop 1 ATR, trail 1 ATR after +1, no target': { stopAtr: 1, trail: 1, trailAfter: 1 },
  'stop 1 ATR, target 2R, breakeven at +1 ATR': { stopAtr: 1, targetR: 2, be: 1 } };
const FILTERS = { 'no filter': {}, 'ADX 20+': { adxMin: 20 }, 'VWAP side': { vwapSide: 1 }, 'ADX 20+ and VWAP side': { adxMin: 20, vwapSide: 1 } };
const ENTRIES = [];
for (const [f, s] of [[5, 13], [9, 21], [9, 26], [13, 34], [20, 50], [5, 20]]) for (const tf of [3, 5, 15]) ENTRIES.push({ family: 'ema_cross', tf, entry: { fast: f, slow: s }, label: `EMA ${f}/${s} crossover, ${tf}-min` });
for (const n of [2, 7, 14]) for (const lo of [20, 30]) ENTRIES.push({ family: 'rsi_revert', tf: 5, entry: { n, lo }, label: `RSI(${n}) back from ${lo}/${100 - lo}, 5-min` });
for (const n of [7, 14]) for (const t of [5, 10]) ENTRIES.push({ family: 'rsi_momo', tf: 5, entry: { n, t }, label: `RSI(${n}) through ${50 + t}/${50 - t}, 5-min` });
for (const confirm of [0, 1]) for (const tf of [3, 5]) ENTRIES.push({ family: 'vwap_cross', tf, entry: { confirm }, label: `VWAP cross${confirm ? ' + EMA 9/21' : ''}, ${tf}-min` });
for (const m of [15, 30]) ENTRIES.push({ family: 'orb', tf: 5, entry: { m }, label: `Opening range ${m} min breakout` });
for (const [n, m] of [[7, 2], [10, 3]]) for (const tf of [5, 15]) ENTRIES.push({ family: 'st_flip', tf, entry: { n, m }, label: `Supertrend(${n},${m}) flip, ${tf}-min` });
for (const k of [2, 2.5]) ENTRIES.push({ family: 'bb_break', tf: 5, entry: { k }, label: `Bollinger(20,${k}) breakout, 5-min` });
for (const tf of [5, 15]) ENTRIES.push({ family: 'macd_cross', tf, entry: {}, label: `MACD(12,26,9) crossover, ${tf}-min` });
ENTRIES.push({ family: 'pdhl', tf: 5, entry: {}, label: 'Previous day high/low break, 5-min' });
ENTRIES.push({ family: 'first5', tf: 5, entry: {}, label: 'First 5-minute candle break' });

function specs() {
  const out = [];
  for (const e of ENTRIES) for (const [xk, x] of Object.entries(EXITS)) for (const [fk, fl] of Object.entries(FILTERS)) for (const fade of [false, true])
    out.push({ id: `${e.family}|${JSON.stringify(e.entry)}|${e.tf}|${xk}|${fk}|${fade ? 'fade' : 'taught'}`, family: e.family, tf: e.tf, entry: e.entry, exits: x, filters: fl, fade,
      label: `${fade ? 'FADE ' : ''}${e.label} · ${xk} · ${fk}` });
  for (let r = 0; r < RANDOM; r++) { const x = Object.values(EXITS)[r % 6]; out.push({ id: `random|${r}`, family: 'random', tf: 5, entry: { seed: r + 1, p: [0.01, 0.02, 0.04][r % 3] }, exits: x, filters: {}, fade: false, label: `Random entries #${r + 1} · ${Object.keys(EXITS)[r % 6]}` }); }
  return out;
}
const MO = { option: BT.MODES.option.defaults, futures: BT.MODES.futures.defaults };
function measure(T) {
  const out = {};
  for (const [p, [a, b]] of Object.entries(PERIODS)) {
    const tt = T.filter((t) => t.day >= a && t.day <= b), m = {};
    for (const mode of ['option', 'futures', 'pts']) {
      const xs = tt.map((t) => mode === 'pts' ? t.pts : BT.money(Object.assign({}, t), mode, MO[mode])), w = xs.filter((x) => x > 0), gp = w.reduce((s, x) => s + x, 0), gl = -xs.filter((x) => x <= 0).reduce((s, x) => s + x, 0);
      let eq = 0, pk = 0, dd = 0; xs.forEach((x) => { eq += x; pk = Math.max(pk, eq); dd = Math.max(dd, pk - eq); });
      m[mode] = { n: xs.length, win: xs.length ? +(100 * w.length / xs.length).toFixed(1) : null, pf: gl ? +(gp / gl).toFixed(3) : (gp ? 99 : null), net: Math.round(gp - gl), avg: xs.length ? +((gp - gl) / xs.length).toFixed(1) : null, dd: Math.round(dd) };
    }
    out[p] = m;
  }
  return out;
}
if (require.main === module) {
  const files = fs.readdirSync(dir).filter((f) => /^nifty50_1m_\d{4}\.bin\.gz$/.test(f)).sort();
  const D = BT.concat(files.map((f) => { const b = zlib.gunzipSync(fs.readFileSync(path.join(dir, f))); return BT.decode(b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); }));
  const all = specs(), mine = all.filter((s, i) => i % OF === SHARD), t0 = Date.now(), res = [];
  for (const s of mine) {
    const R = BT.run(D, BT.compose(s), { mode: 'index', money: { costPts: 0 } });
    res.push({ id: s.id, label: s.label, family: s.family, spec: s, m: measure(R.trades) });
  }
  fs.mkdirSync('quant/results/factory', { recursive: true });
  fs.writeFileSync(`quant/results/factory/shard_${SHARD}.json`, JSON.stringify({ shard: SHARD, of: OF, total: all.length, ran: res.length, seconds: Math.round((Date.now() - t0) / 1000),
    data: { from: new Date((D.ts[0] + 19800) * 1000).toISOString().slice(0, 10), to: new Date((D.ts[D.n - 1] + 19800) * 1000).toISOString().slice(0, 10) }, periods: PERIODS, results: res }));
  console.log(`agent ${SHARD + 1} of ${OF}: ${res.length} of ${all.length} strategies in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
}
module.exports = { specs, measure, PERIODS, EXITS, FILTERS, ENTRIES };
