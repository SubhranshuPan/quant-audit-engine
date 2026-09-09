"""Calibration study for the regret audit estimator.

Asks one question the unit tests cannot: when the engine reports a 95%
confidence interval, does that interval actually contain the truth 95% of the
time? Unit tests prove the estimator matches statsmodels; only simulation
against a known data-generating process shows whether the resulting inference
is calibrated.

Design
------
Costs follow a stationary VAR(1) with scalar persistence phi:

    c_t = c_bar + u_t,      u_t = phi * u_{t-1} + eps_t,   eps ~ N(0, Sigma_eps)

and the audited policy reacts linearly to the cost shock, as in Milestones 1-3:

    pi_hat_t = pi_center - M u_t

Two things make this tractable as a calibration benchmark:

1. The population trajectory covariance has a closed form. Since
   pi_hat_t - E[pi_hat] = -M u_t and c_t - E[c] = u_t,

       C_pop = E[u_t^T (-M u_t)] = -E[tr(M u_t u_t^T)] = -tr(M Sigma_c)

   where Sigma_c = Sigma_eps / (1 - phi^2) is the stationary cost covariance.
   Sigma_eps is derived FROM a fixed Sigma_c, so C_pop is held constant as phi
   varies - the target does not move when persistence changes, which is what
   isolates the effect of serial correlation.

2. Population total regret is also closed-form:

       Regret_pop = C_pop + c_bar^T (pi_center - pi*)

Because pi_hat_t depends on u_t contemporaneously, xi_t is a quadratic form in
an autocorrelated process, so the regret trajectory is genuinely serially
correlated - the setting Newey-West exists for.

The estimator under study is the one the API ships. Everything is imported from
app.core.math_engine rather than reimplemented, so a calibration result here is
a statement about the deployed code.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from app.core.math_engine import (
    calculate_newey_west_hac,
    confidence_interval,
    daily_covariance_regret,
    default_bandwidth,
    regret_series,
)

# The Milestone 1-3 market, kept so results are comparable to the earlier work.
C_BAR = np.array([0.1, 0.2, 0.3])
SIGMA_C = np.array([
    [0.05, 0.01, 0.02],
    [0.01, 0.04, 0.015],
    [0.02, 0.015, 0.06],
])
M = np.array([
    [-0.5, 0.25, 0.25],
    [0.25, -0.5, 0.25],
    [0.25, 0.25, -0.5],
])
PI_CENTER = np.array([0.7, 0.2, 0.1])  # deliberately off-benchmark, so bias != 0
PI_STAR = np.eye(3)[int(np.argmin(C_BAR))]  # oracle on the TRUE mean, so it is fixed

C_POP = float(-np.trace(M @ SIGMA_C))
REGRET_POP = C_POP + float(C_BAR @ (PI_CENTER - PI_STAR))


def simulate(n: int, phi: float, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """One audited trajectory of length `n` with AR(1) persistence `phi`.

    The first shock is drawn from the stationary distribution rather than zero,
    so there is no burn-in bias to discard.
    """
    sigma_eps = SIGMA_C * (1.0 - phi**2)
    chol_eps = np.linalg.cholesky(sigma_eps) if phi else np.linalg.cholesky(SIGMA_C)
    chol_stat = np.linalg.cholesky(SIGMA_C)

    u = np.empty((n, 3))
    u[0] = chol_stat @ rng.standard_normal(3)
    shocks = rng.standard_normal((n - 1, 3)) @ chol_eps.T
    for t in range(1, n):
        u[t] = phi * u[t - 1] + shocks[t - 1]

    c = C_BAR + u
    pi_hat = PI_CENTER - u @ M.T
    return c, pi_hat


@dataclass
class Cell:
    """One grid point: an (n, phi) pair evaluated over `reps` replications."""

    n: int
    phi: float
    reps: int
    # Coverage of C_pop by the interval the engine publishes.
    cov_xi_hac: float
    # Coverage of C_pop using an iid standard error - what HAC is protecting against.
    cov_xi_iid: float
    # Coverage of Regret_pop by that same interval, recentred on total regret.
    # This is the mis-application the code review flagged.
    cov_total_by_xi_se: float
    # Coverage of Regret_pop by the HAC error of the regret series itself.
    cov_total_by_r_se: float
    # Mean interval half-widths, to separate "calibrated" from "merely wide".
    mean_se_xi: float
    mean_se_r: float
    # True sampling deviation of each point estimate, for the ratio the review computed.
    sd_chat: float
    sd_regret: float
    bandwidth: int


def run_cell(n: int, phi: float, reps: int, seed: int) -> Cell:
    rng = np.random.default_rng(seed)
    hits = {"xi_hac": 0, "xi_iid": 0, "total_by_xi": 0, "total_by_r": 0}
    se_xi, se_r, chats, regrets = [], [], [], []

    for _ in range(reps):
        c, pi_hat = simulate(n, phi, rng)

        xi = daily_covariance_regret(c, pi_hat)
        c_hat = float(xi.mean())
        hac_xi = calculate_newey_west_hac(xi)
        iid_xi = calculate_newey_west_hac(xi, max_lags=0)

        r = regret_series(c, pi_hat, PI_STAR)
        regret_hat = float(r.mean())
        hac_r = calculate_newey_west_hac(r)

        lo, hi = confidence_interval(c_hat, hac_xi.standard_error)
        hits["xi_hac"] += lo <= C_POP <= hi

        lo, hi = confidence_interval(c_hat, iid_xi.standard_error)
        hits["xi_iid"] += lo <= C_POP <= hi

        # The mis-application: right standard error, wrong estimand.
        lo, hi = confidence_interval(regret_hat, hac_xi.standard_error)
        hits["total_by_xi"] += lo <= REGRET_POP <= hi

        lo, hi = confidence_interval(regret_hat, hac_r.standard_error)
        hits["total_by_r"] += lo <= REGRET_POP <= hi

        se_xi.append(hac_xi.standard_error)
        se_r.append(hac_r.standard_error)
        chats.append(c_hat)
        regrets.append(regret_hat)

    return Cell(
        n=n,
        phi=phi,
        reps=reps,
        cov_xi_hac=hits["xi_hac"] / reps,
        cov_xi_iid=hits["xi_iid"] / reps,
        cov_total_by_xi_se=hits["total_by_xi"] / reps,
        cov_total_by_r_se=hits["total_by_r"] / reps,
        mean_se_xi=float(np.mean(se_xi)),
        mean_se_r=float(np.mean(se_r)),
        sd_chat=float(np.std(chats, ddof=1)),
        sd_regret=float(np.std(regrets, ddof=1)),
        bandwidth=default_bandwidth(n),
    )


def monte_carlo_error(coverage: float, reps: int) -> float:
    """Standard error of a coverage estimate, so readers can tell a real
    miscalibration from simulation noise."""
    return float(np.sqrt(coverage * (1 - coverage) / reps))


def run_study(reps: int, seed: int) -> dict:
    # Length grid at two persistences: independent, and the moderate positive
    # autocorrelation that daily financial data actually shows.
    lengths = [60, 125, 250, 500, 1000, 2000]
    # Persistence grid at a fixed length, to isolate the effect of phi.
    phis = [0.0, 0.2, 0.4, 0.6, 0.8]

    by_length = [
        run_cell(n, phi, reps, seed + i * 97 + j)
        for j, phi in enumerate([0.0, 0.5])
        for i, n in enumerate(lengths)
    ]
    by_phi = [run_cell(500, phi, reps, seed + 5000 + i) for i, phi in enumerate(phis)]

    return {
        "truth": {"C_pop": C_POP, "Regret_pop": REGRET_POP},
        "reps": reps,
        "seed": seed,
        "by_length": [asdict(c) for c in by_length],
        "by_phi": [asdict(c) for c in by_phi],
    }


def _fmt(cells: list[dict], reps: int, header: str, key: str) -> str:
    lines = [header, ""]
    lines.append(
        f"{key:>6} {'T':>5} {'h':>3} | {'C_T HAC':>9} {'C_T iid':>9} | "
        f"{'Reg (xi SE)':>12} {'Reg (r SE)':>11} | {'SE ratio':>9}"
    )
    lines.append("-" * 76)
    for c in cells:
        label = f"{c['phi']:.1f}" if key == "phi" else f"{c['n']}"
        ratio = c["sd_regret"] / c["mean_se_xi"]
        lines.append(
            f"{label:>6} {c['n']:>5} {c['bandwidth']:>3} | "
            f"{c['cov_xi_hac']:>8.1%} {c['cov_xi_iid']:>9.1%} | "
            f"{c['cov_total_by_xi_se']:>12.1%} {c['cov_total_by_r_se']:>11.1%} | "
            f"{ratio:>8.2f}x"
        )
    lines.append("")
    lines.append(f"Monte Carlo error on a 95% coverage estimate: +/- {1.96 * monte_carlo_error(0.95, reps):.1%}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=2000, help="replications per grid cell")
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "calibration_results.json")
    args = parser.parse_args()

    print(f"Population truth:  C_pop = {C_POP:.6f}   Regret_pop = {REGRET_POP:.6f}")
    print(f"Running {args.reps} replications per cell...\n")

    results = run_study(args.reps, args.seed)
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")

    print(_fmt(
        [c for c in results["by_length"] if c["phi"] == 0.0], args.reps,
        "Coverage of a nominal 95% interval - independent costs (phi = 0)", "T",
    ))
    print()
    print(_fmt(
        [c for c in results["by_length"] if c["phi"] == 0.5], args.reps,
        "Coverage of a nominal 95% interval - persistent costs (phi = 0.5)", "T",
    ))
    print()
    print(_fmt(results["by_phi"], args.reps,
               "Coverage against persistence, at T = 500", "phi"))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
