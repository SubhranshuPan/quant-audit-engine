"""Core audit mathematics: trajectory covariance, policy bias, Newey-West HAC.

Ported from the verified Milestone 1-3 research scripts (code/src/script.py),
whose Newey-West estimator was checked against statsmodels' OLS HAC to machine
precision. Pure NumPy, no I/O -- every function here is a deterministic
function of its arguments so the whole audit is unit-testable without network.

Notation follows Aldridge (2026):
    c_t      (d,)   vector of asset costs on day t (negative log-returns)
    pi_hat_t (d,)   portfolio weights the audited policy actually held on day t
    pi_star  (d,)   benchmark/optimal allocation
"""

import math
from typing import NamedTuple

import numpy as np

class AuditInputError(ValueError):
    """Raised when the *data* is unfit to audit (too short, non-finite, degenerate).

    A subclass of ValueError so existing callers keep working, but a distinct
    type so the API can map bad data to 422 without also swallowing genuine
    internal defects -- a blanket `except ValueError` would turn a real
    alignment bug into a "your request was invalid" response and hide it from
    error monitoring.
    """


Z_95 = 1.959963984540054  # scipy.stats.norm.ppf(0.975); hard-coded to keep this module dependency-free


def daily_covariance_regret(c: np.ndarray, pi_hat: np.ndarray) -> np.ndarray:
    """Per-day summand of Eq. 27, xi_t = (c_t - c_bar) . (pi_hat_t - pi_bar).

    Returns the full (T,) trajectory. Its mean is the trajectory covariance
    (Eq. 27); its autocorrelation is what the HAC estimator below corrects for.
    """
    c, pi_hat = np.asarray(c, dtype=float), np.asarray(pi_hat, dtype=float)
    if c.shape != pi_hat.shape:
        raise ValueError(f"c {c.shape} and pi_hat {pi_hat.shape} must have the same shape")
    if c.ndim != 2 or c.shape[0] < 2:
        raise AuditInputError("c and pi_hat must be 2-D (T, d) arrays with T >= 2")

    if not (np.isfinite(c).all() and np.isfinite(pi_hat).all()):
        raise AuditInputError("c and pi_hat must be finite; drop or fill missing days first")

    dev_c = c - c.mean(axis=0)
    dev_pi = pi_hat - pi_hat.mean(axis=0)
    return np.sum(dev_c * dev_pi, axis=1)


def calculate_trajectory_covariance(c: np.ndarray, pi_hat: np.ndarray) -> float:
    """Trajectory covariance estimator, Eq. 27:

        C_hat_T = (1/T) * sum_t (c_t - c_bar)^T (pi_hat_t - pi_bar)
    """
    return float(daily_covariance_regret(c, pi_hat).mean())


def regret_series(c: np.ndarray, pi_hat: np.ndarray, pi_star: np.ndarray) -> np.ndarray:
    """Per-period total regret, r_t = c_t . (pi_hat_t - pi*).

    Its sample mean equals `C_hat_T + c_bar^T (pi_bar - pi*)` exactly -- the
    covariance identity collapses Theorem 8.2's two terms into a single mean::

        (1/T)sum (c_t-c_bar)(pi_hat_t-pi_bar) + c_bar(pi_bar-pi*)
          = (1/T)sum c_t.pi_hat_t - c_bar.pi_bar + c_bar.pi_bar - c_bar.pi*
          = (1/T)sum c_t.(pi_hat_t - pi*)

    That matters for inference, not just algebra. Because total regret IS a
    sample mean, its correct HAC standard error is this series' Newey-West
    error. Reusing xi's error instead understates the spread by 1.9x-3.1x and
    drops a nominal 95% interval to as low as 47% coverage -- see
    research/calibration_study.py.
    """
    c, pi_hat = np.asarray(c, dtype=float), np.asarray(pi_hat, dtype=float)
    pi_star = np.asarray(pi_star, dtype=float).ravel()
    if c.shape != pi_hat.shape:
        raise ValueError(f"c {c.shape} and pi_hat {pi_hat.shape} must have the same shape")
    if c.ndim != 2 or c.shape[1] != pi_star.size:
        raise ValueError("pi_star length must match the number of assets")
    return np.sum(c * (pi_hat - pi_star), axis=1)


def calculate_policy_bias_correction(
    c_bar: np.ndarray, pi_bar: np.ndarray, pi_star: np.ndarray
) -> float:
    """Bias term of Theorem 8.2: c_bar^T b, where b = pi_bar - pi_star.

    Zero exactly when the policy's average allocation equals the benchmark.
    """
    c_bar, pi_bar, pi_star = (np.asarray(x, dtype=float).ravel() for x in (c_bar, pi_bar, pi_star))
    if not (c_bar.shape == pi_bar.shape == pi_star.shape):
        raise ValueError("c_bar, pi_bar and pi_star must all have the same length")
    return float(c_bar @ (pi_bar - pi_star))


