"""Dependency-free backtester. All prices represent adjusted daily closes."""
from dataclasses import dataclass
from datetime import date, timedelta
import csv
import math
import random
import statistics as stats


@dataclass(frozen=True)
class Bar:
    date: str
    a: float
    b: float


@dataclass(frozen=True)
class Config:
    train: int = 252
    test: int = 63
    entry: float = 1.5
    exit: float = 0.25
    stop: float = 4.0
    max_hold: int = 20
    cost_bps: float = 5.0
    borrow_bps_year: float = 100.0

    def __post_init__(self):
        if self.train < 20 or self.test < 2 or self.max_hold < 1:
            raise ValueError("train >= 20, test >= 2, max_hold >= 1 required")
        if not 0 <= self.exit < self.entry < self.stop:
            raise ValueError("require 0 <= exit < entry < stop")
        if not all(math.isfinite(x) and x >= 0 for x in
                   (self.cost_bps, self.borrow_bps_year)):
            raise ValueError("costs must be finite and non-negative")


def validate(bars):
    previous = None
    for bar in bars:
        current = date.fromisoformat(bar.date)
        if previous is not None and current <= previous:
            raise ValueError("dates must be unique and strictly increasing")
        if not all(math.isfinite(p) and p > 0 for p in (bar.a, bar.b)):
            raise ValueError("prices must be positive and finite")
        previous = current


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not {"date", "a", "b"} <= set(reader.fieldnames or []):
            raise ValueError("CSV requires date,a,b columns")
        bars = [Bar(r["date"], float(r["a"]), float(r["b"])) for r in reader]
    validate(bars)
    return bars


def synthetic(n=1512, seed=7):
    """Deliberately favorable stationary spread, with a stressed middle regime.

    This is a software fixture, not empirical evidence of alpha.
    """
    rng = random.Random(seed)
    day = date(2018, 1, 1)
    log_b, spread = math.log(100), 0.0
    bars = []
    while len(bars) < n:
        if day.weekday() < 5:
            i = len(bars)
            phi, sigma = (0.98, 0.014) if 700 <= i < 950 else (0.88, 0.008)
            log_b += 0.00015 + rng.gauss(0, 0.009)
            spread = phi * spread + rng.gauss(0, sigma)
            bars.append(Bar(day.isoformat(), math.exp(0.4 + 0.9 * log_b + spread), math.exp(log_b)))
        day += timedelta(days=1)
    return bars


def fit(bars):
    """OLS log(A) = intercept + beta * log(B), training observations only.

    Residual variance is descriptive; this is NOT a cointegration test.
    """
    x, y = [math.log(b.b) for b in bars], [math.log(b.a) for b in bars]
    mx, my = stats.mean(x), stats.mean(y)
    denominator = sum((v - mx) ** 2 for v in x)
    if denominator < 1e-12:
        return None
    beta = sum((u - mx) * (v - my) for u, v in zip(x, y)) / denominator
    intercept = my - beta * mx
    residuals = [v - intercept - beta * u for u, v in zip(x, y)]
    scale = stats.stdev(residuals)
    if scale < 1e-8 or not 0.1 <= beta <= 3:
        return None
    return intercept, beta, scale


