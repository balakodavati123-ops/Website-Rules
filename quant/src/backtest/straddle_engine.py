"""Long NIFTY straddle backtest on real traded weekly-option prices (Upstox expired-instrument candles), trade by trade.

For every weekly expiry in range, every trading day from 4 days to expiry (4-DTE) down to expiry day (0-DTE), every entry time and every
strike policy, the engine buys one lot of the call and the put at the chosen strike at the 1-minute close of the entry minute, marks both
legs every minute on their own traded prices, and exits at the first of: the profit target, the stop-loss (both on the combined premium),
or the 15:20 square-off. Each (target, stop) pair is replayed on the same path. Slippage is charged on every leg on the way in and out;
charges follow costs.charges. Strike policies:
  atm            the 50-point strike nearest NIFTY at entry
  lean_150_250   150 points (MODE_1_QUIET) or 250 points (MODE_2/3) toward the morning's move from the open (0.15%+), else toward the move since
                 yesterday's close (0.3%+), else at the money; the leg on the moving side starts in the money
DATA_SOURCE_STATUS per trade: VERIFIED_HISTORICAL when both legs traded in the entry minute and the exit minute, PARTIAL when a price had to
be carried forward from an earlier minute (illiquid strike). Nothing here places an order.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from ..data.upstox_client import BANKNIFTY, NIFTY, VIX, IST, UpstoxClient
from ..data import macro_news_feed as MF
from ..models import regime_pricing as RP
from .costs import charges


@dataclass
class Config:
    start: date = date(2024, 10, 1)
    end: date = field(default_factory=lambda: datetime.now(IST).date())
    entries: tuple = ("09:20", "10:30", "11:00", "12:45")
    targets: tuple = (0.30, 0.50, 0.80)
    stops: tuple = (0.25, 0.35, 0.50)
    square_off: str = "15:20"
    interval: str = "1minute"
    step: int = 50
    slip_pct: float = 0.003            # per leg, per side, as a share of the price
    slip_min: float = 0.10             # at least 0.10 point per leg per side
    max_dte: int = 4
    policies: tuple = ("atm", "lean_150_250")
    capital: float = 100000.0
    weights: tuple = (0.25, 0.20, 0.15)


@dataclass
class Trade:
    trade_id: str
    config_id: str
    strike_policy: str
    target_pct: float
    stop_pct: float
    expiry_date: str
    dte: int
    mode: str
    sigma_iv: float
    sigma_eff: float
    news_scores: str
    spot_at_entry: float
    strike: int
    ce_symbol: str
    pe_symbol: str
    entry_window: str
    entry_timestamp_ist: str
    ce_entry_price: float
    pe_entry_price: float
    combined_entry_premium: float
    lot_size: int
    capital_deployed: float
    exit_timestamp_ist: str
    exit_reason: str
    spot_at_exit: float
    ce_exit_price: float
    pe_exit_price: float
    combined_exit_premium: float
    gross_pnl_inr: float
    slippage_inr: float
    est_charges_inr: float
    net_pnl_inr: float
    return_pct: float
    mae_pct: float
    mfe_pct: float
    data_source_status: str
    morning_move_pct: float


def _minute(t: str, delta: int) -> str:
    h, m = int(t[:2]), int(t[3:]) + delta
    return f"{h + m // 60:02d}:{m % 60:02d}"


def _series(candles) -> dict:
    """{date: {HH:MM bar start: (close, open)}}."""
    out: dict = {}
    for c in candles:
        out.setdefault(c.ts.date(), {})[c.ts.strftime("%H:%M")] = (c.close, c.open)
    return out


def _price_at(bars: dict, t: str) -> float | None:
    """Price at clock time t = close of the bar that started a minute earlier."""
    b = bars.get(_minute(t, -1))
    return b[0] if b else None


class Backtester:
    def __init__(self, client: UpstoxClient, cfg: Config, log=print):
        self.c, self.cfg, self.log = client, cfg, log
        self.status = {"option_prices": "VERIFIED_HISTORICAL (Upstox expired-instrument candles)", "index": "VERIFIED_HISTORICAL (Upstox v3 candles)",
                       "macro": "PARTIAL (Yahoo daily closes, point-in-time; JNIV replaced by Nikkei and TOPIX Banks moves)",
                       "news_sentiment": "SYNTHETIC_MOCK = 0 in the backtest (no historical headline archive); live only"}

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        cfg, c = self.cfg, self.c
        self.log("loading NIFTY, India VIX and Nifty Bank candles ...")
        self.n1 = _series(c.index_candles(NIFTY, "minutes", 1, cfg.start - timedelta(days=7), cfg.end))
        self.v1 = _series(c.index_candles(VIX, "minutes", 1, cfg.start - timedelta(days=7), cfg.end))
        nd = c.index_candles(NIFTY, "days", 1, cfg.start - timedelta(days=40), cfg.end, chunk_days=1500)
        vd = c.index_candles(VIX, "days", 1, cfg.start - timedelta(days=40), cfg.end, chunk_days=1500)
        bd = c.index_candles(BANKNIFTY, "days", 1, cfg.start - timedelta(days=40), cfg.end, chunk_days=1500)
        self.nclose = {x.ts.date(): x.close for x in nd}
        self.vclose = {x.ts.date(): x.close for x in vd}
        self.trading = sorted(d for d in self.nclose if d in self.n1 or d < cfg.start)
        self.tset = set(self.trading)
        self.log("loading cross-market closes ...")
        self.macro = MF.load_all(cfg.start - timedelta(days=10), cfg.end, {x.ts.date(): x.close for x in bd})
        self.expiries = [e for e in c.expired_expiries(NIFTY) if cfg.start.isoformat() <= e <= cfg.end.isoformat()]
        self.log(f"{len(self.expiries)} expired weekly expiries from {self.expiries[0] if self.expiries else '-'} to {self.expiries[-1] if self.expiries else '-'}")

    def prev_trading(self, d: date) -> date | None:
        i = self.trading.index(d) if d in self.tset else None
        return self.trading[i - 1] if i else None

    # ------------------------------------------------------------------ plan the trades, then fetch only the contracts they need
    def plan(self) -> list[dict]:
        cfg, plans = self.cfg, []
        for e in self.expiries:
            E = date.fromisoformat(e)
            days = [d for d in self.trading if d <= E and d >= cfg.start][-(cfg.max_dte + 1):]
            for d in days:
                dte = sum(1 for x in self.trading if d < x <= E)
                if dte > cfg.max_dte or d not in self.n1 or d not in self.v1:
                    continue
                p = self.prev_trading(d)
                if not p or p not in self.nclose or p not in self.vclose:
                    continue
                bars = self.n1[d]
                first = min(bars)
                day_open = bars[first][1]
                sc = MF.scores(d, self.macro)
                for w in cfg.entries:
                    spot, vix = _price_at(bars, w), _price_at(self.v1[d], w)
                    if not spot or not vix:
                        continue
                    se = RP.sigma_eff(vix / 100, sc["S_IN_Bank"], sc["S_US_Macro"], sc["S_Asia_FX"], *cfg.weights)
                    mode = RP.mode_of(se)
                    mo, mp = (spot / day_open - 1) * 100, (spot / self.nclose[p] - 1) * 100
                    dirn = (1 if mo > 0 else -1) if abs(mo) >= 0.15 else (1 if mp > 0 else -1) if abs(mp) >= 0.3 else 0
                    atm = int(round(spot / cfg.step) * cfg.step)
                    for pol in cfg.policies:
                        k = atm if pol == "atm" else atm - (150 if mode == RP.MODES[0] else 250) * dirn
                        plans.append({"day": d, "expiry": e, "dte": dte, "entry": w, "spot": spot, "vix": vix, "se": se, "mode": mode, "scores": sc, "policy": pol,
                                      "strike": k, "mo": round(mo, 2)})
        return plans

    def fetch_contracts(self, plans: list[dict]) -> None:
        cfg, need = self.cfg, {}
        for p in plans:
            need.setdefault(p["expiry"], set()).add(p["strike"])
        self.legs: dict = {}
        jobs = []
        for e, ks in need.items():
            meta = {}
            for x in self.c.expired_contracts(e):
                if x.get("strike_price") in ks and x.get("instrument_type") in ("CE", "PE"):
                    meta[(int(x["strike_price"]), x["instrument_type"])] = x
            E = date.fromisoformat(e)
            for key, x in meta.items():
                jobs.append((e, key, x, E - timedelta(days=9), E))
        self.log(f"fetching {len(jobs)} option contracts ({sum(len(v) for v in need.values())} strikes over {len(need)} expiries) ...")

        def one(j):
            e, key, x, f, t = j
            try:
                return e, key, x, _series(self.c.expired_candles(x["instrument_key"], cfg.interval, f, t))
            except Exception as ex:
                return e, key, x, {"error": str(ex)[:120]}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for i, (e, key, x, ser) in enumerate(pool.map(one, jobs)):
                self.legs[(e,) + key] = (x, ser)
                if i and i % 200 == 0:
                    self.log(f"  {i}/{len(jobs)} contracts ({self.c.calls} network calls, {self.c.cache_hits} from cache)")

    # ------------------------------------------------------------------ replay
    def _slip(self, px: float) -> float:
        return max(self.cfg.slip_min, self.cfg.slip_pct * px)

    def simulate(self, plans: list[dict]) -> list[Trade]:
        cfg, out = self.cfg, []
        for n, p in enumerate(plans):
            ce, pe = self.legs.get((p["expiry"], p["strike"], "CE")), self.legs.get((p["expiry"], p["strike"], "PE"))
            if not ce or not pe or "error" in ce[1] or "error" in pe[1]:
                continue
            cb, pb = ce[1].get(p["day"]) or {}, pe[1].get(p["day"]) or {}
            nb = self.n1[p["day"]]
            times, t = [], p["entry"]
            while t <= cfg.square_off:
                times.append(t)
                t = _minute(t, 1)
            path, last_c, last_p, imputed_at, verified_entry = [], None, None, set(), True
            for t in times:
                c_, p_ = _price_at(cb, t), _price_at(pb, t)
                if c_ is None:
                    imputed_at.add(t)
                if p_ is None:
                    imputed_at.add(t)
                last_c, last_p = c_ if c_ is not None else last_c, p_ if p_ is not None else last_p
                if last_c is None or last_p is None:
                    if t == times[0]:
                        verified_entry = False
                    continue
                path.append((t, last_c, last_p, _price_at(nb, t)))
            if len(path) < 2 or path[0][0] != times[0] or not verified_entry:
                continue                                              # no real price at the entry minute: not a trade we could have made
            lot = int(ce[0].get("lot_size") or 65)
            c0, p0 = path[0][1] + self._slip(path[0][1]), path[0][2] + self._slip(path[0][2])
            e0 = c0 + p0
            vals = [(t, c - self._slip(c), q - self._slip(q), s) for t, c, q, s in path]
            for tgt in cfg.targets:
                for stp in cfg.stops:
                    ex, why, lo, hi = vals[-1], "SQUARE_OFF_1520", 0.0, 0.0
                    for v in vals[1:]:
                        r = (max(v[1], 0.05) + max(v[2], 0.05)) / e0 - 1
                        lo, hi = min(lo, r), max(hi, r)
                        if r >= tgt:
                            ex, why = v, f"TARGET_{int(tgt * 100)}PCT"
                            break
                        if r <= -stp:
                            ex, why = v, f"STOP_{int(stp * 100)}PCT"
                            break
                    c1, p1 = max(ex[1], 0.05), max(ex[2], 0.05)
                    x1 = c1 + p1
                    buy, sell = e0 * lot, x1 * lot
                    ch = charges(buy, sell)["total"]
                    gross = (x1 - e0) * lot
                    slip = (self._slip(path[0][1]) + self._slip(path[0][2]) + self._slip(c1) + self._slip(p1)) * lot
                    net = gross - ch
                    status = "VERIFIED_HISTORICAL" if ex[0] not in imputed_at else "PARTIAL"
                    cid = f"{p['policy']}|{p['entry']}|TP{int(tgt * 100)}|SL{int(stp * 100)}"
                    out.append(Trade(trade_id=f"STRD_{p['day']:%Y%m%d}_{p['entry'].replace(':', '')}_{p['policy']}_{int(tgt * 100)}_{int(stp * 100)}", config_id=cid,
                                     strike_policy=p["policy"], target_pct=tgt, stop_pct=stp, expiry_date=p["expiry"], dte=p["dte"], mode=p["mode"],
                                     sigma_iv=round(p["vix"] / 100, 4), sigma_eff=round(p["se"], 4),
                                     news_scores=f"IN_Bank={p['scores']['S_IN_Bank']};US={p['scores']['S_US_Macro']};Asia={p['scores']['S_Asia_FX']};news=0",
                                     spot_at_entry=round(p["spot"], 2), strike=p["strike"], ce_symbol=ce[0].get("trading_symbol", ""), pe_symbol=pe[0].get("trading_symbol", ""),
                                     entry_window=p["entry"], entry_timestamp_ist=f"{p['day']}T{p['entry']}:00+05:30", ce_entry_price=round(c0, 2), pe_entry_price=round(p0, 2),
                                     combined_entry_premium=round(e0, 2), lot_size=lot, capital_deployed=round(buy, 2), exit_timestamp_ist=f"{p['day']}T{ex[0]}:00+05:30",
                                     exit_reason=why, spot_at_exit=round(ex[3] or 0, 2), ce_exit_price=round(c1, 2), pe_exit_price=round(p1, 2), combined_exit_premium=round(x1, 2),
                                     gross_pnl_inr=round(gross, 2), slippage_inr=round(slip, 2), est_charges_inr=round(ch, 2), net_pnl_inr=round(net, 2),
                                     return_pct=round(net / buy * 100, 2), mae_pct=round(lo * 100, 2), mfe_pct=round(hi * 100, 2), data_source_status=status, morning_move_pct=p["mo"]))
        return out

    def run(self) -> list[Trade]:
        self.load()
        plans = self.plan()
        self.log(f"{len(plans)} entry decisions planned")
        self.fetch_contracts(plans)
        trades = self.simulate(plans)
        self.log(f"{len(trades)} simulated trades ({self.c.calls} network calls, {self.c.cache_hits} from cache)")
        return trades


def as_rows(trades: list[Trade]) -> list[dict]:
    return [asdict(t) for t in trades]
