"""Aggregates every v1 endpoint router."""

from fastapi import APIRouter

from app.api.v1.endpoints import audit, market

api_router = APIRouter()
api_router.include_router(audit.router)
api_router.include_router(market.router)
