"""
Milestone 1 & 2 — Auditing black-box policies against Theorem 4.2 / Eq. 27

Both milestones share the same four building blocks (Market / Benchmark /
Strategy / Audit). Milestone 2 doesn't duplicate them -- it reuses
simulate_market(), build_benchmark() and run_policy() as-is, and extends the
audit step with a bias term, since Milestone 2's policy is deliberately NOT
centered on the benchmark.

    1. simulate_market()              -> ground-truth cost trajectory (shared)
    2. build_benchmark()               -> the oracle portfolio pi*      (shared)
    3. run_policy()                    -> black-box strategy's weights  (shared,
                                           works for ANY center vector, biased or not)
    4a. audit_identity()               -> Milestone 1: True Regret == Covariance
                                           (holds only when the policy is unbiased)
    4b. audit_bias_variance_identity() -> Milestone 2: True Regret == Covariance + Bias
                                           (the general case; Milestone 1 is the
                                           special case where the bias term is 0)

Two more general-purpose audit primitives live at the bottom of Block 4,
added for Milestone 3 (see mileston3.py, which imports them from here):
daily_covariance_regret() exposes the full per-day xi_t trajectory instead
of just its mean, and bartlett_hac_variance() is a generic Newey-West HAC
long-run-variance estimator that works on any time series, not just this
regret trajectory.
"""

import numpy as np

np.random.seed(42)  # legacy RandomState API kept on purpose: switching to
# np.random.default_rng(42) gives a *different* stream, which would break
# reproducibility of numbers already verified against the paper.


# ----------------------------------------------------------------------
# Block 1: The Market (ground truth) -- shared by both milestones
# ----------------------------------------------------------------------
def simulate_market(T: int, c_bar_true: np.ndarray, Sigma_c: np.ndarray):
    """Simulate T days of realized asset costs c_t ~ N(c_bar_true, Sigma_c).

    Returns
    -------
    c : (T, d) array   realized daily costs
    c_bar_sample : (d,) array   sample mean the auditor actually observes
    """
    c = np.random.multivariate_normal(c_bar_true, Sigma_c, size=T)
    c_bar_sample = np.mean(c, axis=0)
    return c, c_bar_sample


# ----------------------------------------------------------------------
# Block 2: The Benchmark (oracle) -- shared by both milestones
# ----------------------------------------------------------------------
def build_benchmark(c_bar_true: np.ndarray) -> np.ndarray:
    """pi* puts 100% weight on the asset with the lowest true expected cost."""
    pi_star = np.zeros_like(c_bar_true)
    pi_star[np.argmin(c_bar_true)] = 1.0
    return pi_star


# ----------------------------------------------------------------------
# Block 3: The Strategy (black-box policy under audit) -- shared
# ----------------------------------------------------------------------
def run_policy(c: np.ndarray, c_bar_sample: np.ndarray, pi_center: np.ndarray, M: np.ndarray):
    """Vectorized version of:
        for t in range(T):
            dev = c[t] - c_bar_sample
            pi_hat[t] = pi_center - M.dot(dev)

    `pi_center` is whatever the policy shifts its daily weights around.
    Milestone 1 passes pi_star (the benchmark itself) -> an UNBIASED policy.
    Milestone 2 passes pi_biased (a deliberately different vector) -> a
    BIASED policy. The function doesn't care which -- it's the same math
    either way, which is exactly why it's reusable across both milestones.

    M.dot(dev) applied row-by-row is the same as (dev_all @ M.T) applied to
    the whole (T, d) matrix at once, because for each row t:
        (dev_all @ M.T)[t, i] = sum_j dev_all[t, j] * M[i, j] = M.dot(dev_all[t])[i]
    """
    assert np.isclose(pi_center.sum(), 1.0), "pi_center must sum to 1 (it's a portfolio weight vector)"
    assert np.allclose(M.sum(axis=0), 0.0), "columns of M must sum to 0 to keep weights on the simplex"

    dev_c = c - c_bar_sample                  # (T, d) broadcast, replaces per-row subtraction
    pi_hat = pi_center - dev_c @ M.T           # (T, d), replaces the for-loop

    # Invariant check: because M's columns sum to 0 and pi_center sums to 1,
    # every pi_hat[t] must still sum to 1. Free correctness test, regardless
    # of whether pi_center is pi_star (unbiased) or something else (biased).
    assert np.allclose(pi_hat.sum(axis=1), 1.0), "policy weights must sum to 1 every day"

    pi_bar_sample = np.mean(pi_hat, axis=0)
    return pi_hat, pi_bar_sample


