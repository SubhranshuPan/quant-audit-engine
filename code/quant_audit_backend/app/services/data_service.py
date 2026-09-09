"""Market data acquisition: yfinance prices -> log returns -> audit costs."""

import io
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from app.core.config import settings


class DataError(RuntimeError):
    """Raised when market data cannot be turned into a usable audit panel.

    The API layer maps this to a 4xx: it always means the *request* was
    unsatisfiable (bad ticker, empty window), not that the server broke.
    """


SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "snapshot_prices.csv"

# (tickers, start, end) -> (fetched_at, frame). Bounded by _CACHE_MAX entries.
_price_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
_CACHE_MAX = 64


def _cache_get(key: tuple) -> pd.DataFrame | None:
    hit = _price_cache.get(key)
    if hit and time.monotonic() - hit[0] < settings.price_cache_seconds:
        return hit[1].copy()  # copy so a caller cannot mutate the cached frame
    return None


def _cache_put(key: tuple, frame: pd.DataFrame) -> None:
    if len(_price_cache) >= _CACHE_MAX:
        # Drop the oldest entry; insertion order is preserved by dict.
        del _price_cache[next(iter(_price_cache))]
    _price_cache[key] = (time.monotonic(), frame.copy())


def load_snapshot(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Prices from the bundled snapshot, for when the live provider is unreachable.

    Raises DataError unless every requested ticker is in the snapshot -- a
    partial fallback would silently audit a different portfolio than asked for.
    """
    if not SNAPSHOT_PATH.exists():
        raise DataError("no bundled snapshot is available")

    frame = pd.read_csv(SNAPSHOT_PATH, index_col=0, parse_dates=True)
    missing = [t for t in tickers if t not in frame.columns]
    if missing:
        raise DataError(
            f"live market data is unavailable and the bundled snapshot does not cover "
            f"{', '.join(missing)}. It covers: {', '.join(frame.columns)}."
        )

    window = frame.loc[str(start):str(end), tickers].dropna(how="any")
    if len(window) < settings.min_observations:
        covered = f"{frame.index[0].date()} to {frame.index[-1].date()}"
        raise DataError(
            f"live market data is unavailable and the bundled snapshot has only "
            f"{len(window)} days in this window. The snapshot covers {covered}."
        )
    return window


def fetch_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Download adjusted closing prices, one column per ticker.

    `auto_adjust=True` makes yfinance's Close column already split- and
    dividend-adjusted, which is the series the audit needs -- using raw Close
    would inject fake one-day losses on every ex-dividend date.
    """
    cache_key = (tuple(tickers), start, end)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        raw = yf.download(
            tickers,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            actions=False,
        )
    except Exception as exc:  # noqa: BLE001 - yfinance raises assorted network/parse errors
        raise DataError(f"market data download failed: {exc}") from exc

    if raw is None or raw.empty:
        raise DataError(f"no price data returned for {tickers} between {start} and {end}")

    # One ticker yields flat columns, several yield a (field, ticker) MultiIndex.
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if not isinstance(raw.columns, pd.MultiIndex):
        close.columns = tickers[:1]

    close = close.reindex(columns=tickers)  # keep the caller's ordering stable

    # A ticker that does not exist comes back as an all-NaN column rather than
    # an error, so an unchecked audit would silently run on garbage.
    missing = [t for t in tickers if close[t].isna().all()]
    if missing:
        raise DataError(f"no price data for ticker(s): {', '.join(missing)}")

    # Drop days where any asset is missing, so every row is a complete
    # cross-section; Eq. 27 needs c_t and pi_hat_t defined on the same assets.
    close = close.dropna(how="any")
    if close.empty:
        raise DataError("no trading days where all requested tickers have prices")

    _cache_put(cache_key, close)
    return close


def prices_to_costs(prices: pd.DataFrame) -> pd.DataFrame:
    """Costs c_t = -r_t, where r_t = log(P_t / P_{t-1}).

    Costs, not returns: the paper frames the audit as regret minimisation, so a
    profitable day is a *negative* cost.
    """
    if (prices <= 0).to_numpy().any():
        raise DataError("prices must be strictly positive to take log returns")

    log_returns = np.log(prices / prices.shift(1)).dropna(how="any")
    if log_returns.empty:
        raise DataError("need at least 2 trading days to compute a return")

    return -log_returns


def load_cost_panel(tickers: list[str], start: date, end: date) -> tuple[pd.DataFrame, str]:
    """fetch_prices + prices_to_costs, with the sample-size guardrail applied.

    Returns (costs, source) where source is "live" or "snapshot". The caller is
    expected to surface that label: presenting frozen prices as live data in a
    compliance tool would be worse than failing outright.
    """
    source = "live"
    try:
        prices = fetch_prices(tickers, start, end)
    except DataError:
        if not settings.use_snapshot_fallback:
            raise
        # Only a provider failure falls back. A bad ticker still fails, because
        # the snapshot cannot answer for a symbol it does not contain.
        prices = load_snapshot(tickers, start, end)
        source = "snapshot"

    costs = prices_to_costs(prices)

    if len(costs) < settings.min_observations:
        raise DataError(
            f"only {len(costs)} trading days available; at least "
            f"{settings.min_observations} are needed for a trustworthy HAC standard error"
        )

    return costs, source


# --------------------------------------------------------------------------
# User-supplied audit panels (CSV upload)
# --------------------------------------------------------------------------
RETURN_PREFIXES = ("return_", "ret_", "r_")
WEIGHT_PREFIXES = ("weight_", "w_", "pi_")


def _strip_prefix(column: str, prefixes: tuple[str, ...]) -> str | None:
    lowered = column.strip().lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return column.strip()[len(prefix):].upper()
    return None


def _resolve_assets(columns, prefixes: tuple[str, ...], kind: str) -> dict[str, str]:
    """Map asset name -> source column for one side of the panel.

    Two aliases of the same prefix family resolve to the same asset (both
    `return_AAPL` and `r_AAPL` give "AAPL"), which is plausible when merging
    exports. Silently keeping the last one would audit a different panel than
    the file describes, so reject the ambiguity instead.
    """
    resolved: dict[str, str] = {}
    for column in columns:
        asset = _strip_prefix(str(column), prefixes)
        if not asset:
            continue
        if asset in resolved:
            raise DataError(
                f"two {kind} columns resolve to asset '{asset}': "
                f"'{resolved[asset]}' and '{column}'"
            )
        resolved[asset] = column
    return resolved


def parse_audit_csv(content: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse an uploaded CSV of daily returns and portfolio weights.

    Expected layout -- one row per trading day, a date column, and a matched
    pair of columns per asset::

        date,return_AAPL,return_MSFT,weight_AAPL,weight_MSFT
        2024-01-02,0.0121,-0.0043,0.6,0.4

    Accepted prefixes are return_/ret_/r_ and weight_/w_/pi_ (case-insensitive).
    Returns (costs, weights) aligned on the same date index, where cost = -return.
    """
    try:
        frame = pd.read_csv(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - pandas raises many parser errors
        raise DataError(f"could not parse CSV: {exc}") from exc

    if frame.empty:
        raise DataError("uploaded CSV contains no rows")

    returns = _resolve_assets(frame.columns, RETURN_PREFIXES, "return")
    weights = _resolve_assets(frame.columns, WEIGHT_PREFIXES, "weight")

    if not returns or not weights:
        raise DataError(
            "CSV must contain return_<ASSET> and weight_<ASSET> columns; "
            f"found columns: {', '.join(map(str, frame.columns))}"
        )

    # Auditing an asset with only half a pair is meaningless, so refuse rather
    # than silently dropping it and reporting a regret for a different portfolio.
    if set(returns) != set(weights):
        unmatched = set(returns).symmetric_difference(weights)
        raise DataError(f"every asset needs both a return and a weight column; unmatched: {sorted(unmatched)}")

    # A one-asset panel carries no cross-sectional information: weights are
    # identically 1.0, so pi_hat - pi_bar is exactly 0, xi is exactly 0, and the
    # audit would hand back a clean "PASSED" off a structurally empty trajectory.
    # /audit/run already requires 2+ tickers; uploads must match.
    if len(returns) < 2:
        raise DataError(
            f"at least 2 assets are required to audit a portfolio, found {len(returns)}"
        )

    assets = sorted(returns)
    index = _read_date_index(frame)

    ret = frame[[returns[a] for a in assets]].apply(pd.to_numeric, errors="coerce")
    wgt = frame[[weights[a] for a in assets]].apply(pd.to_numeric, errors="coerce")
    ret.columns, wgt.columns = assets, assets
    ret.index = wgt.index = index

    valid = ret.notna().all(axis=1) & wgt.notna().all(axis=1)
    ret, wgt = ret[valid], wgt[valid]
    if len(ret) < settings.min_observations:
        raise DataError(
            f"only {len(ret)} complete rows after dropping blanks; "
            f"at least {settings.min_observations} are needed"
        )

    row_sums = wgt.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=1e-3):
        worst = row_sums.iloc[int(np.argmax(np.abs(row_sums - 1.0)))]
        raise DataError(f"portfolio weights must sum to 1 on every row; worst row sums to {worst:.4f}")

    return -ret, wgt


def _read_date_index(frame: pd.DataFrame) -> pd.Index:
    """Use a date-like column as the index, else fall back to the row number.

    Every value must parse, and the result must be unique. A partially
    parseable column would otherwise become an index full of NaT -- which is
    both non-unique and rendered as the literal string "NaT" in the response --
    and a non-unique index makes `.loc` return more rows than it was asked for.
    """
    for column in frame.columns:
        if str(column).strip().lower() in {"date", "datetime", "timestamp", "day"}:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            if parsed.isna().any():
                bad = frame[column][parsed.isna()].iloc[0]
                raise DataError(f"column '{column}' has unparseable dates, e.g. '{bad}'")
            if parsed.duplicated().any():
                dup = parsed[parsed.duplicated()].iloc[0].date()
                raise DataError(f"column '{column}' has duplicate dates, e.g. {dup}")
            return pd.Index(parsed)
    return pd.RangeIndex(len(frame))
