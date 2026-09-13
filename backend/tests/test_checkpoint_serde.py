"""Checkpoint serialization allowlist.

Regression tests for M1_SECURITY_AUDIT finding A-2: `build_serde()` produced an
allow-everything serializer whenever `LANGGRAPH_STRICT_MSGPACK` was absent from
`os.environ`, because `with_msgpack_allowlist()` short-circuits on a permissive
base and returns the object unchanged.

These tests deliberately assert the restriction **with the environment variable
removed**, since that is the condition under which it silently failed — and the
condition the real server runs in, because `backend/.env` is read by
pydantic-settings into `Settings`, never into `os.environ`.
"""

from __future__ import annotations

import os

import pytest

from app.graph.serde import allowlisted_types, build_serde, checkpointer_kwargs

pytestmark = pytest.mark.unit


@pytest.fixture
def without_strict_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact condition that used to defeat the allowlist."""
    monkeypatch.delenv("LANGGRAPH_STRICT_MSGPACK", raising=False)
    assert "LANGGRAPH_STRICT_MSGPACK" not in os.environ


class TestAllowlistIsUnconditional:
    def test_allowlist_is_not_allow_everything(self, without_strict_env: None) -> None:
        allowed = build_serde()._allowed_msgpack_modules
        assert allowed is not True, (
            "serializer accepts any type from a checkpoint — the allowlist was discarded"
        )
        assert isinstance(allowed, set | frozenset | tuple)

    def test_allowlist_actually_contains_our_domain_types(self, without_strict_env: None) -> None:
        allowed = build_serde()._allowed_msgpack_modules
        assert ("app.graph.state", "CampaignState") in allowed
        for expected in (
            ("app.domain.common", "Channel"),
            ("app.domain.campaign", "CampaignBrief"),
            ("app.domain.generation", "GenerationJob"),
            ("app.domain.brand", "BrandProfile"),
        ):
            assert expected in allowed, f"{expected} missing from the checkpoint allowlist"

    def test_a_type_we_never_declared_is_not_allowed(self, without_strict_env: None) -> None:
        """The point of an allowlist is what it excludes."""
        allowed = build_serde()._allowed_msgpack_modules
        assert ("subprocess", "Popen") not in allowed
        assert ("os", "system") not in allowed
        assert not any(module == "builtins" for module, _ in allowed)

    def test_the_checkpointer_factory_carries_the_same_allowlist(
        self, without_strict_env: None
    ) -> None:
        """Nothing may build a checkpointer without it (app/graph/serde.py)."""
        serde = checkpointer_kwargs()["serde"]
        assert serde._allowed_msgpack_modules is not True


class TestAllowlistDerivation:
    def test_it_is_derived_from_the_domain_package_not_hand_listed(self) -> None:
        """A hand-written list rots the first time a field gets a new type.

        Compared by class identity, not by name: `CampaignSpecification` is an
        alias of `CampaignBrief` (PRODUCT_SPEC §1a), so the two names resolve
        to one class and a name-based comparison would report a false gap.
        """
        import app.domain as domain

        declared = set(allowlisted_types())
        exported_models = {
            obj
            for name in domain.__all__
            if isinstance(obj := getattr(domain, name, None), type) and hasattr(obj, "model_fields")
        }
        assert exported_models <= declared

    def test_campaign_state_itself_is_declared(self) -> None:
        from app.graph.state import CampaignState

        assert CampaignState in set(allowlisted_types())
