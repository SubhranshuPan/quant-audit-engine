"""Verifies the from-scratch audit mathematics against independent references.

The Newey-West tests are the load-bearing ones: they assert our estimator
equals statsmodels' OLS HAC covariance to 10 decimal places, which is the
acceptance criterion for the audit engine.
"""

import numpy as np
import pytest
import statsmodels.api as sm

from app.core.math_engine import (
    audit_verdict,
    calculate_newey_west_hac,
    calculate_policy_bias_correction,
    calculate_trajectory_covariance,
    confidence_interval,
    daily_covariance_regret,
    regret_series,
    two_sided_p_value,
    default_bandwidth,
)

M_REBALANCE = np.array([[-0.5, 0.25, 0.25], [0.25, -0.5, 0.25], [0.25, 0.25, -0.5]])


def statsmodels_hac_se(xi: np.ndarray, lags: int) -> float:
    """Reference implementation: SE of the mean via OLS on a constant with HAC errors."""
    fit = sm.OLS(xi, np.ones_like(xi)).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(fit.bse[0])


@pytest.fixture
def market():
    """The exact Milestone 1-3 simulation, so results stay comparable to the research scripts."""
    rng = np.random.RandomState(42)
    c_bar_true = np.array([0.1, 0.2, 0.3])
    sigma_c = np.array([[0.05, 0.01, 0.02], [0.01, 0.04, 0.015], [0.02, 0.015, 0.06]])

    c = rng.multivariate_normal(c_bar_true, sigma_c, size=1000)
    pi_star = np.array([1.0, 0.0, 0.0])  # lowest true expected cost
    pi_hat = pi_star - (c - c.mean(axis=0)) @ M_REBALANCE.T
    return c, pi_hat, pi_star


# --------------------------------------------------------------------------
# Newey-West HAC vs statsmodels -- the acceptance criterion
# --------------------------------------------------------------------------
def test_hac_matches_statsmodels_on_regret_trajectory(market):
    c, pi_hat, _ = market
    xi = daily_covariance_regret(c, pi_hat)

    result = calculate_newey_west_hac(xi)

    assert result.lags == 10  # floor(1000 ** 1/3), guarding the 9.999999999999998 trap
    assert result.standard_error == pytest.approx(statsmodels_hac_se(xi, result.lags), abs=1e-10)


@pytest.mark.parametrize("lags", [0, 1, 3, 10, 25])
def test_hac_matches_statsmodels_across_bandwidths(market, lags):
    c, pi_hat, _ = market
    xi = daily_covariance_regret(c, pi_hat)

    se = calculate_newey_west_hac(xi, max_lags=lags).standard_error

    assert se == pytest.approx(statsmodels_hac_se(xi, lags), abs=1e-10)


@pytest.mark.parametrize("seed", range(5))
def test_hac_matches_statsmodels_on_autocorrelated_noise(seed):
    """AR(1) series: strong serial correlation is exactly what HAC exists to handle."""
    rng = np.random.default_rng(seed)
    xi = np.empty(500)
    xi[0] = rng.normal()
    for t in range(1, 500):
        xi[t] = 0.7 * xi[t - 1] + rng.normal()

    result = calculate_newey_west_hac(xi)

    assert result.standard_error == pytest.approx(statsmodels_hac_se(xi, result.lags), abs=1e-10)


def test_hac_lrv_is_consistent_with_standard_error(market):
    c, pi_hat, _ = market
    xi = daily_covariance_regret(c, pi_hat)

    result = calculate_newey_west_hac(xi)

    assert result.standard_error == pytest.approx(np.sqrt(result.long_run_variance / xi.size))
    assert result.autocovariances.shape == (result.lags + 1,)


def test_zero_lags_reduces_to_plain_variance():
    """h = 0 drops every cross-lag term, leaving gamma_0 -- the population variance."""
    xi = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

    result = calculate_newey_west_hac(xi, max_lags=0)

    assert result.long_run_variance == pytest.approx(xi.var())


def test_default_bandwidth_survives_the_cube_root_rounding_trap():
    assert default_bandwidth(1000) == 10  # 1000 ** (1/3) == 9.999999999999998 in binary floats
    assert default_bandwidth(27) == 3
    assert default_bandwidth(8) == 2
    assert default_bandwidth(2) == 1  # floor would give 1 anyway; the clamp keeps h >= 1


# --------------------------------------------------------------------------
# Eq. 27 trajectory covariance and Theorem 8.2 bias correction
# --------------------------------------------------------------------------
def test_unbiased_policy_regret_equals_trajectory_covariance(market):
    """Theorem 4.2: with pi_bar == pi*, true regret IS the covariance, exactly."""
    c, pi_hat, pi_star = market
    true_regret = np.sum(c * pi_hat, axis=1).mean() - c.mean(axis=0) @ pi_star

    covariance = calculate_trajectory_covariance(c, pi_hat)
    bias = calculate_policy_bias_correction(c.mean(axis=0), pi_hat.mean(axis=0), pi_star)

    assert bias == pytest.approx(0.0, abs=1e-12)
    assert true_regret == pytest.approx(covariance, abs=1e-12)


