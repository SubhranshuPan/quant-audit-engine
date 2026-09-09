# Calibration study

Unit tests prove the estimator matches `statsmodels`. They cannot tell you
whether the resulting inference is **calibrated** — whether a nominal 95%
interval actually contains the truth 95% of the time. That needs simulation
against a data-generating process where the answer is known.

```bash
python -m research.calibration_study --reps 4000
```

Results land in `calibration_results.json`. The run is seeded and reproducible.

## Design

Costs follow a stationary VAR(1) with scalar persistence φ, and the audited
policy reacts linearly to the cost shock:

$$c_t = \bar c + u_t, \qquad u_t = \phi\,u_{t-1} + \varepsilon_t, \qquad
\hat\pi_t = \pi_{\text{center}} - M u_t$$

Two closed forms make this usable as a benchmark:

$$C_{\text{pop}} = -\operatorname{tr}(M\,\Sigma_c), \qquad
\text{Regret}_{\text{pop}} = C_{\text{pop}} + \bar c^\top(\pi_{\text{center}} - \pi^*)$$

$\Sigma_\varepsilon$ is derived *from* a fixed $\Sigma_c$, so $C_{\text{pop}}$
stays constant as φ varies — the target does not move when persistence changes,
which is what isolates the effect of serial correlation. Both closed forms are
checked against a 400,000-step simulation.

Because $\hat\pi_t$ depends on $u_t$ contemporaneously, $\xi_t$ is a quadratic
form in an autocorrelated process, so the regret trajectory is genuinely
serially correlated — the setting Newey–West exists for.

Everything is imported from `app.core.math_engine`. A result here is a statement
about the deployed estimator, not a re-implementation of it.

## Findings

4,000 replications per cell; Monte Carlo error on a 95% coverage estimate is
±0.7%.

### 1. The interval on Ĉ_T is well calibrated

| T | φ = 0 | φ = 0.5 |
|---:|---:|---:|
| 60 | 90.8% | 83.8% |
| 250 | 93.9% | 90.8% |
| 1000 | 94.9% | 94.2% |
| 2000 | 94.6% | 94.6% |

Coverage converges to nominal from below, and persistence slows the
convergence rather than breaking it. This is the expected finite-sample
behaviour of a HAC estimator, and it validates the implementation end to end.

**Practical reading:** below ~250 observations the interval is optimistic. A
"PASSED" on 60 days is weak evidence, and the engine's 30-day floor is a
minimum for producing a number, not a threshold for trusting one.

### 2. HAC earns its keep, and the gap widens with persistence

Coverage of $C_{\text{pop}}$ at T = 500:

| φ | HAC | iid |
|---:|---:|---:|
| 0.0 | 94.6% | 95.2% |
| 0.4 | 93.0% | 89.0% |
| 0.6 | 91.3% | 81.2% |
| 0.8 | 87.1% | **63.1%** |

At φ = 0 an iid error is marginally *better* — HAC estimates more parameters and
pays for it in finite samples. By φ = 0.8 the iid interval covers 63% of the
time while claiming 95%. Using HAC costs almost nothing when it is unnecessary
and saves the conclusion when it is not.

### 3. Reusing the ξ interval for total regret is badly wrong

The audit reports `total_regret = Ĉ_T + c̄ᵀb`. If the interval built for Ĉ_T is
re-centred on that sum — the natural mistake, and the one an earlier code review
flagged — coverage collapses:

| φ | Coverage of Regret_pop | True SD ÷ reported SE |
|---:|---:|---:|
| 0.0 | 68.6% | 1.93× |
| 0.4 | 58.4% | 2.43× |
| 0.8 | **47.4%** | **3.05×** |

A nominal 95% interval delivering 47% is worse than a coin flip. The cause is
that `c̄` is itself a noisy sample mean, and ξ's standard error knows nothing
about that noise. The review estimated the understatement at 1.66×; measured
across the grid it is 1.9×–3.1×.

### 4. There is an exact fix, and it needs no new machinery

The two-term decomposition collapses into a single mean:

$$\hat C_T + \bar c^\top(\bar\pi - \pi^*)
= \frac1T\sum_t c_t^\top \hat\pi_t - \bar c^\top\bar\pi + \bar c^\top\bar\pi - \bar c^\top\pi^*
= \frac1T\sum_t c_t^\top(\hat\pi_t - \pi^*)$$

So **total regret is itself a sample mean** — of $r_t = c_t^\top(\hat\pi_t - \pi^*)$.
Its correct HAC standard error is the same Newey–West estimator applied to that
series. No delta method, no new estimator, one line of code.

Coverage of $\text{Regret}_{\text{pop}}$ using $r_t$'s own error:

| T | φ = 0 | φ = 0.5 |
|---:|---:|---:|
| 60 | 92.7% | 85.6% |
| 250 | 93.8% | 91.3% |
| 1000 | 94.7% | 93.9% |
| 2000 | 94.5% | 93.5% |

Restored to nominal, tracking the Ĉ_T interval's own calibration curve.

## What shipped as a result

`regret_series()` is now in `app/core/math_engine.py`, and the API returns
`regret_standard_error`, `regret_ci_lower` and `regret_ci_upper` alongside the
Ĉ_T interval. The verdict still keys off Ĉ_T, as specified — the second interval
is additional, not a replacement.

On real market data (AAPL/MSFT/SPY/QQQ, 2022–2024) the regret standard error is
**2.5×** the covariance standard error, in line with what the simulation
predicts at moderate persistence.

## Limitations

- One DGP. The policy is linear in the cost shock and the shocks are Gaussian;
  fat tails, regime changes and nonlinear policies are untested.
- Scalar persistence. Real cost series have richer cross-asset dynamics than
  a single φ applied uniformly.
- π* is fixed at the population argmin. The API derives π* from the *sample*
  mean, which adds a further source of noise this study does not measure — so
  the real-world coverage of the shipped endpoint is, if anything, slightly
  worse than reported here.
- Bandwidth is the engine's default $h = \lfloor T^{1/3}\rfloor$ throughout.
  Data-driven bandwidth selection (Andrews, Newey–West automatic) is not
  compared.
