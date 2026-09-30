"""Index `memberships.user_id`.

Audit finding PERF-2. `GET /v1/me` lists the caller's memberships by `user_id`
alone (`MembershipRepository.organizations_for_user`), and every screen in the
product calls it. The only index on the table was the unique constraint on
`(organization_id, user_id)`, whose leading column is the wrong one for that
query, so it was a sequential scan on every page load.

Resolving a request's principal filters on both columns and could already use
the unique index, so this changes nothing about how scope is enforced — it adds
an index and nothing else. No column, no constraint, no data.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_memberships_user_index"
down_revision: str | None = "0009_final_composition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_memberships_user_id", table_name="memberships")
