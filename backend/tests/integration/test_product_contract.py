"""Where the application's vocabulary has to match the database's.

Two defects the hyperlocal benchmark surfaced, pinned so they cannot return:

* the `campaigns.status` column and the enum a caller reaches for must agree
* an integrity failure must be reported as the thing that actually happened

Both are only testable against a real database, because both are about what
PostgreSQL does with a write rather than about what Python thinks it will do.
"""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import text

from app.db.models import Membership
from app.domain.common import CampaignRecordStatus, CampaignStatus, Role
from app.errors import AppError, Conflict, NotFound, ValidationFailed
from app.repositories.campaigns import CampaignRepository
from app.repositories.organizations import MembershipRepository
from tests.integration.factories import make_org, make_user

pytestmark = pytest.mark.integration


async def _campaign(session, workspace):
    from app.repositories.brands import BrandRepository

    brands = BrandRepository(session, workspace.org.id)
    brand = await brands.create(
        name=f"Contract {uuid.uuid4().hex[:8]}", payload={}, created_by=None
    )
    campaigns = CampaignRepository(session, workspace.org.id)
    return await campaigns.create(
        brand_id=brand.id, title="Contract test", project_id=None, created_by=None
    )


# ------------------------------------------------------- campaign status
class TestCampaignStatusMatchesTheDatabase:
    """The defect: `CampaignStatus.AWAITING_APPROVAL` exists in Python and is
    rejected by the column, so code that trusted the enum failed at the write.

    The resolution is that they were never the same vocabulary.
    `CampaignStatus` is the graph's, `CampaignRecordStatus` is the column's,
    and these tests hold that line from both ends.
    """

    @pytest.mark.parametrize("status", list(CampaignRecordStatus), ids=lambda s: s.value)
    async def test_the_database_accepts_every_record_status(
        self, session, workspace, status
    ) -> None:
        """The claim that matters: nothing the application may set is refused."""
        campaign = await _campaign(session, workspace)
        campaigns = CampaignRepository(session, workspace.org.id)

        await campaigns.set_status(campaign, status.value)
        await session.flush()

        stored = await campaigns.get(campaign.id)
        assert stored is not None
        assert stored.status == status.value

    async def test_the_constraint_and_the_enum_agree_exactly(self, session) -> None:
        """Both directions.

        A value the database accepts but the enum omits is a state nobody can
        set deliberately; a value the enum offers but the database rejects is
        the original defect. Read from `pg_constraint`, so this is a statement
        about the live schema rather than about the model file.
        """
        sql = (
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = 'campaigns'::regclass and conname like '%status_valid%'"
        )
        definition = (await session.execute(text(sql))).scalar_one()

        # PostgreSQL rewrites `status in (...)` as
        # `status = ANY (ARRAY['DRAFT'::text, ...])`, so pull the quoted
        # literals out rather than assuming the shape it was written in.
        in_database = set(re.findall(r"'([^']+)'", definition))
        assert in_database == {s.value for s in CampaignRecordStatus}

    async def test_a_graph_status_is_refused_by_the_column(self, session, workspace) -> None:
        """The failure that started this, kept as a test.

        `AWAITING_APPROVAL` is a real workflow state and stays in
        `CampaignStatus`; it is simply not something the row may hold. The
        database refusing it is correct behaviour, not a bug to route around.
        """
        from sqlalchemy.exc import IntegrityError

        campaign = await _campaign(session, workspace)
        campaigns = CampaignRepository(session, workspace.org.id)

        assert CampaignStatus.AWAITING_APPROVAL.value not in {s.value for s in CampaignRecordStatus}
        savepoint = await session.begin_nested()
        with pytest.raises(IntegrityError):
            await campaigns.set_status(campaign, CampaignStatus.AWAITING_APPROVAL.value)
        await savepoint.rollback()

    def test_the_two_enums_are_documented_as_different(self) -> None:
        """A comment is the only thing standing between the next reader and
        the same mistake, so assert it is there."""
        assert "campaigns.status" in (CampaignStatus.__doc__ or "")
        assert "CampaignRecordStatus" in (CampaignStatus.__doc__ or "")
        assert "column" in (CampaignRecordStatus.__doc__ or "")

    def test_the_service_constants_come_from_the_enum(self) -> None:
        from app.services import campaigns as service

        assert CampaignRecordStatus.DRAFT.value == service.STATUS_DRAFT
        assert CampaignRecordStatus.INTERVIEWING.value == service.STATUS_INTERVIEWING
        assert CampaignRecordStatus.SPECIFICATION_READY.value == service.STATUS_SPEC_READY
        assert CampaignRecordStatus.SPECIFICATION_CONFIRMED.value == service.STATUS_SPEC_CONFIRMED
        assert CampaignRecordStatus.FAILED.value == service.STATUS_FAILED


