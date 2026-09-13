"""Final composition over HTTP: the contract the UI actually consumes.

The service tests prove the behaviour; these prove the seam. What matters here
is that a refusal arrives as a `400` with a sentence the interface can show —
not a `500`, not a success with a broken image — and that a rendered file is
served only through a scope-checked row.
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image

from app.domain.common import CHANNEL_DIMENSIONS, Channel
from app.domain.layout import LayoutSpec
from tests.integration.factories import make_org
from tests.integration.test_final_composition import _principal_for_org, _seed, _service

pytestmark = pytest.mark.integration


async def _composed(client, session, workspace, api_storage) -> tuple[str, dict]:
    """A campaign with a default layout, seeded into the app's own storage."""
    campaign, _, _ = await _seed(session, workspace.org, api_storage)
    response = await client.post(
        f"/v1/campaigns/{campaign.id}/composition",
        json={"channel": Channel.INSTAGRAM_POST.value},
    )
    assert response.status_code == 201, response.text
    return str(campaign.id), response.json()


def _element_id(view: dict, role: str) -> str:
    layout = LayoutSpec.model_validate(view["layout"])
    element = layout.by_role(role)
    assert element is not None, f"no {role} in the layout"
    return element.id


class TestTheCompositionContract:
    async def test_compose_then_read_back(self, client, session, workspace, api_storage) -> None:
        campaign_id, created = await _composed(client, session, workspace, api_storage)

        assert created["layout"]["version"] == 1
        assert created["report"]["verdict"] == "PASS"
        assert created["composed_channels"] == [Channel.INSTAGRAM_POST.value]
        assert Channel.INSTAGRAM_POST.value not in created["available_channels"]
        assert Channel.PRINT_A3.value not in created["available_channels"], (
            "print is not offered as a composition target"
        )

        fetched = await client.get(f"/v1/campaigns/{campaign_id}/composition")
        assert fetched.status_code == 200
        assert fetched.json()["layout"]["id"] == created["layout"]["id"]

    async def test_a_campaign_with_nothing_generated_says_why(self, client, workspace) -> None:
        brand = (await client.post("/v1/brands", json={"name": "Northline"})).json()["id"]
        campaign = (
            await client.post("/v1/campaigns", json={"brand_id": brand, "title": "Launch"})
        ).json()

        view = (await client.get(f"/v1/campaigns/{campaign['id']}/composition")).json()

        assert view["layout"] is None
        assert view["can_compose"] is False
        assert view["blocked_reason"], "an empty state must explain itself"

    async def test_an_unknown_campaign_is_404(self, client, workspace) -> None:
        response = await client.get(f"/v1/campaigns/{uuid.uuid4()}/composition")
        assert response.status_code == 404