# ----------------------------------------------------------------------
# Block 4: The Audit -- shared core + two milestone-specific wrappers
# ----------------------------------------------------------------------
def daily_covariance_regret(c, pi_hat, c_bar_sample, pi_bar_sample):
    """Per-day covariance-regret trajectory (Eq. 27's summand, before averaging):
        xi_t = (c_t - c_bar_sample) . (pi_hat_t - pi_bar_sample)

    raw_covariance (in compute_regret_and_covariance below) is just xi.mean().
    Milestone 3 needs the full (T,) trajectory -- not just its mean -- to
    estimate how noisy that mean is (its HAC standard error).
    """
    dev_c = c - c_bar_sample
    dev_pi = pi_hat - pi_bar_sample
    return np.sum(dev_c * dev_pi, axis=1)


def compute_regret_and_covariance(c, pi_hat, pi_star, c_bar_sample, pi_bar_sample):
    """Shared building block for both audits (Eq. 27):
        true_regret    = E[c_t . pi_hat_t] - c_bar . pi_star
        raw_covariance = (1/T) * sum_t (c_t - c_bar).(pi_hat_t - pi_bar)

    These two are equal ONLY when the policy is unbiased (E[pi_hat] == pi_star).
    When it isn't, the gap between them is exactly the bias term Milestone 2 adds.
    """
    # True Regret: replaces np.mean([c[t].dot(pi_hat[t]) for t in range(T)])
    realized_policy_cost = np.mean(np.sum(c * pi_hat, axis=1))
    benchmark_cost = c_bar_sample.dot(pi_star)
    true_regret = realized_policy_cost - benchmark_cost

    # Trajectory covariance (Eq. 27): mean of the same per-day trajectory
    # Milestone 3 analyzes in full via daily_covariance_regret().
    raw_covariance = np.mean(daily_covariance_regret(c, pi_hat, c_bar_sample, pi_bar_sample))

    return true_regret, raw_covariance


def bartlett_hac_variance(xi: np.ndarray, h: int):
    """Newey-West long-run variance of the sample mean of a time series `xi`,
    using Bartlett kernel weights -- i.e. the classic HAC (Heteroskedasticity
    and Autocorrelation Consistent) estimator statsmodels' `cov_type='HAC'`
    also implements. Generic: works on any (T,) series, not just regret.

        gamma[l]  = (1/T) * sum_{t=l}^{T-1} (xi_t - xi_bar)(xi_{t-l} - xi_bar)   -- autocovariance at lag l
        w(l)      = 1 - l / (h + 1)                                             -- Bartlett kernel weight
        Var_LRV   = gamma[0] + 2 * sum_{l=1}^{h} w(l) * gamma[l]
        SE(mean)  = sqrt(Var_LRV / T)

    Returns (gamma, var_lrv, standard_error).
    """
    T = xi.shape[0]
    dev = xi - xi.mean()

    # gamma[l] as a dot product of the two shifted, overlapping slices of dev --
    # this replaces the inner `for t in range(l, T): sum_cov += ...` loop; the
    # outer loop over lags stays (h is tiny, e.g. 10, so it's not worth vectorizing).
    gamma = np.array([np.dot(dev[l:], dev[:T - l]) / T for l in range(h + 1)])

    lags = np.arange(1, h + 1)
    weights = 1.0 - lags / (h + 1)  # Bartlett weight DEPENDS on the lag l
    var_lrv = gamma[0] + 2.0 * np.sum(weights * gamma[1:h + 1])

    standard_error = np.sqrt(var_lrv / T)
    return gamma, var_lrv, standard_error


def audit_identity(c, pi_hat, pi_star, c_bar_sample, pi_bar_sample):
    """Milestone 1: Theorem 4.2 special case for an UNBIASED policy.
    True Regret should equal the raw trajectory covariance, exactly, in any
    finite sample -- this is an algebraic identity, not a statistical
    approximation. We check it with an assertion instead of eyeballing decimals.
    """
    true_regret, raw_covariance = compute_regret_and_covariance(
        c, pi_hat, pi_star, c_bar_sample, pi_bar_sample
    )
    assert np.isclose(true_regret, raw_covariance, atol=1e-9), "Theorem 4.2 identity failed to hold!"
    return true_regret, raw_covariance


