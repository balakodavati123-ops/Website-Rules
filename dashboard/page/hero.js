/* The terminal strip of the main page: a running tape of prices, a running tape of news, and the
   right-hand rail with the paper profit and loss and one card per trade. Everything is read from
   the datasets; the live-session trades come from the session running in this open page. */
(function () {
  const { el, inr, num, pct, cls, tag, mk } = CD; const LE = window.LSE;
  const rd = (id) => { const d = dash.data(id); return d.status === 'ok' ? d.data : []; };
  const sgn = (v, d = 0) => (v > 0 ? '+' : '') + inr(v, d);
  const nice = (s) => CD.cap(String(s || '').replace(/_/g, ' '));
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const dm = (v) => { const m = String(v || '').match(/^\d{4}-(\d{2})-(\d{2})/); return m ? `${Number(m[2])} ${MON[Number(m[1]) - 1]}` : String(v || ''); };

  /* ---------- running tapes ---------- */
  /* The items are laid out twice so the strip loops without a jump. When only the numbers change
     they are rewritten in place, so the strip keeps moving instead of starting again. */
  const SIG = new WeakMap();
  const tape = (box, items, secEach) => {
    if (!items.length) { SIG.delete(box); box.classList.remove('run'); box.replaceChildren(el('span', 'tk dim', 'Waiting for the feeds…')); return; }
    const sig = items.map((x) => x.id).join('|');
    if (SIG.get(box) !== sig) { SIG.set(box, sig);
      const copy = (hide) => items.map((x) => { const s = el('span', 'tk'); s.dataset.id = x.id; if (hide) s.setAttribute('aria-hidden', 'true'); return s; });
      box.replaceChildren(...copy(false), ...copy(true)); box.style.animationDuration = Math.max(40, Math.round(items.length * secEach)) + 's'; box.classList.add('run'); }
    const by = {}; items.forEach((x) => { by[x.id] = x; });
    box.querySelectorAll('.tk').forEach((s) => { const x = by[s.dataset.id]; if (x) s.replaceChildren(...x.nodes()); });
  };
  const quote = (name, pre, val, chg, src, f1, f2, where, note) => () => { const out = [el('b', 'tk-n', name)]; const v = el('span', 'num tk-v'); v.append(pre, mk(val, '', src, f1, where)); out.push(v);
    if (chg !== null && chg !== undefined) { const c = el('span', 'num ' + cls(chg)); c.append(chg > 0 ? '▲ ' : chg < 0 ? '▼ ' : '', mk(pct(chg), '', src, f2, where)); out.push(c); }
    if (note) out.push(el('small', 'tk-x', note)); return out; };

  dash.draw('tape_prices', (box) => { const items = [];
    rd('indices').forEach((x) => items.push({ id: 'i' + x.key, nodes: quote(x.name, '', num(x.live, 2), x.chg_pct, 'indices', 'live', 'chg_pct', 'key=' + x.key, 'live') }));
    rd('comm_live').forEach((x) => items.push({ id: 'c' + x.key, nodes: quote((x.name || '').replace(' Fut', ''), '₹', num(x.live, x.live < 1000 ? 2 : 0), x.chg_pct, 'comm_live', 'live', 'chg_pct', 'key=' + x.key, 'MCX live') }));
    rd('crypto_live').forEach((x) => items.push({ id: 'k' + x.symbol, nodes: quote(x.symbol, '$', num(x.price_usd, 2), x.chg_24h_pct, 'crypto_live', 'price_usd', 'chg_24h_pct', 'symbol=' + x.symbol, '24h') }));
    rd('world_markets').filter((x) => x.last !== null && x.last !== undefined).forEach((x) => items.push({ id: 'w' + x.symbol, nodes: quote(x.name, '', num(x.last, 2), x.chg_pct, 'world_markets', 'last', 'chg_pct', 'symbol=' + CD.enc(x.symbol), 'close ' + String(x.as_of || '').slice(5)) }));
    tape(box, items, 3.6); });

  dash.draw('tape_news', (box) => { const items = []; const dot = (s) => el('i', 'nd' + (s === 'positive' ? ' g' : s === 'negative' ? ' r' : ''));
    rd('news_feed').slice(-8).reverse().forEach((x, i) => items.push({ id: 'f' + i + x.time, nodes: () => [dot(''), el('b', 'tk-n', String(x.category || '').replace('NSE-', '')), document.createTextNode(x.headline), el('small', 'tk-x', `${x.source} · ${x.time} IST`)] }));
    rd('news_live').filter((x) => x.rank === 0).sort((a, b) => String(b.date).localeCompare(String(a.date))).forEach((x) => items.push({ id: 'n' + x.symbol, nodes: () => [dot(x.sentiment), el('b', 'tk-n', x.symbol), document.createTextNode(x.title), el('small', 'tk-x', 'INDmoney')] }));
    rd('world_news').forEach((x, i) => items.push({ id: 'h' + i, nodes: () => [dot(''), el('b', 'tk-n', x.market), document.createTextNode(x.title), el('small', 'tk-x', x.publisher)] }));
    tape(box, items, 9); });

  /* ---------- the rail: live profit and loss ---------- */
  const lsTrades = () => (CD.LS ? CD.LS.book.trades : []);
  const lsPnl = (t) => (t.status === 'OPEN' ? LE.openPnl(t) : t.pnl_rs);
  dash.draw('rail_num', (b) => { const k = b.dataset.k, r = dash.data('book_totals'); const t = r.status === 'ok' && r.data.length ? r.data[0] : null; const ls = lsTrades().reduce((a, x) => a + lsPnl(x), 0);
    if (k === 'counts') { b.textContent = t ? `${t.open_n} open · ${t.pending_n} waiting for the open · ${t.closed_n} closed · ${t.fo_open} option structures open` : '—'; return; }
    if (k !== 'live' && !t) { b.textContent = '—'; return; }
    const v = k === 'live' ? ls : k === 'open' ? t.open_pnl : k === 'closed' ? t.closed_pnl : k === 'fo' ? t.fo_pnl : t.total_pnl + ls;
    b.textContent = sgn(Math.round(v)); b.classList.toggle('up', v > 0); b.classList.toggle('down', v < 0); });

  /* ---------- the rail: one card per trade ---------- */
  const lv = (k, v) => { const s = el('span'); s.append(el('small', '', k), el('b', 'num', v)); return s; };
  const card = (o) => { const c = el('article', 'tcard ' + o.tone); const h = el('header'); h.append(el('span', 'tside', o.side), el('b', 'tsym', o.sym));
    if (o.pnl !== null) { const p = el('span', 'tpnl num ' + cls(o.pnl)); p.append(o.pnl > 0 ? '+' : '', o.mark ? mk(inr(o.pnl, 0), '', o.mark[0], o.mark[1], o.mark[2]) : inr(o.pnl, 0)); h.append(p); }
    const sub = el('div', 'tsub'); sub.append(o.sub); if (o.move !== null && o.move !== undefined) sub.append(el('span', 'num ' + cls(o.move), pct(o.move, 1)));
    const lvl = el('div', 'tlv'); o.levels.forEach((x) => lvl.append(lv(x[0], x[1]))); c.append(h, sub, lvl);
    if (o.bar !== null && o.bar !== undefined) { const bar = el('div', 'tbar'), m = el('i'); m.style.left = Math.max(0, Math.min(100, o.bar)) + '%'; bar.append(m); c.append(bar); }
    c.addEventListener('click', () => CD.goto(o.go || 'trades')); return c; };
  const px = (v) => (v === null || v === undefined || v === '' ? '—' : num(v, 2));

  dash.draw('rail_trades', (box) => { const out = []; const book = rd('trade_book'), fo = rd('fo_book');
    lsTrades().slice().reverse().forEach((t) => { const open = t.status === 'OPEN', p = lsPnl(t);
      out.push(card({ tone: open ? (t.side === 'LONG' ? 'long' : 'short') : p > 0 ? 'win' : 'loss', side: open ? `LIVE ${t.side}` : t.why === 'stop' ? 'STOPPED' : 'CLOSED', sym: t.kind === 'option' ? `NIFTY ${t.strike} ${t.opt}` : t.symbol, pnl: p, mark: null,
        sub: `Live session · ${t.basis} · ${t.time} `, move: t.entry ? ((open ? t.last : t.exit) / t.entry - 1) * 100 * (t.kind === 'stock' && t.side === 'SHORT' ? -1 : 1) : null,
        levels: [['ENTRY', px(t.entry)], ['STOP', px(t.stop)], [open ? 'LTP' : 'EXIT', px(open ? t.last : t.exit)], ['QTY', String(t.qty)]], bar: null, go: 'algo' })); });
    book.filter((t) => t.status === 'OPEN').forEach((t) => { const span = t.target !== null ? t.target - t.stop : null;
      out.push(card({ tone: 'long', side: 'LONG', sym: t.symbol, pnl: t.pnl, mark: ['trade_book', 'pnl', 'id=' + t.id], sub: `${nice(t.strategy)} · booked ${dm(t.booked)} `, move: t.move_pct,
        levels: [['ENTRY', px(t.entry)], ['STOP', px(t.stop)], ['TARGET', t.target !== null ? px(t.target) : 'trail'], ['LTP', px(t.last)]], bar: span && t.last !== null ? ((t.last - t.stop) / span) * 100 : null })); });
    fo.filter((t) => t.status === 'OPEN').forEach((t) => out.push(card({ tone: 'opt', side: 'OPTIONS', sym: `${t.underlying} ${nice(t.strategy)}`, pnl: null, sub: `Expires ${dm(t.expiry)} · settled at the expiry close `, move: null,
      levels: [['CREDIT', inr(t.credit_rs, 0)], ['BEST', inr(t.max_gain_rs, 0)], ['WORST', inr(-Math.abs(t.max_loss_rs), 0)], ['LOT', String(t.lot)]], bar: null, go: 'algo' })));
    book.filter((t) => t.status === 'PENDING').forEach((t) => out.push(card({ tone: 'pend', side: 'ORDER', sym: t.symbol, pnl: null, sub: `${nice(t.strategy)} · fills at the next open `, move: null,
      levels: [['REF', px(t.entry)], ['STOP', px(t.stop)], ['TARGET', t.target !== null ? px(t.target) : 'trail'], ['QTY', t.qty === null ? 'at fill' : String(t.qty)]], bar: null })));
    book.filter((t) => ['WIN', 'LOSS', 'TIME STOP'].includes(t.status)).slice(0, 4).forEach((t) => out.push(card({ tone: t.pnl > 0 ? 'win' : 'loss', side: t.status, sym: t.symbol, pnl: t.pnl, mark: ['trade_book', 'pnl', 'id=' + t.id], sub: `${nice(t.strategy)} · booked ${dm(t.booked)} `, move: t.move_pct,
      levels: [['ENTRY', px(t.entry)], ['STOP', px(t.stop)], ['EXIT', px(t.last)], ['R', t.r_mult === null ? '—' : num(t.r_mult, 2)]], bar: null })));
    if (!out.length) { box.replaceChildren(el('div', 'empty', 'No paper trade yet. Orders appear here when a strategy books one, and live-session trades the moment they open.')); return; }
    box.replaceChildren(...out); });

  /* ---------- World and news tab ---------- */
  dash.draw('stocknews_list', (box) => { const r = CD.need(box, ['news_live']); if (!r) return; const rows = r[0].slice().sort((a, b) => String(b.date).localeCompare(String(a.date)) || a.rank - b.rank);
    if (!rows.length) { box.replaceChildren(el('div', 'empty', 'INDmoney returned no news for the watchlist.')); return; }
    box.replaceChildren(...rows.map((x) => { const row = el('div', 'row'); row.style.gridTemplateColumns = 'auto 1fr auto'; const b = el('div'); b.append(el('div', 'h', x.title), el('div', 'w', x.date ? `dated ${x.date}` : 'date not given'));
      row.append(tag(x.symbol, 'b'), b, tag(x.sentiment || 'neutral', x.sentiment === 'positive' ? 'g' : x.sentiment === 'negative' ? 'r' : '')); return row; })); });
})();