class TestRenderAndExport:
    async def test_render_then_download(self, client, session, workspace, api_storage) -> None:
        campaign_id, _ = await _composed(client, session, workspace, api_storage)

        rendered = await client.post(
            f"/v1/campaigns/{campaign_id}/composition/render",
            json={"channel": Channel.INSTAGRAM_POST.value, "format": "PNG"},
        )
        assert rendered.status_code == 201, rendered.text
        asset = rendered.json()
        assert asset["kind"] == "FINAL_BRANDED_ASSET"
        assert asset["renderer_version"]
        assert asset["layout_version"] == 1
        assert (asset["width"], asset["height"]) == CHANNEL_DIMENSIONS[Channel.INSTAGRAM_POST]

        content = await client.get(asset["url"])
        assert content.status_code == 200
        assert content.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(content.content)).size == (asset["width"], asset["height"])

        download = await client.get(f"{asset['url']}?download=true")
        assert "attachment" in download.headers["content-disposition"]
        assert "instagram_post-v1.png" in download.headers["content-disposition"]

    async def test_jpeg_is_offered_and_pdf_is_not(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign_id, _ = await _composed(client, session, workspace, api_storage)

        jpeg = await client.post(
            f"/v1/campaigns/{campaign_id}/composition/render",
            json={"channel": Channel.INSTAGRAM_POST.value, "format": "JPEG"},
        )
        assert jpeg.status_code == 201
        assert jpeg.json()["mime_type"] == "image/jpeg"

        pdf = await client.post(
            f"/v1/campaigns/{campaign_id}/composition/render",
            json={"channel": Channel.INSTAGRAM_POST.value, "format": "PDF"},
        )
        # The app maps request-schema failures to 400 (app/api/errors.py).
        assert pdf.status_code == 400, "print output is deliberately out of scope"

    async def test_history_is_listed_not_replaced(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign_id, view = await _composed(client, session, workspace, api_storage)
        url = f"/v1/campaigns/{campaign_id}/composition"

        first = (
            await client.post(f"{url}/render", json={"channel": Channel.INSTAGRAM_POST.value})
        ).json()
        await client.patch(
            url,
            params={"channel": Channel.INSTAGRAM_POST.value},
            json={"elements": {_element_id(view, "headline"): {"y": 0.2}}},
        )
        second = (
            await client.post(f"{url}/render", json={"channel": Channel.INSTAGRAM_POST.value})
        ).json()

        listed = (await client.get(f"/v1/campaigns/{campaign_id}/final-assets")).json()
        assert listed["total"] == 2
        assert {item["version"] for item in listed["items"]} == {1, 2}
        assert first["layout_version"] == 1 and second["layout_version"] == 2

        # The first file is still exactly where it was.
        still_there = await client.get(first["url"])
        assert still_there.status_code == 200


class TestTheEditorOverHttp:
    async def test_a_safe_edit_creates_a_new_version(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign_id, view = await _composed(client, session, workspace, api_storage)

        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/composition",
            params={"channel": Channel.INSTAGRAM_POST.value},
            json={"elements": {_element_id(view, "subhead"): {"x": 0.12}}},
        )

        assert response.status_code == 200, response.text
        assert response.json()["layout"]["version"] == 2

    async def test_rewriting_the_cta_is_a_400_with_a_readable_reason(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign_id, view = await _composed(client, session, workspace, api_storage)

        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/composition",
            params={"channel": Channel.INSTAGRAM_POST.value},
            json={"elements": {_element_id(view, "cta"): {"content": "Buy now"}}},
        )

        assert response.status_code == 400
        body = response.json()
        assert "approved campaign fact" in body["error"]["message"]

    async def test_an_off_canvas_move_is_a_400_not_a_crash(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign_id, view = await _composed(client, session, workspace, api_storage)

        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/composition",
            params={"channel": Channel.INSTAGRAM_POST.value},
            json={"elements": {_element_id(view, "headline"): {"x": 0.9, "width": 0.6}}},
        )

        assert response.status_code == 400
        assert "canvas" in response.json()["error"]["message"]

    async def test_an_empty_edit_is_rejected(self, client, session, workspace, api_storage) -> None:
        campaign_id, _ = await _composed(client, session, workspace, api_storage)

        response = await client.patch(
            f"/v1/campaigns/{campaign_id}/composition",
            params={"channel": Channel.INSTAGRAM_POST.value},
            json={"elements": {}},
        )

        assert response.status_code == 400


class TestVariantsOverHttp:
    async def test_two_variants_appear_with_their_own_sizes(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign_id, _ = await _composed(client, session, workspace, api_storage)
        url = f"/v1/campaigns/{campaign_id}/composition"

        for channel in (Channel.INSTAGRAM_STORY, Channel.LINKEDIN):
            created = await client.post(
                f"{url}/variants",
                json={"channel": channel.value, "source": Channel.INSTAGRAM_POST.value},
            )
            assert created.status_code == 201, created.text
            layout = created.json()["layout"]
            assert (layout["width"], layout["height"]) == CHANNEL_DIMENSIONS[channel]

            rendered = await client.post(f"{url}/render", json={"channel": channel.value})
            assert rendered.status_code == 201
            assert (rendered.json()["width"], rendered.json()["height"]) == CHANNEL_DIMENSIONS[
                channel
            ]

        view = (await client.get(url)).json()
        assert len(view["composed_channels"]) == 3
        assert Channel.INSTAGRAM_STORY.value not in view["available_channels"]

    async def test_a_print_variant_is_refused_with_a_reason(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign_id, _ = await _composed(client, session, workspace, api_storage)

        response = await client.post(
            f"/v1/campaigns/{campaign_id}/composition/variants",
            json={"channel": Channel.PRINT_A4.value, "source": Channel.INSTAGRAM_POST.value},
        )

        assert response.status_code == 400
        assert "print production" in response.json()["error"]["message"]


class TestAnInvalidLayoutIsReportedOverHttp:
    async def test_the_api_reports_the_problem_instead_of_rendering(
        self, client, session, workspace, api_storage
    ) -> None:
        """The deliberate invalid case, seen the way the UI sees it."""
        from app.repositories.composition import LayoutSpecRepository

        campaign_id, view = await _composed(client, session, workspace, api_storage)
        layouts = LayoutSpecRepository(session, workspace.org.id)

        broken = dict(view["layout"])
        broken["elements"] = [dict(element) for element in broken["elements"]]
        for element in broken["elements"]:
            if element["role"] in ("headline", "cta"):
                element["box"] = dict(element["box"]) | {
                    "x": 0.0,
                    "y": 0.93,
                    "width": 0.9,
                    "height": 0.07,
                }
        await layouts.create(
            campaign_id=uuid.UUID(campaign_id),
            channel=Channel.INSTAGRAM_POST,
            version=2,
            payload=broken | {"version": 2},
            source_asset_id=None,
            specification_version=1,
        )
        await session.commit()

        state = (await client.get(f"/v1/campaigns/{campaign_id}/composition")).json()
        assert state["report"]["verdict"] == "NEEDS_ADJUSTMENT"
        blocking = [i for i in state["report"]["issues"] if i["severity"] == "blocking"]
        assert blocking, "the UI has nothing to show the user"
        assert all(issue["detail"] for issue in blocking)

        response = await client.post(
            f"/v1/campaigns/{campaign_id}/composition/render",
            json={"channel": Channel.INSTAGRAM_POST.value},
        )
        assert response.status_code == 400
        assert "cannot be rendered" in response.json()["error"]["message"]

        listed = (await client.get(f"/v1/campaigns/{campaign_id}/final-assets")).json()
        assert listed["total"] == 0, "a broken layout must not produce an asset"


class TestTenancyOverHttp:
    async def test_another_organizations_composition_is_404(
        self, client, session, workspace, api_storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, api_storage)
        service = _service(session, _principal_for_org(workspace.user, theirs), api_storage)
        await service.compose(their_campaign.id)
        their_final = await service.render_final(their_campaign.id, channel=Channel.INSTAGRAM_POST)
        await session.commit()

        base = f"/v1/campaigns/{their_campaign.id}"
        assert (await client.get(f"{base}/composition")).status_code == 404
        assert (await client.post(f"{base}/composition", json={})).status_code == 404
        assert (
            await client.patch(
                f"{base}/composition", json={"elements": {str(uuid.uuid4()): {"x": 0.1}}}
            )
        ).status_code == 404
        assert (await client.post(f"{base}/composition/render", json={})).status_code == 404
        assert (await client.get(f"{base}/final-assets")).status_code == 404
        assert (
            await client.get(f"{base}/final-assets/{their_final.id}/content")
        ).status_code == 404

    async def test_another_organizations_asset_id_is_404_under_my_campaign(
        self, client, session, workspace, api_storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, api_storage)
        service = _service(session, _principal_for_org(workspace.user, theirs), api_storage)
        await service.compose(their_campaign.id)
        their_final = await service.render_final(their_campaign.id, channel=Channel.INSTAGRAM_POST)
        await session.commit()

        mine, _ = await _composed(client, session, workspace, api_storage)

        response = await client.get(f"/v1/campaigns/{mine}/final-assets/{their_final.id}")
        assert response.status_code == 404