def audit_bias_variance_identity(c, pi_hat, pi_star, c_bar_sample, pi_bar_sample):
    """Milestone 2: general bias/variance regret decomposition for a BIASED
    policy (E[pi_hat] != pi_star -- here it's centered on pi_biased instead).

        True Regret = Raw Covariance + Bias Correction

    where Bias Correction = c_bar_sample . (pi_bar_sample - pi_star): the
    average cost "charged" for the policy's average weight missing the
    benchmark by (pi_bar_sample - pi_star). Centering the policy on pi_star
    instead of a biased vector makes the bias term collapse to 0 -- which is
    exactly Milestone 1, so Milestone 1 is the zero-bias special case of this.
    """
    true_regret, raw_covariance = compute_regret_and_covariance(
        c, pi_hat, pi_star, c_bar_sample, pi_bar_sample
    )
    bias_sample = pi_bar_sample - pi_star
    bias_correction = c_bar_sample.dot(bias_sample)
    corrected_covariance_regret = raw_covariance + bias_correction

    assert np.isclose(true_regret, corrected_covariance_regret, atol=1e-9), \
        "Bias-variance regret decomposition failed to hold!"

    return true_regret, raw_covariance, bias_sample, bias_correction, corrected_covariance_regret


# ----------------------------------------------------------------------
# Milestone 1 runner: unbiased policy, True Regret == Covariance
# ----------------------------------------------------------------------
def run_milestone1_simulation():
    T, d = 1000, 3
    c_bar_true = np.array([0.1, 0.2, 0.3])
    Sigma_c = np.array([
        [0.05, 0.01, 0.02],
        [0.01, 0.04, 0.015],
        [0.02, 0.015, 0.06],
    ])
    M = np.array([
        [-0.5, 0.25, 0.25],
        [0.25, -0.5, 0.25],
        [0.25, 0.25, -0.5],
    ])

    np.random.seed(42)  # reset so Milestone 1 is reproducible on its own
    c, c_bar_sample = simulate_market(T, c_bar_true, Sigma_c)
    pi_star = build_benchmark(c_bar_true)
    pi_hat, pi_bar_sample = run_policy(c, c_bar_sample, pi_star, M)
    true_regret, raw_covariance = audit_identity(c, pi_hat, pi_star, c_bar_sample, pi_bar_sample)

    print(f"Sample Mean E[pi_hat]: {pi_bar_sample}")
    print(f"optimal Benchmark pi*: {pi_star}\n")
    print(f"--- Algebraic Identity Verification (T = {T}) ---")
    print(f"Sample-Based True Regret:           {true_regret:.12f}")
    print(f"Sample-Based Covariance:            {raw_covariance:.12f}")
    print(f"Exact Mathematical Difference:      {abs(true_regret - raw_covariance):.12f}")
    print("\nIdentity holds: PASS")


# ----------------------------------------------------------------------
# Milestone 2 runner: biased policy, True Regret == Covariance + Bias
# ----------------------------------------------------------------------
def run_milestone2_simulation():
    T, d = 1000, 3
    c_bar_true = np.array([0.1, 0.2, 0.3])
    Sigma_c = np.array([
        [0.05, 0.01, 0.02],
        [0.01, 0.04, 0.015],
        [0.02, 0.015, 0.06],
    ])
    M = np.array([
        [-0.5, 0.25, 0.25],
        [0.25, -0.5, 0.25],
        [0.25, 0.25, -0.5],
    ])
    pi_biased = np.array([0.7, 0.2, 0.1])  # deliberately NOT centered on pi_star

    np.random.seed(42)  # reset so Milestone 2 is reproducible on its own,
    # regardless of whether Milestone 1 ran first. Uses the same market draw
    # as Milestone 1 by construction (same T/c_bar_true/Sigma_c/seed), which
    # is what makes the two milestones a fair apples-to-apples comparison.
    c, c_bar_sample = simulate_market(T, c_bar_true, Sigma_c)
    pi_star = build_benchmark(c_bar_true)
    pi_hat, pi_bar_sample = run_policy(c, c_bar_sample, pi_biased, M)

    (true_regret, raw_covariance, bias_sample,
     bias_correction, corrected_covariance_regret) = audit_bias_variance_identity(
        c, pi_hat, pi_star, c_bar_sample, pi_bar_sample
    )

    print(f"Sample Mean E[pi_hat]: {pi_bar_sample}  (policy centered on {pi_biased}, not pi*)")
    print(f"optimal Benchmark pi*: {pi_star}")
    print(f"Sample Bias (E[pi_hat] - pi*): {bias_sample}\n")
    print(f"--- Bias-Variance Regret Decomposition (T = {T}) ---")
    print(f"True Regret:                        {true_regret:.12f}")
    print(f"Raw Trajectory Covariance:           {raw_covariance:.12f}")
    print(f"Bias Correction (c_bar . bias):      {bias_correction:.12f}")
    print(f"Covariance + Bias Correction:        {corrected_covariance_regret:.12f}")
    print(f"Exact Mathematical Difference:       {abs(true_regret - corrected_covariance_regret):.12f}")
    print("\nIdentity holds: PASS")


if __name__ == "__main__":
    run_milestone1_simulation()
    print("\n" + "=" * 60 + "\n")
    run_milestone2_simulation()
