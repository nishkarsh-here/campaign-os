"""R-2: LangGraph Postgres checkpointer round-trip.

Human-in-the-loop is the product. Every approval gate assumes a paused graph
can be resumed later — after a page reload, a redeploy, or a laptop closing
mid-demo. That assumption is load-bearing for Milestones 4 through 8, so it is
proved here rather than believed.

The two phases run as **separate OS processes**. Nothing is shared but the
Postgres checkpoint: not the saver, not the compiled graph, not the
interpreter. An in-process test would prove almost nothing, because a cached
object graph would carry the state for free.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.config import get_settings

pytestmark = [pytest.mark.integration, pytest.mark.e2e]

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNNER = "tests.integration.r2_resume_runner"


def _run(phase: str, thread_id: str, dsn: str) -> dict:
    """Execute one phase in its own process and return its report."""
    env = {
        **os.environ,
        # Strict: an unregistered type must fail here, not silently on a future
        # LangGraph upgrade. See app/graph/serde.py.
        "LANGGRAPH_STRICT_MSGPACK": "true",
        "PYTHONPATH": str(BACKEND_ROOT),
    }
    result = subprocess.run(
        [sys.executable, "-m", RUNNER, phase, thread_id, dsn],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=BACKEND_ROOT,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"phase {phase} failed:\n{result.stderr}"
    assert "Deserializing unregistered type" not in result.stderr, (
        "A domain type is missing from the checkpoint allowlist "
        f"(app/graph/serde.py):\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def dsn() -> str:
    return get_settings().database_url_sync.replace("/campaign_os", "/campaign_os_test")


@pytest.fixture(scope="module")
def round_trip(dsn: str) -> tuple[dict, dict]:
    """Phase A pauses at a gate and the process exits; phase B is a brand-new
    process that must recover everything from Postgres alone."""
    thread_id = f"r2-{uuid.uuid4().hex[:12]}"
    return _run("a", thread_id, dsn), _run("b", thread_id, dsn)


class TestCheckpointRoundTrip:
    def test_phase_a_pauses_at_the_interrupt(self, round_trip) -> None:
        a, _ = round_trip
        assert a["interrupted"] is True
        assert a["next_nodes"] == ["gate"], "the graph must stop *at* the gate"

    def test_a_fresh_process_sees_the_pending_gate(self, round_trip) -> None:
        """The part the demo depends on: a new process, told only a thread id,
        knows exactly where the graph is waiting."""
        _, b = round_trip
        assert b["resumed_from_pending_node"] == ["gate"]

    def test_resume_runs_to_completion(self, round_trip) -> None:
        _, b = round_trip
        assert b["completed"] is True
        assert b["state"]["status"] == "COMPLETED"

    def test_state_written_before_the_pause_survives(self, round_trip) -> None:
        a, b = round_trip
        before = b["state_before_resume"]
        assert before["brand_name"] == a["state"]["brand_name"]
        assert before["brief_channels"] == a["state"]["brief_channels"]
        assert before["error_count"] == a["state"]["error_count"]

    def test_models_rehydrate_as_models_not_dicts(self, round_trip) -> None:
        """The crux. A node calling `state.brand.primary_color()` breaks if the
        checkpoint hands back a plain dict, and it would break at Milestone 5,
        far from the cause."""
        _, b = round_trip
        before = b["state_before_resume"]
        assert before["brand_type"] == "BrandProfile"
        assert before["brief_type"] == "CampaignBrief"
        assert before["job_type"] == "GenerationJob"
        # A method on the rehydrated model, not just attribute access.
        assert before["brand_primary_hex"] == "#1F2933"

    def test_enums_and_datetimes_survive(self, round_trip) -> None:
        _, b = round_trip
        before = b["state_before_resume"]
        assert before["brand_styles"] == ["premium", "technical"]
        assert before["brief_channels"] == ["instagram_post", "linkedin"]
        assert before["error_has_datetime"] is True


class TestReducersAcrossTheProcessBoundary:
    """Reducers are unit-tested in `test_state.py`; this proves they still
    behave once LangGraph, msgpack and Postgres are in the path."""

    def test_append_reducer_adds_rather_than_replaces(self, round_trip) -> None:
        _, b = round_trip
        assert b["state_before_resume"]["conversation_len"] == 1
        assert b["state"]["conversation_len"] == 2
        assert b["state"]["conversation_roles"] == ["user", "assistant"]

    def test_upsert_reducer_updates_in_place(self, round_trip) -> None:
        """A job moving PENDING -> COMPLETED must stay one row. With a plain
        append reducer the UI would show two of every image."""
        _, b = round_trip
        assert b["state_before_resume"]["job_statuses"] == ["PENDING"]
        assert b["state"]["job_count"] == 1
        assert b["state"]["job_statuses"] == ["COMPLETED"]

    def test_the_human_decision_is_recorded(self, round_trip) -> None:
        _, b = round_trip
        assert b["state"]["approval_gates"] == ["strategy"]
        assert b["state"]["approval_decision"] == "APPROVE"
