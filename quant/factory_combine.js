// Combines the research agents' shards: picks strategies on 2022-23, keeps those that also held in 2024, then shows 2025-26 once.
// The same rules run on random-entry strategies, to show how many "winners" pure chance produces. Writes quant/results/factory.json
// and docs/data/research.json (for the dashboard).
const fs = require('fs'), path = require('path');
const dir = 'quant/results/factory', shards = fs.readdirSync(dir).filter((f) => /^shard_\d+\.json$/.test(f)).map((f) => JSON.parse(fs.readFileSync(path.join(dir, f))));
const all = shards.flatMap((s) => s.results), real = all.filter((r) => r.family !== 'random'), rnd = all.filter((r) => r.family === 'random');
const RULES = { train: { n: 60, pf: 1.15 }, valid: { n: 25, pf: 1.05 }, test: { pf: 1.0 } };
const pipe = (rows, mode) => {
  const s1 = rows.filter((r) => r.m.train[mode].n >= RULES.train.n && r.m.train[mode].pf >= RULES.train.pf);
  const s2 = s1.filter((r) => r.m.valid[mode].n >= RULES.valid.n && r.m.valid[mode].pf >= RULES.valid.pf);
  const s3 = s2.filter((r) => r.m.test[mode].pf > RULES.test.pf && r.m.test[mode].net > 0);
  return { tried: rows.length, passTrain: s1.length, passValid: s2.length, passTest: s3.length, finalists: s2, confirmed: s3 };
};
const out = { agents: shards.map((s) => ({ agent: s.shard + 1, strategies: s.ran, seconds: s.seconds })).sort((a, b) => a.agent - b.agent), data: shards[0].data, periods: shards[0].periods, rules: RULES, modes: {} };
for (const mode of ['option', 'futures', 'pts']) {
  const R = pipe(real, mode), Z = pipe(rnd, mode);
  out.modes[mode] = { real: { tried: R.tried, passTrain: R.passTrain, passValid: R.passValid, passTest: R.passTest }, random: { tried: Z.tried, passTrain: Z.passTrain, passValid: Z.passValid, passTest: Z.passTest },
    finalists: R.finalists.sort((a, b) => b.m.valid[mode].pf - a.m.valid[mode].pf).slice(0, 40).map((r) => ({ id: r.id, label: r.label, spec: r.spec, m: r.m })) };
}
// the user's targets: 80%+ wins with a profit factor of 2+, in any period, any mode
out.targets = {};
for (const mode of ['option', 'futures', 'pts']) for (const p of ['train', 'valid', 'test']) out.targets[`${mode}.${p}`] = real.filter((r) => r.m[p][mode].n >= 25 && r.m[p][mode].win >= 80 && r.m[p][mode].pf >= 2).length;
// best and worst families, by the share of strategies profitable after option costs in every period
const fam = {};
for (const r of real) { const k = r.family + (r.spec.fade ? ' (faded)' : ''); const f = fam[k] || (fam[k] = { family: k, n: 0, allPositive: 0, trainPos: 0, medianTestPF: [] }); f.n++;
  if (['train', 'valid', 'test'].every((p) => r.m[p].option.net > 0)) f.allPositive++; if (r.m.train.option.net > 0) f.trainPos++; f.medianTestPF.push(r.m.test.option.pf || 0); }
out.families = Object.values(fam).map((f) => { const a = f.medianTestPF.sort((x, y) => x - y); return { family: f.family, strategies: f.n, profitableEveryPeriod: f.allPositive, profitableIn2022_23: f.trainPos, medianPF2025_26: a[a.length >> 1] }; }).sort((a, b) => b.medianPF2025_26 - a.medianPF2025_26);
// the overall best by option P&L over all periods, for reference (picked with hindsight: not a selection)
out.hindsightTop = real.map((r) => ({ id: r.id, label: r.label, net: r.m.train.option.net + r.m.valid.option.net + r.m.test.option.net, m: r.m })).sort((a, b) => b.net - a.net).slice(0, 10);
out.generatedAt = new Date().toISOString();
// multi-day strategies (quant/swing_factory.js): the approval queue
try { const sw = JSON.parse(fs.readFileSync('quant/results/swing_factory.json'));
  out.swing = { periods: sw.periods, tried: sw.tried, passTrain: sw.passTrain, passValid: sw.passValid, passTest: sw.passTest, random: sw.random, profitableAllPeriods: sw.profitableAllPeriods,
    top: (sw.top || []).map((r) => ({ id: r.id, label: r.label, spec: r.spec, m: r.m, compound: r.compound && { capitalPerLot: r.compound.capitalPerLot, sizingRule: r.compound.sizingRule,
      oneLotFromOneLakh: r.compound.oneLotFromOneLakh, compounded2024on: { ...r.compound.compounded2024on, path: (r.compound.compounded2024on.path || []).filter((x, i, a) => i % 2 === 0 || i === a.length - 1) } } })) };
} catch (e) { out.swing = null; }
// the CEO's structures on real option prices (quant/run_option_structures.py): the approval queue
try { const os = JSON.parse(fs.readFileSync('quant/results/option_structures.json'));
  out.options = { period: os.period, status: os.status, fallbacks: os.exit_price_fallbacks,
    rows: os.directional.map((r) => ({ id: r.signal + ' · ' + r.structure + ' · ' + r.exits, signal: r.signal, kind: r.kind, structure: r.structure, exits: r.exits, stats: r.stats,
      byYear: Object.fromEntries(Object.entries(r.byYear || {}).map(([y, v]) => [y, { trades: v.trades, profitFactor: v.profitFactor, net: v.net }])) })),
    omni: os.omni };
} catch (e) { out.options = null; }
out.sources = { note: 'Open-source strategies reviewed (rules, failure modes, fixes): see README', base_rate: 'SEBI FY22-FY24 study: 91.1% of individual F&O traders lost money in FY24' };
fs.writeFileSync('quant/results/factory.json', JSON.stringify(out, null, 1));
fs.mkdirSync('docs/data', { recursive: true });
fs.writeFileSync('docs/data/research.json', JSON.stringify(out));
for (const mode of ['option', 'futures', 'pts']) { const M = out.modes[mode]; console.log(`${mode.padEnd(8)} real: ${M.real.tried} tried -> ${M.real.passTrain} pass 2022-23 -> ${M.real.passValid} also 2024 -> ${M.real.passTest} also 2025-26 | random: ${M.random.tried} -> ${M.random.passTrain} -> ${M.random.passValid} -> ${M.random.passTest}`); }
console.log('targets (80%+ wins and PF 2+, >=25 trades):', JSON.stringify(out.targets));
console.log('\nfamilies by median 2025-26 PF (option est.):'); out.families.forEach((f) => console.log(`  ${f.family.padEnd(26)} ${String(f.strategies).padStart(4)} strategies, profitable in every period: ${f.profitableEveryPeriod}, median PF 2025-26 ${f.medianPF2025_26}`));
for (const mode of ['option', 'futures']) { console.log(`\nfinalists (${mode}), best by 2024 PF:`); out.modes[mode].finalists.slice(0, 12).forEach((r) => { const m = r.m; console.log(`  ${r.label}\n     22-23: ${m.train[mode].n} tr ${m.train[mode].win}% PF ${m.train[mode].pf} net ${m.train[mode].net} | 2024: ${m.valid[mode].n} tr ${m.valid[mode].win}% PF ${m.valid[mode].pf} net ${m.valid[mode].net} | 25-26: ${m.test[mode].n} tr ${m.test[mode].win}% PF ${m.test[mode].pf} net ${m.test[mode].net}`); }); }