# ----------------------------------------------------------- membership
class TestGrantReportsWhatActuallyHappened:
    """The defect: every `IntegrityError` became "already a member", so a bad
    role was reported as a duplicate row that did not exist."""

    async def test_a_valid_grant_succeeds(self, session) -> None:
        user = await make_user(session, email=f"grant-{uuid.uuid4().hex[:8]}@example.test")
        org = await make_org(session)
        await session.flush()

        membership = await MembershipRepository(session).grant(
            user_id=user.id, organization_id=org.id, role=Role.MARKETING.value
        )
        assert membership.role == Role.MARKETING.value

    async def test_a_duplicate_membership_is_a_conflict(self, session) -> None:
        user = await make_user(session, email=f"dup-{uuid.uuid4().hex[:8]}@example.test")
        org = await make_org(session)
        await session.flush()
        memberships = MembershipRepository(session)
        await memberships.grant(user_id=user.id, organization_id=org.id, role=Role.ADMIN.value)

        with pytest.raises(Conflict, match="already a member"):
            await memberships.grant(user_id=user.id, organization_id=org.id, role=Role.ADMIN.value)

    async def test_an_invalid_role_is_a_validation_failure_not_a_conflict(self, session) -> None:
        """The exact mislabelling this fixes. 'ADMIN' is the uppercase form,
        which the check constraint rejects — and which used to be reported as
        a duplicate membership."""
        user = await make_user(session, email=f"role-{uuid.uuid4().hex[:8]}@example.test")
        org = await make_org(session)
        await session.flush()

        with pytest.raises(ValidationFailed) as caught:
            await MembershipRepository(session).grant(
                user_id=user.id, organization_id=org.id, role="ADMIN"
            )
        assert not isinstance(caught.value, Conflict)
        assert Role.ADMIN.value in caught.value.details["allowed"]

    async def test_the_allowed_roles_are_named_in_the_error(self, session) -> None:
        """A rejection that does not say what is allowed makes the caller guess."""
        user = await make_user(session, email=f"roles-{uuid.uuid4().hex[:8]}@example.test")
        org = await make_org(session)
        await session.flush()

        with pytest.raises(ValidationFailed) as caught:
            await MembershipRepository(session).grant(
                user_id=user.id, organization_id=org.id, role="wizard"
            )
        assert set(caught.value.details["allowed"]) == {r.value for r in Role}

    async def test_an_unknown_organization_is_not_found_not_a_conflict(self, session) -> None:
        user = await make_user(session, email=f"fk-{uuid.uuid4().hex[:8]}@example.test")
        await session.flush()

        with pytest.raises(NotFound, match="organization") as caught:
            await MembershipRepository(session).grant(
                user_id=user.id, organization_id=uuid.uuid4(), role=Role.VIEWER.value
            )
        assert not isinstance(caught.value, Conflict)

    async def test_an_unknown_user_is_not_found_not_a_conflict(self, session) -> None:
        org = await make_org(session)
        await session.flush()

        with pytest.raises(NotFound, match="user") as caught:
            await MembershipRepository(session).grant(
                user_id=uuid.uuid4(), organization_id=org.id, role=Role.VIEWER.value
            )
        assert not isinstance(caught.value, Conflict)

    async def test_an_unrecognised_violation_is_never_called_a_duplicate(self) -> None:
        """The general rule, tested directly on the translator.

        A wrong label is worse than a vague one, so anything unrecognised
        stays a plain `AppError` carrying the constraint name.
        """
        from sqlalchemy.exc import IntegrityError

        from app.repositories.organizations import _membership_error

        class _Orig(Exception):
            constraint_name = "ck_memberships_some_future_rule"

        error = _membership_error(IntegrityError("stmt", {}, _Orig()))
        assert type(error) is AppError
        assert not isinstance(error, Conflict | ValidationFailed | NotFound)
        assert "ck_memberships_some_future_rule" in error.message

    async def test_a_failed_grant_leaves_the_session_usable(self, session) -> None:
        """The savepoint earns its place: a caller that handles the conflict
        must be able to carry on."""
        user = await make_user(session, email=f"sp-{uuid.uuid4().hex[:8]}@example.test")
        org_a = await make_org(session)
        org_b = await make_org(session)
        await session.flush()
        memberships = MembershipRepository(session)

        await memberships.grant(user_id=user.id, organization_id=org_a.id, role=Role.ADMIN.value)
        with pytest.raises(Conflict):
            await memberships.grant(
                user_id=user.id, organization_id=org_a.id, role=Role.ADMIN.value
            )

        # The session still works.
        second = await memberships.grant(
            user_id=user.id, organization_id=org_b.id, role=Role.VIEWER.value
        )
        assert isinstance(second, Membership)
        assert await memberships.role_in(user.id, org_b.id) == Role.VIEWER.value
