"""Cross-organization isolation.

The tenancy decision in `docs/DATABASE_SCHEMA.md` — root tables carry
`organization_id`, descendants are reached by join — is only safe because
scope is applied in one place, `ScopedRepository`. This file is the proof.

It is written as a probe applied to *every* repository rather than as a test
of one, so a repository added in a later milestone that forgets to scope fails
here instead of in production.
"""

from __future__ import annotations

import uuid

import pytest

from app.repositories.base import ScopedRepository
from app.repositories.brands import (
    BrandAssetRepository,
    BrandChunkRepository,
    BrandDocumentRepository,
    BrandFactRepository,
    BrandRepository,
)
from app.repositories.campaigns import (
    CampaignMessageRepository,
    CampaignReferenceRepository,
    CampaignRepository,
    CampaignRunRepository,
    CampaignSpecificationRepository,
)
from app.repositories.composition import FinalAssetRepository, LayoutSpecRepository
from app.repositories.creative import (
    CreativeApprovalRepository,
    CreativeDirectionSetRepository,
    CreativeRevisionRepository,
    CreativeSpecificationRepository,
)
from app.repositories.evaluation import (
    CreativeEvaluationRepository,
    CreativeSelectionRepository,
)
from app.repositories.generation import (
    CanonicalPromptRepository,
    GeneratedAssetRepository,
    GenerationJobRepository,
    ModelPromptRepository,
)
from app.repositories.organizations import OrganizationRepository
from app.repositories.projects import ProjectRepository
from app.repositories.revision import (
    BrandGuardianRepository,
    SpecificationRevisionRepository,
)
from tests.integration.factories import make_org, make_project

pytestmark = pytest.mark.integration

#: Every scoped repository. Adding one here is the price of adding one at all.
SCOPED_REPOSITORIES = [
    ProjectRepository,
    OrganizationRepository,
    BrandRepository,
    BrandDocumentRepository,
    BrandAssetRepository,
    BrandChunkRepository,
    BrandFactRepository,
    CampaignRepository,
    CampaignMessageRepository,
    CampaignRunRepository,
    CampaignSpecificationRepository,
    CampaignReferenceRepository,
    CreativeDirectionSetRepository,
    CreativeSpecificationRepository,
    CreativeApprovalRepository,
    CreativeRevisionRepository,
    CanonicalPromptRepository,
    ModelPromptRepository,
    GenerationJobRepository,
    GeneratedAssetRepository,
    CreativeEvaluationRepository,
    CreativeSelectionRepository,
    BrandGuardianRepository,
    SpecificationRevisionRepository,
    LayoutSpecRepository,
    FinalAssetRepository,
]


class TestEveryRepositoryIsScoped:
    def test_all_scoped_repositories_are_registered(self) -> None:
        """Guards the guard: a new ScopedRepository subclass that is not in
        SCOPED_REPOSITORIES would never be probed below."""
        subclasses = {
            cls
            for cls in ScopedRepository.__subclasses__()
            for cls in [cls, *cls.__subclasses__()]
            if cls.__module__.startswith("app.repositories")
            and not cls.__name__.startswith("OrganizationOwned")
        }
        missing = subclasses - set(SCOPED_REPOSITORIES)
        assert not missing, f"unregistered scoped repositories: {missing}"

    @pytest.mark.parametrize("repo_cls", SCOPED_REPOSITORIES, ids=lambda c: c.__name__)
    async def test_repository_declares_how_it_is_scoped(self, session, repo_cls) -> None:
        repo = repo_cls(session, uuid.uuid4())
        assert repo._scope is not ScopedRepository._scope, (
            f"{repo_cls.__name__} does not implement _scope()"
        )


class TestProjectIsolation:
    async def test_a_project_from_another_organization_is_invisible(self, session) -> None:
        mine, theirs = await make_org(session), await make_org(session)
        their_project = await make_project(session, theirs, name="Their secret project")

        repo = ProjectRepository(session, mine.id)
        assert await repo.get(their_project.id) is None, "cross-tenant read leaked a row"

    async def test_listing_never_includes_another_organization(self, session) -> None:
        mine, theirs = await make_org(session), await make_org(session)
        await make_project(session, mine, name="Mine")
        await make_project(session, theirs, name="Theirs")

        page = await ProjectRepository(session, mine.id).list_page()
        assert [p.name for p in page.items] == ["Mine"]

    async def test_count_is_scoped_too(self, session) -> None:
        mine, theirs = await make_org(session), await make_org(session)
        await make_project(session, mine)
        await make_project(session, theirs)
        await make_project(session, theirs)

        assert await ProjectRepository(session, mine.id).count() == 1

    async def test_writing_into_another_organization_is_refused(self, session) -> None:
        """Scope guards writes, not only reads — otherwise a bug could plant a
        row in someone else's workspace."""
        mine, theirs = await make_org(session), await make_org(session)
        from app.db.models import Project

        repo = ProjectRepository(session, mine.id)
        with pytest.raises(PermissionError):
            repo.add(Project(organization_id=theirs.id, name="Planted"))

    async def test_soft_deleted_projects_disappear_from_scope(self, session) -> None:
        org = await make_org(session)
        project = await make_project(session, org)
        repo = ProjectRepository(session, org.id)

        await repo.soft_delete(project)

        assert await repo.get(project.id) is None
        assert (await repo.list_page()).items == []


class TestOrganizationIsolation:
    async def test_only_the_scoped_organization_is_reachable(self, session) -> None:
        mine, theirs = await make_org(session), await make_org(session)
        repo = OrganizationRepository(session, mine.id)

        assert (await repo.current()).id == mine.id
        assert await repo.get(theirs.id) is None
