"""The capability matrix, and that every mutating route is behind one.

Audit finding A-1. Two different things are asserted, and the second is the one
that keeps the fix from rotting:

* the matrix itself — every role against every capability, written out, so a
  change to `MATRIX` has to be a deliberate edit to this table as well;
* **coverage** — that no route which changes something is reachable with a plain
  `Principal`. A guard applied to twenty-six routes and forgotten on the
  twenty-seventh is the same defect A-1 was.

Behaviour over HTTP, with real roles and a real database, is in
`tests/integration/test_role_enforcement.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.authz import MATRIX, Capability, authorize, permits
from app.domain.common import Role
from app.domain.workspace import Principal, User
from app.errors import Forbidden

pytestmark = pytest.mark.unit

E = Capability.EDIT_CAMPAIGN
R = Capability.REQUEST_REVISION
A = Capability.APPROVE
B = Capability.EDIT_BRAND
W = Capability.MANAGE_WORKSPACE

#: Read this as the product's access-control table. `docs/PRODUCT_SPEC.md` §4.
EXPECTED: dict[Role, set[Capability]] = {
    Role.ADMIN: {E, R, A, B, W},
    Role.BRAND_MANAGER: {E, R, A, B},
    Role.MARKETING: {E, R, A},
    Role.DESIGNER: {E, R},
    Role.VIEWER: set(),
}


def _principal(role: Role) -> Principal:
    return Principal(
        user=User(id="00000000-0000-0000-0000-000000000001", email="member@example.test"),
        organization_id="00000000-0000-0000-0000-0000000000ff",
        role=role,
    )


class TestTheMatrix:
    @pytest.mark.parametrize("role", list(Role))
    @pytest.mark.parametrize("capability", list(Capability))
    def test_every_role_against_every_capability(self, role: Role, capability: Capability) -> None:
        assert permits(role, capability) is (capability in EXPECTED[role])

    def test_the_matrix_covers_every_role(self) -> None:
        """A role the enum gains and the matrix does not must not be silently
        unrestricted — or silently unusable without anyone noticing."""
        assert set(MATRIX) == set(Role)

    def test_an_unknown_role_grants_nothing(self) -> None:
        """Failing closed. A role in the database that this map has never heard
        of loses access rather than acquiring all of it."""
        assert permits("something_new", Capability.APPROVE) is False  # type: ignore[arg-type]

    def test_a_designer_cannot_approve_their_own_work(self) -> None:
        """The separation the approval gates exist to create. Stated on its own
        because it is the one line of the table that is a product decision
        rather than a convenience."""
        assert permits(Role.DESIGNER, Capability.REQUEST_REVISION) is True
        assert permits(Role.DESIGNER, Capability.APPROVE) is False

    def test_marketing_cannot_change_what_the_brand_asserts(self) -> None:
        assert permits(Role.MARKETING, Capability.APPROVE) is True
        assert permits(Role.MARKETING, Capability.EDIT_BRAND) is False


class TestTheRefusal:
    def test_a_permitted_caller_passes(self) -> None:
        authorize(_principal(Role.ADMIN), Capability.MANAGE_WORKSPACE)

    def test_a_refused_caller_gets_forbidden(self) -> None:
        with pytest.raises(Forbidden) as caught:
            authorize(_principal(Role.VIEWER), Capability.EDIT_CAMPAIGN)
        assert caught.value.code == "FORBIDDEN"

    def test_the_refusal_names_the_role_and_the_right(self) -> None:
        """Enough for the reader to ask the right person. Nothing about anyone
        else's membership."""
        with pytest.raises(Forbidden) as caught:
            authorize(_principal(Role.DESIGNER), Capability.APPROVE)
        message = caught.value.message
        assert "designer" in message
        assert caught.value.details == {
            "required_capability": "approve",
            "role": "designer",
        }

    @pytest.mark.parametrize("capability", list(Capability))
    def test_every_capability_has_a_refusal_sentence(self, capability: Capability) -> None:
        """A `KeyError` while building a 403 would become a 500 — the caller
        would be let through by the error handler's shape, not by the rule."""
        with pytest.raises(Forbidden):
            authorize(_principal(Role.VIEWER), capability)