def test_biased_policy_regret_equals_covariance_plus_bias(market):
    """Theorem 8.2 in the general case: Regret = C_hat_T + c_bar^T b."""
    c, _, pi_star = market
    pi_hat = np.array([0.7, 0.2, 0.1]) - (c - c.mean(axis=0)) @ M_REBALANCE.T  # off-benchmark on purpose

    true_regret = np.sum(c * pi_hat, axis=1).mean() - c.mean(axis=0) @ pi_star
    covariance = calculate_trajectory_covariance(c, pi_hat)
    bias = calculate_policy_bias_correction(c.mean(axis=0), pi_hat.mean(axis=0), pi_star)

    assert abs(bias) > 1e-6
    assert true_regret == pytest.approx(covariance + bias, abs=1e-12)


def test_trajectory_covariance_matches_numpy_covariance_elementwise():
    """Eq. 27 is the sum of the per-asset population covariances between c and pi."""
    rng = np.random.default_rng(0)
    c, pi_hat = rng.normal(size=(200, 4)), rng.normal(size=(200, 4))

    expected = sum(np.cov(c[:, j], pi_hat[:, j], bias=True)[0, 1] for j in range(4))

    assert calculate_trajectory_covariance(c, pi_hat) == pytest.approx(expected)


def test_constant_weights_produce_zero_covariance():
    """A buy-and-hold policy never co-moves with cost, so Eq. 27 must vanish."""
    rng = np.random.default_rng(1)
    c = rng.normal(size=(100, 3))
    pi_hat = np.tile([0.5, 0.3, 0.2], (100, 1))

    assert calculate_trajectory_covariance(c, pi_hat) == pytest.approx(0.0, abs=1e-15)


# --------------------------------------------------------------------------
# SR 11-7 verdict logic
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ci, significant, verdict_fragment",
    [
        ((0.01, 0.05), True, "FLAGGED"),
        ((-0.05, -0.01), True, "Outperforms Benchmark"),
        ((-0.02, 0.03), False, "Indistinguishable from Zero Noise"),
        ((0.0, 0.03), False, "Indistinguishable from Zero Noise"),  # CI touching 0 is not significant
        ((-0.03, 0.0), False, "Indistinguishable from Zero Noise"),
    ],
)
def test_audit_verdict(ci, significant, verdict_fragment):
    is_significant, verdict = audit_verdict(*ci)

    assert is_significant is significant
    assert verdict_fragment in verdict


def test_confidence_interval_is_symmetric_about_the_point_estimate():
    lower, upper = confidence_interval(0.5, 0.1)

    assert (lower + upper) / 2 == pytest.approx(0.5)
    assert upper - lower == pytest.approx(2 * 1.959963984540054 * 0.1)


# --------------------------------------------------------------------------
# Input validation at the trust boundary
# --------------------------------------------------------------------------
def test_mismatched_shapes_are_rejected():
    with pytest.raises(ValueError, match="same shape"):
        daily_covariance_regret(np.zeros((10, 3)), np.zeros((10, 2)))


def test_too_few_observations_are_rejected():
    with pytest.raises(ValueError, match="at least 2"):
        calculate_newey_west_hac(np.array([1.0]))


def test_lags_beyond_sample_length_are_rejected():
    with pytest.raises(ValueError, match="max_lags"):
        calculate_newey_west_hac(np.arange(10.0), max_lags=10)


def test_mismatched_bias_vector_lengths_are_rejected():
    with pytest.raises(ValueError, match="same length"):
        calculate_policy_bias_correction(np.zeros(3), np.zeros(3), np.zeros(2))


# --------------------------------------------------------------------------
# Degenerate and non-finite input (regression tests for the code review)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_trajectory_is_rejected(bad):
    """`nan < 0` is False, so an unguarded NaN would reach audit_verdict and
    be certified PASSED. It must raise instead."""
    xi = np.array([1.0, 2.0, bad, 4.0, 5.0, 6.0, 7.0, 8.0])

    with pytest.raises(ValueError, match="NaN or infinite"):
        calculate_newey_west_hac(xi)


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_panel_is_rejected(bad):
    c = np.ones((10, 2))
    c[3, 1] = bad

    with pytest.raises(ValueError, match="finite"):
        daily_covariance_regret(c, np.ones((10, 2)))


@pytest.mark.parametrize("shape", [(10,), (2, 3, 4)])
def test_non_2d_panels_are_rejected(shape):
    with pytest.raises(ValueError, match="2-D"):
        daily_covariance_regret(np.ones(shape), np.ones(shape))


