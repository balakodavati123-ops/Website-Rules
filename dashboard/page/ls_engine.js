/* Live paper session rules. Pure functions, no DOM, so they can be tested on their own.
   step(book, snap) opens, marks and closes intraday paper trades from live INDmoney figures.
   snap: { day, hhmm, rows: [{symbol, price, chg_pct, day_high, day_low, volume, circ_up, circ_lo}],
           news: {SYMBOL: {sentiment, date}}, nifty: {chg_pct, spot}, chain: [{strike, kind, bid, ask, lot, expiry}] } */
(function (root) {
  const C = { notional: 8000, optMax: 12000, maxTrades: 6, maxStocks: 4, move: 2, idxMove: 0.7, stop: 0.01, optStop: 0.3, from: 9 * 60 + 20, to: 15 * 60 + 10, stockCost: 0.001, optCost: 80 };
  const mins = (h) => { const p = String(h).split(':'); return Number(p[0]) * 60 + Number(p[1]); };

  function close(tr, px, why) {
    const dir = tr.side === 'LONG' ? 1 : -1;
    const pnl = tr.kind === 'stock' ? dir * (px - tr.entry) * tr.qty - C.stockCost * tr.entry * tr.qty : (px - tr.entry) * tr.qty - C.optCost;
    Object.assign(tr, { exit: px, pnl_rs: Math.round(pnl * 100) / 100, status: pnl > 0 ? 'WIN' : 'LOSS', why, last: px });
  }

  function step(book, s) {
    if (book.day !== s.day) { book.day = s.day; book.trades = []; book.seen = {}; book.seq = 0; }
    const t = mins(s.hhmm); const by = {}; s.rows.forEach((r) => { by[r.symbol] = r; });
    book.trades.forEach((tr) => { if (tr.status !== 'OPEN') return;
      if (tr.kind === 'stock') { if (by[tr.symbol]) tr.last = by[tr.symbol].price; }
      else { const c = s.chain.find((x) => x.strike === tr.strike && x.kind === tr.opt && x.expiry === tr.expiry); if (c && c.bid) tr.last = c.bid; }
      if (tr.last == null) return;
      const hit = tr.kind === 'stock' ? (tr.side === 'LONG' ? tr.last <= tr.stop : tr.last >= tr.stop) : tr.last <= tr.stop;
      if (hit || t >= C.to) close(tr, tr.last, hit ? 'stop' : 'time'); });
    if (t < C.from || t >= C.to || book.trades.length >= C.maxTrades) return book;

    const rows = s.rows.slice().sort((a, b) => Math.abs(b.chg_pct) - Math.abs(a.chg_pct));
    const nStock = () => book.trades.filter((x) => x.kind === 'stock').length;
    for (const r of rows) { if (nStock() >= C.maxStocks) break; if (book.seen[r.symbol] || !(r.price >= 20) || r.price * (r.volume || 0) < 1e8) continue;
      const up = r.chg_pct >= C.move && r.price >= 0.99 * r.day_high && !(r.circ_up && r.price >= 0.995 * r.circ_up);
      const dn = r.chg_pct <= -C.move && r.price <= 1.01 * r.day_low && !(r.circ_lo && r.price <= 1.005 * r.circ_lo);
      if (!up && !dn) continue;
      const n = s.news[r.symbol]; const fresh = n && n.date === s.day ? n.sentiment : '';
      if ((up && fresh === 'negative') || (dn && fresh === 'positive')) { book.seen[r.symbol] = 'conflict'; continue; }       // news disagrees with the move: stand aside
      const side = up ? 'LONG' : 'SHORT'; book.seen[r.symbol] = side; book.seq += 1;
      book.trades.push({ id: book.seq, day: s.day, time: s.hhmm, kind: 'stock', symbol: r.symbol, side, entry: r.price, last: r.price, qty: Math.floor(C.notional / r.price),
        stop: Math.round(r.price * (up ? 1 - C.stop : 1 + C.stop) * 100) / 100, basis: fresh ? 'price + news' : 'price only', label: `${r.symbol} ${side.toLowerCase()}`, status: 'OPEN', pnl_rs: 0, exit: '', why: '' }); }

    const nf = s.nifty; if (nf && s.chain.length && Math.abs(nf.chg_pct) >= C.idxMove && book.trades.length < C.maxTrades) {
      const dir = nf.chg_pct > 0 ? 'LONG' : 'SHORT', key = 'NIFTY' + dir; const kind = dir === 'LONG' ? 'CE' : 'PE';
      if (!book.seen[key]) { const strike = s.chain.reduce((b, x) => (Math.abs(x.strike - nf.spot) < Math.abs(b - nf.spot) ? x.strike : b), s.chain[0].strike);
        const c = s.chain.find((x) => x.strike === strike && x.kind === kind);
        if (c && c.ask && c.lot && c.ask * c.lot <= C.optMax) { book.seen[key] = dir; book.seq += 1;
          book.trades.push({ id: book.seq, day: s.day, time: s.hhmm, kind: 'option', symbol: 'NIFTY', side: dir, opt: kind, strike, expiry: c.expiry, entry: c.ask, last: c.bid || c.ask, qty: c.lot, stop: Math.round(c.ask * (1 - C.optStop) * 100) / 100,
            basis: 'index move', label: `NIFTY ${strike} ${kind} buy`, status: 'OPEN', pnl_rs: 0, exit: '', why: '' }); } } }
    return book;
  }

  function stats(book) {
    const g = {}; book.trades.forEach((t) => { const k = (t.kind === 'option' ? 'options ' : 'stocks ') + t.side.toLowerCase() + ' · ' + t.basis; const s = g[k] || (g[k] = { group: k, open: 0, closed: 0, wins: 0, pnl: 0 });
      if (t.status === 'OPEN') { s.open += 1; } else { s.closed += 1; if (t.pnl_rs > 0) s.wins += 1; } s.pnl += t.status === 'OPEN' ? openPnl(t) : t.pnl_rs; });
    return Object.values(g); }
  function openPnl(t) { const dir = t.side === 'LONG' ? 1 : -1; return t.kind === 'stock' ? dir * (t.last - t.entry) * t.qty : (t.last - t.entry) * t.qty; }
  root.LSE = { C, step, stats, openPnl };
})(typeof window !== 'undefined' ? window : globalThis);
