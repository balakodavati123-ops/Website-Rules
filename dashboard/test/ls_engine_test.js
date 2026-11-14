/* Node test for the live paper session rules. Usage: node dashboard/test/ls_engine_test.js */
const fs = require('fs'); const path = require('path'); const assert = require('assert');
global.window = {}; eval(fs.readFileSync(path.join(__dirname, '..', 'page', 'ls_engine.js'), 'utf8')); const E = global.LSE || window.LSE;
const row = (symbol, price, chg, hi, lo, vol = 3e6, extra = {}) => ({ symbol, price, chg_pct: chg, day_high: hi, day_low: lo, volume: vol, circ_up: 0, circ_lo: 0, ...extra });
const chain = [24950, 25100, 25250].flatMap((k) => ['CE', 'PE'].map((kind) => ({ strike: k, kind, bid: 150, ask: 151, lot: 65, expiry: '2026-11-17' })));
const base = (hhmm, rows, news = {}, nifty = null) => ({ day: '2026-11-16', hhmm, rows, news, nifty, chain });
const book = { day: '', trades: [], seen: {}, seq: 0 };

E.step(book, base('09:10', [row('AAA', 100, 3, 100, 98)]));                                   // before 09:20: nothing
assert.equal(book.trades.length, 0);
E.step(book, base('09:30', [row('AAA', 100, 3, 100.2, 98), row('BBB', 200, -3, 205, 199, 3e6, { circ_lo: 199.5 }), row('CCC', 50, 4, 50.1, 48, 1000), row('DDD', 300, 2.5, 300, 296),
  row('EEE', 400, -2.5, 404, 400)], { DDD: { sentiment: 'negative', date: '2026-11-16' }, EEE: { sentiment: 'negative', date: '2026-11-16' } }, { chg_pct: -0.9, spot: 25110 }));
const t = Object.fromEntries(book.trades.map((x) => [x.label, x]));
assert.ok(t['AAA long'] && t['AAA long'].qty === 80 && t['AAA long'].stop === 99 && t['AAA long'].basis === 'price only');
assert.ok(!t['BBB short'], 'a stock stuck at its lower circuit is skipped'); assert.ok(!Object.keys(t).some((k) => k.startsWith('CCC')), 'thin turnover is skipped');
assert.ok(!Object.keys(t).some((k) => k.startsWith('DDD')), 'negative news against a long is a conflict'); assert.equal(book.seen.DDD, 'conflict');
assert.ok(t['EEE short'] && t['EEE short'].basis === 'price + news' && t['EEE short'].stop === 404);
assert.ok(t['NIFTY 25100 PE buy'] && t['NIFTY 25100 PE buy'].stop === 105.7 && t['NIFTY 25100 PE buy'].qty === 65);
const n = book.trades.length; E.step(book, base('09:31', [row('AAA', 100, 3, 100.2, 98)])); assert.equal(book.trades.length, n, 'one trade per name per day');

// stop: AAA falls to 98.9 (long stop 99), EEE short squeezes above its stop
E.step(book, base('10:00', [row('AAA', 98.9, 1, 100.2, 98), row('EEE', 404.5, -2, 404.6, 400)], {}, { chg_pct: -0.9, spot: 25110 }));
assert.equal(t['AAA long'].status, 'LOSS'); assert.equal(t['AAA long'].why, 'stop'); assert.equal(t['AAA long'].pnl_rs, Math.round(((98.9 - 100) * 80 - 0.001 * 100 * 80) * 100) / 100);
assert.equal(t['EEE short'].status, 'LOSS');
// forced close at 15:10, option marked at the bid from the chain
const c2 = chain.map((x) => (x.kind === 'PE' && x.strike === 25100 ? { ...x, bid: 170 } : x));
E.step(book, { day: '2026-11-16', hhmm: '15:10', rows: [], news: {}, nifty: null, chain: c2 });
assert.equal(t['NIFTY 25100 PE buy'].status, 'WIN'); assert.equal(t['NIFTY 25100 PE buy'].exit, 170); assert.equal(t['NIFTY 25100 PE buy'].pnl_rs, (170 - 151) * 65 - 80);
const s = E.stats(book); assert.ok(s.find((x) => x.group === 'options short · index move' && x.wins === 1));
E.step(book, base('09:30', [])); E.step(book, { day: '2026-11-17', hhmm: '09:30', rows: [], news: {}, nifty: null, chain }); assert.equal(book.trades.length, 0, 'a new day starts a clean book');
const b2 = { day: '', trades: [], seen: {}, seq: 0 };
E.step(b2, base('10:00', ['A', 'B', 'C', 'D', 'E', 'F'].map((x, i) => row(x, 100 + i, 3 + i, 100 + i, 98)), {}, { chg_pct: 1.2, spot: 25110 }));
assert.equal(b2.trades.filter((x) => x.kind === 'stock').length, 4, 'stocks stop at four'); assert.ok(b2.trades.some((x) => x.label === 'NIFTY 25100 CE buy'), 'the index option still gets its slot');
console.log('live session rules ok');
