"""What a member's role permits — enforced here, on the server.

Audit finding A-1. `memberships.role` has carried five values since migration
001 and `get_principal` has resolved it into every `Principal` since Milestone 1,
but nothing read it: every mutating route accepted a `viewer` exactly as it
accepted an `admin`. The interface hid the controls
(`frontend/src/lib/capabilities.ts`), which tidies a screen and protects
nothing — a `curl` with a valid token was unrestricted.

**This module is the authority; the frontend map is its mirror.** The two must
agree, and the direction of truth is this one. `tests/test_authz.py` pins the
matrix so a change here is deliberate rather than incidental.

## The matrix

Taken from `docs/PRODUCT_SPEC.md` §4, which names the four working roles and
what each cares about, plus `viewer`. Nothing is invented:

* **Admin** — "workspace, members, projects": everything.
* **Brand manager** — "compliance, consistency · Brand Brain, Brand Guardian,
  approvals": brand truth and the gates, but not the workspace.
* **Marketing** — "speed from idea to asset · campaign chat, approvals": runs
  campaigns and signs them off, but does not change what the brand asserts.
* **Designer** — "creative control, editability · direction cards, editor,
  variants": makes and revises work, and does **not** sign it off. That
  separation is the reason the approval gates exist at all; a designer who can
  approve their own direction has a gate that does nothing.
* **Viewer** — reads.

## Two rules that keep this honest

**Authorization is not tenancy.** A role says what a member may do *inside* an
organization they already belong to. Membership is still resolved first by
`get_principal`, and every repository still filters by organization on every
read and write. A capability check can only ever narrow that; it never widens
it, and removing one would not expose another tenant's data.

**A missing capability is 403, an absent membership is 404.** By the time a
capability is checked the caller has already proved they belong here, so there
is nothing left to conceal — telling them they lack the right is more useful
than pretending the campaign does not exist. `get_principal` keeps answering
404 for an organization the caller is not in, which is the case where existence
really is the secret (M1_SECURITY_AUDIT).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends

from app.api.deps import get_principal
from app.domain.common import Role
from app.domain.workspace import Principal
from app.errors import Forbidden


class Capability(StrEnum):
    """One verb per thing a person can do that changes something."""

    #: Create and edit campaigns, briefs, references, creative plans, and run
    #: the stages that produce work — generation, evaluation, brand checks,
    #: composition and render.
    EDIT_CAMPAIGN = "edit_campaign"
    #: Ask for another round on a creative. Deliberately separate from
    #: `APPROVE`: a designer may say "not this" without being able to say
    #: "ship this".
    REQUEST_REVISION = "request_revision"
    #: Pass a human approval gate — strategy, creative plan, the selection of a
    #: final creative, or a revised plan.
    APPROVE = "approve"
    #: Change what the brand asserts: profile, claims, palette, uploaded
    #: documents and assets, and accepting an extracted fact as brand truth.
    EDIT_BRAND = "edit_brand"
    #: Create projects and organizations.
    MANAGE_WORKSPACE = "manage_workspace"


#: Single source of truth. Mirrored in `frontend/src/lib/capabilities.ts`.
MATRIX: dict[Role, frozenset[Capability]] = {
    Role.ADMIN: frozenset(Capability),
    Role.BRAND_MANAGER: frozenset(
        {
            Capability.EDIT_CAMPAIGN,
            Capability.REQUEST_REVISION,
            Capability.APPROVE,
            Capability.EDIT_BRAND,
        }
    ),
    Role.MARKETING: frozenset(
        {Capability.EDIT_CAMPAIGN, Capability.REQUEST_REVISION, Capability.APPROVE}
    ),
    Role.DESIGNER: frozenset({Capability.EDIT_CAMPAIGN, Capability.REQUEST_REVISION}),
    Role.VIEWER: frozenset(),
}

#: The sentence a refused caller reads. Their own role, and what it lacks —
#: enough to ask the right person for help, and nothing about anyone else.
_REFUSAL = {
    Capability.EDIT_CAMPAIGN: "change this campaign",
    Capability.REQUEST_REVISION: "ask for a revision",
    Capability.APPROVE: "approve this",
    Capability.EDIT_BRAND: "change this brand",
    Capability.MANAGE_WORKSPACE: "manage this workspace",
}


def permits(role: Role, capability: Capability) -> bool:
    """Whether the role grants the capability.

    An unknown role grants nothing. Failing closed matters more here than in
    the interface: a role the database gained and this map did not should lose
    access rather than acquire all of it.
    """
    return capability in MATRIX.get(role, frozenset())


def authorize(principal: Principal, capability: Capability) -> None:
    """Refuse the caller unless their role grants the capability.

    Called directly, rather than as a dependency, where the required capability
    depends on the request *body* — both creative gates accept a decision that
    is either an approval or a revision request, and those are different rights
    held by different roles.
    """
    if not permits(principal.role, capability):
        raise Forbidden(
            f"Your role ({principal.role.value}) cannot {_REFUSAL[capability]}. "
            "Ask someone with the right role in this organization.",
            details={"required_capability": capability.value, "role": principal.role.value},
        )


def require(capability: Capability) -> Callable[..., Awaitable[Principal]]:
    """A dependency that resolves a `Principal` and checks one capability.

    Routes depend on this *instead of* `PrincipalDep`, so the check cannot be
    forgotten separately from getting hold of the caller — the same reason
    `media_access()` binds a token to its route rather than trusting each route
    to verify what a signature was signed for.
    """

    async def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        authorize(principal, capability)
        return principal

    return dependency


EditCampaignDep = Annotated[Principal, Depends(require(Capability.EDIT_CAMPAIGN))]
RequestRevisionDep = Annotated[Principal, Depends(require(Capability.REQUEST_REVISION))]
ApproveDep = Annotated[Principal, Depends(require(Capability.APPROVE))]
EditBrandDep = Annotated[Principal, Depends(require(Capability.EDIT_BRAND))]
ManageWorkspaceDep = Annotated[Principal, Depends(require(Capability.MANAGE_WORKSPACE))]
