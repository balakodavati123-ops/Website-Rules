/* Market desks. The front page showed one team of agents, the equity desks. This gives F&O, crypto and
   commodities (MCX) their own teams, each with a data analyst, a technical or options analyst, a risk
   officer and a trading officer who hand a name to the next desk, read the live feeds on this page and
   say what they see. The tabs switch the flow picture, the agent cards and the organisation chart.
   Each agent is a rule program, not a separate AI. The background desk on GitHub trades by the same rules. */
(function () {
  const { el, num, pct, cls, inr } = CD; const E = CD.ENG;
  const rd = (id) => { const d = dash.data(id); return d.status === 'ok' ? d.data : []; };
  const AG = (CD.MAG = {
    FDATA: { name: 'Derivatives Data Analyst', short: 'Deriv Data', init: 'DD', c: '#29d3ee', fg: '#04101c' }, FFLOW: { name: 'Options Flow Analyst', short: 'Options Flow', init: 'OF', c: '#4f8cff', fg: '#fff' },
    FVOL: { name: 'Volatility Analyst', short: 'Volatility', init: 'VA', c: '#ff7ac6', fg: '#fff' }, FSTR: { name: 'Options Strategist', short: 'Strategist', init: 'OS', c: '#a184ff', fg: '#fff' },
    FRISK: { name: 'Derivatives Risk Officer', short: 'Deriv Risk', init: 'DR', c: '#ffb64a', fg: '#2a1a00' }, FTO: { name: 'F&O Trading Officer', short: 'F&O Trader', init: 'FT', c: '#2de3a5', fg: '#04201a' },
    KDATA: { name: 'Crypto Data Analyst', short: 'Crypto Data', init: 'CD', c: '#29d3ee', fg: '#04101c' }, KTECH: { name: 'Crypto Technical Analyst', short: 'Crypto Tech', init: 'CT', c: '#4f8cff', fg: '#fff' },
    KLIQ: { name: 'Liquidity and Breadth Analyst', short: 'Liquidity', init: 'LB', c: '#ff7ac6', fg: '#fff' }, KRISK: { name: 'Crypto Risk Officer', short: 'Crypto Risk', init: 'CR', c: '#ffb64a', fg: '#2a1a00' },
    KTO: { name: 'Crypto Trading Officer', short: 'Crypto Trader', init: 'KT', c: '#2de3a5', fg: '#04201a' },
    MDATA: { name: 'Commodities Data Analyst', short: 'MCX Data', init: 'MD', c: '#29d3ee', fg: '#04101c' }, MTECH: { name: 'Commodities Technical Analyst', short: 'MCX Tech', init: 'MT', c: '#4f8cff', fg: '#fff' },
    MOI: { name: 'Open Interest Analyst', short: 'Open Interest', init: 'OI', c: '#a184ff', fg: '#fff' }, MMACRO: { name: 'Currency and Macro Analyst', short: 'Macro', init: 'CM', c: '#ff7ac6', fg: '#fff' },
    MRISK: { name: 'Commodities Risk Officer', short: 'MCX Risk', init: 'MR', c: '#ffb64a', fg: '#2a1a00' }, MTO: { name: 'Commodities Trading Officer', short: 'MCX Trader', init: 'CTO', c: '#2de3a5', fg: '#04201a' } });
  const MK = {
    EQUITY: { name: 'Equities', chain: null },
    FNO: { name: 'F&O', chain: ['FDATA', 'FFLOW', 'FVOL', 'FSTR', 'FRISK', 'FTO', 'COO'], what: 'NIFTY option structures' },
    CRYPTO: { name: 'Crypto', chain: ['KDATA', 'KTECH', 'KLIQ', 'KRISK', 'KTO', 'COO'], what: 'coins' },
    COMM: { name: 'Commodities', chain: ['MDATA', 'MTECH', 'MOI', 'MMACRO', 'MRISK', 'MTO', 'COO'], what: 'MCX futures' } };
  const STATE = ['PULLING', 'SCREENING', 'CHECKING', 'SIZING', 'DECIDING', 'REPORTING', 'REVIEWING'];
  const M = (CD.MKT = { market: 'EQUITY', i: -1, focus: 0, cur: null, view: null, txt: {}, timer: null });
  const agent = (id) => AG[id] || CD.AGENTS[id];
  const sgn = (v, d = 2) => (v > 0 ? '+' : '') + Number(v).toFixed(d) + '%';
  const names = (rows, n = 4) => (rows.length ? rows.slice(0, n).map((r) => r.label).join(', ') + (rows.length > n ? ` and ${rows.length - n} more` : '') : 'none');

  /* ----- what each market's desks see, from the live feeds on this page ----- */
  const build = {
    FNO() {
      const idx = rd('indices'), nf = idx.find((x) => /^NIFTY 50$/i.test(x.name)) || {}, vx = idx.find((x) => /VIX/i.test(x.name)) || {}, ch = rd('nifty_chain');
      const chg = nf.chg_pct || 0, vix = vx.live, spot = (ch[0] && ch[0].spot) || nf.live;
      const atm = ch.length ? ch.reduce((b, x) => (Math.abs(x.strike - spot) < Math.abs(b - spot) ? x.strike : b), ch[0].strike) : null;
      const ce = ch.find((x) => x.strike === atm && x.kind === 'CE'), pe = ch.find((x) => x.strike === atm && x.kind === 'PE'), st = ce && pe && ce.ask && pe.ask ? ce.ask + pe.ask : null;
      const rich = vix >= 13 && vix < 22, calm = Math.abs(chg) < 0.4;
      const S = [['iron_condor', 'Iron condor', 'FIXED RETURN', Math.abs(chg) < 0.5 && vix < 20, Math.abs(chg) >= 0.5 ? 'MOVE TOO BIG' : 'VIX TOO HIGH'], ['credit_spread', 'Credit spread', 'FIXED RETURN', Math.abs(chg) >= 0.15 && vix < 22, Math.abs(chg) < 0.15 ? 'NO DIRECTION' : 'VIX TOO HIGH'],
        ['short_strangle', 'Short strangle', 'HIGH RETURN / HIGH LOSS', rich && calm && vix < 18, vix < 13 ? 'PREMIUM TOO THIN' : !calm ? 'MOVE TOO BIG' : 'VIX TOO HIGH'], ['debit_spread', 'Debit spread', 'HIGH RETURN / LOW LOSS', Math.abs(chg) >= 0.25, 'NO TREND'],
        ['long_breakout', 'Long option breakout', 'HIGH RETURN / LOW LOSS', Math.abs(chg) >= 0.5, 'MOVE UNDER 0.5%']];
      const rows = S.map(([k, label, cls_, ok, why], i) => ({ symbol: k, label, key: '', chg_pct: chg, val_txt: cls_.replace('HIGH RETURN / ', 'HI / ').replace('FIXED RETURN', 'FIXED'), failed: ok ? 0 : 1, fail_text: why, score: 90 - i, horizon: 'Day' }));
      const ok = rows.filter((r) => !r.failed);
      return { rows, st: { hubText: spot ? `NIFTY ${Number(spot).toLocaleString('en-IN', { maximumFractionDigits: 1 })}  ${sgn(chg)}` : 'NIFTY', hubChg: chg }, txt: {
        FDATA: spot ? `Read the NIFTY option chain: ${ch.length} quotes, expiry ${ch[0] ? ch[0].expiry : '—'}. NIFTY ${num(spot, 1)} (${sgn(chg)} on the close).` : 'Waiting for the option chain.',
        FFLOW: st ? `At the money (${atm}) the call costs ${num(ce.ask, 1)} and the put ${num(pe.ask, 1)}. A straddle is ${num(st, 1)}: the market expects about ±${(st / spot * 100).toFixed(2)}% to expiry.` : 'No two-sided prices at the money yet.',
        FVOL: vix ? `India VIX ${num(vix, 2)}: ${vix < 13 ? 'premiums are thin, selling options pays little' : vix < 18 ? 'normal' : vix < 22 ? 'rich premiums, but moves can be big' : 'stress: no short-premium trades'}.` : 'No VIX reading yet.',
        FSTR: `Fit for today: ${names(ok, 5)}. Ruled out: ${rows.length - ok.length}.`,
        FRISK: 'One lot of 65. Every structure has a capped loss except the short strangle, which is stopped when the loss equals its credit. All out by 15:15.',
        FTO: ok.length ? `Takes ${ok[0].label.toLowerCase()} first. The background desk books these after 09:45 from Upstox option prices, and shows each leg and why.` : 'Nothing fits today. No F&O trade is forced.',
        COO: 'Ranks the five structures by their closed-trade results and pauses any that lose over 30 trades.' } };
    },
    CRYPTO() {
      const c = rd('crypto_live');
      const rows = c.map((x) => { let sp = []; try { sp = JSON.parse(x.spark); } catch (e) { sp = []; } const w = sp.slice(-24), hi = Math.max(...w), lo = Math.min(...w), last = w[w.length - 1];
        const brk = x.chg_24h_pct >= 1.5, dip = w.length > 5 && last <= hi * 0.96 && last >= lo * 1.005 && x.chg_24h_pct > -6 && !brk;
        return { symbol: x.symbol, label: x.symbol, key: '', chg_pct: x.chg_24h_pct, val_txt: null, failed: brk || dip ? 0 : 1, fail_text: x.chg_24h_pct < 0 ? 'NO DIP SETUP' : 'UNDER +1.5%', score: Math.round(Math.abs(x.chg_24h_pct) * 10) + 50, horizon: brk ? 'Breakout' : dip ? 'Dip bounce' : '', price: x.price_usd, cap: x.market_cap }; });
      const ok = rows.filter((r) => !r.failed), up = rows.filter((r) => r.chg_pct > 0).length, tot = c.reduce((a, x) => a + (x.market_cap || 0), 0), btc = c.find((x) => x.symbol === 'BTC');
      return { rows, st: { hubText: btc ? `BTC $${num(btc.price_usd, 0)}  ${sgn(btc.chg_24h_pct)}` : 'CRYPTO', hubChg: btc ? btc.chg_24h_pct : 0 }, txt: {
        KDATA: c.length ? `Read ${c.length} coins from CoinGecko: ${c.slice(0, 3).map((x) => `${x.symbol} $${num(x.price_usd, x.price_usd < 10 ? 3 : 0)} (${sgn(x.chg_24h_pct, 1)})`).join(', ')}.` : 'Waiting for the coin feed.',
        KTECH: `Two rules: up 1.5% or more on the day (breakout), or 4% under its recent high but already off the low (dip bounce). Pass: ${names(ok)}.`,
        KLIQ: c.length ? `${up} of ${c.length} coins are up in 24 hours${btc && tot ? `; Bitcoin is ${(btc.market_cap / tot * 100).toFixed(0)}% of the value tracked` : ''}.` : '—',
        KRISK: 'Spot only and long only: Indian retail cannot short spot crypto. ₹10,000 a trade, stop 1.5%, target 3%, out after 8 hours, three open at most. Crypto trades all day and night.',
        KTO: ok.length ? `First in line: ${ok[0].label} (${ok[0].horizon.toLowerCase()}, ${sgn(ok[0].chg_pct, 1)}). The background desk books it by these rules; check the Trades panel for what it did.` : 'No coin passes either rule. No trade is forced.',
        COO: 'Compares breakout and dip-bounce by closed trades and pauses the one that keeps losing.' } };
    },
    COMM() {
      const c = rd('comm_live'), w = rd('world_markets');
      const rows = c.map((x) => { const up = x.chg_pct >= 0.8 && x.live >= x.high * 0.997, dn = x.chg_pct <= -0.8 && x.live <= x.low * 1.003, nm = String(x.name || '').replace(/ Fut$/i, '').replace(/ \d+ \w+$/i, '');
        return { symbol: x.key, label: nm, key: '', chg_pct: x.chg_pct, val_txt: null, failed: up || dn ? 0 : 1, fail_text: Math.abs(x.chg_pct) < 0.8 ? 'UNDER 0.8% MOVE' : 'NOT AT THE EXTREME', score: Math.round(Math.abs(x.chg_pct) * 20) + 50, horizon: up ? 'Long' : dn ? 'Short' : '', oi: x.oi, oi_chg: x.oi_chg }; });
      const ok = rows.filter((r) => !r.failed), g = rows.find((r) => /gold/i.test(r.label)), oi = rows.slice().sort((a, b) => Math.abs(b.oi_chg || 0) - Math.abs(a.oi_chg || 0))[0];
      const usd = w.find((x) => /INR/i.test(x.symbol + x.name)), dx = w.find((x) => /dollar index|DX/i.test(x.name + x.symbol));
      return { rows, st: { hubText: g ? `${g.label} ${sgn(g.chg_pct)}` : 'MCX', hubChg: g ? g.chg_pct : 0 }, txt: {
        MDATA: c.length ? `Read ${c.length} MCX futures live from INDmoney: ${rows.slice(0, 4).map((r) => `${r.label} ${sgn(r.chg_pct, 1)}`).join(', ')}.` : 'Waiting for MCX prices (the market runs 09:00 to 23:30).',
        MTECH: `Rule: up or down 0.8% or more and within 0.3% of the day's high or low. Pass: ${names(ok)}.`,
        MOI: oi ? `Biggest open-interest change: ${oi.label} ${sgn(oi.oi_chg || 0, 1)}. Rising interest on a move means new money behind it.` : '—',
        MMACRO: usd || dx ? `${usd ? `Dollar-rupee ${num(usd.last, 2)} (${sgn(usd.chg_pct)})` : ''}${usd && dx ? '; ' : ''}${dx ? `dollar index ${num(dx.last, 2)} (${sgn(dx.chg_pct)})` : ''}, last close. A stronger dollar usually weighs on gold and silver.` : 'World currency data comes from the morning run.',
        MRISK: 'Micro and mini contracts only, about ₹60,000 of exposure a trade, stop 0.6%, target 1.2%, everything out by 23:15, four open at most.',
        MTO: ok.length ? `First in line: ${ok[0].label} (${ok[0].horizon.toLowerCase()}, ${sgn(ok[0].chg_pct, 1)}). The background desk books these by the same rule.` : 'Nothing is at an extreme with a 0.8% move. No trade is forced.',
        COO: 'Reviews the momentum rule by closed trades and pauses it if it keeps losing.' } };
    },
  };

  M.chain = () => (MK[M.market].chain || []);
  M.refresh = () => { if (M.market === 'EQUITY') { M.view = null; return; } const v = build[M.market](); v.chain = M.chain(); v.st.survivors = v.rows.filter((r) => !r.failed).length; v.st.killed = v.rows.length - v.st.survivors; v.st.quote_time = new Date().toISOString(); M.view = v; M.txt = v.txt; };
  M.step = () => { if (M.market === 'EQUITY') return; M.refresh(); const ch = M.chain(), v = M.view; if (!v || !ch.length) return; M.i = (M.i + 1) % ch.length; if (M.i === 0) M.focus += 1;
    const ok = v.rows.filter((r) => !r.failed), pool = ok.length ? ok : v.rows; const row = pool.length ? pool[M.focus % pool.length] : null; M.cur = { agent: ch[M.i], state: STATE[M.i] || 'REVIEWING', row, text: M.txt[ch[M.i]] || '' };
    dash.draw('mkt_agents'); dash.draw('mkt_title'); };
  M.teams = () => ({ EQUITY: null, FNO: [['iron_condor', 'Iron Condor'], ['credit_spread', 'Credit Spread'], ['short_strangle', 'Short Strangle'], ['debit_spread', 'Debit Spread'], ['long_breakout', 'Long Option Breakout']],
    CRYPTO: [['crypto_breakout', 'Crypto Breakout'], ['crypto_dip_bounce', 'Crypto Dip Bounce']], COMM: [['mcx_momentum', 'MCX Momentum']] }[M.market]);
  M.set = (m) => { M.market = m; M.i = -1; M.focus = 0; M.cur = null; M.refresh(); document.querySelectorAll('[data-mk]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mk === m)));
    if (m !== 'EQUITY') M.step(); ['flow_stage', 'mkt_agents', 'mkt_title', 'org_stage', 'org_count'].forEach((n) => dash.draw(n)); };
  document.querySelectorAll('[data-mk]').forEach((b) => b.addEventListener('click', () => M.set(b.dataset.mk)));
  M.timer = setInterval(() => { if (!document.hidden && E.shown && M.market !== 'EQUITY' && !E.paused) M.step(); }, 2600);

  dash.draw('mkt_title', (n) => { const c = M.cur, a = c && agent(c.agent); n.textContent = M.market === 'EQUITY' ? 'Equity desks' : `${MK[M.market].name} desks${a ? ' · ' + a.name : ''}`; });
  dash.draw('mkt_agents', (box) => { if (M.market === 'EQUITY') { box.replaceChildren(el('p', 'note', 'The equity desks are the ten cards below the picture. Pick F&O, Crypto or Commodities above to see those teams.')); return; }
    if (!M.view) M.refresh(); const v = M.view, kids = [];
    M.chain().forEach((id) => { const a = agent(id), on = M.cur && M.cur.agent === id, card = el('article', 'mk-card' + (on ? ' on' : '')); card.style.setProperty('--c', a.c);
      const h = el('header'), i = el('i', 'ic', a.init); i.style.background = a.c; i.style.color = a.fg; const b = el('b', '', a.name), s = el('small', '', on ? M.cur.state : 'WAITING');
      h.append(i, b, s); card.append(h, el('p', '', (v && v.txt[id]) || 'Waiting for the feed.')); kids.push(card); });
    box.replaceChildren(...kids); });
})();
