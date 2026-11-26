// Searches the five dashboard strategies (docs/bt.js) on the NIFTY 50 1-minute database: settings picked on 2022-2024, checked on 2025-2026.
// node quant/bt_research.js DIR_WITH_nifty50_1m_YYYY.bin.gz  ->  quant/results/bt_strategies.json
const fs = require('fs'), path = require('path'), zlib = require('zlib'), BT = require('../docs/bt.js');
const dir = process.argv[2] || 'data', SPLIT = '2025-01-01', MODE = 'futures';
const files = fs.readdirSync(dir).filter((f) => /^nifty50_1m_\d{4}\.bin\.gz$/.test(f)).sort();
const D = BT.concat(files.map((f) => { const b = zlib.gunzipSync(fs.readFileSync(path.join(dir, f))); return BT.decode(b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); }));
const r1 = (x) => (x == null || !isFinite(x) ? x : Math.round(x * 100) / 100), slim = (s) => ({ trades: s.trades, winRate: r1(s.winRate), profitFactor: r1(s.profitFactor), net: Math.round(s.net), expectancy: r1(s.expectancy), avgWin: r1(s.avgWin), avgLoss: r1(s.avgLoss), maxDD: Math.round(s.maxDD) });
const out = { data: { from: BT.hhmm && D.n ? new Date((D.ts[0] + 19800) * 1000).toISOString().slice(0, 10) : null, to: new Date((D.ts[D.n - 1] + 19800) * 1000).toISOString().slice(0, 10), candles: D.n },
  mode: MODE, money: BT.MODES[MODE].defaults, split: SPLIT, strategies: {} };
for (const s of BT.STRATS) {
  const [kx, xs, ky, ys] = s.grid, t0 = Date.now();
  const rows = BT.grid(D, s.id, { mode: MODE }, kx, xs, ky, ys, SPLIT).map((r) => ({ [kx]: r.x, [ky]: r.y, train: slim(r.train), test: slim(r.test) }));
  const ok = rows.filter((r) => r.train.trades >= 100);
  const byPF = ok.slice().sort((a, b) => (b.train.profitFactor || 0) - (a.train.profitFactor || 0))[0];
  const byWin = ok.filter((r) => (r.train.profitFactor || 0) >= 1).sort((a, b) => b.train.winRate - a.train.winRate)[0] || null;
  const hi80 = ok.filter((r) => r.train.winRate >= 80).sort((a, b) => (b.train.profitFactor || 0) - (a.train.profitFactor || 0));
  const both = ok.filter((r) => r.train.winRate >= 80 && r.train.profitFactor >= 2), bothTest = rows.filter((r) => r.test.trades >= 30 && r.test.winRate >= 80 && r.test.profitFactor >= 2);
  const maxWin = ok.slice().sort((a, b) => b.train.winRate - a.train.winRate)[0];
  out.strategies[s.id] = { name: s.name, about: s.about, axes: [kx, ky], combos: rows.length, bestProfitFactor: byPF, bestWinRateStillProfitable: byWin, highestWinRate: maxWin,
    over80pctWins: { count: hi80.length, best: hi80[0] || null }, meetsBothTargetsInTraining: both.length, meetsBothTargetsInTesting: bothTest.length, rows };
  const also = (r) => { if (!r) return; for (const m of ['index', 'option']) { const R = BT.run(D, s.id, { mode: m, params: { [kx]: r[kx], [ky]: r[ky] } }); r[m] = { train: slim(BT.stats(R.trades.filter((t) => t.day < SPLIT), 0)), test: slim(BT.stats(R.trades.filter((t) => t.day >= SPLIT), 0)) }; } };
  [byPF, byWin, maxWin, hi80[0]].forEach(also);
  const f = (r) => r ? `${kx} ${r[kx]} / ${ky} ${r[ky]}: train ${r.train.trades} tr ${r.train.winRate}% won PF ${r.train.profitFactor} avg Rs ${r.train.expectancy} | test ${r.test.trades} tr ${r.test.winRate}% won PF ${r.test.profitFactor} avg Rs ${r.test.expectancy}` : 'none';
  const g = (r) => r && r.option ? `   option est.: train PF ${r.option.train.profitFactor} ${r.option.train.winRate}% won avg Rs ${r.option.train.expectancy} | test PF ${r.option.test.profitFactor} ${r.option.test.winRate}% won avg Rs ${r.option.test.expectancy}; index pts: train PF ${r.index.train.profitFactor}, test PF ${r.index.test.profitFactor}` : '';
  console.log(`\n${s.name} (${rows.length} settings, ${((Date.now() - t0) / 1000).toFixed(1)}s)\n  best profit factor  ${f(byPF)}\n${g(byPF)}\n  best win rate, PF>=1 ${f(byWin)}\n  highest win rate    ${f(maxWin)}\n${g(maxWin)}\n  80%+ wins: ${hi80.length} settings; best ${f(hi80[0])}\n  80%+ wins AND PF>=2: training ${both.length}, testing ${bothTest.length}`);
}
out.patterns = BT.patterns(D);
fs.mkdirSync('quant/results', { recursive: true });
fs.writeFileSync('quant/results/bt_strategies.json', JSON.stringify(out, null, 1));
console.log('\npatterns', JSON.stringify(out.patterns));
