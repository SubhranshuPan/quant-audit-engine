"""Market endpoints: inspect the data an audit would run on, without auditing."""

from datetime import date

import numpy as np
from fastapi import APIRouter, Query

from app.core.config import settings
from app.schemas.audit import AuditRequest, MarketDataResponse
from app.services.data_service import load_cost_panel

router = APIRouter(prefix="/market", tags=["market"])

TRADING_DAYS_PER_YEAR = 252


@router.get("/summary", response_model=MarketDataResponse, summary="Summarise a data window")
def summary(
    tickers: list[str] = Query(..., min_length=2, max_length=settings.max_tickers),
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> MarketDataResponse:
    """Return-and-volatility summary of the exact panel `/audit/run` would use.

    Useful for checking coverage before spending time on an audit -- a window
    with too few overlapping trading days fails here with the same error.

    Validation is delegated to `AuditRequest` rather than re-implemented, so
    "the exact panel /audit/run would use" stays true: an inverted window, a
    blanks-only ticker list and a single ticker are all rejected here for the
    same reasons and with the same messages as on the audit endpoint.
    """
    request = AuditRequest(tickers=tickers, start_date=start_date, end_date=end_date)
    costs, source = load_cost_panel(request.tickers, request.start_date, request.end_date)
    returns = -costs  # report returns, which is what a human expects to read

    return MarketDataResponse(
        data_source=source,
        tickers=list(costs.columns),
        start_date=str(costs.index[0].date()),
        end_date=str(costs.index[-1].date()),
        observations=len(costs),
        mean_daily_return={c: float(returns[c].mean()) for c in returns.columns},
        annualised_volatility={
            c: float(returns[c].std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
            for c in returns.columns
        },
    )
