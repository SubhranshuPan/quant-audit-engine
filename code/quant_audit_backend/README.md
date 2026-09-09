# Quant AI Investment Strategy Audit Engine

Milestone 4 — production FastAPI backend for the audit methodology in
*Evaluating AI Investment Strategies* (Aldridge, 2026).

Given a strategy's realised weight trajectory and the market it traded, the
engine answers one SR 11-7 question: **is this strategy's regret larger than
sampling noise?** It estimates the trajectory covariance (Eq. 27), corrects it
for policy bias (Theorem 8.2), and puts a Newey-West HAC confidence interval
around the result so the verdict survives serially-correlated daily data.

Milestones 1–3 (`../src/`) established and verified the same mathematics on
simulated data; this service carries it over to real market data behind an API.

## The mathematics

| Quantity | Formula | Code |
|---|---|---|
| Trajectory covariance | $\hat{C}_T = \frac{1}{T}\sum_t (c_t-\bar c)^\top(\hat\pi_t-\bar\pi)$ | `calculate_trajectory_covariance` |
| Policy bias correction | $\bar c^\top b,\; b = \bar\pi - \pi^*$ | `calculate_policy_bias_correction` |
| Total regret | $\text{Regret}^{(T)} = \hat C_T + \bar c^\top b$ | `run_audit` |
| Bandwidth | $h = \lfloor T^{1/3} \rfloor$ | `default_bandwidth` |
| Long-run variance | $\hat\sigma^2 = \hat\gamma_0 + 2\sum_{\ell=1}^{h}\left(1-\tfrac{\ell}{h+1}\right)\hat\gamma_\ell$ | `calculate_newey_west_hac` |
| Standard error | $\text{SE} = \sqrt{\hat\sigma^2 / T}$ | `calculate_newey_west_hac` |
| 95% interval | $\hat C_T \pm 1.96\,\text{SE}$ | `confidence_interval` |

Costs are negative log-returns, $c_t = -\log(P_t/P_{t-1})$, so a profitable day
is a negative cost and positive regret means underperformance.

### Verdicts

| Interval | `is_significant` | Verdict |
|---|---|---|
| entirely $> 0$ | `true` | FLAGGED: Statistically Significant Regret / Model Underperformance Detected |
| contains $0$ | `false` | PASSED: Regret Statistically Indistinguishable from Zero Noise |
| entirely $< 0$ | `true` | PASSED: Model Outperforms Benchmark |
| zero width at a non-zero point | `false` | INCONCLUSIVE: Degenerate Zero-Variance Trajectory / Regret Cannot Be Certified |

The fourth row covers a trajectory whose HAC long-run variance is exactly zero.
Declaring a non-zero point estimate "significant" off an interval of width zero
would be a confident verdict backed by no evidence, so the engine declines
instead. An interval that is exactly $[0,0]$ is different — a buy-and-hold
policy has $\xi_t \equiv 0$, and "regret is exactly zero" is a real answer, so
that case still PASSES.

## Quickstart

```bash
cd quant_audit_backend
python -m venv venv
venv\Scripts\activate          # Windows;  source venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt   # requirements.txt alone is runtime-only
uvicorn app.main:app --reload
```

Interactive docs at <http://127.0.0.1:8000/docs>.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/audit/run` | Audit a built-in strategy on live yfinance data |
| `POST` | `/api/v1/audit/upload` | Audit a portfolio you ran yourself, from CSV |
| `GET` | `/api/v1/audit/strategies` | Describe the built-in strategies |
| `GET` | `/api/v1/market/summary` | Return/volatility summary of a data window |
| `GET` | `/health` | Liveness probe |

### `POST /api/v1/audit/run`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/audit/run \
  -H "Content-Type: application/json" \
  -d '{"tickers":["AAPL","MSFT","SPY","GLD"],
       "start_date":"2022-01-01","end_date":"2024-01-01",
       "strategy_type":"momentum","rolling_window":20}'
