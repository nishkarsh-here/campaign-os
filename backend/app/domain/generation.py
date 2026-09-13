"""Image generation jobs and their outputs.

Every job carries an explicit status and an idempotency key: a retry must never
double-charge a provider, and a crashed run must be resumable without
regenerating what already succeeded.

**Providers run independently.** One job per provider, each reaching its own
terminal status. A batch where two of three providers succeeded produced two
usable plates, and `GenerationBatch.outcome` says so rather than calling the
whole thing a failure.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.domain.common import DomainModel, ExecutionError, Id, JobStatus, new_id, utc_now
from app.domain.prompt import VISUAL_PLATE


class AssetKind(StrEnum):
    """What a stored image actually is.

    `VISUAL_PLATE` is the only kind Milestone 6 produces. Naming it prevents
    the quiet lie of treating a raw model output as a brand-ready creative —
    the logo, headline, CTA and exact colours are applied later by the
    deterministic renderer (ADR-006).
    """

    VISUAL_PLATE = VISUAL_PLATE
    FINAL_COMPOSITION = "FINAL_COMPOSITION"


class GenerationJob(DomainModel):
    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    #: The compiled prompt this job executes. Traceable from here back through
    #: the canonical prompt to the approved Creative Specification.
    prompt_id: Id
    specification_id: Id
    specification_version: int = Field(default=1, ge=1)
    provider: str
    model: str
    status: JobStatus = JobStatus.PENDING
    #: Groups the jobs started by one "generate creatives" request.
    batch_id: Id
    #: Same key, same charge. A retry increments `attempt`, which is part of
    #: the key, so a deliberate retry is a new charge and a replayed request
    #: is not.
    idempotency_key: str
    attempt: int = Field(default=1, ge=1)
    provider_job_id: str | None = None
    error: ExecutionError | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    def can_retry(self) -> bool:
        """Only a failure is worth retrying. Re-running a success would charge
        for an image we already have; re-running a cancellation would undo a
        human decision."""
        return self.status is JobStatus.FAILED

    @model_validator(mode="after")
    def _terminal_jobs_explain_themselves(self) -> GenerationJob:
        if self.status is JobStatus.FAILED and self.error is None:
            raise ValueError("A failed generation job must carry an error.")
        return self


class GeneratedAsset(DomainModel):
    """A raw generated plate. Brand text is *not* in this image (ADR-006)."""

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    generation_job_id: Id
    prompt_id: Id
    specification_id: Id
    specification_version: int = Field(default=1, ge=1)
    provider: str
    model: str
    kind: AssetKind = AssetKind.VISUAL_PLATE
    #: Generated, never derived from anything a user typed.
    storage_key: str
    mime_type: str = "image/png"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    seed: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    #: Safe provider metadata only — model version, finish reason, timings.
    #: Never credentials, never a raw provider payload.
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationBatch(DomainModel):
    """One "generate creatives" request, across every provider it started.

    A read model: the jobs are the state, this is how a human reads them.
    """

    id: Id
    campaign_id: Id
    specification_id: Id
    specification_version: int = Field(default=1, ge=1)
    jobs: list[GenerationJob] = Field(default_factory=list)
    assets: list[GeneratedAsset] = Field(default_factory=list)

    @property
    def succeeded(self) -> list[GenerationJob]:
        return [j for j in self.jobs if j.status is JobStatus.COMPLETED]

    @property
    def failed(self) -> list[GenerationJob]:
        return [j for j in self.jobs if j.status is JobStatus.FAILED]

    @property
    def running(self) -> list[GenerationJob]:
        return [j for j in self.jobs if not j.is_terminal()]

    def latest_per_provider(self) -> list[GenerationJob]:
        """The most recent attempt for each provider.

        A retry adds a job rather than replacing one — the earlier attempt is
        history worth keeping. But "how did the providers do?" is answered by
        where each one *ended up*, not by how many times it was asked.
        """
        newest: dict[str, GenerationJob] = {}
        for job in self.jobs:
            current = newest.get(job.provider)
            if current is None or job.attempt > current.attempt:
                newest[job.provider] = job
        return [newest[name] for name in sorted(newest)]

    def outcome(self) -> str:
        """Human-readable. Partial success is success, and says so.

        Counted per provider, not per job: after two retries of one provider,
        "1/3 providers succeeded" would be wrong in a system that only ever had
        two providers.
        """
        if not self.jobs:
            return "Nothing generated yet."
        latest = self.latest_per_provider()
        total = len(latest)
        done = sum(1 for job in latest if job.status is JobStatus.COMPLETED)
        failed = sum(1 for job in latest if job.status is JobStatus.FAILED)
        pending = sum(1 for job in latest if not job.is_terminal())
        noun = "provider" if total == 1 else "providers"
        if pending:
            return f"{done}/{total} {noun} finished, {pending} still generating."
        if failed and done:
            return f"{done}/{total} {noun} succeeded — {failed} failed."
        if failed:
            return f"All {total} {noun} failed."
        return f"All {total} {noun} succeeded."

    def is_complete(self) -> bool:
        return bool(self.jobs) and all(job.is_terminal() for job in self.jobs)
