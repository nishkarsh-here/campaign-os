"""The revision loop.

Feedback must **refine, never restart**. That single sentence drives every
decision in this module.

A `RevisionDelta` makes the refinement explicit and auditable: the fields being
preserved are named, the fields being changed are named with a reason, and the
user sees both *before* anything regenerates (PRODUCT_SPEC §8). The delta is
deliberately not a rewritten specification — a model handed "here is the plan,
return a better one" will quietly restate everything, and the approved parts
would be lost in the noise of a diff nobody can read.

**Locked fields.** Some facts a human already approved may not be changed on a
model's initiative: the call to action, how the product is shown, how the brand
appears, and the constraints that keep the plate usable. Feedback may ask for
one of them explicitly — `explicit_unlocks` records that it did — but a
revision can never mutate one by drifting into it.

Applying a delta is a **pure function** (`app.services.revision_application`),
so "v1 + this delta = exactly this v2" is something a test can assert field by
field, and a user can be shown before they approve.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from app.domain.common import DomainModel, Id, new_id

#: Fields on a `CreativeSpecification` a revision may not change unless the
#: feedback explicitly asked. These are the ones a human signed off, and the
#: ones a drifting model is most likely to "improve" without being asked.
LOCKED_FIELDS: tuple[str, ...] = (
    "cta",
    "cta_guidance",
    "product_integration",
    "brand_integration",
    "negative_constraints",
)

#: Fields a revision may never touch at all, explicitly requested or not.
#: Identity and provenance: changing them would make the new version pretend to
#: be something else rather than a successor.
IMMUTABLE_FIELDS: tuple[str, ...] = (
    "id",
    "campaign_id",
    "direction_id",
    "version",
    "human_edited_fields",
    "locked_fields",
)


class RevisionAction(StrEnum):
    """What a delta does to one field.

    `KEEP` is as important as the rest: naming what stays is how a user can see
    that a revision is a refinement and not a rewrite.
    """

    KEEP = "KEEP"
    CHANGE = "CHANGE"
    ADD = "ADD"
    REMOVE = "REMOVE"


class FieldChange(DomainModel):
    """One field, one intent, one reason."""

    field: str = Field(description="A field on CreativeSpecification.")
    action: RevisionAction = RevisionAction.CHANGE
    reason: str = Field(description="Why, in the user's terms.", max_length=300)
    #: The concrete replacement. `None` means "regenerate this field", which
    #: the application service refuses rather than guessing at.
    new_value: str | None = Field(default=None, max_length=1200)

    @model_validator(mode="after")
    def _actions_carry_what_they_need(self) -> FieldChange:
        if self.action in (RevisionAction.CHANGE, RevisionAction.ADD) and not self.new_value:
            raise ValueError(f"{self.field}: {self.action.value} needs a new value")
        if self.action is RevisionAction.KEEP:
            raise ValueError("KEEP belongs in `keep`, not in a field change")
        return self


class RevisionDelta(DomainModel):
    """The interpreted intent of a piece of feedback.

    Carries no specification text of its own beyond the values it is changing,
    so what a user approves is the *change*, not a wall of restated plan.
    """

    id: Id = Field(default_factory=new_id)
    iteration: int = Field(ge=1)
    user_feedback: str = Field(min_length=1, max_length=2000)
    #: What we understood. Shown for confirmation before anything runs.
    interpretation: str = Field(default="", max_length=600)
    #: Fields provably unchanged. Named, not implied.
    keep: list[str] = Field(default_factory=list, max_length=40)
    change: list[FieldChange] = Field(default_factory=list, max_length=20)
    add: list[FieldChange] = Field(default_factory=list, max_length=10)
    remove: list[FieldChange] = Field(default_factory=list, max_length=10)
    #: Locked fields the feedback explicitly asked to change. A revision may
    #: touch a locked field only if it is named here.
    explicit_unlocks: list[str] = Field(default_factory=list, max_length=10)
    #: Why this revision was proposed, in a sentence or two. Never a trace.
    rationale: str = Field(default="", max_length=600)

    def touched_fields(self) -> list[str]:
        """Every field this delta would write, in a stable order."""
        seen: dict[str, None] = {}
        for item in (*self.change, *self.add, *self.remove):
            seen.setdefault(item.field, None)
        return list(seen)

    def is_empty(self) -> bool:
        return not (self.change or self.add or self.remove)

    @model_validator(mode="after")
    def _no_field_both_kept_and_changed(self) -> RevisionDelta:
        conflict = set(self.touched_fields()) & set(self.keep)
        if conflict:
            raise ValueError(f"Fields cannot be both kept and changed: {sorted(conflict)}")
        return self

    @model_validator(mode="after")
    def _a_field_is_touched_once(self) -> RevisionDelta:
        """Two instructions for one field have no defined order, so they are a
        contradiction rather than a plan."""
        touched = [item.field for item in (*self.change, *self.add, *self.remove)]
        duplicates = sorted({f for f in touched if touched.count(f) > 1})
        if duplicates:
            raise ValueError(f"A field may only be revised once: {duplicates}")
        return self

    @model_validator(mode="after")
    def _immutable_fields_are_untouchable(self) -> RevisionDelta:
        blocked = sorted(set(self.touched_fields()) & set(IMMUTABLE_FIELDS))
        if blocked:
            raise ValueError(f"These fields can never be revised: {blocked}")
        return self

    @model_validator(mode="after")
    def _locked_fields_need_an_explicit_unlock(self) -> RevisionDelta:
        """The heart of "refine, never restart".

        A locked field may be changed — the user is allowed to change their
        mind — but only when the feedback said so and the planner recorded it.
        A delta that reached for one uninvited is rejected outright rather than
        silently trimmed, because a silently trimmed delta is a revision that
        did not do what its own summary said.
        """
        reached = set(self.touched_fields()) & set(LOCKED_FIELDS)
        uninvited = sorted(reached - set(self.explicit_unlocks))
        if uninvited:
            raise ValueError(
                f"These fields are locked and were not explicitly unlocked: {uninvited}"
            )
        return self


class RevisionStatus(StrEnum):
    """Where one round of revision stands.

    Two human decisions, so three resting states between them. Explicit rather
    than inferred, for the same reason every other long-running thing in this
    system carries a status: a user must always be able to see what is waiting
    on them.
    """

    #: A delta has been proposed. Waiting on the human to approve or edit it.
    PROPOSED = "PROPOSED"
    #: The delta was approved and applied. A new specification version exists,
    #: waiting on the human to approve *it*.
    APPLIED = "APPLIED"
    #: The revised specification was approved. Regeneration may start.
    APPROVED = "APPROVED"
    #: The human threw the proposal away. The specification never changed.
    REJECTED = "REJECTED"


class RevisionRecord(DomainModel):
    """One entry of campaign history.

    Enough to answer "what changed, why, who asked, and what came of it" — and
    enough for a later milestone to say "this creative was revised because the
    guardian flagged product prominence".
    """

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    iteration: int = Field(ge=1)
    status: RevisionStatus = RevisionStatus.PROPOSED
    delta: RevisionDelta
    #: The asset whose review prompted this. History, not a dependency.
    source_asset_id: Id | None = None
    from_version: int = Field(ge=1)
    #: Null until the delta is applied.
    to_version: int | None = Field(default=None, ge=1)
    from_specification_id: Id | None = None
    to_specification_id: Id | None = None
    #: What actually differed between the two versions, computed by the
    #: application service rather than taken from the delta's intent.
    changed_fields: list[str] = Field(default_factory=list, max_length=40)
    #: Which findings were on the table when this was proposed.
    evaluation_id: Id | None = None
    guardian_id: Id | None = None
