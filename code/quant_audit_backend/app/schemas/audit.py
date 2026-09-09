"""Request/response contracts for the audit API."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings

StrategyType = Literal["momentum", "reversion", "min_variance"]


class AuditRequest(BaseModel):
    """Audit a built-in strategy against real market data.

    Dates are typed as `date` rather than `str` so Pydantic rejects malformed
    input at the boundary instead of letting yfinance fail opaquely later.
    """

    tickers: Annotated[list[str], Field(min_length=2, max_length=settings.max_tickers)]
    start_date: date
    end_date: date
    strategy_type: StrategyType = "momentum"
    rolling_window: Annotated[int, Field(ge=2, le=252)] = 20

    @model_validator(mode="after")
    def _validate(self) -> "AuditRequest":
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be strictly before end_date")

        # Uppercase and de-duplicate while preserving order: a repeated ticker
        # would otherwise be double-counted in the portfolio weights.
        seen: dict[str, None] = {}
        for raw in self.tickers:
            symbol = raw.strip().upper()
            if not symbol:
                raise ValueError("tickers must not contain blank entries")
            seen[symbol] = None
        if len(seen) < 2:
            raise ValueError("at least 2 distinct tickers are required to form a portfolio")
        self.tickers = list(seen)
        return self


class DailyPoint(BaseModel):
    """One row of the audited trajectory, for charting in the front end."""

    date: str
    xi: float = Field(description="Daily covariance-regret contribution (Eq. 27 summand)")
    cumulative_regret: float = Field(description="Running mean of xi up to and including this day")
    portfolio_cost: float = Field(description="c_t . pi_hat_t, the realised cost of the day")
    weights: list[float] = Field(
        description="pi_hat_t, the policy's allocation on this day, ordered like `assets`"
    )


class AuditResponse(BaseModel):
    """Full SR 11-7 audit result for one strategy."""

    trajectory_covariance: float = Field(description="C_hat_T, Eq. 27")
    bias_correction: float = Field(
        description=(
            "c_bar^T b, where b = pi_bar - pi*. A deterministic function of the sample "
            "means; it carries no standard error of its own and is NOT covered by the "
            "interval below."
        )
    )
    total_regret: float = Field(
        description=(
            "Theorem 8.2: trajectory_covariance + bias_correction. Carries its own interval "
            "(regret_ci_lower/upper) -- the ci_lower/ci_upper pair and the verdict describe "
            "trajectory_covariance alone and must not be read as certifying this sum."
        )
    )
    regret_standard_error: float = Field(
        description=(
            "HAC standard error of total_regret, from the per-period series "
            "r_t = c_t . (pi_hat_t - pi*) whose mean is total_regret. Substantially larger "
            "than standard_error, because it also carries the sampling noise in c_bar."
        )
    )
    regret_ci_lower: float = Field(description="95% HAC lower bound on total_regret")
    regret_ci_upper: float = Field(description="95% HAC upper bound on total_regret")
    standard_error: float = Field(description="Newey-West HAC standard error of C_hat_T")
    p_value: float | None = Field(
        description=(
            "Two-sided p-value for H0: C_hat_T = 0, under a normal approximation. "
            "None when the standard error is 0, where no test is defined."
        )
    )
    ci_lower: float = Field(description="95% HAC lower bound on C_hat_T")
    ci_upper: float = Field(description="95% HAC upper bound on C_hat_T")
    is_significant: bool = Field(
        description="True when the interval on C_hat_T excludes zero in either direction"
    )
    audit_verdict: str = Field(
        description="SR 11-7 verdict: FLAGGED, PASSED, or INCONCLUSIVE for a degenerate trajectory"
    )

    data_source: str = Field(
        default="uploaded",
        description=(
            "Where the prices came from: 'live' from the market data provider, 'snapshot' "
            "from the bundled dataset when the provider was unreachable, or 'uploaded' for "
            "a user-supplied CSV. A snapshot result is frozen data, not current prices."
        ),
    )
    observations: int = Field(description="T, the number of audited trading days")
    assets: list[str]
    hac_lags: int = Field(description="Bartlett bandwidth h = floor(T ** 1/3)")
    mean_weights: list[float] = Field(description="pi_bar, the policy's average allocation")
    benchmark_weights: list[float] = Field(description="pi*, the benchmark allocation")
    daily_series: list[DailyPoint]


class MarketDataResponse(BaseModel):
    """Sanity-check payload for /market: what the audit actually downloaded."""

    data_source: str
    tickers: list[str]
    start_date: str
    end_date: str
    observations: int
    mean_daily_return: dict[str, float]
    annualised_volatility: dict[str, float]
