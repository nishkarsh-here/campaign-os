"""Campaign discovery over HTTP, and its tenancy boundary.

A campaign carries a brand's confidential positioning into a conversation, so
cross-organization access is the primary risk here as it was for brands.
"""

from __future__ import annotations

import itertools
import tempfile
import uuid

import pytest

from app.config import Settings, get_settings
from app.db.models import BrandProfileRow, CampaignRow
from app.domain.common import Role
from app.domain.workspace import Principal, User
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.evaluation import CreativeEvaluationRepository
from app.repositories.revision import BrandGuardianRepository
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration


async def _brand_row(session, org, name: str = "Northline") -> BrandProfileRow:
    row = BrandProfileRow(
        organization_id=org.id,
        name=name,
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": name,
            "positioning": "Their secret positioning",
            "audience_description": "Architects and contractors",
        },
    )
    session.add(row)
    await session.flush()
    return row


async def _campaign_row(session, org, brand, title: str = "Their campaign") -> CampaignRow:
    campaign_id = uuid.uuid4()
    row = CampaignRow(
        id=campaign_id,
        organization_id=org.id,
        brand_profile_id=brand.id,
        title=title,
        status="DRAFT",
        thread_id=str(campaign_id),
        draft_inputs={"key_message": "their confidential message"},
    )
    session.add(row)
    await session.flush()
    return row


_BRAND_SEQUENCE = itertools.count(1)

#: Generation and evaluation both run in background tasks, which the harness
#: stubs out (see conftest): the test session lives in a rolled-back
#: transaction a background session could not see. These helpers drive the same
#: service code on the test session instead, so the HTTP tests still assert
#: against real results rather than mocked ones.
_TEST_STORAGE_ROOT = tempfile.mkdtemp(prefix="campaign-os-api-tests-")


def _test_settings() -> Settings:
    base = get_settings().model_dump()
    base.update({"image_provider": "mock", "image_providers": "", "mock_failure_mode": "none"})
    return Settings(**base)


def _test_storage() -> LocalStorageProvider:
    return LocalStorageProvider(_TEST_STORAGE_ROOT)


def _principal_for(workspace) -> Principal:
    return Principal(
        user=User(id=str(workspace.user.id), email=workspace.user.email),
        organization_id=str(workspace.org.id),
        role=Role.ADMIN,
    )


async def _run_guardian(
    session, workspace, campaign_id: str, *, failure_mode: str = "none"
) -> None:
    """Run the claimed brand checks on the test session."""
    from app.services.revision_stage import RevisionStageService

    service = RevisionStageService(
        session,
        _principal_for(workspace),
        settings=_test_settings(),
        storage=_test_storage(),
        llm=MockLLMProvider(failure_mode),
        embeddings=MockEmbeddingProvider(),
    )
    rows = await BrandGuardianRepository(session, workspace.org.id).for_campaign(
        uuid.UUID(campaign_id)
    )
    await service.run_guardian_checks([row.id for row in rows])


async def _run_evaluations(
    session, workspace, campaign_id: str, *, failure_mode: str = "none"
) -> None:
    """Run the claimed evaluations on the test session."""
    from app.services.evaluation_stage import EvaluationService

    service = EvaluationService(
        session,
        _principal_for(workspace),
        settings=_test_settings(),
        storage=_test_storage(),
        llm=MockLLMProvider(failure_mode),
        embeddings=MockEmbeddingProvider(),
    )
    rows = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
        uuid.UUID(campaign_id)
    )
    await service.run_evaluations([row.id for row in rows])


async def _my_brand(client, name: str | None = None) -> str:
    """A brand in the caller's organization. Names are unique per workspace,
    so successive calls get distinct ones."""
    label = name or f"Northline {next(_BRAND_SEQUENCE)}"
    response = await client.post("/v1/brands", json={"name": label})
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestCampaignCrud:
    async def test_create_requires_a_brand(self, client, workspace) -> None:
        brand_id = await _my_brand(client)
        response = await client.post(
            "/v1/campaigns", json={"brand_id": brand_id, "title": "Maharashtra launch"}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "Maharashtra launch"
        assert body["brand_id"] == brand_id
        assert body["status"] == "DRAFT"

    async def test_get_then_list(self, client, workspace) -> None:
        brand_id = await _my_brand(client)
        created = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"})
        ).json()

        fetched = await client.get(f"/v1/campaigns/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["title"] == "Launch"

        listed = await client.get("/v1/campaigns")
        assert [c["id"] for c in listed.json()["items"]] == [created["id"]]

    async def test_listing_can_filter_by_brand(self, client, workspace) -> None:
        first = await _my_brand(client)
        second = (await client.post("/v1/brands", json={"name": "Other"})).json()["id"]
        await client.post("/v1/campaigns", json={"brand_id": first, "title": "A"})
        await client.post("/v1/campaigns", json={"brand_id": second, "title": "B"})

        listed = await client.get(f"/v1/campaigns?brand_id={second}")
        assert [c["title"] for c in listed.json()["items"]] == ["B"]

    async def test_a_blank_title_is_rejected(self, client, workspace) -> None:
        brand_id = await _my_brand(client)
        response = await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": ""})
        assert response.status_code == 400

    async def test_a_malformed_campaign_id_is_404(self, client, workspace) -> None:
        assert (await client.get("/v1/campaigns/not-a-uuid")).status_code == 404


class TestBrandSelectionIsScoped:
    async def test_a_campaign_cannot_select_another_organizations_brand(
        self, client, session, workspace
    ) -> None:
        """The brand is resolved through the scoped repository, so a foreign
        brand id is indistinguishable from one that does not exist."""
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs, name="Competitor")

        response = await client.post(
            "/v1/campaigns", json={"brand_id": str(their_brand.id), "title": "Sneaky"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    async def test_an_unknown_brand_id_is_404(self, client, workspace) -> None:
        response = await client.post(
            "/v1/campaigns", json={"brand_id": str(uuid.uuid4()), "title": "X"}
        )
        assert response.status_code == 404


class TestCampaignTenancy:
    async def test_another_organizations_campaign_is_404(self, client, session, workspace) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)

        response = await client.get(f"/v1/campaigns/{their_campaign.id}")
        assert response.status_code == 404
        assert "confidential" not in response.text

    async def test_listing_never_includes_another_organizations_campaign(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        await _campaign_row(session, theirs, their_brand)
        mine = await _my_brand(client)
        await client.post("/v1/campaigns", json={"brand_id": mine, "title": "Mine"})

        listed = await client.get("/v1/campaigns")
        assert [c["title"] for c in listed.json()["items"]] == ["Mine"]

    async def test_starting_discovery_on_another_organizations_campaign_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)

        response = await client.post(f"/v1/campaigns/{their_campaign.id}/discovery/start")
        assert response.status_code == 404

    async def test_answering_another_organizations_campaign_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)

        response = await client.post(
            f"/v1/campaigns/{their_campaign.id}/discovery/answer", json={"answer": "hello"}
        )
        assert response.status_code == 404

    async def test_reading_another_organizations_conversation_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)

        assert (
            await client.get(f"/v1/campaigns/{their_campaign.id}/conversation")
        ).status_code == 404

    async def test_reading_another_organizations_specification_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)

        assert (
            await client.get(f"/v1/campaigns/{their_campaign.id}/specification")
        ).status_code == 404

    async def test_editing_another_organizations_specification_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)

        response = await client.patch(
            f"/v1/campaigns/{their_campaign.id}/specification", json={"objective": "hijacked"}
        )
        assert response.status_code == 404

    async def test_confirming_another_organizations_specification_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)

        response = await client.post(f"/v1/campaigns/{their_campaign.id}/specification/confirm")
        assert response.status_code == 404

    async def test_uploading_a_reference_to_another_organizations_campaign_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        their_campaign = await _campaign_row(session, theirs, their_brand)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

        response = await client.post(
            f"/v1/campaigns/{their_campaign.id}/references",
            files={"file": ("ref.png", png, "image/png")},
        )
        assert response.status_code == 404