def test_single_row_panel_is_rejected():
    with pytest.raises(ValueError, match="T >= 2"):
        daily_covariance_regret(np.ones((1, 3)), np.ones((1, 3)))


def test_negative_lags_are_rejected():
    with pytest.raises(ValueError, match="max_lags"):
        calculate_newey_west_hac(np.arange(10.0), max_lags=-1)


def test_constant_nonzero_trajectory_is_not_flagged_on_a_zero_width_interval():
    """A zero-variance trajectory gives SE = 0. Declaring that "significant"
    would be a confident verdict backed by an interval of width zero."""
    xi = np.full(500, 0.02)

    hac = calculate_newey_west_hac(xi)
    ci = confidence_interval(float(xi.mean()), hac.standard_error)
    is_significant, verdict = audit_verdict(*ci)

    assert hac.standard_error == 0.0
    assert ci == (0.02, 0.02)
    assert is_significant is False
    assert verdict.startswith("INCONCLUSIVE")


def test_buy_and_hold_zero_trajectory_still_passes():
    """xi identically 0 is a real answer (regret is exactly zero), not a
    degenerate one -- it must not be downgraded to INCONCLUSIVE."""
    is_significant, verdict = audit_verdict(*confidence_interval(0.0, 0.0))

    assert is_significant is False
    assert "Indistinguishable from Zero Noise" in verdict


# --------------------------------------------------------------------------
# Two-sided p-value (added for the dashboard's report table)
# --------------------------------------------------------------------------
def test_p_value_matches_scipy():
    """erfc-based tail vs scipy's normal survival function."""
    from scipy import stats

    for point, se in [(0.5, 0.1), (-0.5, 0.1), (0.001, 0.4), (3.0, 1.0), (0.0, 1.0)]:
        expected = 2 * stats.norm.sf(abs(point / se))
        assert two_sided_p_value(point, se) == pytest.approx(expected, abs=1e-12)


def test_p_value_is_none_when_no_test_is_defined():
    """SE = 0 admits no test; 0.0 would read as overwhelming significance."""
    assert two_sided_p_value(0.5, 0.0) is None
    assert two_sided_p_value(0.5, -1.0) is None


def test_p_value_agrees_with_the_95_percent_interval():
    """p < 0.05 exactly when the 95% interval excludes zero - the verdict and
    the p-value must never disagree in the response."""
    rng = np.random.default_rng(4)
    for _ in range(200):
        point, se = rng.normal(0, 0.01), abs(rng.normal(0, 0.005)) + 1e-6
        lower, upper = confidence_interval(point, se)
        is_significant, _ = audit_verdict(lower, upper)

        assert is_significant == (two_sided_p_value(point, se) < 0.05)


# --------------------------------------------------------------------------
# The regret series and its interval (see research/calibration_study.py)
# --------------------------------------------------------------------------
def test_regret_series_mean_equals_the_theorem_82_decomposition(market):
    """The identity the corrected interval rests on: total regret is itself a
    sample mean, so it has a HAC error of its own."""
    c, pi_hat, pi_star = market

    decomposition = calculate_trajectory_covariance(c, pi_hat) + calculate_policy_bias_correction(
        c.mean(axis=0), pi_hat.mean(axis=0), pi_star
    )

    assert regret_series(c, pi_hat, pi_star).mean() == pytest.approx(decomposition, abs=1e-15)


@pytest.mark.parametrize("seed", range(5))
def test_regret_identity_holds_for_arbitrary_panels(seed):
    """Not a property of the milestone simulation - it is algebra, so it holds
    for any costs, any weights and any benchmark."""
    rng = np.random.default_rng(seed)
    c, pi_hat = rng.normal(0.001, 0.02, (300, 5)), rng.dirichlet(np.ones(5), size=300)
    pi_star = rng.dirichlet(np.ones(5))

    decomposition = calculate_trajectory_covariance(c, pi_hat) + calculate_policy_bias_correction(
        c.mean(axis=0), pi_hat.mean(axis=0), pi_star
    )

    assert regret_series(c, pi_hat, pi_star).mean() == pytest.approx(decomposition, abs=1e-15)


def test_regret_standard_error_exceeds_the_covariance_error(market):
    """It must, because it also carries the sampling noise in c_bar. Borrowing
    xi's error instead is what drops coverage to as low as 47%."""
    c, pi_hat, pi_star = market

    se_xi = calculate_newey_west_hac(daily_covariance_regret(c, pi_hat)).standard_error
    se_r = calculate_newey_west_hac(regret_series(c, pi_hat, pi_star)).standard_error

    assert se_r > se_xi


def test_regret_series_rejects_a_mismatched_benchmark():
    with pytest.raises(ValueError, match="pi_star"):
        regret_series(np.zeros((10, 3)), np.zeros((10, 3)), np.zeros(2))
