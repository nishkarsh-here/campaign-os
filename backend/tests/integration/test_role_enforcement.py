"""Role enforcement over HTTP, with real memberships.

Audit finding A-1. `tests/test_authz.py` pins the matrix and the coverage; this
asserts that a request actually gets refused, through the whole stack — the same
`curl` that used to let a `viewer` approve a campaign.

**How the permitted case is asserted.** The capability check is a dependency, so
it runs before the handler and before any row is looked up. A refused caller is
therefore a `403` whether or not the campaign exists, and a permitted caller on
a campaign that does not exist is a `404`. So the assertion is "not 403": it
proves the guard let them past, without each row of the table having to seed a
whole campaign. Where a route needs no pre-existing resource — projects — the
success is executed for real.

One user with five memberships, one per role, because that is also the shape
that catches the worst possible bug here: a role leaking across organizations.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common import Role
from tests.integration.factories import make_membership, make_org

pytestmark = pytest.mark.integration

ORG_HEADER = "X-Organization-Id"

#: One representative route per capability, chosen because the guard sits on the
#: dependency and so needs no fixture to reach.
ROUTES: dict[str, tuple[str, str, dict]] = {
    "edit_campaign": ("POST", "/v1/campaigns/{campaign}/generation/start", {}),
    "request_revision": ("POST", "/v1/campaigns/{campaign}/revision", {"feedback": "warmer"}),
    "approve": ("POST", "/v1/campaigns/{campaign}/revision/approve", {}),
    "edit_brand": ("POST", "/v1/brands", {"name": "Probe"}),
    "manage_workspace": ("POST", "/v1/projects", {"name": "Probe"}),
}

#: Mirrors `app.api.authz.MATRIX`, written out again on purpose: a table copied
#: from the code under test asserts only that the code equals itself.
GRANTS: dict[Role, set[str]] = {
    Role.ADMIN: {"edit_campaign", "request_revision", "approve", "edit_brand", "manage_workspace"},
    Role.BRAND_MANAGER: {"edit_campaign", "request_revision", "approve", "edit_brand"},
    Role.MARKETING: {"edit_campaign", "request_revision", "approve"},
    Role.DESIGNER: {"edit_campaign", "request_revision"},
    Role.VIEWER: set(),
}

ABSENT_CAMPAIGN = "00000000-0000-0000-0000-00000000dead"


@pytest.fixture
async def orgs_by_role(session: AsyncSession, workspace) -> dict[Role, str]:
    """The dev stub's user, a member of one organization per role."""
    resolved: dict[Role, str] = {}
    for role in Role:
        org = await make_org(session, slug=f"role-{role.value}")
        await make_membership(session, workspace.user, org, role=role.value)
        resolved[role] = str(org.id)
    await session.commit()
    return resolved


async def _call(client: AsyncClient, capability: str, org_id: str):
    method, template, body = ROUTES[capability]
    return await client.request(
        method,
        template.format(campaign=ABSENT_CAMPAIGN),
        json=body,
        headers={ORG_HEADER: org_id},
    )


class TestEveryRoleAgainstEveryCapability:
    @pytest.mark.parametrize("role", list(Role))
    @pytest.mark.parametrize("capability", list(ROUTES))
    async def test_the_route_refuses_exactly_the_roles_the_matrix_refuses(
        self, client: AsyncClient, orgs_by_role: dict[Role, str], role: Role, capability: str
    ) -> None:
        response = await _call(client, capability, orgs_by_role[role])
        permitted = capability in GRANTS[role]
        if permitted:
            assert response.status_code != 403, (
                f"{role.value} should be allowed to {capability}, got {response.text}"
            )
        else:
            assert response.status_code == 403, (
                f"{role.value} must not be allowed to {capability}, got {response.status_code}"
            )


class TestTheRefusalIsReadable:
    async def test_a_viewer_is_told_their_role_and_what_it_lacks(
        self, client: AsyncClient, orgs_by_role: dict[Role, str]
    ) -> None:
        response = await _call(client, "edit_campaign", orgs_by_role[Role.VIEWER])

        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "FORBIDDEN"
        assert "viewer" in error["message"]
        assert error["details"]["required_capability"] == "edit_campaign"

    async def test_a_designer_is_refused_an_approval_but_not_a_revision(
        self, client: AsyncClient, orgs_by_role: dict[Role, str]
    ) -> None:
        """The product decision, end to end."""
        designer = orgs_by_role[Role.DESIGNER]

        assert (await _call(client, "approve", designer)).status_code == 403
        assert (await _call(client, "request_revision", designer)).status_code != 403


class TestAPermittedCallerActuallySucceeds:
    """Not just "not 403" — one route run to completion, so the guard is shown
    to let real work through rather than merely failing later."""

    async def test_an_admin_creates_a_project(
        self, client: AsyncClient, orgs_by_role: dict[Role, str]
    ) -> None:
        response = await client.post(
            "/v1/projects",
            json={"name": "Spring launch"},
            headers={ORG_HEADER: orgs_by_role[Role.ADMIN]},
        )
        assert response.status_code == 201, response.text
        assert response.json()["name"] == "Spring launch"

    async def test_a_marketing_member_cannot(
        self, client: AsyncClient, orgs_by_role: dict[Role, str]
    ) -> None:
        response = await client.post(
            "/v1/projects",
            json={"name": "Spring launch"},
            headers={ORG_HEADER: orgs_by_role[Role.MARKETING]},
        )
        assert response.status_code == 403


class TestReadsAreNotRestricted:
    """A viewer is a viewer. Adding role checks to reads would be a new product
    decision, and this pins that none was made."""

    @pytest.mark.parametrize(
        "path", ["/v1/projects", "/v1/brands", "/v1/campaigns", "/v1/organizations/current"]
    )
    async def test_a_viewer_may_still_read(
        self, client: AsyncClient, orgs_by_role: dict[Role, str], path: str
    ) -> None:
        response = await client.get(path, headers={ORG_HEADER: orgs_by_role[Role.VIEWER]})
        assert response.status_code == 200, response.text


class TestARoleDoesNotCrossOrganizations:
    """The failure that would be worse than having no enforcement at all."""

    async def test_admin_in_one_organization_is_only_a_viewer_in_another(
        self, client: AsyncClient, orgs_by_role: dict[Role, str]
    ) -> None:
        admin_org = orgs_by_role[Role.ADMIN]
        viewer_org = orgs_by_role[Role.VIEWER]

        assert (await _call(client, "manage_workspace", admin_org)).status_code == 201
        assert (await _call(client, "manage_workspace", viewer_org)).status_code == 403

    async def test_an_organization_the_caller_does_not_belong_to_is_still_404(
        self, client: AsyncClient, session: AsyncSession, orgs_by_role: dict[Role, str]
    ) -> None:
        """Authorization narrows; it never replaces tenancy. A non-member must
        keep learning nothing about whether the organization exists."""
        stranger = await make_org(session, slug="not-mine")
        await session.commit()

        response = await _call(client, "manage_workspace", str(stranger.id))

        assert response.status_code == 404