class TestReferences:
    async def test_a_reference_image_is_persisted_and_served(self, client, workspace) -> None:
        brand_id = await _my_brand(client)
        campaign = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"})
        ).json()
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

        created = await client.post(
            f"/v1/campaigns/{campaign['id']}/references",
            files={"file": ("poster.png", png, "image/png")},
            data={"note": "I like this composition"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["note"] == "I like this composition"

        content = await client.get(body["url"])
        assert content.status_code == 200
        assert content.content == png

    async def test_a_non_image_reference_is_rejected(self, client, workspace) -> None:
        brand_id = await _my_brand(client)
        campaign = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "L"})
        ).json()
        response = await client.post(
            f"/v1/campaigns/{campaign['id']}/references",
            files={"file": ("doc.pdf", b"%PDF-1.7 x", "application/pdf")},
        )
        assert response.status_code == 400


class TestDiscoveryFlow:
    """Start → answer → specification → edit → confirm, over HTTP."""

    async def _campaign(self, client) -> str:
        brand_id = await _my_brand(client)
        return (
            await client.post(
                "/v1/campaigns", json={"brand_id": brand_id, "title": "Maharashtra launch"}
            )
        ).json()["id"]

    async def test_starting_discovery_returns_the_first_question(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        response = await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["question"] is not None
        assert body["question"]["priority"] == "HIGH"
        assert body["interview_complete"] is False
        assert body["missing"]

    async def test_starting_twice_resumes_rather_than_restarting(self, client, workspace) -> None:
        """A browser refresh must not throw the conversation away."""
        campaign_id = await self._campaign(client)
        first = (await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")).json()
        await client.post(
            f"/v1/campaigns/{campaign_id}/discovery/answer",
            json={"answer": "This is a product launch."},
        )
        again = (await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")).json()

        assert again["turn"] == 1, "the answered turn survived"
        assert again["question"]["field"] != first["question"]["field"]
        assert again["known"]["campaign_objective"]

    async def test_an_answer_updates_what_we_know(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/discovery/answer",
            json={"answer": "This is a product launch."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["known"]["campaign_objective"]
        assert body["known"]["assertions"]["campaign_objective"]["certainty"] == "stated"

    async def test_a_blank_answer_is_rejected(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/discovery/answer", json={"answer": "   "}
        )
        assert response.status_code == 400

    async def test_the_conversation_is_persisted(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        await client.post(
            f"/v1/campaigns/{campaign_id}/discovery/answer",
            json={"answer": "This is a product launch."},
        )
        transcript = (await client.get(f"/v1/campaigns/{campaign_id}/conversation")).json()
        roles = [m["role"] for m in transcript["items"]]
        assert roles == ["assistant", "user"]
        assert "product launch" in transcript["items"][1]["content"]

    async def _complete(self, client, campaign_id: str) -> dict:
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        answers = [
            "This is a product launch.",
            "The FS-9 facade system.",
            "Architects and specifiers in Maharashtra.",
            "Engineered to outlast the building it clads.",
            "LinkedIn and Instagram post.",
            "Request a specification pack.",
        ]
        body: dict = {}
        for answer in answers:
            body = (
                await client.post(
                    f"/v1/campaigns/{campaign_id}/discovery/answer", json={"answer": answer}
                )
            ).json()
            if body.get("interview_complete"):
                break
        return body

    async def test_a_completed_interview_produces_a_specification(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        body = await self._complete(client, campaign_id)

        assert body["interview_complete"] is True
        spec = body["specification"]
        assert spec is not None
        assert spec["objective"] and spec["audience"] and spec["product"]
        assert spec["key_message"] and spec["channels"]

        stored = await client.get(f"/v1/campaigns/{campaign_id}/specification")
        assert stored.status_code == 200
        assert stored.json()["objective"] == spec["objective"]

        campaign = (await client.get(f"/v1/campaigns/{campaign_id}")).json()
        assert campaign["status"] == "SPECIFICATION_READY"

    async def test_a_human_edit_is_recorded_and_preserved(self, client, workspace) -> None:
        """The milestone's requirement: AI compilation must not undo an edit."""
        campaign_id = await self._campaign(client)
        await self._complete(client, campaign_id)

        edited = await client.patch(
            f"/v1/campaigns/{campaign_id}/specification",
            json={"key_message": "A human wrote this message"},
        )
        assert edited.status_code == 200
        body = edited.json()
        assert body["key_message"] == "A human wrote this message"
        assert body["field_assertions"]["key_message"]["edited_by_human"] is True
        assert body["field_assertions"]["key_message"]["certainty"] == "stated"

        # Re-entering discovery must not overwrite it.
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        after = (await client.get(f"/v1/campaigns/{campaign_id}/specification")).json()
        assert after["key_message"] == "A human wrote this message"

    async def test_an_empty_edit_is_rejected(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await self._complete(client, campaign_id)
        response = await client.patch(f"/v1/campaigns/{campaign_id}/specification", json={})
        assert response.status_code == 400

    async def test_editing_before_a_specification_exists_is_404(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/specification", json={"objective": "x"}
        )
        assert response.status_code == 404

    async def test_confirmation_closes_discovery(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await self._complete(client, campaign_id)

        confirmed = await client.post(f"/v1/campaigns/{campaign_id}/specification/confirm")
        assert confirmed.status_code == 200

        campaign = (await client.get(f"/v1/campaigns/{campaign_id}")).json()
        assert campaign["status"] == "SPECIFICATION_CONFIRMED"

    async def test_a_confirmed_specification_cannot_be_edited(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await self._complete(client, campaign_id)
        await client.post(f"/v1/campaigns/{campaign_id}/specification/confirm")

        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/specification", json={"objective": "changed"}
        )
        assert response.status_code == 409

    async def test_discovery_cannot_reopen_a_confirmed_campaign(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await self._complete(client, campaign_id)
        await client.post(f"/v1/campaigns/{campaign_id}/specification/confirm")

        response = await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        assert response.status_code == 409


class TestReferenceIntelligenceApi:
    """Milestone 4 over HTTP: analysis, review, preferences, creative context."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128

    async def _campaign(self, client) -> str:
        brand_id = await _my_brand(client)
        return (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"})
        ).json()["id"]

    async def _upload(self, client, campaign_id: str, name: str = "poster.png") -> dict:
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/references",
            files={"file": (name, self.PNG, "image/png")},
            data={"note": "I like the restraint"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def test_uploading_a_reference_analyses_it(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        body = await self._upload(client, campaign_id)

        assert body["status"] == "COMPLETED"
        assert body["analysis"] is not None
        assert body["analysis"]["style_families"]
        assert body["analysis"]["composition"]
        assert body["analysis"]["color"]["dominant_palette"]
        assert body["error"] is None

    async def test_the_analysis_states_what_it_will_not_reuse(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        body = await self._upload(client, campaign_id)
        assert body["analysis"]["not_transferable"]

    async def test_references_are_listed_with_their_analysis(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        await self._upload(client, campaign_id)
        listed = (await client.get(f"/v1/campaigns/{campaign_id}/references")).json()
        assert len(listed["items"]) == 1
        assert listed["items"][0]["analysis"] is not None

    async def test_a_human_can_accept_the_analysis(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        reference = await self._upload(client, campaign_id)

        accepted = await client.post(
            f"/v1/campaigns/{campaign_id}/references/{reference['id']}/accept"
        )
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] is True

    async def test_reanalysis_can_be_requested(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        reference = await self._upload(client, campaign_id)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/references/{reference['id']}/analyze"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"

    async def test_an_unknown_reference_is_404(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/references/{uuid.uuid4()}/analyze"
        )
        assert response.status_code == 404

    async def test_style_options_are_offered_in_plain_language(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        options = (await client.get(f"/v1/campaigns/{campaign_id}/preferences/options")).json()
        assert len(options["items"]) == 8
        assert all(o["description"] for o in options["items"])

    async def test_preferences_become_a_weighted_profile(self, client, workspace) -> None:
        campaign_id = await self._campaign(client)
        saved = await client.put(
            f"/v1/campaigns/{campaign_id}/preferences",
            json={"selected_styles": ["premium", "minimal"]},
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["preferences"]["style_profile"]["weights"]
        assert body["profile"][0]["weight"] > 0
        assert "premium" in body["summary"]

    async def test_preferences_persist_and_reweight_with_references(
        self, client, workspace
    ) -> None:
        campaign_id = await self._campaign(client)
        await client.put(
            f"/v1/campaigns/{campaign_id}/preferences", json={"selected_styles": ["premium"]}
        )
        before = (await client.get(f"/v1/campaigns/{campaign_id}/preferences")).json()
        await self._upload(client, campaign_id)
        after = (await client.get(f"/v1/campaigns/{campaign_id}/preferences")).json()

        assert before["preferences"]["selected_styles"] == ["premium"]
        assert (
            after["preferences"]["style_profile"]["weights"]
            != (before["preferences"]["style_profile"]["weights"])
        )

    async def test_the_creative_context_combines_everything(self, client, workspace) -> None:
        brand_id = await _my_brand(client, "Northline")
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"})
        ).json()["id"]
        await self._upload(client, campaign_id)
        await client.put(
            f"/v1/campaigns/{campaign_id}/preferences", json={"selected_styles": ["premium"]}
        )

        response = await client.get(f"/v1/campaigns/{campaign_id}/creative-context")
        assert response.status_code == 200
        body = response.json()
        context = body["context"]
        assert context["brand_name"] == "Northline"
        assert context["reference_style"]["reference_count"] == 1
        assert context["style_profile"]["weights"]
        assert body["summary"]
        # No specification yet — the gap is named, not filled in.
        assert any("specification" in g.lower() for g in context["gaps"])
        assert body["ready"] is False


class TestReferenceIntelligenceTenancy:
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128

    async def _their_campaign(self, session) -> CampaignRow:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        return await _campaign_row(session, theirs, their_brand)

    async def test_listing_another_organizations_references_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/references")).status_code == 404

    async def test_analyzing_another_organizations_reference_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/references/{uuid.uuid4()}/analyze")
        assert response.status_code == 404

    async def test_accepting_another_organizations_analysis_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/references/{uuid.uuid4()}/accept")
        assert response.status_code == 404

    async def test_reading_another_organizations_preferences_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/preferences")).status_code == 404

    async def test_setting_another_organizations_preferences_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.put(
            f"/v1/campaigns/{theirs.id}/preferences", json={"selected_styles": ["bold"]}
        )
        assert response.status_code == 404

    async def test_another_organizations_creative_context_is_404(
        self, client, session, workspace
    ) -> None:
        """The context carries brand guardrails and reference DNA — the most
        sensitive assembled object in the product."""
        theirs = await self._their_campaign(session)
        response = await client.get(f"/v1/campaigns/{theirs.id}/creative-context")
        assert response.status_code == 404
        assert "secret positioning" not in response.text

    async def test_a_reference_id_from_another_campaign_is_404(
        self, client, session, workspace
    ) -> None:
        """Even inside one organization, a reference is reachable only through
        the campaign that owns it."""
        mine = (
            await client.post(
                "/v1/campaigns",
                json={"brand_id": await _my_brand(client), "title": "Mine"},
            )
        ).json()["id"]
        other = (
            await client.post(
                "/v1/campaigns",
                json={"brand_id": await _my_brand(client), "title": "Other"},
            )
        ).json()
        # Same organization, different campaign.
        uploaded = await client.post(
            f"/v1/campaigns/{other['id']}/references",
            files={"file": ("p.png", self.PNG, "image/png")},
        )
        reference_id = uploaded.json()["id"]

        response = await client.post(f"/v1/campaigns/{mine}/references/{reference_id}/analyze")
        assert response.status_code == 404


class TestCreativeStageApi:
    """Milestone 5 over HTTP: directions, both gates, and edits."""

    async def _confirmed(self, client, session) -> str:
        """A campaign with a confirmed specification — the creative entry."""
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"})
        ).json()["id"]
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        for answer in (
            "This is a product launch.",
            "The FS-9 facade system.",
            "Architects and specifiers in Maharashtra.",
            "Engineered to outlast the building it clads.",
            "LinkedIn and Instagram post.",
        ):
            body = (
                await client.post(
                    f"/v1/campaigns/{campaign_id}/discovery/answer", json={"answer": answer}
                )
            ).json()
            if body.get("interview_complete"):
                break
        await client.post(f"/v1/campaigns/{campaign_id}/specification/confirm")
        return campaign_id

    async def test_the_stage_cannot_start_before_the_campaign_is_confirmed(
        self, client, workspace
    ) -> None:
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Early"})
        ).json()["id"]
        response = await client.post(f"/v1/campaigns/{campaign_id}/creative/start")
        assert response.status_code == 409

    async def test_starting_produces_three_directions(self, client, session, workspace) -> None:
        campaign_id = await self._confirmed(client, session)
        response = await client.post(f"/v1/campaigns/{campaign_id}/creative/start")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["gate"] == "strategy_gate"
        assert len(body["direction_set"]["directions"]) == 3
        assert body["diversity"]["passed"] is True
        assert body["direction_set"]["recommendation_reasons"]

    async def test_starting_twice_resumes_rather_than_regenerating(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._confirmed(client, session)
        first = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        again = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        assert again["direction_set"]["version"] == first["direction_set"]["version"]

    async def test_approving_a_direction_produces_a_specification(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._confirmed(client, session)
        started = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        chosen = started["direction_set"]["directions"][1]["id"]

        response = await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={"decision": "APPROVE", "direction_id": chosen},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["selected_direction_id"] == chosen
        assert body["specification"] is not None
        assert body["gate"] == "specification_gate"

    async def test_approving_without_a_direction_is_rejected(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._confirmed(client, session)
        await client.post(f"/v1/campaigns/{campaign_id}/creative/start")
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy", json={"decision": "APPROVE"}
        )
        assert response.status_code == 400

    async def test_a_decision_from_the_wrong_gate_is_rejected(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._confirmed(client, session)
        await client.post(f"/v1/campaigns/{campaign_id}/creative/start")
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy", json={"decision": "SELECT"}
        )
        assert response.status_code == 400

    async def test_requesting_changes_regenerates_a_new_version(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._confirmed(client, session)
        first = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()

        revised = await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={"decision": "REQUEST_REVISION", "feedback": "Too technical."},
        )
        assert revised.status_code == 200
        body = revised.json()
        assert body["direction_set"]["version"] == first["direction_set"]["version"] + 1
        assert body["selected_direction_id"] is None

    async def test_the_specification_is_editable_and_edits_persist(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._confirmed(client, session)
        started = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        chosen = started["direction_set"]["directions"][0]["id"]
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={"decision": "APPROVE", "direction_id": chosen},
        )

        edited = await client.patch(
            f"/v1/campaigns/{campaign_id}/creative/specification",
            json={"headline": "A human wrote this headline"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["headline"] == "A human wrote this headline"
        assert "headline" in edited.json()["human_edited_fields"]

        current = (await client.get(f"/v1/campaigns/{campaign_id}/creative")).json()
        assert current["specification"]["headline"] == "A human wrote this headline"

    async def test_editing_leaves_the_gate_open(self, client, session, workspace) -> None:
        """An edit writes to graph state, which starts a checkpoint where the
        gate node has not re-run — so its interrupt has not re-materialised.
        Reading the gate from the interrupt alone reported none, leaving the
        stage with nothing open and nothing approved: the user could not
        approve what they had just edited."""
        campaign_id = await self._confirmed(client, session)
        started = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={
                "decision": "APPROVE",
                "direction_id": started["direction_set"]["directions"][0]["id"],
            },
        )
        await client.patch(
            f"/v1/campaigns/{campaign_id}/creative/specification",
            json={"headline": "A human wrote this headline"},
        )

        current = (await client.get(f"/v1/campaigns/{campaign_id}/creative")).json()
        assert current["gate"] == "specification_gate"
        assert current["approved"] is False

        approved = await client.post(
            f"/v1/campaigns/{campaign_id}/creative/specification/decide",
            json={"decision": "APPROVE"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["approved"] is True
        # The edit survives the approval it was made before.
        assert approved.json()["specification"]["headline"] == "A human wrote this headline"

    async def test_approving_the_specification_completes_milestone_5(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._confirmed(client, session)
        started = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        chosen = started["direction_set"]["directions"][0]["id"]
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={"decision": "APPROVE", "direction_id": chosen},
        )

        approved = await client.post(
            f"/v1/campaigns/{campaign_id}/creative/specification/decide",
            json={"decision": "APPROVE"},
        )
        assert approved.status_code == 200
        body = approved.json()
        assert body["approved"] is True
        assert body["gate"] is None  # nothing pending; no image was generated

    async def test_an_empty_edit_is_rejected(self, client, session, workspace) -> None:
        campaign_id = await self._confirmed(client, session)
        started = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={
                "decision": "APPROVE",
                "direction_id": started["direction_set"]["directions"][0]["id"],
            },
        )
        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/creative/specification", json={}
        )
        assert response.status_code == 400


class TestCreativeStageTenancy:
    async def _their_campaign(self, session) -> CampaignRow:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        return await _campaign_row(session, theirs, their_brand)

    async def test_reading_another_organizations_creative_stage_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/creative")).status_code == 404

    async def test_starting_another_organizations_creative_stage_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.post(f"/v1/campaigns/{theirs.id}/creative/start")).status_code == 404

    async def test_approving_in_another_organization_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(
            f"/v1/campaigns/{theirs.id}/creative/strategy",
            json={"decision": "APPROVE", "direction_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    async def test_editing_another_organizations_specification_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.patch(
            f"/v1/campaigns/{theirs.id}/creative/specification", json={"headline": "hijacked"}
        )
        assert response.status_code == 404

    async def test_deciding_another_organizations_specification_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(
            f"/v1/campaigns/{theirs.id}/creative/specification/decide",
            json={"decision": "APPROVE"},
        )
        assert response.status_code == 404


class TestGenerationApi:
    """The HTTP surface. Generation itself is covered in test_generation.py —
    what the API owns is the approval gate, job creation, retry rules, asset
    serving, and never leaking a provider secret."""

    async def _approved(self, client, session) -> str:
        """A campaign whose Creative Specification a human has approved."""
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"})
        ).json()["id"]
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        for answer in (
            "This is a product launch.",
            "The FS-9 facade system.",
            "Architects and specifiers in Maharashtra.",
            "Engineered to outlast the building it clads.",
            "LinkedIn and Instagram post.",
        ):
            body = (
                await client.post(
                    f"/v1/campaigns/{campaign_id}/discovery/answer", json={"answer": answer}
                )
            ).json()
            if body.get("interview_complete"):
                break
        await client.post(f"/v1/campaigns/{campaign_id}/specification/confirm")

        started = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={
                "decision": "APPROVE",
                "direction_id": started["direction_set"]["directions"][0]["id"],
            },
        )
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/specification/decide",
            json={"decision": "APPROVE"},
        )
        return campaign_id

    async def test_generation_is_blocked_before_the_specification_is_approved(
        self, client, session, workspace
    ) -> None:
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Early"})
        ).json()["id"]

        view = (await client.get(f"/v1/campaigns/{campaign_id}/generation")).json()
        assert view["can_generate"] is False
        assert "approve" in view["blocked_reason"].lower()

        response = await client.post(f"/v1/campaigns/{campaign_id}/generation/start")
        assert response.status_code == 409

    async def test_compiling_returns_the_prompts_without_generating(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._approved(client, session)
        response = await client.post(f"/v1/campaigns/{campaign_id}/generation/compile")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["canonical_prompt"]["subject"]
        assert body["prompts"], "every configured provider gets a prompt"
        assert body["jobs"] == [], "compiling must not start a job"
        assert body["assets"] == []

    async def test_the_compiled_prompt_carries_no_brand_text(
        self, client, session, workspace
    ) -> None:
        """ADR-006: the image model renders the plate, not the headline."""
        campaign_id = await self._approved(client, session)
        body = (await client.post(f"/v1/campaigns/{campaign_id}/generation/compile")).json()

        specification = (await client.get(f"/v1/campaigns/{campaign_id}/creative")).json()[
            "specification"
        ]
        for prompt in body["prompts"]:
            assert specification["headline"] not in prompt["text"]
            assert specification["cta"] not in prompt["text"]

    async def test_starting_accepts_and_creates_pending_jobs(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._approved(client, session)
        response = await client.post(f"/v1/campaigns/{campaign_id}/generation/start")

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["jobs"], "a job per configured provider"
        assert {job["status"] for job in body["jobs"]} == {"PENDING"}
        assert body["batch_id"]
        assert body["complete"] is False

    async def test_a_job_reports_its_provider_and_model(self, client, session, workspace) -> None:
        campaign_id = await self._approved(client, session)
        body = (await client.post(f"/v1/campaigns/{campaign_id}/generation/start")).json()
        job = body["jobs"][0]
        assert job["provider"] == "mock"
        assert job["model"]
        assert job["attempt"] == 1
        assert job["can_retry"] is False

    async def test_retrying_a_pending_job_is_a_conflict(self, client, session, workspace) -> None:
        campaign_id = await self._approved(client, session)
        body = (await client.post(f"/v1/campaigns/{campaign_id}/generation/start")).json()
        job_id = body["jobs"][0]["id"]

        response = await client.post(f"/v1/campaigns/{campaign_id}/generation/jobs/{job_id}/retry")
        assert response.status_code == 409

    async def test_an_unknown_job_cannot_be_retried(self, client, session, workspace) -> None:
        campaign_id = await self._approved(client, session)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/generation/jobs/{uuid.uuid4()}/retry"
        )
        assert response.status_code == 404

    async def test_the_asset_list_shares_the_generation_shape(
        self, client, session, workspace
    ) -> None:
        campaign_id = await self._approved(client, session)
        await client.post(f"/v1/campaigns/{campaign_id}/generation/start")

        assets = (await client.get(f"/v1/campaigns/{campaign_id}/assets")).json()
        generation = (await client.get(f"/v1/campaigns/{campaign_id}/generation")).json()
        assert assets["jobs"] == generation["jobs"]

    async def test_no_response_carries_a_provider_secret(self, client, session, workspace) -> None:
        """Credentials are server-side only and must never reach the client."""
        campaign_id = await self._approved(client, session)
        await client.post(f"/v1/campaigns/{campaign_id}/generation/compile")
        bodies = [
            (await client.get(f"/v1/campaigns/{campaign_id}/generation")).text,
            (await client.post(f"/v1/campaigns/{campaign_id}/generation/start")).text,
            (await client.get(f"/v1/campaigns/{campaign_id}/assets")).text,
        ]
        for body in bodies:
            lowered = body.lower()
            for secret in ("api_key", "apikey", "gemini_api_key", "authorization", "bearer "):
                assert secret not in lowered

    async def test_the_prompt_view_hides_provider_parameters(
        self, client, session, workspace
    ) -> None:
        """`parameters` is opaque outside app/providers/ — nothing the browser
        needs, and a surface a later provider could leak through."""
        campaign_id = await self._approved(client, session)
        body = (await client.post(f"/v1/campaigns/{campaign_id}/generation/compile")).json()
        assert "parameters" not in body["prompts"][0]


class TestGenerationTenancy:
    async def _their_campaign(self, session) -> CampaignRow:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        return await _campaign_row(session, theirs, their_brand)

    async def test_reading_another_organizations_generation_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/generation")).status_code == 404

    async def test_starting_generation_for_another_organization_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/generation/start")
        assert response.status_code == 404

    async def test_compiling_for_another_organization_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/generation/compile")
        assert response.status_code == 404

    async def test_listing_another_organizations_assets_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/assets")).status_code == 404

    async def test_retrying_another_organizations_job_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(
            f"/v1/campaigns/{theirs.id}/generation/jobs/{uuid.uuid4()}/retry"
        )
        assert response.status_code == 404

    async def test_an_arbitrary_asset_id_is_404(self, client, workspace) -> None:
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Mine"})
        ).json()["id"]
        assert (
            await client.get(f"/v1/campaigns/{campaign_id}/assets/{uuid.uuid4()}")
        ).status_code == 404
        assert (
            await client.get(f"/v1/campaigns/{campaign_id}/assets/{uuid.uuid4()}/content")
        ).status_code == 404

    async def test_a_malformed_asset_id_is_404_not_500(self, client, workspace) -> None:
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Mine"})
        ).json()["id"]
        assert (
            await client.get(f"/v1/campaigns/{campaign_id}/assets/not-a-uuid")
        ).status_code == 404


class TestEvaluationApi:
    """The HTTP surface. Orchestration is covered in test_evaluation.py — what
    the API owns is the gate, the 202, retry rules, selection, and never
    leaking raw model output."""

    async def _with_assets(self, client, session, workspace) -> tuple[str, list[str]]:
        """A campaign with generated plates, reached the way a user reaches it."""
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"})
        ).json()["id"]
        await client.post(f"/v1/campaigns/{campaign_id}/discovery/start")
        for answer in (
            "This is a product launch.",
            "The FS-9 facade system.",
            "Architects and specifiers in Maharashtra.",
            "Engineered to outlast the building it clads.",
            "LinkedIn and Instagram post.",
        ):
            body = (
                await client.post(
                    f"/v1/campaigns/{campaign_id}/discovery/answer", json={"answer": answer}
                )
            ).json()
            if body.get("interview_complete"):
                break
        await client.post(f"/v1/campaigns/{campaign_id}/specification/confirm")

        started = (await client.post(f"/v1/campaigns/{campaign_id}/creative/start")).json()
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/strategy",
            json={
                "decision": "APPROVE",
                "direction_id": started["direction_set"]["directions"][0]["id"],
            },
        )
        await client.post(
            f"/v1/campaigns/{campaign_id}/creative/specification/decide",
            json={"decision": "APPROVE"},
        )
        await client.post(f"/v1/campaigns/{campaign_id}/generation/start")

        # The background runner is stubbed in tests, so drive generation
        # directly on the test session — the same code the task would run.
        from app.services.generation import GenerationService

        service = GenerationService(
            session,
            _principal_for(workspace),
            settings=_test_settings(),
            storage=_test_storage(),
            llm=MockLLMProvider(),
            embeddings=MockEmbeddingProvider(),
        )
        view = await service.current(uuid.UUID(campaign_id))
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        assets = (await client.get(f"/v1/campaigns/{campaign_id}/assets")).json()["assets"]
        return campaign_id, [asset["id"] for asset in assets]

    async def test_evaluation_is_blocked_before_anything_is_generated(
        self, client, workspace
    ) -> None:
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Early"})
        ).json()["id"]

        view = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).json()
        assert view["can_evaluate"] is False
        assert "Generate creatives" in view["blocked_reason"]

        response = await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})
        assert response.status_code == 409

    async def test_starting_accepts_and_claims_pending_evaluations(
        self, client, session, workspace
    ) -> None:
        campaign_id, assets = await self._with_assets(client, session, workspace)
        response = await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["in_flight"] == len(assets)
        assert {e["status"] for e in body["evaluations"]} == {"PENDING"}
        assert body["evaluator_version"]

    async def test_a_pending_evaluation_is_shown_not_hidden(
        self, client, session, workspace
    ) -> None:
        """A missing card is a silent gap; the UI must never have one."""
        campaign_id, assets = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})

        body = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).json()
        assert len(body["evaluations"]) == len(assets)
        for evaluation in body["evaluations"]:
            assert evaluation["overall_score"] is None
            assert evaluation["dimensions"] == []
            assert evaluation["can_retry"] is False

    async def test_a_subset_can_be_evaluated(self, client, session, workspace) -> None:
        campaign_id, assets = await self._with_assets(client, session, workspace)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/evaluation/start", json={"asset_ids": assets[:1]}
        )
        assert response.status_code == 202
        assert response.json()["in_flight"] == 1

    async def test_an_unknown_asset_id_is_404(self, client, session, workspace) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/evaluation/start",
            json={"asset_ids": [str(uuid.uuid4())]},
        )
        assert response.status_code == 404

    async def test_a_completed_evaluation_renders_its_scores(
        self, client, session, workspace
    ) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})
        await _run_evaluations(session, workspace, campaign_id)

        body = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).json()
        assert body["in_flight"] == 0
        assert body["ranked"], "a completed batch ranks"
        first = body["ranked"][0]
        assert first["rank"] == 1
        assert first["asset"] is not None, "the plate travels with its ranking"
        assert first["reason"]

        evaluation = next(e for e in body["evaluations"] if e["status"] == "COMPLETED")
        assert 0 <= evaluation["overall_score"] <= 100
        assert len(evaluation["dimensions"]) == 10
        assert all(d["label"] and 0 <= d["score"] <= 100 for d in evaluation["dimensions"])
        assert evaluation["disposition"] in {"PASS", "NEEDS_REVIEW", "REJECT"}
        assert evaluation["disposition_reasons"]

    async def test_the_recommendation_is_returned(self, client, session, workspace) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})
        await _run_evaluations(session, workspace, campaign_id)

        body = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).json()
        assert body["recommendation"] is not None
        assert body["recommendation"]["reason"]
        assert body["outcome"]

    async def test_retrying_a_pending_evaluation_is_a_conflict(
        self, client, session, workspace
    ) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        body = (await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})).json()
        evaluation_id = body["evaluations"][0]["id"]

        response = await client.post(
            f"/v1/campaigns/{campaign_id}/evaluation/{evaluation_id}/retry"
        )
        assert response.status_code == 409

    async def test_an_unknown_evaluation_cannot_be_retried(
        self, client, session, workspace
    ) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        response = await client.post(f"/v1/campaigns/{campaign_id}/evaluation/{uuid.uuid4()}/retry")
        assert response.status_code == 404

    async def test_a_human_can_select_and_it_persists(self, client, session, workspace) -> None:
        campaign_id, assets = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})
        await _run_evaluations(session, workspace, campaign_id)

        response = await client.post(
            f"/v1/campaigns/{campaign_id}/evaluation/select",
            json={"generated_asset_id": assets[0], "note": "Client liked this one."},
        )
        assert response.status_code == 200, response.text
        assert response.json()["selected_asset_id"] == assets[0]

        again = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).json()
        assert again["selected_asset_id"] == assets[0]

    async def test_selecting_an_unknown_asset_is_404(self, client, session, workspace) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/evaluation/select",
            json={"generated_asset_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    async def test_no_response_carries_raw_model_output(self, client, session, workspace) -> None:
        """Only the short user-facing summaries — never a reasoning trace or a
        provider payload."""
        campaign_id, _ = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})
        await _run_evaluations(session, workspace, campaign_id)

        text = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).text.lower()
        for forbidden in ("api_key", "apikey", "authorization", "bearer ", "traceback", "system"):
            assert forbidden not in text

    async def test_a_fully_failed_batch_is_still_legible(self, client, session, workspace) -> None:
        """Every evaluation failing must not look like nothing having happened.

        The UI reads `evaluations` to render failure cards and their retries, so
        a response that reported only the (empty) ranking would leave a user
        with no explanation and no way forward — which is exactly what it did
        before this was fixed.
        """
        campaign_id, assets = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})
        await _run_evaluations(session, workspace, campaign_id, failure_mode="rate_limit")

        body = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).json()
        assert body["ranked"] == []
        assert body["in_flight"] == 0
        assert len(body["evaluations"]) == len(assets)
        assert all(e["status"] == "FAILED" for e in body["evaluations"])
        assert all(e["can_retry"] and e["error_message"] for e in body["evaluations"])
        assert body["outcome"] == f"0/{len(assets)} assets evaluated — {len(assets)} failed."
        # And it says plainly that there is nothing to recommend.
        assert body["recommendation"] is not None
        assert body["recommendation"]["generated_asset_id"] is None

    async def test_summaries_stay_concise(self, client, session, workspace) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/evaluation/start", json={})
        await _run_evaluations(session, workspace, campaign_id)

        body = (await client.get(f"/v1/campaigns/{campaign_id}/evaluation")).json()
        for evaluation in body["evaluations"]:
            assert len(evaluation["rationale"]) <= 600
            assert len(evaluation["strengths"]) <= 4
            assert len(evaluation["concerns"]) <= 4


class TestEvaluationTenancy:
    async def _their_campaign(self, session) -> CampaignRow:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        return await _campaign_row(session, theirs, their_brand)

    async def test_reading_another_organizations_evaluation_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/evaluation")).status_code == 404

    async def test_starting_evaluation_for_another_organization_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/evaluation/start", json={})
        assert response.status_code == 404

    async def test_retrying_another_organizations_evaluation_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/evaluation/{uuid.uuid4()}/retry")
        assert response.status_code == 404

    async def test_selecting_in_another_organization_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(
            f"/v1/campaigns/{theirs.id}/evaluation/select",
            json={"generated_asset_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    async def test_a_malformed_evaluation_id_is_404_not_500(
        self, client, session, workspace
    ) -> None:
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Mine"})
        ).json()["id"]
        response = await client.post(f"/v1/campaigns/{campaign_id}/evaluation/not-a-uuid/retry")
        assert response.status_code == 404


class TestGuardianApi:
    """The HTTP surface for the brand check."""

    async def _with_assets(self, client, session, workspace) -> tuple[str, list[str]]:
        return await TestEvaluationApi()._with_assets(client, session, workspace)

    async def test_the_check_is_blocked_before_anything_is_generated(
        self, client, workspace
    ) -> None:
        brand_id = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": brand_id, "title": "Early"})
        ).json()["id"]

        view = (await client.get(f"/v1/campaigns/{campaign_id}/guardian")).json()
        assert view["can_check"] is False
        response = await client.post(f"/v1/campaigns/{campaign_id}/guardian/start", json={})
        assert response.status_code == 409

    async def test_starting_accepts_and_claims_checks(self, client, session, workspace) -> None:
        campaign_id, assets = await self._with_assets(client, session, workspace)
        response = await client.post(f"/v1/campaigns/{campaign_id}/guardian/start", json={})

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["in_flight"] == len(assets)
        assert {r["status"] for r in body["results"]} == {"PENDING"}
        assert body["guardian_version"]

    async def test_a_completed_check_renders_its_verdict(self, client, session, workspace) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/guardian/start", json={})
        await _run_guardian(session, workspace, campaign_id)

        body = (await client.get(f"/v1/campaigns/{campaign_id}/guardian")).json()
        assert body["in_flight"] == 0
        result = body["results"][0]
        assert result["verdict"] in {"PASS", "NEEDS_REVISION", "REJECT"}
        assert result["checks"], "every verdict shows the checks behind it"
        assert all(c["label"] for c in result["checks"])
        assert any(c["deterministic"] for c in result["checks"])
        assert result["asset"] is not None

    async def test_a_failed_check_is_shown_with_a_retry(self, client, session, workspace) -> None:
        """An outage must never look like brand approval."""
        campaign_id, _ = await self._with_assets(client, session, workspace)
        await client.post(f"/v1/campaigns/{campaign_id}/guardian/start", json={})
        await _run_guardian(session, workspace, campaign_id, failure_mode="rate_limit")

        body = (await client.get(f"/v1/campaigns/{campaign_id}/guardian")).json()
        for result in body["results"]:
            assert result["status"] == "FAILED"
            assert result["verdict"] is None
            assert result["can_retry"] is True
            assert result["error_message"]

    async def test_retrying_a_pending_check_is_a_conflict(self, client, session, workspace) -> None:
        campaign_id, _ = await self._with_assets(client, session, workspace)
        body = (await client.post(f"/v1/campaigns/{campaign_id}/guardian/start", json={})).json()
        result_id = body["results"][0]["id"]
        response = await client.post(f"/v1/campaigns/{campaign_id}/guardian/{result_id}/retry")
        assert response.status_code == 409


class TestRevisionApi:
    """The HTTP surface for feedback, the delta and the two gates."""

    async def _approved(self, client, session, workspace) -> tuple[str, list[str]]:
        return await TestEvaluationApi()._with_assets(client, session, workspace)

    async def test_feedback_produces_a_reviewable_plan(self, client, session, workspace) -> None:
        campaign_id, assets = await self._approved(client, session, workspace)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={
                "feedback": "Everything is good except the environment — make it more local.",
                "source_asset_id": assets[0],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["current"] is not None
        assert body["current"]["status"] == "PROPOSED"
        assert body["current"]["to_version"] is None
        delta = body["current"]["delta"]
        assert delta["change"], "the plan names what changes"
        assert delta["keep"], "and what stays"
        assert delta["rationale"]
        # Before and after, so a user can see what they are approving.
        assert delta["change"][0]["current_value"]
        assert delta["change"][0]["new_value"]
        assert delta["change"][0]["label"]

    async def test_vague_feedback_asks_for_more_rather_than_guessing(
        self, client, session, workspace
    ) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/revision", json={"feedback": "not sure about it"}
        )
        assert response.status_code == 400
        assert "could not tell" in response.text.lower()

    async def test_empty_feedback_is_rejected_by_the_schema(
        self, client, session, workspace
    ) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        response = await client.post(f"/v1/campaigns/{campaign_id}/revision", json={"feedback": ""})
        assert response.status_code == 400

    async def test_the_two_gates_create_a_new_version(self, client, session, workspace) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "Everything is good except the environment."},
        )

        applied = await client.post(f"/v1/campaigns/{campaign_id}/revision/approve-delta")
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["current"]["status"] == "APPLIED"
        assert body["current"]["to_version"] == 2
        assert body["diff"], "the UI is shown before and after"
        assert body["diff"][0]["before"] != body["diff"][0]["after"]

        approved = await client.post(f"/v1/campaigns/{campaign_id}/revision/approve")
        assert approved.status_code == 200
        assert approved.json()["current"]["status"] == "APPROVED"

    async def test_gate_two_cannot_be_skipped(self, client, session, workspace) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "Everything is good except the environment."},
        )
        response = await client.post(f"/v1/campaigns/{campaign_id}/revision/approve")
        assert response.status_code == 409

    async def test_a_human_can_edit_the_plan(self, client, session, workspace) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "Everything is good except the environment."},
        )

        edited = await client.patch(
            f"/v1/campaigns/{campaign_id}/revision/delta",
            json={
                "interpretation": "Change the lighting instead.",
                "keep": ["environment"],
                "change": [
                    {
                        "field": "lighting",
                        "reason": "I decided",
                        "new_value": "soft dusk light",
                    }
                ],
                "rationale": "Human edit.",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["current"]["delta"]["change"][0]["field"] == "lighting"

    async def test_an_edit_cannot_unlock_a_protected_field(
        self, client, session, workspace
    ) -> None:
        """An edit must not become the way around the rules."""
        campaign_id, _ = await self._approved(client, session, workspace)
        await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "Everything is good except the environment."},
        )

        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/revision/delta",
            json={
                "interpretation": "sneak",
                "keep": [],
                "change": [{"field": "cta", "reason": "x", "new_value": "Buy now"}],
                "rationale": "x",
            },
        )
        assert response.status_code == 400
        assert "locked" in response.text.lower()

    async def test_a_revision_can_be_discarded(self, client, session, workspace) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "Everything is good except the environment."},
        )
        rejected = await client.post(f"/v1/campaigns/{campaign_id}/revision/reject")
        assert rejected.status_code == 200
        assert rejected.json()["current"] is None
        # The record that the question was asked survives.
        assert rejected.json()["history"]

    async def test_only_one_revision_may_be_open(self, client, session, workspace) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        first = await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "Everything is good except the environment."},
        )
        assert first.status_code == 201
        second = await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "And the lighting is too harsh."},
        )
        assert second.status_code == 409

    async def test_no_response_carries_raw_model_output(self, client, session, workspace) -> None:
        campaign_id, _ = await self._approved(client, session, workspace)
        await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "Everything is good except the environment."},
        )
        text = (await client.get(f"/v1/campaigns/{campaign_id}/revision")).text.lower()
        for forbidden in ("api_key", "apikey", "authorization", "bearer ", "traceback"):
            assert forbidden not in text


class TestGuardianAndRevisionTenancy:
    async def _their_campaign(self, session) -> CampaignRow:
        theirs = await make_org(session)
        their_brand = await _brand_row(session, theirs)
        return await _campaign_row(session, theirs, their_brand)

    async def test_reading_another_organizations_guardian_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/guardian")).status_code == 404

    async def test_starting_a_guardian_check_elsewhere_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/guardian/start", json={})
        assert response.status_code == 404

    async def test_retrying_another_organizations_check_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(f"/v1/campaigns/{theirs.id}/guardian/{uuid.uuid4()}/retry")
        assert response.status_code == 404

    async def test_reading_another_organizations_revision_is_404(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        assert (await client.get(f"/v1/campaigns/{theirs.id}/revision")).status_code == 404

    async def test_proposing_a_revision_elsewhere_is_404(self, client, session, workspace) -> None:
        theirs = await self._their_campaign(session)
        response = await client.post(
            f"/v1/campaigns/{theirs.id}/revision", json={"feedback": "change the environment"}
        )
        assert response.status_code == 404

    async def test_approving_a_revision_elsewhere_is_404(self, client, session, workspace) -> None:
        theirs = await self._their_campaign(session)
        for path in ("approve-delta", "approve", "reject"):
            response = await client.post(f"/v1/campaigns/{theirs.id}/revision/{path}")
            assert response.status_code == 404, path

    async def test_editing_a_revision_elsewhere_is_404(self, client, session, workspace) -> None:
        theirs = await self._their_campaign(session)
        response = await client.patch(
            f"/v1/campaigns/{theirs.id}/revision/delta",
            json={"interpretation": "x", "keep": [], "change": [], "rationale": "x"},
        )
        assert response.status_code == 404

    async def test_another_organizations_asset_cannot_seed_a_revision(
        self, client, session, workspace
    ) -> None:
        theirs = await self._their_campaign(session)
        mine = await _my_brand(client)
        campaign_id = (
            await client.post("/v1/campaigns", json={"brand_id": mine, "title": "Mine"})
        ).json()["id"]
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/revision",
            json={"feedback": "change the environment", "source_asset_id": str(theirs.id)},
        )
        assert response.status_code in (404, 409)
