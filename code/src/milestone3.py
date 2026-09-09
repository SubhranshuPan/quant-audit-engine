"""
Milestone 3 -- Is the audited covariance-regret statistically significant,
or could it just be noise from a finite (T = 1000 day) sample?

Reuses Milestone 1/2's building blocks from script.py (simulate_market,
build_benchmark, run_policy, daily_covariance_regret) to build the real
per-day covariance-regret trajectory xi_t, then estimates the Newey-West
(HAC) standard error of its mean with bartlett_hac_variance() and checks
that scratch estimate against statsmodels' own OLS-HAC estimator.
"""

import numpy as np
# pyrefly: ignore [missing-import]
import statsmodels.api as sm

from script import (
    simulate_market,
    build_benchmark,
    run_policy,
    daily_covariance_regret,
    bartlett_hac_variance,
)


def run_milestone3_hac_audit():
    # ---- same market/policy setup as Milestone 1, for a real xi_t trajectory ----
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

    np.random.seed(42)  # reset so Milestone 3 is reproducible on its own
    c, c_bar_sample = simulate_market(T, c_bar_true, Sigma_c)
    pi_star = build_benchmark(c_bar_true)
    pi_hat, pi_bar_sample = run_policy(c, c_bar_sample, pi_star, M)

    # ----------------------------------------
    # 1. Daily covariance-regret trajectory (xi)
    # ----------------------------------------
    xi = daily_covariance_regret(c, pi_hat, c_bar_sample, pi_bar_sample)
    xi_bar = np.mean(xi)  # mean per-period covariance -- same number Milestone 1 calls raw_covariance

    # ----------------------------------------
    # 2. Bandwidth lag determination (h)
    # ----------------------------------------
    # Pro-tip: 1000**(1/3) in Python floating point evaluates to 9.999999999999998!
    # We round it to avoid np.floor bringing it down to 9 instead of 10.
    h = int(np.floor(np.round(T ** (1 / 3), 6)))  # h = 10 lags

    # ----------------------------------------
    # 3 & 4. Autocovariance (gamma) + Newey-West HAC estimate (scratch)
    # ----------------------------------------
    gamma, var_lrv, standard_error = bartlett_hac_variance(xi, h)

    # ----------------------------------------
    # 5. Verify against statsmodels
    # ----------------------------------------
    # Regress the daily regrets (xi) on a constant (column of ones) and
    # request Heteroskedasticity and Autocorrelation Consistent (HAC) covariance.
    X = np.ones(T)
    results = sm.OLS(xi, X).fit(cov_type='HAC', cov_kwds={'maxlags': h})
    se_statsmodel = results.bse[0]
    var_lrv_statsmodel = se_statsmodel ** 2 * T  # invert SE = sqrt(Var/T) to compare variances too

    # ----------------------------------------
    # 6. 95% confidence interval + significance verdict
    # ----------------------------------------
    z = 1.96  # 95% two-sided normal critical value
    ci_low, ci_high = xi_bar - z * standard_error, xi_bar + z * standard_error
    zero_excluded = ci_low > 0 or ci_high < 0

    print(f"Trading Days (T):           {T}")
    print(f"HAC Bandwidth Lags (h):     {h}\n")
    print(f"Mean Per-Period Covariance: {xi_bar:.12f}\n")
    print("--- HAC Variance Verification ---")
    print(f"Scratch LRV Variance:        {var_lrv:.12f}")
    print(f"Statsmodels LRV Variance:    {var_lrv_statsmodel:.12f}")
    print(f"Variance Discrepancy:        {abs(var_lrv - var_lrv_statsmodel):.12f}\n")
    print("--- Standard Error (SE) Verification ---")
    print(f"Scratch SE of Mean:          {standard_error:.12f}")
    print(f"Statsmodels SE of Mean:      {se_statsmodel:.12f}")
    print(f"SE Discrepancy:              {abs(standard_error - se_statsmodel):.12f}\n")
    print("--- 95% Confidence Interval for Mean Per-Period Covariance ---")
    print(f"Interval:                    [{ci_low:.6f}, {ci_high:.6f}]")
    print(f"Is 0 excluded?               {zero_excluded}")

    assert np.isclose(standard_error, se_statsmodel, atol=1e-9), \
        "Scratch HAC standard error does not match statsmodels!"
    print("\nScratch HAC estimator matches statsmodels: PASS")


if __name__ == "__main__":
    run_milestone3_hac_audit()
