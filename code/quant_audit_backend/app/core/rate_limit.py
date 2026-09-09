"""Per-client rate limiting.

A public deployment of this API is an amplifier: one cheap request makes the
server perform an outbound market-data download. Without a limit, an
unauthenticated caller can both exhaust the host and get its IP blocked by the
upstream data provider.
"""

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# ponytail: in-process sliding window. Correct for a single worker, which is
# what a small deployment runs. Behind several workers each holds its own
# counter, so the effective limit multiplies by the worker count - move to Redis
# if this ever runs replicated.
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limit on the endpoints that cost real work.

    Cheap endpoints (health, docs, the strategy list) are exempt, so a
    monitoring probe can never be throttled out.
    """

    def __init__(self, app, limit: int, window_seconds: int = 60, exempt: tuple[str, ...] = ()):
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self.exempt = exempt
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client(self, request: Request) -> str:
        # Behind a proxy the socket address is the proxy, so prefer the
        # forwarded chain's first entry when the platform sets one.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or any(path.startswith(p) for p in self.exempt):
            return await call_next(request)

        now = time.monotonic()
        hits = self._hits[self._client(request)]
        while hits and now - hits[0] > self.window:
            hits.popleft()

        if len(hits) >= self.limit:
            retry_after = int(self.window - (now - hits[0])) + 1
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "detail": (
                        f"Rate limit reached ({self.limit} requests per "
                        f"{self.window}s). Try again in {retry_after}s."
                    )
                },
            )

        hits.append(now)
        # Unbounded growth is the obvious failure mode for a dict keyed by client
        # address, so sweep emptied entries whenever the table gets large.
        if len(self._hits) > 4096:
            for key in [k for k, v in self._hits.items() if not v]:
                del self._hits[key]

        return await call_next(request)