def backtest(bars, cfg=Config()):
    """Signal at close t-1; execute at close t; earn t->t+1 returns.

    Each fold starts and ends flat. Frozen training normalization and hedge.
    Daily target weights have gross exposure <= 1. Cash earns zero.
    Transaction costs include rebalancing drift, entry, exit and liquidation.
    """
    validate(bars)
    if len(bars) < cfg.train + 2:
        raise ValueError("insufficient observations for formation and trading")
    rows, folds = [], []
    equity = 1.0
    for start in range(cfg.train, len(bars), cfg.test):
        end = min(start + cfg.test, len(bars))
        model = fit(bars[start - cfg.train:start])
        fold = len(folds)
        folds.append({"fold": fold, "train_start": bars[start-cfg.train].date,
                      "train_end": bars[start-1].date, "test_start": bars[start].date,
                      "test_end": bars[end-1].date, "model": model})
        held_a = held_b = 0.0
        side, age = 0, 0
        for t in range(start, end):
            ra = bars[t].a / bars[t-1].a - 1
            rb = bars[t].b / bars[t-1].b - 1
            gross = held_a * ra + held_b * rb
            borrow = (max(-held_a, 0) + max(-held_b, 0)) * cfg.borrow_bps_year / 10000 / 252
            growth = 1 + gross - borrow
            if growth <= 0:
                raise ValueError("portfolio insolvent")
            drift_a, drift_b = held_a * (1+ra) / growth, held_b * (1+rb) / growth
            z = None
            if model:
                intercept, beta, scale = model
                prior = bars[t-1]
                z = (math.log(prior.a) - intercept - beta * math.log(prior.b)) / scale
                if side:
                    age += 1
                    if abs(z) <= cfg.exit or abs(z) >= cfg.stop or side*z >= 0 or age >= cfg.max_hold:
                        side, age = 0, 0
                elif cfg.entry <= abs(z) < cfg.stop:
                    side, age = (-1 if z > 0 else 1), 0
                target_a = side / (1+beta)
                target_b = -side * beta / (1+beta)
            else:
                target_a = target_b = 0.0
            if t == end-1:
                target_a = target_b = 0.0
                side = 0
            # Targets are fractions of pre-cost equity. After paying costs,
            # rescale held weights so next day's accounting remains exact.
            # Reserve a worst-case fee buffer to keep post-cost gross <= 1.
            fee_rate = cfg.cost_bps / 10000
            buffer = max(0.0, 1 - fee_rate * (1 + abs(drift_a) + abs(drift_b)))
            target_a *= buffer
            target_b *= buffer
            turnover = abs(target_a-drift_a) + abs(target_b-drift_b)
            fee = turnover * fee_rate
            if fee >= 1:
                raise ValueError("transaction costs exhaust portfolio equity")
            net = growth * (1-fee) - 1
            equity *= 1 + net
            held_a, held_b = target_a/(1-fee), target_b/(1-fee)
            rows.append({"date": bars[t].date, "fold": fold, "z_signal": z,
                         "weight_a": held_a, "weight_b": held_b, "gross_return": gross,
                         "net_return": net, "turnover": turnover,
                         "cost_return": growth*fee + borrow, "equity": equity})
    return rows, folds


def summary(rows):
    returns = [r["net_return"] for r in rows]
    vol = stats.stdev(returns) if len(returns) > 1 else 0.0
    peak, drawdown = 1.0, 0.0
    for r in rows:
        peak = max(peak, r["equity"])
        drawdown = min(drawdown, r["equity"]/peak-1)
    return {"observations": len(rows), "total_return": rows[-1]["equity"]-1,
            "annualized_return": rows[-1]["equity"]**(252/len(rows))-1,
            "annualized_volatility": vol*math.sqrt(252),
            "sharpe_zero_rf": stats.mean(returns)/vol*math.sqrt(252) if vol else 0.0,
            "max_drawdown": drawdown,
            "annualized_turnover": sum(r["turnover"] for r in rows)*252/len(rows)}


def bootstrap_mean_ci(rows, samples=1000, block=20, seed=11):
    """Circular moving-block bootstrap CI for annualized arithmetic mean.

    Conditional on this realized strategy path; no refitting/model uncertainty.
    """
    rng = random.Random(seed)
    values = [r["net_return"] for r in rows]
    means = []
    for _ in range(samples):
        draw = []
        while len(draw) < len(values):
            start = rng.randrange(len(values))
            draw.extend(values[(start+j) % len(values)] for j in range(block))
        means.append(stats.mean(draw[:len(values)]) * 252)
    means.sort()
    return [means[int(samples*0.025)], means[min(samples-1, int(samples*0.975))]]
