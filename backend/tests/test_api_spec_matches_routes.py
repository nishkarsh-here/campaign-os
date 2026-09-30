"""`docs/API_SPEC.md` describes the API that exists.

Audit finding DOC-1. The document had drifted structurally: 49 documented
operations, 77 implemented, 31 in agreement. It specified a whole "Running the
graph" section (`POST /runs`, `GET /runs/{run_id}`) that was never built, told a
client to poll `GET /runs/{run_id}` every 1.5 s, and omitted every endpoint the
frontend actually drives the stages with.

It drifted because nothing checked it. `tests/test_config.py` already asserts
`.env.example` against `Settings` in both directions — the mechanism existed and
was simply never pointed at the API. This is that, for routes.

**Both directions, because each failure is bad in its own way.** A documented
endpoint that does not exist sends someone to build against a 404. An endpoint
nobody documented is one they cannot find, which is how `/overview` came to be
missing from a document that specified a view-model endpoint instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SPEC = Path(__file__).resolve().parents[2] / "docs/API_SPEC.md"
METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")

#: Operations the document names in order to say they do **not** exist, each
#: with a phrase the document must carry to explain it. They are listed because
#: an earlier draft specified them and someone may still be holding that draft;
#: "this was never built, and here is why" is more useful than silence.
#:
#: Method-qualified, because absence is per operation: `POST /v1/organizations`
#: is real and `GET /v1/organizations` is deliberately not.
#:
#: The phrase is what stops this becoming a dumping ground — an entry added to
#: silence a failure has to come with a sentence in the document.
DELIBERATELY_ABSENT: dict[tuple[str, str], str] = {
    ("GET", "/v1/files/{storage_key}"): "never built, and it should not be",
    ("POST", "/v1/campaigns/{id}/approvals"): "Per-gate endpoints rather than one generic",
    ("GET", "/v1/campaigns/{id}/state"): "There is no `/state`",
    ("POST", "/v1/campaigns/{id}/cancel"): "A campaign is not cancellable",
    ("POST", "/v1/campaigns/{id}/runs"): "no `/runs`",
    ("GET", "/v1/campaigns/{id}/runs"): "generic run resource",
    ("GET", "/v1/campaigns/{id}/runs/{run_id}"): "There is no run resource to poll",
    ("GET", "/v1/campaigns/{id}/messages"): "There is no `/messages` pair",
    ("POST", "/v1/campaigns/{id}/messages"): "answer is posted to `/discovery/answer`",
    # One sentence disowns all four at once, so they share it.
    ("GET", "/v1/campaigns/{id}/brief"): "Earlier drafts listed `/brief`",
    ("GET", "/v1/campaigns/{id}/directions"): "`/directions`",
    ("GET", "/v1/campaigns/{id}/prompts"): "`/prompts`",
    ("GET", "/v1/campaigns/{id}/revisions"): "`/revisions`. None",
    ("GET", "/v1/organizations"): "There is no `GET /v1/organizations`",
    ("DELETE", "/v1/campaigns/{id}/references/{ref_id}"): "A reference cannot be deleted",
    ("DELETE", "/v1/brands/{id}/assets/{asset_id}"): "",
}


def _normalise(path: str) -> str:
    """Compare paths, not parameter names. `{id}` and `{campaign_id}` are the
    same route; a test that treated them as different would fail on spelling."""
    return re.sub(r"\{[^}]*\}", "{}", path.split("?")[0].rstrip("/"))


ABSENT = {(method, _normalise(path)) for method, path in DELIBERATELY_ABSENT}


def _implemented() -> set[tuple[str, str]]:
    """From the OpenAPI schema, which ADR-010 makes authoritative."""
    from app.config import get_settings
    from app.main import create_app

    schema = create_app(get_settings()).openapi()
    return {
        (method.upper(), _normalise(path))
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() in METHODS
    }


def _documented() -> set[tuple[str, str]]:
    """Every `METHOD /v1/...` the document states, from its tables, its fenced
    endpoint blocks and its prose."""
    text = SPEC.read_text()
    found: set[tuple[str, str]] = set()

    for line in text.splitlines():
        stripped = line.strip()

        # Table rows: | `GET/PATCH/DELETE` | `/v1/...` | notes |
        if stripped.startswith("|"):
            cells = [c.strip().strip("`") for c in stripped.strip("|").split("|")]
            if len(cells) >= 2 and cells[1].strip("`").startswith("/v1"):
                verbs, path = cells[0], cells[1].strip("`")
                for verb in re.split(r"[/,\s]+", verbs):
                    if verb.upper() in METHODS:
                        found.add((verb.upper(), _normalise(path)))
            continue

        # Fenced blocks and prose: `GET   /v1/... -> View`
        match = re.match(rf"^({'|'.join(METHODS)})\s+(/v1\S*)", stripped)
        if match:
            found.add((match.group(1), _normalise(match.group(2))))

    for match in re.finditer(rf"`({'|'.join(METHODS)})\s+(/v1[^`]*)`", text):
        found.add((match.group(1), _normalise(match.group(2))))

    return found


class TestTheDocumentWasActuallyParsed:
    """Guards the test. A regex that stopped matching would turn the two
    assertions below green while the document said anything at all."""

    def test_the_spec_exists_and_is_substantial(self) -> None:
        assert SPEC.exists()
        assert len(SPEC.read_text()) > 10_000

    def test_a_useful_number_of_operations_were_extracted(self) -> None:
        assert len(_documented()) >= 60, f"only parsed {len(_documented())}"

    def test_the_routes_were_read_from_the_app(self) -> None:
        assert len(_implemented()) >= 70, f"only found {len(_implemented())}"


class TestTheDocumentAndTheAppAgree:
    def test_every_documented_endpoint_exists(self) -> None:
        phantom = sorted(
            f"{method} {path}"
            for method, path in _documented() - _implemented()
            if (method, path) not in ABSENT
        )
        assert not phantom, (
            "documented but not implemented — remove them or build them:\n" + "\n".join(phantom)
        )

    def test_every_endpoint_is_documented(self) -> None:
        undocumented = sorted(f"{method} {path}" for method, path in _implemented() - _documented())
        assert not undocumented, (
            "implemented but not documented — a client cannot find these:\n"
            + "\n".join(undocumented)
        )


class TestTheAbsencesAreStatedRatherThanSilent:
    """An endpoint an earlier draft specified is worth a sentence saying it was
    never built. Someone may still be holding that draft."""

    @pytest.mark.parametrize(
        ("operation", "phrase"),
        [(op, phrase) for op, phrase in DELIBERATELY_ABSENT.items() if phrase],
        ids=lambda value: value if isinstance(value, str) else f"{value[0]} {value[1]}",
    )
    def test_the_document_explains_each_absence(
        self, operation: tuple[str, str], phrase: str
    ) -> None:
        assert phrase in SPEC.read_text(), f"{operation[0]} {operation[1]} is absent, unexplained"

    @pytest.mark.parametrize("operation", sorted(DELIBERATELY_ABSENT))
    def test_none_of_them_is_secretly_implemented(self, operation: tuple[str, str]) -> None:
        """If one gets built, it must leave this list — an endpoint documented as
        absent while it answers requests is the worst of both."""
        method, path = operation
        assert (method, _normalise(path)) not in _implemented()


class TestThePollingContractNamesRealEndpoints:
    """The specific instance that would have cost a client the most: the
    document told them to poll an endpoint that returns 404."""

    def test_the_polling_section_does_not_mention_a_run_resource(self) -> None:
        section = SPEC.read_text().split("## Polling contract", 1)[1]
        assert "/runs/" not in section

    @pytest.mark.parametrize(
        "path",
        [
            "/v1/campaigns/{id}/generation",
            "/v1/campaigns/{id}/evaluation",
            "/v1/campaigns/{id}/guardian",
            "/v1/campaigns/{id}/overview",
        ],
    )
    def test_each_polled_endpoint_is_real(self, path: str) -> None:
        section = SPEC.read_text().split("## Polling contract", 1)[1]
        assert path in section
        assert ("GET", _normalise(path)) in _implemented()


class TestTheDocumentedErrorCodesAreTheEmittableOnes:
    """Audit finding DOC-3. Two documented codes could not be emitted and six
    emittable ones were undocumented."""

    @staticmethod
    def _emittable() -> set[str]:
        """Every `code` on an error class the app can raise.

        Walked rather than listed: a code added to a new `ProviderError` subclass
        and not documented is exactly the drift this catches, and a hand-written
        list here would have to be remembered too.
        """
        import app.errors as errors
        from app.providers import base
        from app.providers.local import storage

        codes = {"INTERNAL"}
        for module in (errors, base, storage):
            for name in dir(module):
                attribute = getattr(module, name)
                if isinstance(attribute, type) and isinstance(
                    getattr(attribute, "code", None), str
                ):
                    codes.add(attribute.code)
        return codes

    @staticmethod
    def _documented() -> set[str]:
        """The code table only.

        Scoped to the section between the error envelope and the next bullet,
        because the document is full of other tables whose first column is also a
        backticked capital word — the HTTP methods. Reading those as error codes
        is how this test first claimed `GET` was an unreachable code.
        """
        text = SPEC.read_text()
        section = text.split("| Code | When |", 1)[1].split("- **Idempotency:**", 1)[0]
        return set(re.findall(r"^\s*\| `([A-Z_]+)` \|", section, re.M))

    def test_the_code_table_was_found(self) -> None:
        assert "| Code | When |" in SPEC.read_text()
        assert "VALIDATION_FAILED" in self._documented()
        assert len(self._documented()) >= 10

    def test_no_http_method_was_mistaken_for_an_error_code(self) -> None:
        assert not {"GET", "POST", "PATCH", "PUT", "DELETE"} & self._documented()

    def test_every_documented_code_can_occur(self) -> None:
        unreachable = sorted(self._documented() - self._emittable())
        assert not unreachable, f"documented but nothing can emit these: {unreachable}"

    def test_every_emittable_code_is_documented(self) -> None:
        missing = sorted(self._emittable() - self._documented())
        assert not missing, f"a client cannot handle what it is not told about: {missing}"

    def test_the_two_codes_the_audit_found_unreachable_are_gone(self) -> None:
        """`RATE_LIMITED` and `GRAPH_ERROR` were documented and unemittable."""
        assert "RATE_LIMITED" not in self._documented() - {"PROVIDER_RATE_LIMITED"}
        assert "GRAPH_ERROR" not in self._documented()
