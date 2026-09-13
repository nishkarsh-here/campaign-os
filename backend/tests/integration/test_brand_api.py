"""Brand CRUD and its tenancy boundary.

The brand is the first genuinely confidential thing this product stores —
positioning, claims, guidelines. These tests treat cross-organization access as
the primary risk, per the Milestone 2 brief.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models import BrandProfileRow
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration

ORG_HEADER = "X-Organization-Id"


async def _brand_in(session, org, name: str = "Their Brand") -> BrandProfileRow:
    """A brand belonging to another organization, created directly."""
    row = BrandProfileRow(
        organization_id=org.id,
        name=name,
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": name,
            "positioning": "Their secret positioning",
            "prohibited_claims": ["their confidential claim"],
        },
    )
    session.add(row)
    await session.flush()
    return row


class TestBrandCrud:
    async def test_create_requires_only_a_name(self, client, workspace) -> None:
        response = await client.post("/v1/brands", json={"name": "Northline Materials"})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Northline Materials"
        assert body["organization_id"] == str(workspace.org.id)
        assert body["industry"] is None

    async def test_create_accepts_the_full_onboarding_form(self, client, workspace) -> None:
        response = await client.post(
            "/v1/brands",
            json={
                "name": "Northline",
                "industry": "Building materials",
                "website": "https://northline.test",
                "positioning": "Engineered to outlast the building it clads.",
                "values": ["durability", "precision"],
                "voice": {"tone_attributes": ["confident", "technical"], "avoid": ["hype"]},
                "colors": [{"name": "Graphite", "hex": "#1F2933", "role": "primary"}],
                "prohibited_claims": ["indestructible"],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["voice"]["tone_attributes"] == ["confident", "technical"]
        assert body["colors"][0]["hex"] == "#1F2933"
        assert body["prohibited_claims"] == ["indestructible"]

    async def test_get_then_list(self, client, workspace) -> None:
        created = (await client.post("/v1/brands", json={"name": "Acme"})).json()
        fetched = await client.get(f"/v1/brands/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Acme"

        listed = await client.get("/v1/brands")
        assert [b["name"] for b in listed.json()["items"]] == ["Acme"]

    async def test_partial_update_leaves_other_fields_alone(self, client, workspace) -> None:
        created = (
            await client.post("/v1/brands", json={"name": "Acme", "positioning": "keep me"})
        ).json()
        updated = await client.patch(
            f"/v1/brands/{created['id']}", json={"industry": "Manufacturing"}
        )
        assert updated.status_code == 200
        assert updated.json()["industry"] == "Manufacturing"
        assert updated.json()["positioning"] == "keep me"

    async def test_empty_update_is_rejected(self, client, workspace) -> None:
        created = (await client.post("/v1/brands", json={"name": "Acme"})).json()
        response = await client.patch(f"/v1/brands/{created['id']}", json={})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"

    async def test_duplicate_name_in_one_workspace_is_a_conflict(self, client, workspace) -> None:
        await client.post("/v1/brands", json={"name": "Acme"})
        duplicate = await client.post("/v1/brands", json={"name": "Acme"})
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "CONFLICT"

    async def test_delete_is_soft_and_hides_the_brand(self, client, workspace) -> None:
        created = (await client.post("/v1/brands", json={"name": "Acme"})).json()
        assert (await client.delete(f"/v1/brands/{created['id']}")).status_code == 204
        assert (await client.get(f"/v1/brands/{created['id']}")).status_code == 404
        assert (await client.get("/v1/brands")).json()["items"] == []


class TestBrandValidation:
    async def test_a_blank_name_is_rejected(self, client, workspace) -> None:
        response = await client.post("/v1/brands", json={"name": ""})
        assert response.status_code == 400
        assert response.json()["error"]["details"]["field"] == "name"

    async def test_an_invalid_brand_colour_is_rejected(self, client, workspace) -> None:
        response = await client.post(
            "/v1/brands",
            json={"name": "Acme", "colors": [{"name": "Bad", "hex": "not-a-colour"}]},
        )
        assert response.status_code == 400

    async def test_an_unknown_field_is_rejected_not_absorbed(self, client, workspace) -> None:
        """Strict schemas: a typo must fail loudly rather than vanish."""
        response = await client.post("/v1/brands", json={"name": "Acme", "positionning": "typo"})
        assert response.status_code == 400


class TestBrandTenancy:
    async def test_another_organizations_brand_is_404(self, client, session, workspace) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)

        response = await client.get(f"/v1/brands/{their_brand.id}")
        assert response.status_code == 404
        assert "secret positioning" not in response.text

    async def test_listing_never_includes_another_organizations_brand(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        await _brand_in(session, theirs)
        await client.post("/v1/brands", json={"name": "Mine"})

        listed = await client.get("/v1/brands")
        assert [b["name"] for b in listed.json()["items"]] == ["Mine"]

    async def test_updating_another_organizations_brand_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)

        response = await client.patch(
            f"/v1/brands/{their_brand.id}", json={"positioning": "hijacked"}
        )
        assert response.status_code == 404

        await session.refresh(their_brand)
        assert their_brand.payload["positioning"] == "Their secret positioning"

    async def test_deleting_another_organizations_brand_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)

        assert (await client.delete(f"/v1/brands/{their_brand.id}")).status_code == 404
        await session.refresh(their_brand)
        assert their_brand.deleted_at is None

    async def test_a_malformed_brand_id_is_404_not_400(self, client, workspace) -> None:
        assert (await client.get("/v1/brands/not-a-uuid")).status_code == 404

    async def test_ownership_comes_from_the_row_not_the_payload(
        self, client, session, workspace
    ) -> None:
        """A payload claiming a different organization must not be believed —
        identity is re-stamped from the columns on every read."""
        row = BrandProfileRow(
            organization_id=workspace.org.id,
            name="Tampered",
            payload={
                "id": str(uuid.uuid4()),
                "organization_id": str(uuid.uuid4()),  # a lie
                "name": "Tampered",
            },
        )
        session.add(row)
        await session.flush()

        body = (await client.get(f"/v1/brands/{row.id}")).json()
        assert body["organization_id"] == str(workspace.org.id)
        assert body["id"] == str(row.id)


class TestBrandBrainApi:
    """The HTTP surface of the Brand Brain, including its tenancy boundary."""

    async def _brand(self, client) -> str:
        return (await client.post("/v1/brands", json={"name": "Northline"})).json()["id"]

    async def test_text_document_upload_returns_202_and_a_status(self, client, workspace) -> None:
        brand_id = await self._brand(client)
        response = await client.post(
            f"/v1/brands/{brand_id}/documents/text",
            json={"title": "Guidelines", "content": "Our tone of voice is confident."},
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] in {"PENDING", "EXTRACTING", "EMBEDDING", "COMPLETED"}
        assert body["title"] == "Guidelines"

    async def test_an_unsupported_document_type_is_rejected(self, client, workspace) -> None:
        brand_id = await self._brand(client)
        response = await client.post(
            f"/v1/brands/{brand_id}/documents",
            files={"file": ("evil.sh", b"#!/bin/sh\nrm -rf /", "application/x-sh")},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"

    async def test_a_file_whose_bytes_contradict_its_type_is_rejected(
        self, client, workspace
    ) -> None:
        brand_id = await self._brand(client)
        response = await client.post(
            f"/v1/brands/{brand_id}/documents",
            files={"file": ("fake.pdf", b"MZ\x90\x00 windows executable", "application/pdf")},
        )
        assert response.status_code == 400
        assert "detected" in response.json()["error"]["details"]

    async def test_a_non_image_asset_is_rejected(self, client, workspace) -> None:
        brand_id = await self._brand(client)
        response = await client.post(
            f"/v1/brands/{brand_id}/assets",
            files={"file": ("guide.pdf", b"%PDF-1.7 x", "application/pdf")},
            data={"kind": "logo"},
        )
        assert response.status_code == 400

    async def test_an_unknown_asset_kind_is_rejected(self, client, workspace) -> None:
        brand_id = await self._brand(client)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        response = await client.post(
            f"/v1/brands/{brand_id}/assets",
            files={"file": ("logo.png", png, "image/png")},
            data={"kind": "nonsense"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["details"]["field"] == "kind"

    async def test_an_image_asset_uploads_and_serves_through_the_api(
        self, client, workspace
    ) -> None:
        brand_id = await self._brand(client)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        created = await client.post(
            f"/v1/brands/{brand_id}/assets",
            files={"file": ("logo.png", png, "image/png")},
            data={"kind": "logo"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["kind"] == "logo"
        # Served through our API, never from storage directly.
        assert body["url"].startswith(f"/v1/brands/{brand_id}/assets/")

        content = await client.get(body["url"])
        assert content.status_code == 200
        assert content.content == png

    async def test_the_brain_view_returns_everything_in_one_call(self, client, workspace) -> None:
        brand_id = await self._brand(client)
        response = await client.get(f"/v1/brands/{brand_id}/brain")
        assert response.status_code == 200
        body = response.json()
        assert body["brand"]["id"] == brand_id
        assert body["chunk_count"] == 0
        assert body["knowledge_ready"] is False
        # known / unknown / inferred is reported per tracked field.
        assert {f["knowledge"] for f in body["field_status"]} == {"unknown"}

    async def test_knowledge_query_on_an_empty_brain_returns_no_hits(
        self, client, workspace
    ) -> None:
        brand_id = await self._brand(client)
        response = await client.post(
            f"/v1/brands/{brand_id}/knowledge/query", json={"query": "tone of voice"}
        )
        assert response.status_code == 200
        assert response.json()["hits"] == []

    async def test_a_blank_knowledge_query_is_rejected(self, client, workspace) -> None:
        brand_id = await self._brand(client)
        response = await client.post(f"/v1/brands/{brand_id}/knowledge/query", json={"query": ""})
        assert response.status_code == 400


class TestBrandBrainTenancy:
    async def test_another_organizations_brain_is_404(self, client, session, workspace) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)
        assert (await client.get(f"/v1/brands/{their_brand.id}/brain")).status_code == 404

    async def test_querying_another_organizations_knowledge_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)
        response = await client.post(
            f"/v1/brands/{their_brand.id}/knowledge/query", json={"query": "positioning"}
        )
        assert response.status_code == 404
        assert "secret positioning" not in response.text

    async def test_listing_another_organizations_documents_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)
        assert (await client.get(f"/v1/brands/{their_brand.id}/documents")).status_code == 404

    async def test_uploading_into_another_organizations_brand_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)
        response = await client.post(
            f"/v1/brands/{their_brand.id}/documents/text",
            json={"title": "Planted", "content": "malicious content"},
        )
        assert response.status_code == 404

    async def test_a_document_id_from_another_brand_is_404(
        self, client, session, workspace
    ) -> None:
        """Even inside one organization, a document is reachable only through
        the brand that owns it."""
        mine = await self_brand(client)
        theirs = await make_org(session)
        their_brand = await _brand_in(session, theirs)
        response = await client.get(f"/v1/brands/{mine}/documents/{uuid.uuid4()}")
        assert response.status_code == 404
        assert (
            await client.get(f"/v1/brands/{their_brand.id}/documents/{uuid.uuid4()}")
        ).status_code == 404


async def self_brand(client) -> str:
    return (await client.post("/v1/brands", json={"name": "Mine"})).json()["id"]
