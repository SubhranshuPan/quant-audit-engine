"""Audit endpoints: built-in strategies on live data, or a user-supplied CSV."""

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.schemas.audit import AuditRequest, AuditResponse
from app.services.audit_service import run_audit, audit_strategy
from app.services.data_service import DataError, parse_audit_csv

router = APIRouter(prefix="/audit", tags=["audit"])


@router.post("/run", response_model=AuditResponse, summary="Audit a built-in strategy")
def run(request: AuditRequest) -> AuditResponse:
    """Download real prices, run the chosen strategy, and audit its regret.

    Returns the Eq. 27 trajectory covariance, the Theorem 8.2 bias correction,
    a Newey-West HAC 95% interval and the SR 11-7 verdict.
    """
    return audit_strategy(request)


@router.post("/upload", response_model=AuditResponse, summary="Audit an uploaded CSV")
async def upload(file: UploadFile = File(...)) -> AuditResponse:
    """Audit a portfolio the caller ran themselves.

    The CSV needs a date column plus matched `return_<ASSET>` and
    `weight_<ASSET>` columns -- see `parse_audit_csv` for accepted prefixes.
    """
    if file.filename and not file.filename.lower().endswith((".csv", ".txt")):
        raise DataError(f"expected a .csv file, got '{file.filename}'")

    # Check the size BEFORE reading. Starlette spools large uploads to disk, but
    # `await file.read()` pulls the whole body into one bytes object and undoes
    # that -- so a read-then-check would let any unauthenticated caller force an
    # arbitrary allocation per worker before we reject it.
    limit_mb = settings.max_upload_bytes // 1024 // 1024
    if file.size is not None and file.size > settings.max_upload_bytes:
        raise DataError(f"file exceeds the {limit_mb} MB limit")

    content = await file.read()
    if not content:
        raise DataError("uploaded file is empty")
    if len(content) > settings.max_upload_bytes:  # belt and braces if size was unset
        raise DataError(f"file exceeds the {limit_mb} MB limit")

    costs, weights = parse_audit_csv(content)
    return run_audit(costs, weights)


@router.get("/strategies", summary="List the built-in strategies")
def strategies() -> dict[str, str]:
    return {
        "momentum": "Overweights assets with the strongest trailing return over the rolling window.",
        "reversion": "Overweights assets with the weakest trailing return, betting on mean reversion.",
        "min_variance": "Inverse-variance weights; the minimum-variance portfolio ignoring correlations.",
    }
