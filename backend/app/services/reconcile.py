"""Recover jobs a restart left in flight.

Generation, evaluation and brand checks run as in-process background tasks
(ADR-012). That is the right trade for this product — no broker to operate, no
worker fleet to deploy — and it has one consequence that has to be handled
rather than hoped about: **if the process dies mid-job, nothing is left to
finish it.** The row stays `RUNNING`, the interface polls it forever, and the
user is looking at a spinner that will never resolve.

So at startup, a job that was in flight when a previous process ended is marked
`FAILED` with a sentence saying exactly that. It then looks like every other
failure — visible, explained, and retryable through the button that is already
there. A wrong-but-honest `FAILED` beats a permanent spinner: the work is
cheap to redo and the user can see that they need to.

**It will not touch another instance's live work.** Only rows older than a
grace window are reconciled, and that window is the generation timeout plus a
margin — long enough that a job still genuinely running somewhere is never
inside it. Behind more than one instance this is a heuristic rather than a
guarantee, which is the honest limit of doing this without a coordinator.

This is deliberately *not* a worker, a scheduler or a lease. It runs once, at
startup, and does one thing.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import BrandGuardianResultRow, CreativeEvaluationRow, GenerationJobRow
from app.domain.common import JobStatus, utc_now
from app.logging import get_logger

log = get_logger(__name__)

#: Added to the generation timeout to get the grace window. A job that has been
#: RUNNING for longer than its own timeout plus this is not running any more.
GRACE = timedelta(minutes=5)

#: Said to the user, not logged at them. It names the cause and implies the fix.
REASON = "Interrupted by a server restart. Nothing was charged for this attempt — retry it."

_TABLES = (GenerationJobRow, CreativeEvaluationRow, BrandGuardianResultRow)


async def reconcile_interrupted_jobs(session: AsyncSession, settings: Settings) -> int:
    """Fail anything a previous process abandoned. Returns how many rows moved."""
    cutoff = utc_now() - (timedelta(seconds=settings.generation_timeout_s) + GRACE)
    in_flight = (JobStatus.PENDING.value, JobStatus.RUNNING.value)

    moved = 0
    for table in _TABLES:
        result = await session.execute(
            update(table)
            .where(table.status.in_(in_flight), table.created_at < cutoff)
            .values(status=JobStatus.FAILED.value, error=REASON, finished_at=utc_now())
        )
        count = getattr(result, "rowcount", 0) or 0
        if count:
            log.warning("reconciled_interrupted_jobs", table=table.__tablename__, rows=count)
        moved += count

    await session.commit()
    return moved
