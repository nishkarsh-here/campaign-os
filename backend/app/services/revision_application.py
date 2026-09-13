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

from app.domain.common import Channel
from app.domain.creative import CreativeSpecification
from app.domain.revision import (
    IMMUTABLE_FIELDS,
    LOCKED_FIELDS,
    RevisionDelta,
    locked_leaf,
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
        parsed = parse_channel_copy_field(item.field)
        if parsed is not None:
            _set_channel_copy(data, parsed, item.new_value, item.field)
        else:
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
        parsed = parse_channel_copy_field(item.field)
        if parsed is not None:
            # Removing an override means "go back to the default for this
            # channel", not "this channel has no headline".
            _set_channel_copy(data, parsed, None, item.field)
        elif item.field in LIST_FIELDS:
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


#: The root of a per-channel copy field name. A delta carries `field` as text,
#: so a channel override is addressed by a dotted path —
#: `channel_copy.instagram_story.headline` — which is the only shape that lets
#: one channel be revised without rewriting the whole map as prose.
CHANNEL_COPY_ROOT = "channel_copy"

#: Leaves an override may carry. Deliberately the same three as `ChannelCopy`.
_CHANNEL_COPY_LEAVES: frozenset[str] = frozenset({"headline", "subhead", "cta"})


def parse_channel_copy_field(name: str) -> tuple[Channel, str] | None:
    """`channel_copy.linkedin.headline` -> `(Channel.LINKEDIN, "headline")`.

    Returns `None` for anything that is not one of these, so a caller can fall
    through to ordinary field handling without a second pattern.
    """
    parts = name.split(".")
    if len(parts) != 3 or parts[0] != CHANNEL_COPY_ROOT:
        return None
    try:
        channel = Channel(parts[1])
    except ValueError as exc:
        raise RevisionNotApplicable(f"{parts[1]!r} is not a channel.") from exc
    if parts[2] not in _CHANNEL_COPY_LEAVES:
        raise RevisionNotApplicable(
            f"{parts[2]!r} is not per-channel copy. "
            f"Expected one of {', '.join(sorted(_CHANNEL_COPY_LEAVES))}."
        )
    return channel, parts[2]


def _guard(name: str, delta: RevisionDelta) -> None:
    """The last line of defence.

    The delta's own validator already refuses an uninvited locked field, and
    the planner drops one before it gets that far. Checking again here means a
    delta assembled by any future path — an import, a fixture, a new endpoint —
    still cannot quietly rewrite an approved fact.
    """
    if name in IMMUTABLE_FIELDS:
        raise RevisionNotApplicable(f"{name} can never be revised.")

    parsed = parse_channel_copy_field(name)
    if parsed is not None:
        # A channel's call to action is an approved fact exactly as the default
        # one is. Locking the root instead would lock every override together,
        # so that a headline tweak on one channel would need the CTA unlocked.
        if locked_leaf(name) and name not in delta.explicit_unlocks:
            raise RevisionNotApplicable(
                f"{name} is locked and this revision did not explicitly unlock it."
            )
        return

    if name in LOCKED_FIELDS and name not in delta.explicit_unlocks:
        raise RevisionNotApplicable(
            f"{name} is locked and this revision did not explicitly unlock it."
        )
    if name == CHANNEL_COPY_ROOT:
        raise RevisionNotApplicable(
            "Per-channel copy is revised one channel at a time, as "
            "channel_copy.<channel>.<headline|subhead|cta>."
        )
    if name not in CreativeSpecification.model_fields:
        raise RevisionNotApplicable(f"{name} is not a field of the creative plan.")


def _set_channel_copy(
    data: dict[str, Any], parsed: tuple[Channel, str], value: str | None, field: str
) -> None:
    """Write one leaf of one channel's override, leaving every other alone.

    Reads and writes the map in place rather than replacing it, which is what
    makes "revise the story headline" leave the LinkedIn override untouched —
    the property acceptance criterion 5 asks for.
    """
    channel, leaf = parsed
    # Normalised to `Channel` keys. `model_dump()` without mode="json" yields
    # enum keys, but a payload round-tripped through JSONB yields strings, and
    # a map holding both would silently keep two overrides for one channel.
    # `None` leaves are stripped as they are read. `model_dump()` writes every
    # optional field, so an override always arrives with all three keys and a
    # map that kept them would never look empty — and the last leaf could be
    # removed without the override itself ever going away.
    overrides: dict[Channel, dict[str, str]] = {
        Channel(key): {leaf: text for leaf, text in (value_ or {}).items() if text}
        for key, value_ in (data.get(CHANNEL_COPY_ROOT) or {}).items()
    }
    existing = overrides.get(channel, {})

    if value is None:
        existing.pop(leaf, None)
    else:
        text = value.strip()
        if not text:
            raise RevisionNotApplicable(f"{field} cannot be set to nothing.")
        existing[leaf] = text

    # An override with nothing left in it is dropped rather than kept empty:
    # "no override" and "an override that overrides nothing" should not be two
    # states a reader has to tell apart.
    if existing:
        overrides[channel] = existing
    else:
        overrides.pop(channel, None)
    data[CHANNEL_COPY_ROOT] = overrides


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
