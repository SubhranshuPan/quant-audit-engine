# Quant AI Investment Strategy Audit Engine

Auditing black-box investment strategies for statistically significant regret,
implementing *Evaluating AI Investment Strategies* (Aldridge, 2026).

You are handed a strategy you cannot open — a vendor model, a neural network,
someone else's book. It lost to its benchmark last year. Two questions follow,
and they are different questions:

1. **Was the underperformance real, or was it luck?** A year is ~250 observations.
   Plenty of strategies lose to a benchmark over 250 days purely by chance.
2. **If it was real, what broke?** Wrong assets on average, or the right assets at
   the wrong moments? Different failures, different fixes.

This engine answers both from the outside, using only the weights the strategy
held and what the assets cost. It never needs the model.

## The decomposition

Total regret splits into two independent channels (Theorem 8.2), reported
separately:

| Channel | Quantity | Asks |
|---|---|---|
| **Timing** | $\hat{C}_T = \frac{1}{T}\sum_t (c_t-\bar c)^\top(\hat\pi_t-\bar\pi)$ | On the days an asset got expensive, were you holding more of it than usual? |
| **Allocation** | $\bar c^\top b,\; b = \bar\pi - \pi^*$ | Ignoring day-to-day moves, did holding this mix cost money? |

Measured over 985 trading days on AAPL/MSFT/SPY/GLD, the three built-in
strategies split exactly along that seam — momentum and mean reversion come out
near mirror images in the timing channel, which is what two opposite signals on
the same data should do:

| Strategy | Timing | Allocation | Total |
|---|---:|---:|---:|
| Momentum | +2.79 bp | +2.95 bp | +5.74 bp |
| Mean reversion | −3.09 bp | +3.62 bp | +0.53 bp |
| Minimum variance | −1.60 bp | +4.83 bp | +3.24 bp |

Because daily regret contributions are serially correlated, inference uses a
**Newey–West HAC** estimator with bandwidth $h = \lfloor T^{1/3}\rfloor$. The
from-scratch implementation matches `statsmodels` to **1e-10** across five
bandwidths and five AR(1) processes.

## A calibration study, and what it found

Unit tests prove the estimator computes the right formula. They cannot prove the
resulting inference is honest. [`research/`](code/quant_audit_backend/research/README.md)
runs 4,000 Monte Carlo replications per cell against a data-generating process
with a closed-form truth:

- The interval on $\hat C_T$ is **well calibrated** — 94.9% coverage at T=1000.
- **HAC earns its keep asymmetrically**: at φ=0 an iid error is marginally
  better; at φ=0.8 it covers 63.1% while claiming 95%.
- Re-using that interval for *total regret* — the natural mistake — collapses to
  **47.4% coverage** under persistence, understating the spread by 1.9×–3.1×.
- There is an **exact fix requiring no new machinery**: the decomposition
  collapses to a single mean, $\hat C_T + \bar c^\top(\bar\pi-\pi^*) =
  \frac1T\sum_t c_t^\top(\hat\pi_t-\pi^*)$, so the same estimator applied to that
  series gives the correct standard error. Coverage returns to nominal.

That correction ships: the API returns `regret_standard_error` with its own
interval alongside the $\hat C_T$ one.

## Layout

```
code/
  src/                    Milestones 1-3: the identities validated on simulated data
  quant_audit_backend/    FastAPI service, the estimator, and the calibration study
  quant_audit_dashboard/  React + Tailwind audit console
```

- [Backend README](code/quant_audit_backend/README.md) — API, mathematics, deployment
- [Dashboard README](code/quant_audit_dashboard/README.md) — design system, chart palette validation
- [Calibration study](code/quant_audit_backend/research/README.md) — method, findings, limitations

## Running it

```bash
# API
cd code/quant_audit_backend
python -m venv venv && venv/Scripts/activate     # source venv/bin/activate on Unix
pip install -r requirements.txt
uvicorn app.main:app --port 8000                 # docs at /docs

# Dashboard
cd code/quant_audit_dashboard
npm install && npm run dev                       # http://localhost:5173
```

```bash
pytest                                   # 105 tests
pytest -m live                           # additionally hits the real market data API
python -m research.calibration_study     # reproduces the study
```

## Engineering notes

- **105 tests.** The load-bearing ones assert the scratch Newey–West equals
  `statsmodels` to 1e-10, and that the Theorem 8.2 identity holds to 1e-15 for
  arbitrary panels.
- **Reviewed in three passes**, 30 findings. Four of them returned a confident
  `PASSED` verdict on data the engine should have refused — a NaN long-run
  variance (`nan < 0` is false, so it slipped the guard), a two-day sample after
  the rolling window ate the data, a single-asset panel with a structurally zero
  trajectory, and a repeated-date file that reported half the rows it audited.
  None failed a test; the suite was green throughout.
- **Deployment-hardened**: per-client rate limiting, CORS locked to a configured
  origin, cached prices, and a bundled snapshot so the demo survives the market
  data provider blocking datacenter IPs. Snapshot results are always labelled —
  presenting frozen prices as live in a compliance tool would be worse than
  failing.

## Limitations

The benchmark $\pi^*$ is an in-sample oracle — 100% in the asset that turned out
cheapest — so mild positive regret against it is the normal state of any sane
diversified strategy. The tool reports statistical significance, not sign. The
built-in strategies are a calibration harness, not investment recommendations;
the real use is auditing your own weights via CSV upload. Transaction costs,
slippage and capacity are not modelled.
