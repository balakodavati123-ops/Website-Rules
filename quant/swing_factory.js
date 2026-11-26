// Multi-day (positional) NIFTY strategies: held across sessions until the opposite signal or a stop. One futures lot, NSE charges + slippage.
// Picked on 2022-23, must hold in 2024, shown once on 2025-26; random entries run through the same rules.  node quant/swing_factory.js DATA_DIR
const fs = require('fs'), path = require('path'), zlib = require('zlib'), BT = require('../docs/bt.js');
const dir = process.argv[2] || 'data', P = { train: ['2022-01-01', '2023-12-31'], valid: ['2024-01-01', '2024-12-31'], test: ['2025-01-01', '2099-12-31'] };
const D = BT.concat(fs.readdirSync(dir).filter((f) => /^nifty50_1m_\d{4}\.bin\.gz$/.test(f)).sort().map((f) => { const b = zlib.gunzipSync(fs.readFileSync(path.join(dir, f))); return BT.decode(b.buffer.slice(b.byteOffset, b.byteOffset + b.length)); }));
const EX = { 'until the opposite signal': {}, 'ATR stop 2 + opposite signal': { stopAtr: 2 }, 'trailing 3 ATR after +2 + opposite signal': { stopAtr: 3, trail: 3, trailAfter: 2 } };
const FL = { 'no filter': {}, 'ADX 20+': { adxMin: 20 } }, specs = [];
const E = [];
for (const [f, s] of [[5, 13], [9, 21], [9, 26], [13, 34], [20, 50], [21, 55]]) for (const tf of [30, 60, 125]) E.push({ family: 'ema_cross', tf, entry: { fast: f, slow: s }, label: `EMA ${f}/${s}, ${tf}-min` });
for (const [n, m] of [[7, 2], [10, 3]]) for (const tf of [30, 60, 125]) E.push({ family: 'st_flip', tf, entry: { n, m }, label: `Supertrend(${n},${m}), ${tf}-min` });
for (const tf of [30, 60, 125]) E.push({ family: 'macd_cross', tf, entry: {}, label: `MACD(12,26,9), ${tf}-min` });
for (const e of E) for (const [xk, x] of Object.entries(EX)) for (const [fk, fl] of Object.entries(FL)) specs.push({ ...e, id: `${e.label}|${xk}|${fk}`, label: `${e.label} · ${xk} · ${fk}`, exits: x, filters: fl });
for (let r = 0; r < 100; r++) specs.push({ id: `random|${r}`, label: `Random #${r + 1}`, family: 'random', tf: [30, 60, 125][r % 3], entry: { seed: 1000 + r, p: [0.02, 0.05, 0.1][r % 3] }, exits: Object.values(EX)[r % 3], filters: {} });
const out = [];
for (const s of specs) {
  const R = BT.runSwing(D, s), m = {};
  for (const [k, [a, b]] of Object.entries(P)) {
    const T = R.trades.filter((t) => t.day >= a && t.day <= b), S = BT.stats(T, 0), itm = T.map((t) => (0.8 * t.pts - 4 * t.bars * s.tf / 375 - 2) * 65 - 60), iw = itm.filter((v) => v > 0), igp = iw.reduce((x, v) => x + v, 0), igl = -itm.filter((v) => v <= 0).reduce((x, v) => x + v, 0);
    m[k] = { n: S.trades, win: S.winRate == null ? null : +S.winRate.toFixed(1), pf: S.profitFactor == null ? null : +Math.min(S.profitFactor, 99).toFixed(3), net: Math.round(S.net), avgPts: T.length ? +(T.reduce((x, t) => x + t.pts, 0) / T.length).toFixed(1) : null, dd: Math.round(S.maxDD), holdDays: T.length ? +(T.reduce((x, t) => x + t.bars * s.tf / 375, 0) / T.length).toFixed(1) : null,
      itm: { win: T.length ? +(100 * iw.length / T.length).toFixed(1) : null, pf: igl ? +(igp / igl).toFixed(3) : null, net: Math.round(igp - igl) } };
  }
  out.push({ id: s.id, label: s.label, family: s.family, spec: s, m });
}
const pass = (rows) => { const a = rows.filter((r) => r.m.train.n >= 30 && r.m.train.pf >= 1.15), b = a.filter((r) => r.m.valid.n >= 12 && r.m.valid.pf >= 1.05), c = b.filter((r) => r.m.test.pf > 1 && r.m.test.net > 0); return [rows.length, a.length, b.length, c.length, b, c]; };
const real = out.filter((r) => r.family !== 'random'), rnd = out.filter((r) => r.family === 'random'), [n, a, b, c, fin, conf] = pass(real), [rn, ra, rb, rc] = pass(rnd);
console.log(`real: ${n} tried -> ${a} pass 2022-23 -> ${b} also 2024 -> ${c} also 2025-26 | random: ${rn} -> ${ra} -> ${rb} -> ${rc}`);
const allPos = real.filter((r) => ['train', 'valid', 'test'].every((k) => r.m[k].net > 0));
console.log(`profitable in all three periods: ${allPos.length} of ${real.length} (random: ${rnd.filter((r) => ['train', 'valid', 'test'].every((k) => r.m[k].net > 0)).length} of ${rnd.length})`);
fin.sort((x, y) => y.m.valid.pf - x.m.valid.pf).slice(0, 15).forEach((r) => console.log(`  ${r.label.padEnd(70)} 22-23 PF ${r.m.train.pf} (${r.m.train.n} tr, ${r.m.train.win}%) | 2024 PF ${r.m.valid.pf} (${r.m.valid.n}) | 25-26 PF ${r.m.test.pf} (${r.m.test.n} tr, ${r.m.test.win}%, net Rs ${r.m.test.net}, avg ${r.m.test.avgPts} pts, worst DD Rs ${r.m.test.dd}, hold ${r.m.test.holdDays} d)`));
function compound(spec) {
  /* the in-the-money option P&L per lot, trade by trade */
  const R = BT.runSwing(D, spec), pl = (t) => (0.8 * t.pts - 4 * t.bars * spec.tf / 375 - 2) * 65 - 60;
  const walk = (T, start, perLot) => { let eq = start, pk = eq, dd = 0, ddPct = 0, low = eq; const path = [], yr = {};
    for (const t of T) { const lots = eq < 40000 ? 0 : perLot ? Math.max(1, Math.floor(eq / perLot)) : 1; if (lots < 1) { path.push([t.exitDay, Math.round(eq), 0]); continue; }      // keep one lot while the account can buy it
      eq += pl(t) * lots; pk = Math.max(pk, eq); dd = Math.max(dd, pk - eq); ddPct = Math.max(ddPct, (pk - eq) / pk * 100); low = Math.min(low, eq); path.push([t.exitDay, Math.round(eq), lots]); yr[t.exitDay.slice(0, 4)] = Math.round(eq); }
    return { start, end: Math.round(eq), lowest: Math.round(low), worstDrawdownRs: Math.round(dd), worstDrawdownPct: +ddPct.toFixed(1), yearEnd: yr, path }; };
  const train = R.trades.filter((t) => t.day < '2024-01-01'), later = R.trades.filter((t) => t.day >= '2024-01-01');
  /* the plain one-lot drawdown of 2022-23, measured on unlimited capital */ const ddTrain = walk(train, 1e9, 0).worstDrawdownRs, perLot = Math.max(100000, Math.ceil(ddTrain / 0.3 / 50000) * 50000);
  const oneLot = walk(R.trades, 100000, 0);
  return { capitalPerLot: perLot, sizingRule: `one lot for each Rs ${perLot.toLocaleString('en-IN')} of equity (3.3x the worst one-lot drawdown of 2022-23)`,
    oneLotFromOneLakh: { ...oneLot, ruined: oneLot.lowest < 40000, path: undefined },
    compounded2024on: walk(later, perLot, perLot) };
}
const top = fin.filter((r) => conf.includes(r)).sort((x, y) => (y.m.valid.pf + y.m.test.pf) - (x.m.valid.pf + x.m.test.pf)).slice(0, 8);
top.forEach((r) => { r.compound = compound(r.spec); const c = r.compound, o = c.oneLotFromOneLakh, k = c.compounded2024on;
  console.log(`  ${r.label}\n     ITM option PF 22-23 ${r.m.train.itm.pf} / 2024 ${r.m.valid.itm.pf} / 25-26 ${r.m.test.itm.pf} | one lot from Rs 1,00,000: lowest Rs ${o.lowest.toLocaleString('en-IN')}${o.ruined ? ' (account wiped)' : ''}, end Rs ${o.end.toLocaleString('en-IN')}, worst drawdown Rs ${o.worstDrawdownRs.toLocaleString('en-IN')}\n     needs Rs ${c.capitalPerLot.toLocaleString('en-IN')} a lot; compounded 2024-26 from that: Rs ${k.start.toLocaleString('en-IN')} -> Rs ${k.end.toLocaleString('en-IN')} (x${(k.end / k.start).toFixed(2)}), worst drawdown ${k.worstDrawdownPct}%, year ends ${JSON.stringify(k.yearEnd)}`); });
fs.writeFileSync('quant/results/swing_factory.json', JSON.stringify({ periods: P, tried: n, passTrain: a, passValid: b, passTest: c, random: { tried: rn, passTrain: ra, passValid: rb, passTest: rc }, profitableAllPeriods: allPos.length,
  finalists: fin.sort((x, y) => y.m.valid.pf - x.m.valid.pf).map((r) => ({ id: r.id, label: r.label, spec: r.spec, m: r.m })), top: top.map((r) => ({ id: r.id, label: r.label, spec: r.spec, m: r.m, compound: r.compound })), results: out.map((r) => ({ id: r.id, label: r.label, family: r.family, m: r.m })) }));
