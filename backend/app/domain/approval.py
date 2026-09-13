"""Human-in-the-loop gates.

Three gates, each with its own decision vocabulary. Modelled as data rather
than as booleans so the API, the graph and the UI all agree on what is legal at
a given moment (GRAPH_SPEC §4).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from app.domain.common import DomainModel, Id, new_id, utc_now


class Gate(StrEnum):
    STRATEGY = "strategy"
    SPECIFICATION = "specification"
    FINAL = "final"


class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"
    EDIT = "EDIT"
    SELECT = "SELECT"
    REGENERATE = "REGENERATE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


#: The only legal decisions per gate. The API rejects anything else with 400,
#: and the graph's routing table is keyed on exactly these.
ALLOWED_DECISIONS: dict[Gate, tuple[Decision, ...]] = {
    Gate.STRATEGY: (Decision.APPROVE, Decision.REJECT, Decision.REQUEST_REVISION),
    Gate.SPECIFICATION: (Decision.APPROVE, Decision.EDIT, Decision.REQUEST_REVISION),
    Gate.FINAL: (Decision.SELECT, Decision.REGENERATE, Decision.REQUEST_CHANGES),
}


class PendingGate(DomainModel):
    """What the graph is waiting for. This is the `interrupt()` payload and the
    thing the UI renders as a decision — so it carries everything needed to
    decide and nothing else."""

    gate: Gate
    options: list[Decision]
    payload: dict[str, Any] = Field(default_factory=dict)
    prompt_text: str = Field(default="", description="The question, in plain language.")


class ApprovalDecision(DomainModel):
    """A human's answer. Persisted; this is the audit trail."""

    id: Id = Field(default_factory=new_id)
    gate: Gate
    decision: Decision
    target_id: Id | None = Field(default=None, description="direction / spec / asset id")
    feedback: str | None = None
    edits: dict[str, Any] = Field(default_factory=dict)
    decided_by: Id | None = None
    decided_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _decision_legal_for_gate(self) -> ApprovalDecision:
        allowed = ALLOWED_DECISIONS[self.gate]
        if self.decision not in allowed:
            names = ", ".join(d.value for d in allowed)
            raise ValueError(
                f"{self.decision} is not valid at gate '{self.gate}'. Allowed: {names}"
            )
        return self
