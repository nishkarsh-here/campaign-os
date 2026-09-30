"""Liveness and readiness.

Reports what the process actually depends on right now, so a misconfiguration
is visible from one call instead of from a failing user journey.

That claim used not to hold for the providers: this route listed
`settings.storage_provider` and friends and returned `"status": "ok"`, so a
selected name with no adapter behind it read as a working integration and the
failure surfaced at the first upload (audit findings DOC-5 / BG-8). The names are
still reported, because they answer "what is this instance configured for" — but
`provider_status` now says which of them were actually constructed, and an
unbuilt one degrades the overall status.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep, SettingsDep
from app.api.schemas import HealthResponse
from app.providers.registry import provider_readiness

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(session: SessionDep, settings: SettingsDep) -> HealthResponse:
    try:
        await session.execute(text("select 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - health must report, never raise
        database = "unavailable"

    # Constructing a provider is an import and an object — no I/O, no network —
    # so this is cheap enough to answer for now rather than for boot time. It
    # says the adapter exists and is configured, never that the vendor is up.
    readiness = provider_readiness(settings)
    healthy = database == "ok" and all(status.built for status in readiness)

    return HealthResponse(
        status="ok" if healthy else "degraded",
        database=database,
        # `auth` is in `readiness` now rather than appended from settings, so the
        # identity provider is reported the same way as every other seam: the
        # name it is configured for, and separately whether it constructed.
        providers={status.kind: status.name for status in readiness},
        provider_status={
            status.kind: "ok" if status.built else "unavailable" for status in readiness
        },
        demo_mode=settings.demo_mode,
    )
