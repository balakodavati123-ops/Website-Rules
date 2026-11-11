/* Checks the floor's rules on answers shaped like INDmoney's. Usage: node dashboard/test/floor_calc_test.js */
const fs = require('fs'); const path = require('path'); const assert = require('assert');
const C = {}; global.dash = { calc: (id, o) => { C[id] = o; } };
eval(fs.readFileSync(path.join(__dirname, '..', 'page', 'floor_data.js'), 'utf8'));
const mover = (symbol, name, price, chg, hi, vol, w52, circ, cap = 'Large Cap') => ({ symbol, name, price, chg_pct: chg, day_high: hi, volume: vol, w52_high: w52, circ_up: circ, sector: 'Financial Services', cap });
const deskRules = [['paper_start', 32000], ['risk_normal', 1], ['risk_caution', 0.5], ['stop_pct', 5], ['target_pct', 20]].map(([key, value]) => ({ key, value }));
const limits = C.floor_rules.fn(deskRules);
const highs = [mover('ICICIBANK', 'ICICI Bank Ltd', 1571.6, -1.1, 1616, 29190011, 1616, 1612.7), mover('544937', 'National Stock Exchange Of India Ltd', 1945.9, 0.92, 1965, 3737636, 1965, 2313.75),
  mover('KOTAKBANK', 'Kotak Mahindra Bank Ltd', 487.7, 1.71, 491.05, 23453403, 491.05, 497.7)];
const gainers = [mover('LOCKED', 'Locked Ltd', 150, 4.9, 150, 5000000, 150, 150, 'Small Cap'), mover('RUNNER', 'Runner Ltd', 220, 12.4, 221, 9000000, 221, 264, 'Small Cap'), mover('THIN', 'Thin Ltd', 60, 3, 60.5, 100000, 61, 72, 'Small Cap')];
const watch = [{ symbol: 'KOTAKBANK', name: 'Kotak Mahindra Bank', live: 487.7, chg_pct: 1.71, high: 491.05, volume: 23453403, w52_high: 491.05, upper: 497.7, cap: 'LARGE CAP', target: 471.2, upside: -1.73, buy_pct: 83.8, analysts: 37 }];
const idx = (vix) => [{ name: 'India VIX', live: vix, chg_pct: 0.6, time: '2026-11-11T15:14:59+05:30' }, { name: 'NIFTY 50', live: 25255, chg_pct: 0.84, time: '2026-11-11T15:59:44+05:30' }];
const paper = [{ equity: 32000 }]; const ledger = [{ status: 'PENDING', symbol: 'PNB', risk_rs: 159 }]; const strategies = [{ strategy: 'breakout_52w', win_rate: 0.29 }];
const run = (vix) => C.floor_rows.fn(gainers, highs, [], watch, idx(vix), limits, paper, ledger, [], strategies);
const rows = run(17.53); const by = Object.fromEntries(rows.map((r) => [r.symbol, r]));
assert.equal(by.ICICIBANK.failed, 5); assert.match(by.ICICIBANK.fail_reason, /down 1\.1% today/);
assert.equal(by.LOCKED.failed, 3); assert.equal(by.RUNNER.failed, 4); assert.equal(by.THIN.failed, 1);
assert.equal(by['544937'].label, 'National Stock Exchange Of India'); assert.ok(!by['544937'].bull.includes('544937'));
const k = by.KOTAKBANK; assert.equal(k.failed, 0); assert.deepEqual([k.f1, k.f2, k.f3, k.f4, k.f5, k.f6], [19, 15, 15, 15, 10, 8]); assert.equal(k.score, 82); assert.equal(k.verdict, 'SETUP');
assert.equal(k.qty, 6); assert.equal(k.risk_rs, 146); assert.equal(k.stop, 463.31); assert.match(k.size_note, /Half size because India VIX is 17\.5/); assert.match(k.bear, /below the price/);
assert.ok(run(21).every((r) => r.failed), 'a VIX above 20 leaves no survivors'); assert.equal(run(21).find((r) => r.symbol === 'KOTAKBANK').failed, 8);
assert.equal(run(14).find((r) => r.symbol === 'KOTAKBANK').qty, 13, 'full size in a normal market');
const st = C.floor_stats.fn(rows, limits, gainers, [], [], idx(17.53))[0];
assert.equal(st.seen, 6); assert.equal(st.killed, 4); assert.equal(st.setups, 2); assert.equal(st.regime, 'CAUTION'); assert.match(st.scout_txt, /Prices as of 15:59 on 11 Nov/);
const side = C.floor_side.fn([{ symbol: 'BTC', price_inr: 7418058.6, chg_24h_pct: -0.08, premium_pct: 7.8, verified: 'yes', as_of_hm: '11 Nov 19:59' }], [], [], ledger, [{ pending: 1, open_positions: 0, trades: 0, need_trades: 100, equity: 32000, confidence: 0, need_conf: 98, ready: false }], []);
assert.match(side.find((r) => r.key === 'crypto').text, /BTC ₹74,18,059 \(-0\.1% in 24 hours\)/); assert.ok(side.find((r) => r.key === 'gate').text.includes('0 of 100'));
console.log('floor rules ok:', rows.length, 'names,', st.setups, 'setups');