```

```json
{
  "trajectory_covariance": 0.000414,
  "bias_correction": 0.000164,
  "total_regret": 0.000578,
  "standard_error": 0.000212,
  "regret_standard_error": 0.000353,
  "regret_ci_lower": -0.000307,
  "regret_ci_upper": 0.001075,
  "p_value": 0.112,
  "data_source": "live",
  "ci_lower": -0.000002,
  "ci_upper": 0.000829,
  "is_significant": false,
  "audit_verdict": "PASSED: Regret Statistically Indistinguishable from Zero Noise",
  "observations": 480,
  "assets": ["AAPL", "MSFT", "SPY", "GLD"],
  "hac_lags": 7,
  "mean_weights": [0.256, 0.263, 0.198, 0.283],
  "benchmark_weights": [0.0, 1.0, 0.0, 0.0],
  "daily_series": [
    {"date": "2022-02-01", "xi": 0.0013, "cumulative_regret": 0.0013,
     "portfolio_cost": -0.0042, "weights": [0.26, 0.27, 0.19, 0.28]}
  ]
}
```

Built-in strategies, all long-only and rebalanced daily on a `rolling_window`
lookback:

- **momentum** — softmax of the cross-sectionally standardised trailing return.
- **reversion** — the same, with the sign flipped.
- **min_variance** — inverse-variance weights (minimum-variance ignoring correlations).

Every signal is lagged one day, so no weight is built from the return it is
about to earn. Without that shift the audit would measure look-ahead bias
rather than skill.

### `POST /api/v1/audit/upload`

Upload a CSV with a date column and a matched pair of columns per asset:

```csv
date,return_AAPL,return_MSFT,weight_AAPL,weight_MSFT
2024-01-02,0.0121,-0.0043,0.6,0.4
2024-01-03,-0.0075,0.0090,0.55,0.45
```

Accepted prefixes: `return_` / `ret_` / `r_` and `weight_` / `w_` / `pi_`
(case-insensitive). Requirements, all enforced with a 422:

- at least 2 assets — a one-asset panel has weights identically 1.0, so the trajectory is structurally zero and the audit would be vacuous;
- every asset has both a return and a weight column, and no two columns resolve to the same asset (`return_AAA` and `r_AAA` together are rejected, not silently deduplicated);
- weights sum to 1 on every row;
- dates all parse and are unique;
- at least `QUANT_MIN_OBSERVATIONS` (30) complete rows.

Individual weights may be negative: long/short portfolios are legitimate to
audit, and Eq. 27 does not require the simplex. Only the built-in strategies on
`/audit/run` are long-only, by construction.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/audit/upload -F "file=@portfolio.csv"
```

`daily_series[].weights` is the policy's allocation on that day, ordered like
`assets` — the trajectory Eq. 27 was computed on, which the dashboard plots
directly. `p_value` is the two-sided normal tail for H0: Ĉ_T = 0, and is `null`
when the standard error is 0, where no test is defined.

### Two intervals, two estimands

`ci_lower`/`ci_upper` and the verdict describe **Ĉ_T**. `total_regret` carries its
own pair, `regret_ci_lower`/`regret_ci_upper`, derived from the identity

```
Ĉ_T + c̄ᵀ(π̄ − π*)  ==  mean_t [ c_tᵀ(π̂_t − π*) ]
```

Total regret is itself a sample mean, so the same Newey–West estimator applied to
`r_t = c_tᵀ(π̂_t − π*)` gives its correct standard error. Reusing Ĉ_T's error
instead understates the spread by 1.9×–3.1× and drops a nominal 95% interval to
as low as **47% coverage** — measured in [`research/`](research/README.md).

`data_source` reports where the prices came from: `live`, `snapshot` (the bundled
dataset, used when the provider is unreachable) or `uploaded`.

## Deploying

Three things to set before this is public:

```bash
QUANT_CORS_ORIGINS='["https://your-frontend.example.com"]'   # never ship the wildcard
QUANT_RATE_LIMIT_PER_MINUTE=30                                # the API triggers outbound downloads
QUANT_USE_SNAPSHOT_FALLBACK=true                              # yfinance is often blocked from datacenter IPs
```

`Dockerfile` and `render.yaml` are ready to use. The rate limiter keeps its counter
in process, so the container runs a single worker on purpose — replicas would each
allow the full limit. Move the counter to Redis before scaling out.

The snapshot covers AAPL, MSFT, SPY, QQQ, GLD and TLT from 2019 to 2024. When it is
used, the response says so and the dashboard shows a notice: presenting frozen
prices as current ones would be worse than failing.

