// Exit research on the NIFTY 50 1-minute database with the dashboard's engine (docs/bt.js):
// 1) how NIFTY behaves into the close, 2) how much profit our trades see and give back, 3) exits that protect profit or leave earlier.
// node quant/bt_exits.js DIR  ->  quant/results/bt_exits.json
const fs = require('fs'), path = require('path'), zlib = require('zlib'), BT = require('../docs/bt.js');
const dir = process.argv[2] || 'data', SPLIT = '2025-01-01';
const D = BT.concat(fs.readdirSync(dir).filter((f) => /^nifty50_1m_\d{4}\.bin\.gz$/.test(f)).sort().map((f) => { const b = zlib.gunzipSync(fs.readFileSync(path.join(dir, f))); return BT.decode(b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); }));
const r2 = (x) => (x == null || !isFinite(x) ? x : Math.round(x * 100) / 100), out = { split: SPLIT };

// 1) into the close
const B1 = BT.bars(D, 1), at = (d, hm) => { for (let i = d.a; i < d.b; i++) if (B1.m[i] === hm) return i; return -1; }, last = { };
for (const [lab, hm] of [['from 14:30', 14 * 60 + 30], ['from 15:00', 15 * 60], ['from 15:15', 15 * 60 + 15]]) {
  const mv = [], up = [], dn = [];
  for (const d of B1.days) { const i = at(d, hm), j = d.b - 1; if (i < 0) continue; const m = (B1.c[j] / B1.o[i] - 1) * 100, dayDir = B1.o[i] - B1.o[d.a]; mv.push(m); (dayDir >= 0 ? up : dn).push(m); }
  const avg = (a) => a.reduce((s, x) => s + x, 0) / a.length, downPct = (a) => 100 * a.filter((x) => x < 0).length / a.length;
  last[lab] = { days: mv.length, avgMovePct: r2(avg(mv) * 100) / 100, downDaysPct: r2(downPct(mv)), avgAbsMovePct: r2(avg(mv.map(Math.abs)) * 100) / 100,
    upDays: { days: up.length, avgMovePct: r2(avg(up) * 100) / 100, downPct: r2(downPct(up)) }, downDays: { days: dn.length, avgMovePct: r2(avg(dn) * 100) / 100, upPct: r2(100 - downPct(dn)) } };
}
out.intoTheClose = last;
console.log('INTO THE CLOSE', JSON.stringify(last));

// 2) and 3) exits
const VARIANTS = {
  'as designed (target, stop, out 15:15)': {},
  'same, but out by 14:30': { params: { exit: '14:30' } },
  'breakeven after +1 ATR': { exits: { be: 1 } },
  'target + trailing stop 1 ATR after +1 ATR': { exits: { trail: 1, trailAfter: 1 } },
  'no target, trailing stop 1.5 ATR after +1 ATR': { exits: { noTarget: 1, trail: 1.5, trailAfter: 1 } },
  'no target, out when momentum fades (EMA 9)': { exits: { noTarget: 1, flip: 1 } },
  'no target, trail 1 ATR after +0.5 + momentum exit': { exits: { noTarget: 1, trail: 1, trailAfter: 0.5, flip: 1 } } };
const slim = (s) => ({ trades: s.trades, winRate: r2(s.winRate), profitFactor: r2(s.profitFactor), avg: r2(s.expectancy) });
out.strategies = {};
for (const s of BT.STRATS) {
  const res = {};
  for (const [name, v] of Object.entries(VARIANTS)) {
    const row = {};
    for (const mode of ['futures', 'option', 'index']) {
      const R = BT.run(D, s.id, { mode, params: v.params || {}, exits: v.exits || {} });
      const a = R.trades.filter((t) => t.day < SPLIT), b = R.trades.filter((t) => t.day >= SPLIT);
      row[mode] = { train: slim(BT.stats(a, 0)), test: slim(BT.stats(b, 0)) };
      if (mode === 'index') {
        const S = R.stats, ex = BT.breakdown(R).byExit;
        row.profit = { avgBestPts: r2(S.avgBestPts), avgKeptPts: r2(S.avgPts), avgGaveBackPts: r2(S.avgGaveBack), wentGreenPct: r2(S.wentGreen), greenThenLostPct: r2(S.greenThenLost) };
        row.exits = Object.fromEntries(Object.entries(ex).map(([k, x]) => [k, { share: r2(100 * x.trades / S.trades), avgPts: r2(x.expectancy) }]));
      }
    }
    res[name] = row;
  }
  out.strategies[s.id] = { name: s.name, variants: res };
  console.log('\n' + s.name);
  for (const [name, r] of Object.entries(res)) console.log(`  ${name.padEnd(52)} futures PF ${r.futures.train.profitFactor} -> ${r.futures.test.profitFactor} (${r.futures.train.winRate}% / ${r.futures.test.winRate}% won) | option est PF ${r.option.train.profitFactor} -> ${r.option.test.profitFactor} | index PF ${r.index.train.profitFactor} -> ${r.index.test.profitFactor} | best ${r.profit.avgBestPts} kept ${r.profit.avgKeptPts} gave back ${r.profit.avgGaveBackPts} pts; green-then-lost ${r.profit.greenThenLostPct}% | exits ${Object.entries(r.exits).map(([k, x]) => k + ' ' + x.share + '% avg ' + x.avgPts).join(', ')}`);
}
fs.writeFileSync('quant/results/bt_exits.json', JSON.stringify(out, null, 1));
