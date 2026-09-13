"""Recovery from a restart that happened mid-job.

The in-process background-task model (ADR-012) has exactly one sharp edge: if
the process dies while a job is running, nothing is left to finish it. The row
stays RUNNING and the interface polls a spinner that will never resolve, which
is the specific failure "no infinite spinners" forbids.

Two properties matter, and they pull against each other:

* an abandoned job must end up FAILED, visible and retryable
* a job that is *still running* — here, or in another instance — must not be
  killed by a restart of this one

The grace window is how both hold, and both directions are asserted below.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.db.models import GenerationJobRow
from app.domain.common import JobStatus, utc_now
from app.services.reconcile import GRACE, REASON, reconcile_interrupted_jobs
from tests.integration.test_final_composition import _seed, _settings

pytestmark = pytest.mark.integration


@pytest.fixture
def storage():
    from app.providers.local.storage import LocalStorageProvider
    from tests.integration.test_final_composition import _STORAGE_ROOT

    return LocalStorageProvider(_STORAGE_ROOT)


async def _job(session, org, campaign, *, status: str, age: timedelta) -> GenerationJobRow:
    """A job of a given age and status, written directly.

    Direct because the point is to simulate a row a *dead process* left behind,
    which no service method can produce on purpose.
    """
    from app.db.models import CanonicalPromptRow, ModelPromptRow

    prompt_row = (
        await session.execute(
            ModelPromptRow.__table__.select().where(ModelPromptRow.campaign_id == campaign.id)
        )
    ).first()
    assert prompt_row is not None, "the fixture campaign has a compiled prompt"
    canonical_row = (
        await session.execute(
            CanonicalPromptRow.__table__.select().where(
                CanonicalPromptRow.campaign_id == campaign.id
            )
        )
    ).first()
    assert canonical_row is not None

    row = GenerationJobRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        model_prompt_id=prompt_row.id,
        specification_id=canonical_row.specification_id,
        specification_version=1,
        batch_id=uuid.uuid4(),
        provider="mock",
        model="mock-image-1",
        status=status,
        idempotency_key=f"key-{uuid.uuid4()}",
        created_at=utc_now() - age,
    )
    session.add(row)
    await session.flush()
    return row


def _old() -> timedelta:
    return timedelta(seconds=_settings().generation_timeout_s) + GRACE + timedelta(minutes=1)


class TestAbandonedJobsAreRecovered:
    async def test_a_running_job_from_a_dead_process_becomes_a_visible_failure(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        job = await _job(
            session, workspace.org, campaign, status=JobStatus.RUNNING.value, age=_old()
        )

        moved = await reconcile_interrupted_jobs(session, _settings())

        assert moved >= 1
        await session.refresh(job)
        assert job.status == JobStatus.FAILED.value
        assert job.error == REASON, "a failure with no reason is as bad as a spinner"
        assert job.finished_at is not None

    async def test_a_pending_job_is_recovered_too(self, session, workspace, storage) -> None:
        """PENDING is worse than RUNNING: the task never even started, so there
        is nothing that could ever move it."""
        campaign, _, _ = await _seed(session, workspace.org, storage)
        job = await _job(
            session, workspace.org, campaign, status=JobStatus.PENDING.value, age=_old()
        )

        await reconcile_interrupted_jobs(session, _settings())

        await session.refresh(job)
        assert job.status == JobStatus.FAILED.value


class TestLiveWorkIsLeftAlone:
    async def test_a_job_inside_the_grace_window_is_untouched(
        self, session, workspace, storage
    ) -> None:
        """The dangerous direction. A restart of one instance must not kill a
        job another instance is still working on."""
        campaign, _, _ = await _seed(session, workspace.org, storage)
        job = await _job(
            session,
            workspace.org,
            campaign,
            status=JobStatus.RUNNING.value,
            age=timedelta(seconds=5),
        )

        await reconcile_interrupted_jobs(session, _settings())

        await session.refresh(job)
        assert job.status == JobStatus.RUNNING.value
        assert job.error is None

    async def test_a_terminal_job_is_never_rewritten(self, session, workspace, storage) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        done = await _job(
            session, workspace.org, campaign, status=JobStatus.COMPLETED.value, age=_old()
        )

        await reconcile_interrupted_jobs(session, _settings())

        await session.refresh(done)
        assert done.status == JobStatus.COMPLETED.value
        assert done.error is None

    async def test_running_it_twice_changes_nothing_the_second_time(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        await _job(session, workspace.org, campaign, status=JobStatus.RUNNING.value, age=_old())

        first = await reconcile_interrupted_jobs(session, _settings())
        second = await reconcile_interrupted_jobs(session, _settings())

        assert first >= 1
        assert second == 0, "startup reconciliation must be idempotent"
