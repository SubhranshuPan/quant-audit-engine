"""Endpoint tests.

Market data is stubbed by monkeypatching `load_cost_panel` where the endpoint
module looks it up, so the suite is deterministic and runs offline. One
network test is marked `live` and deselected by default.
"""

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app

ASSETS = ["AAA", "BBB", "CCC"]


@pytest.fixture
def client():
    return TestClient(app)


def synthetic_costs(days: int = 400, seed: int = 7) -> pd.DataFrame:
    """A deterministic cost panel shaped like real daily data."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2022-01-03", periods=days)
    values = rng.normal(loc=-0.0004, scale=0.012, size=(days, len(ASSETS)))
    return pd.DataFrame(values, index=index, columns=ASSETS)


@pytest.fixture
def offline(monkeypatch):
    """Replace the yfinance-backed loader in both endpoint call paths."""
    panel = synthetic_costs()
    loader = lambda *a, **k: (panel, "live")  # noqa: E731 - matches load_cost_panel's shape
    monkeypatch.setattr("app.services.audit_service.load_cost_panel", loader)
    monkeypatch.setattr("app.api.v1.endpoints.market.load_cost_panel", loader)
    return panel


def audit_payload(**overrides):
    return {
        "tickers": ASSETS,
        "start_date": "2022-01-01",
        "end_date": "2023-12-31",
        "strategy_type": "momentum",
        "rolling_window": 20,
    } | overrides


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------
def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_strategies_lists_all_three(client):
    body = client.get("/api/v1/audit/strategies").json()

    assert set(body) == {"momentum", "reversion", "min_variance"}


# --------------------------------------------------------------------------
# POST /audit/run
# --------------------------------------------------------------------------
@pytest.mark.parametrize("strategy", ["momentum", "reversion", "min_variance"])
def test_run_returns_a_complete_audit(client, offline, strategy):
    response = client.post("/api/v1/audit/run", json=audit_payload(strategy_type=strategy))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assets"] == ASSETS
    assert body["observations"] == len(body["daily_series"])
    assert body["hac_lags"] >= 1
    assert body["audit_verdict"].startswith(("PASSED", "FLAGGED"))


def test_run_is_internally_consistent(client, offline):
    """Theorem 8.2 and the CI construction must hold in the serialised response."""
    body = client.post("/api/v1/audit/run", json=audit_payload()).json()

    assert body["total_regret"] == pytest.approx(
        body["trajectory_covariance"] + body["bias_correction"], abs=1e-12
    )
    midpoint = (body["ci_lower"] + body["ci_upper"]) / 2
    assert midpoint == pytest.approx(body["trajectory_covariance"], abs=1e-12)
    assert body["standard_error"] > 0
    # is_significant must agree with the interval it was derived from.
    assert body["is_significant"] == (body["ci_lower"] > 0 or body["ci_upper"] < 0)


def test_run_weights_average_to_a_valid_portfolio(client, offline):
    body = client.post("/api/v1/audit/run", json=audit_payload()).json()

    assert sum(body["mean_weights"]) == pytest.approx(1.0)
    assert sum(body["benchmark_weights"]) == pytest.approx(1.0)
    assert all(w >= 0 for w in body["mean_weights"])


def test_cumulative_regret_ends_at_the_trajectory_covariance(client, offline):
    """The running mean of xi must land exactly on Eq. 27 by the final day."""
    body = client.post("/api/v1/audit/run", json=audit_payload()).json()

    assert body["daily_series"][-1]["cumulative_regret"] == pytest.approx(
        body["trajectory_covariance"], abs=1e-12
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_date": "2023-12-31", "end_date": "2022-01-01"},  # inverted window
        {"start_date": "2022-01-01", "end_date": "2022-01-01"},  # empty window
        {"tickers": ["AAA"]},  # a portfolio needs 2+ assets
        {"tickers": ["AAA", "AAA"]},  # duplicates collapse to 1 distinct
        {"tickers": []},
        {"strategy_type": "astrology"},
        {"rolling_window": 0},
        {"rolling_window": 5000},
        {"start_date": "not-a-date"},
    ],
)
def test_run_rejects_invalid_requests(client, offline, overrides):
    response = client.post("/api/v1/audit/run", json=audit_payload(**overrides))

    assert response.status_code == 422


def test_run_rejects_a_window_shorter_than_the_rolling_lookback(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.audit_service.load_cost_panel", lambda *a, **k: (synthetic_costs(days=40), "live")
    )

    response = client.post("/api/v1/audit/run", json=audit_payload(rolling_window=60))

    assert response.status_code == 422
    assert "rolling_window" in response.json()["detail"]


def test_run_surfaces_a_bad_ticker_as_422_not_500(client, monkeypatch):
    """A DataError from the data layer must never leak as an opaque 500."""
    from app.services.data_service import DataError

    def boom(*a, **k):
        raise DataError("no price data for ticker(s): NOPE")

    monkeypatch.setattr("app.services.audit_service.load_cost_panel", boom)

    response = client.post("/api/v1/audit/run", json=audit_payload(tickers=["NOPE", "AAA"]))

    assert response.status_code == 422
    assert "NOPE" in response.json()["detail"]


# --------------------------------------------------------------------------
# POST /audit/upload
# --------------------------------------------------------------------------
def make_csv(rows: int = 60, weight_scale: float = 1.0, seed: int = 3) -> bytes:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({"date": pd.bdate_range("2023-01-02", periods=rows)})
    weights = rng.dirichlet(np.ones(len(ASSETS)), size=rows) * weight_scale
    for i, asset in enumerate(ASSETS):
        frame[f"return_{asset}"] = rng.normal(0.0004, 0.011, rows)
        frame[f"weight_{asset}"] = weights[:, i]
    return frame.to_csv(index=False).encode()


def post_csv(client, content: bytes, name: str = "portfolio.csv"):
    return client.post(
        "/api/v1/audit/upload", files={"file": (name, io.BytesIO(content), "text/csv")}
    )


def test_upload_audits_a_valid_csv(client):
    response = post_csv(client, make_csv())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assets"] == ASSETS
    assert body["observations"] == 60
    assert body["total_regret"] == pytest.approx(
        body["trajectory_covariance"] + body["bias_correction"], abs=1e-12
    )


def test_upload_accepts_short_column_prefixes(client):
    frame = pd.read_csv(io.BytesIO(make_csv()))
    frame.columns = [c.replace("return_", "r_").replace("weight_", "w_") for c in frame.columns]

    response = post_csv(client, frame.to_csv(index=False).encode())

    assert response.status_code == 200, response.text
    assert response.json()["assets"] == ASSETS


def test_upload_rejects_weights_that_do_not_sum_to_one(client):
    response = post_csv(client, make_csv(weight_scale=0.5))

    assert response.status_code == 422
    assert "sum to 1" in response.json()["detail"]


def test_upload_rejects_an_unmatched_asset_column(client):
    frame = pd.read_csv(io.BytesIO(make_csv()))
    frame = frame.drop(columns=["weight_CCC"])

    response = post_csv(client, frame.to_csv(index=False).encode())

    assert response.status_code == 422
    assert "CCC" in response.json()["detail"]


def test_upload_rejects_a_csv_without_the_expected_columns(client):
    response = post_csv(client, b"date,price\n2023-01-02,101.5\n2023-01-03,102.0\n")

    assert response.status_code == 422
    assert "weight_" in response.json()["detail"]


def test_upload_rejects_too_few_rows(client):
    response = post_csv(client, make_csv(rows=10))

    assert response.status_code == 422
    assert "at least" in response.json()["detail"]


def test_upload_rejects_an_empty_file(client):
    response = post_csv(client, b"")

    assert response.status_code == 422


def test_upload_rejects_a_non_csv_extension(client):
    response = post_csv(client, make_csv(), name="model.xlsx")

    assert response.status_code == 422
    assert "csv" in response.json()["detail"].lower()


def test_upload_requires_a_file(client):
    assert client.post("/api/v1/audit/upload").status_code == 422


# --------------------------------------------------------------------------
# GET /market/summary
# --------------------------------------------------------------------------
def test_market_summary(client, offline):
    response = client.get(
        "/api/v1/market/summary",
        params={"tickers": ASSETS, "start_date": "2022-01-01", "end_date": "2023-12-31"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tickers"] == ASSETS
    assert body["observations"] == 400
    assert set(body["annualised_volatility"]) == set(ASSETS)
    # ~1.2% daily vol annualises to roughly 19%; assert the order of magnitude only.
    assert all(0.05 < v < 0.60 for v in body["annualised_volatility"].values())


def test_market_summary_requires_tickers(client, offline):
    response = client.get(
        "/api/v1/market/summary", params={"start_date": "2022-01-01", "end_date": "2023-12-31"}
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Live network test -- run with `pytest -m live`
# --------------------------------------------------------------------------
@pytest.mark.live
def test_run_against_real_market_data(client):
    response = client.post(
        "/api/v1/audit/run",
        json=audit_payload(tickers=["AAPL", "MSFT", "SPY"], end_date="2024-01-01"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["observations"] > 200


# --------------------------------------------------------------------------
# Regression tests for the second code review
# --------------------------------------------------------------------------
def test_upload_observations_matches_the_series_length(client):
    """The invariant the strategy path already asserts, missing on the upload
    path -- which is how the duplicate-index miscount below shipped green."""
    body = post_csv(client, make_csv(rows=60)).json()

    assert body["observations"] == len(body["daily_series"]) == 60


def test_upload_rejects_duplicate_dates(client):
    """A non-unique index makes `.loc` return more rows than it selected, so T
    was reported as 60 while the audit actually ran on 120 rows."""
    frame = pd.read_csv(io.BytesIO(make_csv(rows=60)))
    doubled = pd.concat([frame, frame], ignore_index=True)

    response = post_csv(client, doubled.to_csv(index=False).encode())

    assert response.status_code == 422
    assert "duplicate dates" in response.json()["detail"]


def test_upload_rejects_partially_unparseable_dates(client):
    """Previously `.any()` accepted the column, filling the rest with NaT and
    emitting daily_series rows literally dated "NaT"."""
    frame = pd.read_csv(io.BytesIO(make_csv(rows=60)))
    frame.loc[5:, "date"] = "not-a-date"

    response = post_csv(client, frame.to_csv(index=False).encode())

    assert response.status_code == 422
    assert "unparseable dates" in response.json()["detail"]


def test_upload_rejects_a_single_asset_panel(client):
    """One asset means weights are identically 1.0, so xi is structurally zero
    and the audit would return a clean PASSED off an empty trajectory."""
    response = post_csv(client, make_csv_for(["ONLY"]))

    assert response.status_code == 422
    assert "at least 2 assets" in response.json()["detail"]


def test_upload_rejects_colliding_column_prefixes(client):
    """`return_AAA` and `r_AAA` both resolve to AAA; keeping the last silently
    audits a different panel than the file describes."""
    frame = pd.read_csv(io.BytesIO(make_csv(rows=60)))
    frame["r_AAA"] = frame["return_AAA"]

    response = post_csv(client, frame.to_csv(index=False).encode())

    assert response.status_code == 422
    assert "resolve to asset 'AAA'" in response.json()["detail"]


def make_csv_for(assets: list[str], rows: int = 60, seed: int = 3) -> bytes:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({"date": pd.bdate_range("2023-01-02", periods=rows)})
    weights = rng.dirichlet(np.ones(len(assets)), size=rows)
    for i, asset in enumerate(assets):
        frame[f"return_{asset}"] = rng.normal(0.0004, 0.011, rows)
        frame[f"weight_{asset}"] = weights[:, i]
    return frame.to_csv(index=False).encode()


@pytest.mark.parametrize("days, window", [(32, 30), (35, 30), (40, 20)])
def test_run_enforces_min_observations_after_the_rolling_window(client, monkeypatch, days, window):
    """The rolling window consumes `window` rows, so a panel that clears the
    30-day gate can still audit T=2 -- and did, returning 200 with SE ~1e-20
    and a confident 'PASSED: Model Outperforms Benchmark'."""
    monkeypatch.setattr(
        "app.services.audit_service.load_cost_panel", lambda *a, **k: (synthetic_costs(days=days), "live")
    )

    response = client.post("/api/v1/audit/run", json=audit_payload(rolling_window=window))

    assert response.status_code == 422
    assert "audited days" in response.json()["detail"]


def test_wildcard_cors_does_not_grant_credentialed_access(client):
    """Starlette echoes the caller's Origin rather than sending "*" when
    credentials are allowed, so wildcard + credentials would let any site make
    credentialed requests against a local instance."""
    headers = client.get("/health", headers={"Origin": "https://evil.example"}).headers

    assert headers.get("access-control-allow-credentials") is None


@pytest.mark.parametrize(
    "params",
    [
        {"tickers": ["AAA", "BBB"], "start_date": "2023-12-31", "end_date": "2022-01-01"},
        {"tickers": [" ", "  "], "start_date": "2022-01-01", "end_date": "2023-12-31"},
        {"tickers": ["AAA"], "start_date": "2022-01-01", "end_date": "2023-12-31"},
    ],
)
def test_market_summary_applies_the_same_validation_as_audit_run(client, offline, params):
    """Its docstring promises the panel /audit/run would use, so it must reject
    what /audit/run rejects -- and with a 422, not a 500."""
    response = client.get("/api/v1/market/summary", params=params)

    assert response.status_code == 422


def test_internal_value_errors_are_not_disguised_as_client_errors(client, monkeypatch):
    """A blanket ValueError handler would turn a genuine server defect into a
    friendly 422 and hide it from error monitoring."""

    def boom(*a, **k):
        raise ValueError("internal alignment bug")

    monkeypatch.setattr("app.services.audit_service.load_cost_panel", boom)
    offline_client = TestClient(app, raise_server_exceptions=False)

    response = offline_client.post("/api/v1/audit/run", json=audit_payload())

    assert response.status_code == 500
    assert "internal alignment bug" not in response.text


def test_response_carries_daily_weights_for_the_allocation_chart(client, offline):
    """The stacked-area chart needs pi_hat_t per day; mean_weights alone cannot
    reconstruct it."""
    body = client.post("/api/v1/audit/run", json=audit_payload()).json()

    for point in body["daily_series"]:
        assert len(point["weights"]) == len(body["assets"])
        assert sum(point["weights"]) == pytest.approx(1.0)

    # The reported mean must actually be the mean of the daily vectors.
    for i, mean in enumerate(body["mean_weights"]):
        column = [p["weights"][i] for p in body["daily_series"]]
        assert mean == pytest.approx(sum(column) / len(column))


def test_response_carries_a_p_value_consistent_with_the_verdict(client, offline):
    body = client.post("/api/v1/audit/run", json=audit_payload()).json()

    assert body["p_value"] is not None
    assert 0.0 <= body["p_value"] <= 1.0
    assert body["is_significant"] == (body["p_value"] < 0.05)


def test_response_carries_a_separate_interval_for_total_regret(client, offline):
    """Total regret gets its own HAC interval rather than borrowing the one
    built for the covariance term."""
    body = client.post("/api/v1/audit/run", json=audit_payload()).json()

    assert body["regret_standard_error"] > body["standard_error"]

    midpoint = (body["regret_ci_lower"] + body["regret_ci_upper"]) / 2
    assert midpoint == pytest.approx(body["total_regret"], abs=1e-12)
    half_width = (body["regret_ci_upper"] - body["regret_ci_lower"]) / 2
    assert half_width == pytest.approx(1.959963984540054 * body["regret_standard_error"])

    # The two intervals are about different estimands and must not be confused.
    assert body["regret_ci_upper"] - body["regret_ci_lower"] > body["ci_upper"] - body["ci_lower"]


# --------------------------------------------------------------------------
# Snapshot fallback: a public deploy where the data provider is blocked
# --------------------------------------------------------------------------
def test_snapshot_fallback_serves_a_labelled_result_when_live_data_fails(client, monkeypatch):
    """yfinance is frequently blocked from datacenter IPs. The demo must still
    work - but the result has to say the prices are frozen, not current."""
    from app.services.data_service import DataError

    def blocked(*a, **k):
        raise DataError("market data download failed: connection refused")

    monkeypatch.setattr("app.services.data_service.fetch_prices", blocked)

    response = client.post(
        "/api/v1/audit/run",
        json=audit_payload(tickers=["AAPL", "MSFT", "SPY"], start_date="2021-01-01",
                           end_date="2023-01-01"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data_source"] == "snapshot"


def test_a_ticker_outside_the_snapshot_still_fails(client, monkeypatch):
    """The fallback must not quietly substitute a different portfolio."""
    from app.services.data_service import DataError

    monkeypatch.setattr(
        "app.services.data_service.fetch_prices",
        lambda *a, **k: (_ for _ in ()).throw(DataError("provider down")),
    )

    response = client.post(
        "/api/v1/audit/run",
        json=audit_payload(tickers=["AAPL", "NVDA"], start_date="2021-01-01",
                           end_date="2023-01-01"),
    )

    assert response.status_code == 422
    assert "NVDA" in response.json()["detail"]


def test_live_results_are_labelled_live(client, offline):
    assert client.post("/api/v1/audit/run", json=audit_payload()).json()["data_source"] == "live"


def test_uploaded_results_are_labelled_uploaded(client):
    assert post_csv(client, make_csv()).json()["data_source"] == "uploaded"


def test_prices_are_cached_so_a_repeat_audit_costs_the_provider_nothing(monkeypatch):
    """One successful download should serve subsequent identical requests - the
    difference between a demo that survives and one that gets IP-banned."""
    from datetime import date
    import app.services.data_service as ds

    ds._price_cache.clear()
    calls = []
    index = pd.bdate_range("2022-01-03", periods=300)
    tickers = ["AAA", "BBB"]
    raw = pd.DataFrame(
        np.tile(100.0 + np.arange(300)[:, None] * 0.1, (1, 2)),
        index=index,
        columns=pd.MultiIndex.from_product([["Close"], tickers]),
    )

    def counted(*a, **k):
        calls.append(1)
        return raw

    monkeypatch.setattr(ds.yf, "download", counted)

    first = ds.fetch_prices(tickers, date(2022, 1, 1), date(2023, 1, 1))
    second = ds.fetch_prices(tickers, date(2022, 1, 1), date(2023, 1, 1))

    assert len(calls) == 1  # the second request never reached the provider
    pd.testing.assert_frame_equal(first, second)

    # A different window is a different key and does hit the provider again.
    ds.fetch_prices(tickers, date(2022, 6, 1), date(2023, 1, 1))
    assert len(calls) == 2

    # The cache hands back copies, so a caller mutating its frame cannot poison it.
    first.iloc[0, 0] = -999.0
    assert ds.fetch_prices(tickers, date(2022, 1, 1), date(2023, 1, 1)).iloc[0, 0] != -999.0
