"""State reducers.

LangGraph merges each node's partial update into the shared state. For scalars
last-write-wins is right. For collections it is not: two branches appending to
`errors` must not clobber each other, and a node updating one generation job's
status must not duplicate the job.

Each reducer here is a pure function `(current, update) -> merged`, which is
what makes them trivially testable in isolation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class HasId(Protocol):
    id: str


def append[T](current: list[T] | None, update: list[T] | T | None) -> list[T]:
    """Append-only. Use for logs: conversation, errors, revision history."""
    base = list(current or [])
    if update is None:
        return base
    if isinstance(update, list):
        base.extend(update)
    else:
        base.append(update)
    return base


def upsert_on(key: str) -> Callable[[list[Any] | None, Any], list[Any]]:
    """Build an upsert reducer keyed on `key`, preserving first-seen order.

    Needed wherever an item has a lifecycle: a `GenerationJob` moves
    PENDING -> RUNNING -> COMPLETED and must stay one row, not three.

    The key is explicit because not every domain object is keyed by `id` —
    `ReferenceAnalysis` is keyed by the reference it describes, since there is
    exactly one analysis per reference. Assuming `id` here crashed at runtime
    (ARCHITECTURE_REVIEW C-1); `tests/test_state.py` now asserts that every
    annotated field's item type really carries its key.
    """

    def reducer(current: list[Any] | None, update: list[Any] | Any | None) -> list[Any]:
        base = list(current or [])
        if update is None:
            return base
        incoming = update if isinstance(update, list) else [update]
        index = {getattr(item, key): i for i, item in enumerate(base)}
        for item in incoming:
            identity = getattr(item, key)
            pos = index.get(identity)
            if pos is None:
                index[identity] = len(base)
                base.append(item)
            else:
                base[pos] = item
        return base

    reducer.__name__ = f"upsert_on_{key}"
    #: Read by the guard test to check the key against the item type.
    reducer.upsert_key = key  # type: ignore[attr-defined]
    return reducer


#: The common case: objects keyed by `id`.
upsert_by_id = upsert_on("id")


def merge_dict(current: dict[str, Any] | None, update: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow merge. Used for per-gate approval state."""
    merged = dict(current or {})
    merged.update(update or {})
    return merged
