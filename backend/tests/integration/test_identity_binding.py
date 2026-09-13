"""Identity binding.

Regression tests for M1_SECURITY_AUDIT finding A-1. `upsert_from_identity`
resolved `by_subject(subject) or by_email(email)`, so an identity provider that
asserted a victim's email address was handed the victim's user row — and with
it every organization the victim belonged to.

These tests pin the rule that replaced it: **the subject is the identity, the
email is a profile attribute.**
"""

from __future__ import annotations

import pytest

from app.errors import Conflict
from app.repositories.organizations import MembershipRepository, UserRepository
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration


class TestIdentityIsTheSubject:
    async def test_a_known_subject_returns_the_same_user(self, session) -> None:
        users = UserRepository(session)
        first = await users.upsert_from_identity(
            subject="idp|alice", email="alice@corp.test", display_name="Alice"
        )
        again = await users.upsert_from_identity(
            subject="idp|alice", email="alice@corp.test", display_name="Alice"
        )
        assert first.id == again.id

    async def test_an_unknown_subject_with_a_taken_email_is_refused(self, session) -> None:
        """The account-takeover path. A second identity asserting an existing
        user's email must NOT be given that user's account."""
        users = UserRepository(session)
        victim = await users.upsert_from_identity(
            subject="idp|victim", email="victim@corp.test", display_name="Victim"
        )

        # A savepoint, so the expected flush failure rolls back only the
        # attempted insert and the session stays usable for the assertions.
        savepoint = await session.begin_nested()
        with pytest.raises(Conflict):
            await users.upsert_from_identity(
                subject="idp|attacker", email="victim@corp.test", display_name="Attacker"
            )
        await savepoint.rollback()

        # The victim's row is untouched and still bound to the victim's subject.
        still = await UserRepository(session).by_email("victim@corp.test")
        assert still is not None
        assert still.auth_subject == "idp|victim"
        assert still.id == victim.id

    async def test_an_attacker_cannot_inherit_the_victims_memberships(self, session) -> None:
        """The consequence that made this critical rather than cosmetic."""
        users = UserRepository(session)
        memberships = MembershipRepository(session)
        org = await make_org(session)
        victim = await users.upsert_from_identity(
            subject="idp|victim2", email="v2@corp.test", display_name="Victim"
        )
        await memberships.grant(user_id=victim.id, organization_id=org.id, role="admin")

        savepoint = await session.begin_nested()
        with pytest.raises(Conflict):
            await users.upsert_from_identity(
                subject="idp|attacker2", email="v2@corp.test", display_name="Attacker"
            )
        await savepoint.rollback()

        # Membership still belongs to exactly one user: the victim.
        assert await MembershipRepository(session).role_in(victim.id, org.id) == "admin"

    async def test_an_unclaimed_email_no_longer_grants_a_free_account_claim(self, session) -> None:
        """A row with no auth_subject (seeded, invited, imported) used to be
        claimable by anyone whose provider asserted that email."""
        from app.db.models import User

        orphan = User(email="orphan@corp.test", display_name="Orphan", auth_subject=None)
        session.add(orphan)
        await session.flush()

        savepoint = await session.begin_nested()
        with pytest.raises(Conflict):
            await UserRepository(session).upsert_from_identity(
                subject="idp|opportunist", email="orphan@corp.test", display_name="Nope"
            )
        await savepoint.rollback()

    async def test_the_same_person_under_a_new_subject_is_a_conflict_not_a_merge(
        self, session
    ) -> None:
        """Genuine provider migration is an explicit, deliberate operation —
        not something a login silently performs."""
        users = UserRepository(session)
        await users.upsert_from_identity(
            subject="dev-stub:bob@corp.test", email="bob@corp.test", display_name="Bob"
        )
        savepoint = await session.begin_nested()
        with pytest.raises(Conflict):
            await users.upsert_from_identity(
                subject="supabase|bob", email="bob@corp.test", display_name="Bob"
            )
        await savepoint.rollback()


class TestProvisioning:
    async def test_a_brand_new_subject_is_provisioned(self, session) -> None:
        user = await UserRepository(session).upsert_from_identity(
            subject="idp|new", email="new@corp.test", display_name="New"
        )
        assert user.id is not None
        assert user.auth_subject == "idp|new"

    async def test_a_missing_display_name_is_filled_in_later(self, session) -> None:
        users = UserRepository(session)
        await users.upsert_from_identity(
            subject="idp|noname", email="noname@corp.test", display_name=None
        )
        updated = await users.upsert_from_identity(
            subject="idp|noname", email="noname@corp.test", display_name="Now Named"
        )
        assert updated.display_name == "Now Named"

    async def test_an_existing_display_name_is_not_overwritten(self, session) -> None:
        users = UserRepository(session)
        await users.upsert_from_identity(
            subject="idp|named", email="named@corp.test", display_name="Chosen"
        )
        updated = await users.upsert_from_identity(
            subject="idp|named", email="named@corp.test", display_name="From IdP"
        )
        assert updated.display_name == "Chosen"