class TestEveryMutatingRouteIsGuarded:
    """Coverage, read off the router sources.

    Route-level, not handler-level: a handler may add a narrower check (both
    creative gates do, because the right depends on the decision in the body),
    but nothing that changes state may be reachable on a bare `PrincipalDep`.
    """

    #: The deliberate exceptions, each with the reason it is one.
    ALLOWED_UNGUARDED = {
        # A POST that reads. `{query, k}` is a body because it is a query, not
        # because anything is written.
        ("POST", "/knowledge/query"): "read-only retrieval",
        # Creating an organization establishes scope rather than acting inside
        # one; there is no membership yet whose role could be consulted. The
        # creator becomes its admin.
        ("POST", ""): "establishes the scope it would be checked against",
    }

    #: Checked inside the handler because the capability depends on the body.
    IN_HANDLER = {
        "/{campaign_id}/creative/strategy",
        "/{campaign_id}/creative/specification/decide",
    }

    @staticmethod
    def _routes() -> list[tuple[str, str, str, str]]:
        decorator = re.compile(r'@router\.(get|post|patch|put|delete)\(\s*\n?\s*"([^"]*)"', re.M)
        found = []
        for path in sorted((Path(__file__).parent.parent / "app/api/routers").glob("*.py")):
            source = path.read_text()
            lines = source.splitlines()
            for match in decorator.finditer(source):
                method = match.group(1).upper()
                if method == "GET":
                    continue
                start = source[: match.start()].count("\n")
                signature = "\n".join(lines[start : start + 34])
                dependency = re.search(r"principal: (\w+)|user: (\w+)", signature)
                found.append(
                    (
                        path.name,
                        method,
                        match.group(2),
                        (dependency.group(1) or dependency.group(2)) if dependency else "NONE",
                    )
                )
        return found

    def test_the_routers_were_actually_read(self) -> None:
        """Guards the test rather than the code: a regex that silently stops
        matching would turn this whole class green."""
        routes = self._routes()
        assert len(routes) >= 30, f"only found {len(routes)} mutating routes"

    def test_no_mutating_route_accepts_a_bare_principal(self) -> None:
        offenders = [
            (name, method, route)
            for name, method, route, dependency in self._routes()
            if dependency == "PrincipalDep"
            and (method, route) not in self.ALLOWED_UNGUARDED
            and route not in self.IN_HANDLER
        ]
        assert not offenders, f"unguarded mutating routes: {offenders}"

    def test_the_two_body_dependent_gates_check_in_the_handler(self) -> None:
        """They are exempt from the route-level rule, so the handler-level check
        has to be asserted or the exemption is a hole."""
        source = (Path(__file__).parent.parent / "app/api/routers/campaigns.py").read_text()
        assert source.count("authorize(principal, _gate_capability(body.decision))") == 2

    def test_a_gate_decision_maps_to_the_right_capability(self) -> None:
        from app.api.routers.campaigns import _gate_capability
        from app.domain.approval import Decision

        assert _gate_capability(Decision.APPROVE) is Capability.APPROVE
        assert _gate_capability(Decision.REJECT) is Capability.APPROVE
        assert _gate_capability(Decision.SELECT) is Capability.APPROVE
        assert _gate_capability(Decision.REQUEST_REVISION) is Capability.REQUEST_REVISION
        assert _gate_capability(Decision.EDIT) is Capability.REQUEST_REVISION


class TestTheFrontendMirrorAgrees:
    """The interface hides what the server refuses, and the two must say the
    same thing. The server is the authority; this catches the mirror drifting."""

    def test_the_typescript_matrix_matches(self) -> None:
        source = (
            Path(__file__).parent.parent.parent / "frontend/src/lib/capabilities.ts"
        ).read_text()
        block = source.split("const MATRIX", 1)[1].split("};", 1)[0]
        for role, expected in EXPECTED.items():
            line = next(
                raw for raw in block.splitlines() if raw.strip().startswith(f"{role.value}:")
            )
            declared = set(re.findall(r"'([a-z_]+)'", line))
            assert declared == {c.value for c in expected}, f"{role.value} disagrees"
