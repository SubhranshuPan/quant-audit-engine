"""FastAPI entry point for the Quant AI Investment Strategy Audit Engine."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.math_engine import AuditInputError
from app.core.rate_limit import RateLimitMiddleware
from app.services.data_service import DataError

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    description=(
        "Audits investment strategies for statistically significant regret using the "
        "trajectory covariance estimator (Eq. 27), the Theorem 8.2 policy bias "
        "correction and Newey-West HAC inference, per Aldridge (2026)."
    ),
)

# Starlette does not send a literal "*" when credentials are allowed -- it echoes
# the caller's Origin header, so wildcard + credentials would grant every site on
# the internet credentialed access to a locally running instance. Credentials are
# therefore enabled only once the origin list is actually restricted.
_wildcard_origins = "*" in settings.cors_origins

# Mounted before CORS so a throttled response still carries CORS headers and the
# browser can read the 429 rather than reporting an opaque network error.
app.add_middleware(
    RateLimitMiddleware,
    limit=settings.rate_limit_per_minute,
    exempt=("/health", "/docs", "/redoc", "/openapi.json"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=not _wildcard_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DataError)
def handle_data_error(request: Request, exc: DataError) -> JSONResponse:
    """DataError always means the caller asked for something unsatisfiable.

    Handled centrally so no endpoint has to wrap its service calls in try/except,
    and so a bad ticker never surfaces as an opaque 500.
    """
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
def handle_validation_error(request: Request, exc: ValidationError) -> JSONResponse:
    """Pydantic errors raised *inside* a handler, not while parsing the request.

    `/market/summary` validates its query by constructing an `AuditRequest`, so
    it reuses the audit rules instead of duplicating them. FastAPI only
    auto-handles `RequestValidationError`, so without this a bad window would
    surface as a 500. Mirrors FastAPI's own 422 body shape.
    """
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.exception_handler(AuditInputError)
def handle_audit_input_error(request: Request, exc: AuditInputError) -> JSONResponse:
    """Degenerate data reaching the math engine (too few rows, non-finite values).

    Deliberately NOT a blanket `ValueError` handler: that would also convert
    genuine internal defects -- a shape mismatch from an alignment bug in
    `run_audit`, say -- into a friendly 422, hiding a 500-class fault from error
    monitoring and leaking the internal message to the caller.
    """
    return JSONResponse(status_code=422, content={"detail": str(exc)})


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.version}