def default_bandwidth(n: int) -> int:
    """Newey-West bandwidth h = int(floor(T ** (1/3))), at least 1.

    The round() guards a floating-point trap: 1000 ** (1/3) evaluates to
    9.999999999999998, which floor() would silently truncate to 9 instead of 10.
    """
    return max(1, int(np.floor(np.round(n ** (1 / 3), 6))))


class HACResult(NamedTuple):
    standard_error: float
    long_run_variance: float
    lags: int
    autocovariances: np.ndarray


def calculate_newey_west_hac(xi: np.ndarray, max_lags: int | None = None) -> HACResult:
    """Newey-West (Bartlett-kernel) HAC standard error of the mean of `xi`.

        gamma_l = (1/T) * sum_{t=l}^{T-1} (xi_t - xi_bar)(xi_{t-l} - xi_bar)
        LRV     = gamma_0 + 2 * sum_{l=1}^{h} (1 - l/(h+1)) * gamma_l
        SE      = sqrt(LRV / T)

    Matches statsmodels.OLS(xi, ones).fit(cov_type='HAC',
    cov_kwds={'maxlags': h}).bse to machine precision -- see
    tests/test_math_engine.py. The 1/T normalisation (rather than 1/(T-1) or a
    small-sample correction) is what makes that equality exact.
    """
    xi = np.asarray(xi, dtype=float).ravel()
    n = xi.size
    if n < 2:
        raise AuditInputError("xi must contain at least 2 observations")
    # NaN must be rejected here, not downstream: `nan < 0` is False, so a NaN
    # long-run variance would slip past the guard below, sail through sqrt, and
    # reach audit_verdict -- where `nan > 0` and `nan < 0` are both False, so a
    # corrupt sample would be certified "PASSED" instead of failing loudly.
    if not np.isfinite(xi).all():
        raise AuditInputError("xi contains NaN or infinite values; clean the trajectory before auditing")

    h = default_bandwidth(n) if max_lags is None else int(max_lags)
    if not 0 <= h < n:
        raise AuditInputError(f"max_lags must be in [0, {n}), got {h}")

    dev = xi - xi.mean()
    # gamma_l as a dot product of two overlapping slices; h is tiny (~10), so
    # the loop over lags is cheaper than building a lag matrix.
    gamma = np.array([dev[l:] @ dev[: n - l] / n for l in range(h + 1)])

    weights = 1.0 - np.arange(1, h + 1) / (h + 1)  # Bartlett kernel
    lrv = float(gamma[0] + 2.0 * (weights @ gamma[1:]))

    # A negative LRV is possible in finite samples; sqrt would produce NaN and
    # poison the whole audit response, so surface it as an explicit failure.
    if lrv < 0:
        raise AuditInputError(f"Newey-West long-run variance is negative ({lrv:.3e}); try fewer lags")

    return HACResult(float(np.sqrt(lrv / n)), lrv, h, gamma)


def confidence_interval(point: float, standard_error: float, z: float = Z_95) -> tuple[float, float]:
    """Two-sided normal confidence interval, 95% by default."""
    return point - z * standard_error, point + z * standard_error


def two_sided_p_value(point: float, standard_error: float) -> float | None:
    """P-value of H0: the true value is 0, under a normal approximation.

        p = 2 * (1 - Phi(|z|)) = erfc(|z| / sqrt(2)),  z = point / SE

    math.erfc is exact to double precision and keeps this module free of a
    scipy dependency. Returns None when SE is 0 -- a zero-variance trajectory
    admits no test, and 0.0 would read as overwhelming significance.
    """
    if not standard_error > 0:
        return None
    return math.erfc(abs(point / standard_error) / math.sqrt(2))


INCONCLUSIVE = (
    "INCONCLUSIVE: Degenerate Zero-Variance Trajectory / Regret Cannot Be Certified"
)


def audit_verdict(ci_lower: float, ci_upper: float) -> tuple[bool, str]:
    """SR 11-7 model-risk verdict from the confidence interval.

    Returns (is_significant, verdict). Significant means the interval excludes
    zero in either direction -- the regret is not attributable to sample noise.
    """
    # A zero-width interval means the HAC long-run variance was exactly 0, so
    # there is no sampling uncertainty to test against. Declaring a non-zero
    # point estimate "significant" off an interval of width 0 would be a
    # confident verdict backed by no evidence, so decline instead. An exact
    # zero is different: a buy-and-hold policy has xi identically 0, and
    # "regret is exactly zero" is a real answer, not a degenerate one.
    if ci_lower == ci_upper and ci_lower != 0:
        return False, INCONCLUSIVE

    if ci_lower > 0:
        return True, "FLAGGED: Statistically Significant Regret / Model Underperformance Detected"
    if ci_upper < 0:
        return True, "PASSED: Model Outperforms Benchmark"
    return False, "PASSED: Regret Statistically Indistinguishable from Zero Noise"
