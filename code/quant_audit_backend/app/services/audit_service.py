"""Orchestration: market data + strategy weights -> a full SR 11-7 audit result."""

import numpy as np
import pandas as pd

from app.core.math_engine import (
    audit_verdict,
    calculate_newey_west_hac,
    calculate_policy_bias_correction,
    confidence_interval,
    daily_covariance_regret,
    regret_series,
    two_sided_p_value,
)
from app.core.config import settings
from app.schemas.audit import AuditRequest, AuditResponse, DailyPoint, StrategyType
from app.services.data_service import DataError, load_cost_panel


def _softmax(scores: np.ndarray) -> np.ndarray:
    """Row-wise softmax of cross-sectionally standardised scores.

    Standardising first makes the mapping scale-free: raw daily returns are
    ~1e-3, so a plain softmax of them would collapse to equal weights and the
    strategy would have no trajectory to audit. Subtracting the row max is the
    usual overflow guard.
    """
    std = scores.std(axis=1, keepdims=True)
    z = scores / np.where(std > 0, std, 1.0)  # a flat cross-section stays flat
    exp = np.exp(z - z.max(axis=1, keepdims=True))
    return exp / exp.sum(axis=1, keepdims=True)


def build_weights(costs: pd.DataFrame, strategy: StrategyType, window: int) -> pd.DataFrame:
    """Long-only weights for a built-in strategy, one row per trading day.

    Every signal is shifted one day. Without that shift the weights for day t
    would be built from day t's own realised cost, and the audit would measure
    look-ahead bias rather than strategy skill -- Eq. 27 would report a large
    fake negative regret for any strategy at all.
    """
    if len(costs) <= window:
        raise DataError(
            f"rolling_window={window} needs more than {window} trading days, got {len(costs)}"
        )

    returns = -costs  # r_t = -c_t

    if strategy == "min_variance":
        # Inverse-variance weights: the closed-form minimum-variance portfolio
        # when cross-asset correlations are ignored. Naturally non-negative.
        signal = returns.rolling(window).var().shift(1)
        raw = 1.0 / signal.replace(0.0, np.nan)
        weights = raw.div(raw.sum(axis=1), axis=0)
    else:
        trend = returns.rolling(window).mean().shift(1)
        # Momentum buys recent winners; reversion buys recent losers.
        scores = trend if strategy == "momentum" else -trend
        valid = scores.dropna(how="any")
        weights = pd.DataFrame(
            _softmax(valid.to_numpy()), index=valid.index, columns=valid.columns
        )

    weights = weights.dropna(how="any")
    if weights.empty:
        raise DataError(f"strategy '{strategy}' produced no usable weights for this sample")

    return weights


def build_benchmark(c_bar: np.ndarray) -> np.ndarray:
    """pi*: the oracle allocation, 100% in the lowest average-cost asset.

    This is the paper's benchmark and it is deliberately harsh -- it is chosen
    with hindsight over the audited window, so a positive regret is the norm
    rather than a scandal. The verdict answers whether that regret is larger
    than sampling noise, not whether it exists.
    """
    pi_star = np.zeros(len(c_bar))
    pi_star[int(np.argmin(c_bar))] = 1.0
    return pi_star


def run_audit(
    costs: pd.DataFrame,
    weights: pd.DataFrame,
    pi_star: np.ndarray | None = None,
    data_source: str = "uploaded",
) -> AuditResponse:
    """The shared audit core, used by both the strategy and the upload endpoint.

    Applies Eq. 27, the Theorem 8.2 bias correction and the Newey-West HAC
    interval to an already-aligned (costs, weights) panel.
    """
    # Align on the intersection: strategy weights start `window` days late, and
    # uploaded files may cover a different span than their returns.
    common = costs.index.intersection(weights.index)
    costs, weights = costs.loc[common], weights.loc[common, costs.columns]

    # Count rows AFTER .loc, not len(common): an Index intersection is unique,
    # but .loc on a non-unique index returns every matching row, so a file with
    # repeated dates would report a T smaller than the sample actually audited.
    observations = len(costs)

    # The real sample-size gate. load_cost_panel checks the raw panel, but a
    # rolling window then consumes `window` rows -- without this, a 32-day panel
    # with rolling_window=30 audits T=2 and certifies it with SE ~1e-20.
    if observations < settings.min_observations:
        raise DataError(
            f"only {observations} audited days after aligning costs and weights; at least "
            f"{settings.min_observations} are needed for a trustworthy HAC standard error"
        )

    c, pi_hat = costs.to_numpy(dtype=float), weights.to_numpy(dtype=float)
    c_bar, pi_bar = c.mean(axis=0), pi_hat.mean(axis=0)

    if pi_star is None:
        pi_star = build_benchmark(c_bar)

    xi = daily_covariance_regret(c, pi_hat)
    covariance = float(xi.mean())  # Eq. 27 is exactly the mean of the trajectory
    bias = calculate_policy_bias_correction(c_bar, pi_bar, pi_star)
    hac = calculate_newey_west_hac(xi)

    # The interval is placed around the covariance term only: the bias term is
    # a deterministic function of the sample means, so the HAC standard error
    # describes the sampling noise in C_hat_T, not in the bias.
    ci_lower, ci_upper = confidence_interval(covariance, hac.standard_error)
    is_significant, verdict = audit_verdict(ci_lower, ci_upper)

    # Total regret is itself a sample mean -- of r_t = c_t . (pi_hat_t - pi*) -- so it
    # gets its own HAC error rather than borrowing xi's. Borrowing understates the
    # spread by 1.9x-3.1x; see research/calibration_study.py.
    r = regret_series(c, pi_hat, pi_star)
    hac_regret = calculate_newey_west_hac(r)
    regret_lo, regret_hi = confidence_interval(float(r.mean()), hac_regret.standard_error)

    portfolio_cost = np.sum(c * pi_hat, axis=1)
    cumulative = np.cumsum(xi) / np.arange(1, len(xi) + 1)

    return AuditResponse(
        trajectory_covariance=covariance,
        bias_correction=bias,
        total_regret=covariance + bias,
        regret_standard_error=hac_regret.standard_error,
        regret_ci_lower=regret_lo,
        regret_ci_upper=regret_hi,
        standard_error=hac.standard_error,
        p_value=two_sided_p_value(covariance, hac.standard_error),
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        is_significant=is_significant,
        audit_verdict=verdict,
        data_source=data_source,
        observations=observations,
        assets=list(costs.columns),
        hac_lags=hac.lags,
        mean_weights=pi_bar.tolist(),
        benchmark_weights=np.asarray(pi_star, dtype=float).tolist(),
        daily_series=[
            DailyPoint(
                date=str(idx.date() if hasattr(idx, "date") else idx),
                xi=float(xi[i]),
                cumulative_regret=float(cumulative[i]),
                portfolio_cost=float(portfolio_cost[i]),
                weights=pi_hat[i].tolist(),
            )
            for i, idx in enumerate(costs.index)
        ],
    )


def audit_strategy(request: AuditRequest) -> AuditResponse:
    """End-to-end audit of one built-in strategy on real market data."""
    costs, source = load_cost_panel(request.tickers, request.start_date, request.end_date)
    weights = build_weights(costs, request.strategy_type, request.rolling_window)
    return run_audit(costs, weights, data_source=source)
