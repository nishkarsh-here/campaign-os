"""Shared primitives for every domain schema.

`DomainModel` is deliberately strict: unknown fields are rejected. Most domain
objects arrive from a language model, and silently accepting an invented field
is how a system drifts from its own contract without anyone noticing. The
`LLMProvider.structured()` repair pass (ADR-009) exists precisely so this
strictness produces a retry rather than a crash.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# A domain id is a UUID rendered as a string: JSON-serializable, and therefore
# safe to place in LangGraph state, which is checkpointed as JSON.
Id = Annotated[str, Field(min_length=1, max_length=64)]
Score = Annotated[float, Field(ge=0.0, le=10.0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    """Base for all domain schemas."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class JobStatus(StrEnum):
    """The single status vocabulary. Used by jobs, documents, exports, runs."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_HUMAN = "WAITING_HUMAN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CampaignStatus(StrEnum):
    """Where a campaign has reached **in the LangGraph workflow**.

    This lives in `CampaignState`, is checkpointed as JSON, and is the only
    status a graph node ever sets. It spans the whole product arc, including
    stages that are not graph stages at all — generation, evaluation and
    revision left the graph in ADR-012 and ADR-013 — because the state object
    is also what the interview reads to decide it is finished.

    **It is not the `campaigns.status` column.** That column tracks a much
    narrower thing, the discovery lifecycle of the row, and its vocabulary is
    `CampaignRecordStatus` below. Writing a `CampaignStatus` into the column
    is rejected by the database, which is the correct outcome and the reason
    the two enums are now separate and separately named.
    """

    DRAFT = "DRAFT"
    INTERVIEWING = "INTERVIEWING"
    STRATEGY = "STRATEGY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    GENERATING = "GENERATING"
    EVALUATING = "EVALUATING"
    REVISING = "REVISING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CampaignRecordStatus(StrEnum):
    """What the `campaigns.status` **column** may hold.

    The row's own lifecycle, which is about one question: how far has the
    discovery interview got, and has a human confirmed the result? Everything
    after confirmation — directions, generation, evaluation, composition —
    is tracked by its own table with its own status, so the campaign row has
    nothing further to say and deliberately says nothing.

    These are the exact values the `campaigns.status_valid` check constraint
    accepts. The constraint is generated from this enum rather than written
    out beside it, so the two cannot drift; `tests/test_domain_schemas.py`
    asserts the database accepts every member.
    """

    DRAFT = "DRAFT"
    INTERVIEWING = "INTERVIEWING"
    #: The interview produced a Campaign Specification; nobody has agreed it.
    SPECIFICATION_READY = "SPECIFICATION_READY"
    #: A human confirmed it. This is the terminal happy state for the row.
    SPECIFICATION_CONFIRMED = "SPECIFICATION_CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Role(StrEnum):
    ADMIN = "admin"
    BRAND_MANAGER = "brand_manager"
    MARKETING = "marketing"
    DESIGNER = "designer"
    VIEWER = "viewer"


class Channel(StrEnum):
    """Output channels. Each maps to a fixed aspect ratio in the layout engine."""

    INSTAGRAM_POST = "instagram_post"
    #: Instagram feed portrait, 4:5. A distinct channel rather than a crop of
    #: the square: it is the tallest frame the feed will show without cropping
    #: and therefore the one most feed creative is actually built for, and it
    #: needs its own safe area and type scale.
    INSTAGRAM_PORTRAIT = "instagram_portrait"
    INSTAGRAM_STORY = "instagram_story"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    WEB_BANNER = "web_banner"
    PRINT_A3 = "print_a3"
    PRINT_A4 = "print_a4"


CHANNEL_DIMENSIONS: dict[Channel, tuple[int, int]] = {
    Channel.INSTAGRAM_POST: (1080, 1080),
    Channel.INSTAGRAM_PORTRAIT: (1080, 1350),  # 4:5
    Channel.INSTAGRAM_STORY: (1080, 1920),
    Channel.LINKEDIN: (1200, 627),
    Channel.FACEBOOK: (1200, 630),
    Channel.WEB_BANNER: (1456, 816),
    Channel.PRINT_A3: (3508, 4961),  # 297x420mm @ 300dpi
    Channel.PRINT_A4: (2480, 3508),  # 210x297mm @ 300dpi
}


class StyleFamily(StrEnum):
    """Creative Style Explorer vocabulary — how users express taste without
    needing design terminology (PRODUCT_SPEC §10)."""

    PREMIUM = "premium"
    MINIMAL = "minimal"
    TECHNICAL = "technical"
    CINEMATIC = "cinematic"
    BOLD = "bold"
    FESTIVE = "festive"
    LOCAL_CULTURAL = "local_cultural"
    EDITORIAL = "editorial"


class ErrorSeverity(StrEnum):
    WARNING = "warning"  # degraded, run continues
    ERROR = "error"  # node failed, run may continue
    FATAL = "fatal"  # run cannot continue


class ExecutionError(DomainModel):
    """A failure recorded in state. Never raised past a node boundary silently —
    if it is in state, it is shown in the UI (ARCHITECTURE §5)."""

    id: Id = Field(default_factory=new_id)
    node: str
    severity: ErrorSeverity = ErrorSeverity.ERROR
    code: str = Field(description="Stable machine code, e.g. PROVIDER_TIMEOUT.")
    message: str = Field(description="User-safe. No secrets, no vendor internals.")
    detail: str | None = Field(default=None, description="Log-side detail.")
    occurred_at: datetime = Field(default_factory=utc_now)


class Recommendation(DomainModel):
    """An AI recommendation, always with reasons a human can read.

    `reasons` is a decision summary, not chain-of-thought (CLAUDE.md rule 8).
    """

    target_id: Id
    reasons: list[str] = Field(min_length=1, max_length=6)
    confidence: Confidence = 0.7
