"""Effective volatility, the three volatility modes, and Black-76 option pricing with Greeks.

  sigma_eff = sigma_IV * max(0.25, 1 + w_IN * S_IN_Bank + w_US * S_US_Macro + w_Asia * S_Asia_FX)     (defaults 0.25, 0.20, 0.15)
  MODE_1_QUIET            sigma_eff < 0.13
  MODE_2_VOLATILE         0.13 <= sigma_eff < 0.18
  MODE_3_HIGH_VOLATILITY  sigma_eff >= 0.18
  T = max(trading minutes left to expiry, 1) / (252 * 375)            (NSE session 09:15-15:30 = 375 minutes; nights and weekends carry no time)
  Black-76: C = e^(-rT) [F N(d1) - K N(d2)],  P = e^(-rT) [K N(-d2) - F N(-d1)],  F = S e^((r - q) T)
  Expected daily range R_exp = spot * sigma_eff / sqrt(252)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

SESSION_MIN, YEAR_SESSIONS = 375, 252
MODES = ("MODE_1_QUIET", "MODE_2_VOLATILE", "MODE_3_HIGH_VOLATILITY")


def sigma_eff(sigma_iv: float, s_in: float = 0.0, s_us: float = 0.0, s_asia: float = 0.0, w_in: float = 0.25, w_us: float = 0.20, w_asia: float = 0.15) -> float:
    return max(1e-4, sigma_iv) * max(0.25, 1 + w_in * s_in + w_us * s_us + w_asia * s_asia)


def mode_of(se: float, lo: float = 0.13, hi: float = 0.18) -> str:
    return MODES[0] if se < lo else MODES[1] if se < hi else MODES[2]


def trading_minutes_left(now: datetime, expiry: date, trading_days: set[date] | None = None) -> float:
    """Minutes of NSE session left from `now` to 15:30 on expiry day, counting only trading days (weekdays when the calendar is unknown)."""
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    left = max(0.0, min(SESSION_MIN, (close - now).total_seconds() / 60)) if now.date() <= expiry else 0.0
    d, n = now.date() + timedelta(days=1), 0
    while d <= expiry:
        n += (d in trading_days) if trading_days else (d.weekday() < 5)
        d += timedelta(days=1)
    return left + n * SESSION_MIN


def t_years(minutes: float) -> float:
    return max(minutes, 1.0) / (YEAR_SESSIONS * SESSION_MIN)


def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


@dataclass
class Quote:
    price: float
    delta: float
    gamma: float
    theta_per_day: float
    vega_per_pt: float


def black76(spot: float, strike: float, T: float, sigma: float, kind: str, r: float = 0.065, q: float = 0.012) -> Quote:
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if T <= 0 or sigma <= 0:
        intr = max(spot - strike, 0.0) if kind == "CE" else max(strike - spot, 0.0)
        return Quote(intr, (1.0 if spot > strike else 0.0) if kind == "CE" else (-1.0 if spot < strike else 0.0), 0.0, 0.0, 0.0)
    F = spot * math.exp((r - q) * T)
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / strike) + 0.5 * sigma * sigma * T) / v
    d2 = d1 - v
    df = math.exp(-r * T)
    if kind == "CE":
        px, delta = df * (F * ncdf(d1) - strike * ncdf(d2)), df * ncdf(d1) * F / spot
    else:
        px, delta = df * (strike * ncdf(-d2) - F * ncdf(-d1)), -df * ncdf(-d1) * F / spot
    gamma = df * npdf(d1) * (F / spot) ** 2 / (spot * v)
    vega = df * F * npdf(d1) * math.sqrt(T) / 100
    theta = -(df * F * npdf(d1) * sigma / (2 * math.sqrt(T))) / YEAR_SESSIONS
    return Quote(px, delta, gamma, theta, vega)


def straddle_fair(spot: float, strike: float, T: float, sigma: float) -> float:
    return black76(spot, strike, T, sigma, "CE").price + black76(spot, strike, T, sigma, "PE").price


def expected_daily_range(spot: float, se: float) -> float:
    return spot * se / math.sqrt(YEAR_SESSIONS)