## Benchmark choice

$\pi^*$ is the **oracle** allocation: 100% in the asset with the lowest mean
cost over the audited window. This matches the paper and is deliberately
harsh — it is chosen with hindsight, so mild positive regret is the norm. The
verdict is about whether that regret exceeds sampling noise, not whether it
exists. `run_audit` accepts an explicit `pi_star` if you want a different
benchmark (equal-weight, a stated policy target) from Python.

## Testing

`requirements-dev.txt` adds statsmodels and scipy, which exist purely as
independent references for the tests: statsmodels for the HAC estimator, scipy
for the normal tail. The shipped app imports neither, so the runtime image does
not carry them.

```bash
pytest              # 105 offline tests
pytest -m live      # additionally hits the real yfinance API
```

`tests/test_math_engine.py` is the acceptance suite: it asserts the
from-scratch Newey-West estimator equals
`statsmodels.OLS(xi, ones).fit(cov_type="HAC", cov_kwds={"maxlags": h}).bse`
to within `1e-10`, across five bandwidths and five AR(1) processes. The `1/T`
normalisation (rather than a small-sample correction) is what makes that
equality exact — changing it will break the match.

## Layout

```
app/
  main.py                     FastAPI app, CORS, DataError -> 422 handlers
  core/config.py              Settings (env prefix QUANT_)
  core/math_engine.py         Eq. 27, Theorem 8.2, Newey-West HAC  [pure NumPy]
  schemas/audit.py            Pydantic request/response contracts
  services/data_service.py    yfinance download, log returns, CSV parsing
  services/audit_service.py   Strategies + audit orchestration
  api/v1/router.py            Router aggregation
  api/v1/endpoints/           audit.py, market.py
  core/rate_limit.py          Per-client sliding-window limiter
  data/snapshot_prices.csv    Bundled fallback prices
research/
  calibration_study.py        Monte Carlo coverage study of the estimator
  README.md                   Findings
tests/
  test_math_engine.py         Math vs statsmodels
  test_api.py                 Endpoints (network stubbed)
  test_rate_limit.py          Throttling behaviour
```

`math_engine.py` performs no I/O — every function is a deterministic function
of its arguments, which is why the audit mathematics is testable offline.

## Configuration

Environment variables use the `QUANT_` prefix (or a `.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `QUANT_CORS_ORIGINS` | `["*"]` | Narrow this before exposing the service |
| `QUANT_MAX_TICKERS` | `50` | Cap on assets per request |
| `QUANT_MAX_UPLOAD_BYTES` | `10485760` | Upload size limit |
| `QUANT_RATE_LIMIT_PER_MINUTE` | `30` | Per-client request cap; `/health` and docs are exempt |
| `QUANT_PRICE_CACHE_SECONDS` | `3600` | How long a downloaded price panel is reused |
| `QUANT_USE_SNAPSHOT_FALLBACK` | `true` | Serve bundled prices when the provider fails |
| `QUANT_MIN_OBSERVATIONS` | `30` | Minimum *audited* days, enforced after the rolling window is consumed and costs/weights are aligned — not just on the raw download |

## Limitations

- The oracle benchmark is in-sample by construction; it is a regret yardstick, not an investable strategy.
- The HAC interval and the verdict cover $\hat C_T$ only. `total_regret` is a point estimate: the bias term is a deterministic function of the sample means and carries no interval, so the reported interval is narrower than the true sampling spread of the sum. Do not read `is_significant` as certifying `total_regret`.
- Non-finite inputs are rejected rather than propagated. A NaN would otherwise pass silently through the verdict logic — `nan > 0` and `nan < 0` are both false — and be certified PASSED.
- `min_variance` ignores cross-asset correlations, which is the diagonal approximation, not the full Markowitz solution.
- yfinance is an unofficial API with no availability guarantee; `/audit/run` is only as reliable as it is.
- CORS ships wide open for local use. Credentials are automatically disabled while `cors_origins` contains `*`, because Starlette echoes the caller's `Origin` instead of sending `*` when credentials are allowed — the combination would grant any site credentialed access. Set a real origin list to re-enable them.
