"""Liveness and readiness.

Reports what the process actually depends on right now, so a misconfiguration
is visible from one call instead of from a failing user journey.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep, SettingsDep
from app.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(session: SessionDep, settings: SettingsDep) -> HealthResponse:
    try:
        await session.execute(text("select 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - health must report, never raise
        database = "unavailable"
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        database=database,
        providers={
            "llm": settings.llm_provider,
            "image": settings.image_provider,
            "embedding": settings.embedding_provider,
            "storage": settings.storage_provider,
            "search": settings.search_provider,
            "auth": settings.auth_provider,
        },
        demo_mode=settings.demo_mode,
    )
