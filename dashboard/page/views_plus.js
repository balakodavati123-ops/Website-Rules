/* Pre-market world view, the strategy league and the chart inside the Algo tab. */
(function () {
  const { el, inr, num, pct, cls, mk, need, tag, PAL } = CD; const STATUS = { APPROVED: 'g', PROBATION: 'a', REJECTED: 'r' };

  dash.draw('world_cards', (box) => { const r = need(box, ['world_markets']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const c = el('div', 'mcx-card'), w = 'symbol=' + CD.enc(x.symbol); c.appendChild(el('div', 'sub', `${x.group} · ${x.name}`));
      const v = el('div', 'num'); v.style.cssText = 'font-size:18px;font-weight:650;margin-top:2px'; v.append(x.last === null ? 'Data Unverified' : mk(num(x.last, 2), '', 'world_markets', 'last', w));
      const d = el('div', 'num ' + cls(x.chg_pct)); if (x.chg_pct !== null) d.append(mk(pct(x.chg_pct), '', 'world_markets', 'chg_pct', w), ` · close of ${x.as_of}`);
      const sp = el('div'); sp.style.marginTop = '4px'; let arr = []; try { arr = JSON.parse(x.spark); } catch (e) { arr = []; } CD.spark(sp, arr, (x.chg_pct || 0) >= 0 ? PAL.green : PAL.red, 180, 30);
      c.append(v, d, sp, el('div', 'sub', x.why)); return c; })); });
  dash.draw('events_body', (body) => { const r = need(body, ['events_today']); if (!r) return;
    CD.fillTable(body, r[0], [{ cls: 'num', render: (d) => d.date.slice(5) }, { render: (d) => (d.watchlist === 'yes' ? tag(d.symbol, 'b') : d.symbol) }, { render: (d) => d.kind }, { cls: 'hs', render: (d) => d.detail }], ['date', 'symbol', 'kind']); });
  dash.draw('news_list', (box) => { const r = need(box, ['world_news']); if (!r) return;
    box.replaceChildren(...r[0].map((x) => { const row = el('div', 'row'); row.style.gridTemplateColumns = 'auto 1fr'; const b = el('div'); b.append(el('div', 'h', x.title), el('div', 'w', `${x.publisher} · ${String(x.time).replace('T', ' ').slice(0, 16)} UTC`)); row.append(tag(x.market, 'v'), b); return row; }));
    if (!r[0].length) box.replaceChildren(el('div', 'empty', 'No headlines were saved this morning.')); });

  dash.draw('league_body', (body) => { const r = need(body, ['strategy_board']); if (!r) return;
    CD.fillTable(body, r[0], [{ cls: 'num', render: (d) => String(d.rank) }, { render: (d) => d.strategy }, { cls: 'num r', render: (d) => `${d.closed} / ${d.need_trades}` }, { cls: 'num r', render: (d) => String(d.open) },
      { cls: 'num r', render: (d) => (d.closed ? pct(d.win_rate, 0, false) : '—') }, { cls: 'num r', render: (d) => (d.closed ? el('span', cls(d.avg_r), num(d.avg_r, 2)) : '—') },
      { cls: 'num r', render: (d) => (d.closed > 1 ? pct(d.confidence, 0, false) : '—') }, { cls: 'num r', render: (d) => el('span', cls(d.pnl), inr(d.pnl)) },
      { cls: 'hs', render: (d) => (d.backtest ? tag(d.backtest, STATUS[d.backtest] || '') : '—') }, { render: (d) => tag(d.ready ? 'READY FOR REAL MONEY' : 'PAPER ONLY', d.ready ? 'g' : '') }], 'strategy'); });

  const toRows = (rows) => rows.map((r) => ({ t: new Date(String(r.t).replace(' ', 'T') + '+05:30'), o: r.o, h: r.h, l: r.l, c: r.c, v: r.v })).filter((r) => !Number.isNaN(r.t.getTime()));
  dash.draw('algo_pick', (em) => { em.textContent = CD.pickName ? `${CD.pickName} · daily candles, one year` : 'press "Open chart" on a name above'; });
  dash.draw('candle_algo', (box) => { if (!CD.pickName) { box.replaceChildren(el('div', 'empty', 'Pick a name from the approved list to see its history, its moving averages and where the recent drift points.')); return; }
    const r = need(box, ['candles']); if (!r) return; const s = CD.candleChart(box, toRows(r[0]), { iv: dash.params().iv, label: `${CD.pickName}: candles with moving averages and a projection band` });
    if (s) { const p = el('p', 'note'); p.textContent = `Last ${num(s.last, 2)}. The straight-line fit of recent closes points to ${num(s.projEnd, 2)} in ${s.steps} sessions (${pct((s.projEnd / s.last - 1) * 100, 1)}), with support near ${num(s.support, 2)} and resistance near ${num(s.resistance, 2)}. A drift line is not a forecast.`; box.appendChild(p); } });
})();
