"""API contract tests for the Milestone 1 surface.

Covers the happy path, the error envelope, and — most importantly — that a
resource in another organization is invisible over HTTP, not merely at the
repository layer.
"""

from __future__ import annotations

import uuid

import pytest

from tests.integration.factories import make_membership, make_org, make_project, make_user

pytestmark = pytest.mark.integration

ORG_HEADER = "X-Organization-Id"


async def _workspace(session):
    """A user with exactly one organization — the dev-stub shape."""
    user = await make_user(session, email="demo@campaign-os.local")
    user.auth_subject = "dev-stub:demo@campaign-os.local"
    org = await make_org(session)
    await make_membership(session, user, org)
    await session.flush()
    return user, org


class TestHealth:
    async def test_health_reports_database_and_providers(self, client) -> None:
        response = await client.get("/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        # Health is where a misconfigured provider becomes visible in one call.
        assert body["providers"]["image"] == "mock"
        assert body["providers"]["auth"] == "dev_stub"

    async def test_every_response_carries_a_request_id(self, client) -> None:
        response = await client.get("/v1/health")
        assert response.headers["X-Request-Id"]

    async def test_an_inbound_request_id_is_preserved(self, client) -> None:
        response = await client.get("/v1/health", headers={"X-Request-Id": "trace-abc"})
        assert response.headers["X-Request-Id"] == "trace-abc"


class TestMe:
    async def test_me_returns_the_caller_and_their_organizations(self, client, session) -> None:
        _, org = await _workspace(session)
        response = await client.get("/v1/me")
        assert response.status_code == 200
        body = response.json()
        assert body["user"]["email"] == "demo@campaign-os.local"
        assert [m["organization"]["id"] for m in body["organizations"]] == [str(org.id)]
        assert body["active_organization_id"] == str(org.id)

    async def test_me_works_before_any_organization_is_chosen(self, client, session) -> None:
        """The shell calls /me *to discover* organizations, so it must not
        itself require one to be resolved.

        The seeded user carries the dev stub's subject. It previously carried
        a different one and was still matched by email — the behaviour removed
        by M1_SECURITY_AUDIT finding A-1.
        """
        user = await make_user(session, email="demo@campaign-os.local")
        user.auth_subject = "dev-stub:demo@campaign-os.local"
        await session.flush()

        response = await client.get("/v1/me")
        assert response.status_code == 200
        assert response.json()["organizations"] == []


class TestProjectsCrud:
    async def test_create_then_read_then_list(self, client, session) -> None:
        await _workspace(session)

        created = await client.post("/v1/projects", json={"name": "Launch campaign"})
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]

        fetched = await client.get(f"/v1/projects/{project_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Launch campaign"

        listed = await client.get("/v1/projects")
        assert [p["id"] for p in listed.json()["items"]] == [project_id]
        assert listed.json()["next_cursor"] is None

    async def test_update_changes_only_what_was_sent(self, client, session) -> None:
        await _workspace(session)
        created = await client.post(
            "/v1/projects", json={"name": "Original", "description": "keep me"}
        )
        project_id = created.json()["id"]

        updated = await client.patch(f"/v1/projects/{project_id}", json={"name": "Renamed"})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Renamed"
        assert updated.json()["description"] == "keep me"

    async def test_empty_update_is_rejected(self, client, session) -> None:
        await _workspace(session)
        project_id = (await client.post("/v1/projects", json={"name": "P"})).json()["id"]
        response = await client.patch(f"/v1/projects/{project_id}", json={})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"

    async def test_delete_is_soft_and_hides_the_project(self, client, session) -> None:
        await _workspace(session)
        project_id = (await client.post("/v1/projects", json={"name": "P"})).json()["id"]

        assert (await client.delete(f"/v1/projects/{project_id}")).status_code == 204
        assert (await client.get(f"/v1/projects/{project_id}")).status_code == 404
        assert (await client.get("/v1/projects")).json()["items"] == []

    async def test_pagination_walks_every_project_once(self, client, session) -> None:
        await _workspace(session)
        for i in range(5):
            await client.post("/v1/projects", json={"name": f"P{i}"})

        seen: list[str] = []
        cursor = None
        for _ in range(10):  # bounded, so a broken cursor cannot loop forever
            url = f"/v1/projects?limit=2{f'&cursor={cursor}' if cursor else ''}"
            page = (await client.get(url)).json()
            seen.extend(p["name"] for p in page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert sorted(seen) == ["P0", "P1", "P2", "P3", "P4"]

    async def test_a_malformed_cursor_is_a_clean_400(self, client, session) -> None:
        await _workspace(session)
        response = await client.get("/v1/projects?cursor=not-base64!!")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"


class TestCrossOrganizationOverHttp:
    async def test_another_organizations_project_is_404_not_403(self, client, session) -> None:
        """404, never 403: a caller must not be able to learn that a resource
        exists (API_SPEC §Scope)."""
        await _workspace(session)
        theirs = await make_org(session)
        their_project = await make_project(session, theirs, name="Their project")

        response = await client.get(f"/v1/projects/{their_project.id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
        assert "Their project" not in response.text

    async def test_updating_another_organizations_project_is_404(self, client, session) -> None:
        """PATCH was the one mutation with no cross-tenant probe. The handler
        resolves through the scoped repository, so this passes — the test
        exists so a future refactor cannot quietly remove that."""
        await _workspace(session)
        theirs = await make_org(session)
        their_project = await make_project(session, theirs, name="Their project")

        response = await client.patch(
            f"/v1/projects/{their_project.id}", json={"name": "Renamed by an outsider"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    async def test_an_outsider_patch_does_not_mutate_the_row(self, client, session) -> None:
        await _workspace(session)
        theirs = await make_org(session)
        their_project = await make_project(session, theirs, name="Untouched")

        await client.patch(f"/v1/projects/{their_project.id}", json={"name": "Hijacked"})

        await session.refresh(their_project)
        assert their_project.name == "Untouched"

    async def test_deleting_another_organizations_project_is_404(self, client, session) -> None:
        await _workspace(session)
        theirs = await make_org(session)
        their_project = await make_project(session, theirs)

        assert (await client.delete(f"/v1/projects/{their_project.id}")).status_code == 404

    async def test_an_unknown_organization_header_is_404(self, client, session) -> None:
        await _workspace(session)
        response = await client.get("/v1/projects", headers={ORG_HEADER: str(uuid.uuid4())})
        assert response.status_code == 404

    async def test_a_malformed_organization_header_is_404(self, client, session) -> None:
        await _workspace(session)
        response = await client.get("/v1/projects", headers={ORG_HEADER: "not-a-uuid"})
        assert response.status_code == 404

    async def test_belonging_to_several_organizations_requires_choosing(
        self, client, session
    ) -> None:
        user, _ = await _workspace(session)
        second = await make_org(session)
        await make_membership(session, user, second)
        await session.flush()

        ambiguous = await client.get("/v1/projects")
        assert ambiguous.status_code == 403
        assert ORG_HEADER in ambiguous.json()["error"]["message"]

        resolved = await client.get("/v1/projects", headers={ORG_HEADER: str(second.id)})
        assert resolved.status_code == 200


class TestErrorEnvelope:
    async def test_every_error_has_the_documented_shape(self, client, session) -> None:
        await _workspace(session)
        body = (await client.get(f"/v1/projects/{uuid.uuid4()}")).json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"code", "message", "details", "request_id"}
        assert body["error"]["request_id"]

    async def test_validation_failure_names_the_field(self, client, session) -> None:
        await _workspace(session)
        response = await client.post("/v1/projects", json={"name": ""})
        assert response.status_code == 400
        assert response.json()["error"]["details"]["field"] == "name"
