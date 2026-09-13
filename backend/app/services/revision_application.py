"""Applying a revision.

A **pure function**: `v1 + delta = exactly this v2`, every time. No model, no
clock, no database. That is the whole point — a user approves a change, and
what runs is the change they approved, not a model's second interpretation of
their feedback.

It is also what makes "everything is good except the environment" mean what it
says. Only the named fields move; every other field is copied across
untouched, and `changed_fields` reports what actually differed rather than what
the delta intended.

The previous version is never mutated. `apply_revision` returns a *new*
`CreativeSpecification` with a new id and the next version number, so the
assets generated from v1 keep pointing at a v1 that still says what it said.
"""

from __future__ import annotations

from typing import Any

from app.domain.creative import CreativeSpecification
from app.domain.revision import (
    IMMUTABLE_FIELDS,
    LOCKED_FIELDS,
    RevisionDelta,
)
from app.logging import get_logger

log = get_logger(__name__)

#: Fields that hold a list of short strings. `ADD` appends and `REMOVE` drops;
#: on any other field those actions have no meaning.
LIST_FIELDS: frozenset[str] = frozenset({"palette", "mood", "style_families", "regional_cues"})


class RevisionNotApplicable(ValueError):
    """The delta cannot be applied to this specification as written."""


def apply_revision(
    specification: CreativeSpecification, delta: RevisionDelta
) -> tuple[CreativeSpecification, list[str]]:
    """Produce the next version. Returns it and the fields that really changed.

    Deterministic and total: given the same inputs it always returns the same
    output, and every field not named by the delta is carried across exactly.
    """
    if delta.is_empty():
        raise RevisionNotApplicable("This revision makes no changes.")

    data: dict[str, Any] = specification.model_dump()
    before = specification.model_dump(mode="json")

    for item in delta.change:
        _guard(item.field, delta)
        data[item.field] = _coerce(specification, item.field, item.new_value)

    for item in delta.add:
        _guard(item.field, delta)
        if item.field not in LIST_FIELDS:
            raise RevisionNotApplicable(
                f"{item.field} is not a list, so there is nothing to add to."
            )
        existing = list(data.get(item.field) or [])
        value = str(item.new_value)
        if value not in existing:
            existing.append(value)
        data[item.field] = existing

    for item in delta.remove:
        _guard(item.field, delta)
        if item.field in LIST_FIELDS:
            data[item.field] = [
                entry for entry in (data.get(item.field) or []) if entry != item.new_value
            ]
        elif _is_optional(item.field):
            data[item.field] = None
        else:
            raise RevisionNotApplicable(
                f"{item.field} is required, so it cannot be removed — change it instead."
            )

    # Identity and provenance: a revision produces a successor, not a disguise.
    # Dropping the id lets the model mint a fresh one, so v2 is its own row and
    # v1 keeps saying exactly what it said.
    data.pop("id", None)
    data["version"] = specification.version + 1
    # A human's earlier edits are still theirs. Anything this revision rewrote
    # is no longer a human edit, because a human did not write the new value.
    touched = set(delta.touched_fields())
    data["human_edited_fields"] = sorted(set(specification.human_edited_fields) - touched)
    data["locked_fields"] = sorted(set(specification.locked_fields) | set(LOCKED_FIELDS))

    revised = CreativeSpecification.model_validate(data)

    after = revised.model_dump(mode="json")
    changed = sorted(
        name
        for name in before
        if name not in ("id", "version", "human_edited_fields", "locked_fields")
        and before[name] != after.get(name)
    )
    _assert_kept(delta, before, after)

    log.info(
        "revision_applied",
        from_version=specification.version,
        to_version=revised.version,
        changed=changed,
    )
    return revised, changed


def _guard(name: str, delta: RevisionDelta) -> None:
    """The last line of defence.

    The delta's own validator already refuses an uninvited locked field, and
    the planner drops one before it gets that far. Checking again here means a
    delta assembled by any future path — an import, a fixture, a new endpoint —
    still cannot quietly rewrite an approved fact.
    """
    if name in IMMUTABLE_FIELDS:
        raise RevisionNotApplicable(f"{name} can never be revised.")
    if name in LOCKED_FIELDS and name not in delta.explicit_unlocks:
        raise RevisionNotApplicable(
            f"{name} is locked and this revision did not explicitly unlock it."
        )
    if name not in CreativeSpecification.model_fields:
        raise RevisionNotApplicable(f"{name} is not a field of the creative plan.")


def _coerce(specification: CreativeSpecification, name: str, value: str | None) -> Any:
    """Turn the delta's text into the field's own shape.

    A delta carries strings because a human reads and edits it. A list field
    takes a comma-separated list; everything else takes the text as written.
    Nothing here guesses at a nested model — a structured field is changed
    wholesale by the service that owns it, not by prose.
    """
    if value is None:
        raise RevisionNotApplicable(f"{name} has no new value.")
    if name in LIST_FIELDS:
        return [part.strip() for part in value.split(",") if part.strip()]

    current = getattr(specification, name, None)
    if isinstance(current, bool) or isinstance(current, int) and not isinstance(current, bool):
        raise RevisionNotApplicable(f"{name} is not text and cannot be revised this way.")
    if current is not None and not isinstance(current, str):
        raise RevisionNotApplicable(f"{name} is structured and cannot be revised as text.")
    return value


def _is_optional(name: str) -> bool:
    info = CreativeSpecification.model_fields.get(name)
    return info is not None and not info.is_required()


def _assert_kept(delta: RevisionDelta, before: dict[str, Any], after: dict[str, Any]) -> None:
    """KEEP has to mean kept.

    The promise the whole revision loop rests on: a user who was told a field
    would be preserved must find it preserved. Checked against the real before
    and after rather than trusted, because a bug here would be invisible and
    would quietly undo approved work.
    """
    broken = [name for name in delta.keep if name in before and before[name] != after.get(name)]
    if broken:
        raise RevisionNotApplicable(
            f"These fields were promised unchanged but differ: {sorted(broken)}"
        )
