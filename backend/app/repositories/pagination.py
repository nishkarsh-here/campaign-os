"""Keyset pagination, in one place.

Audit findings DOC-2/BG-6 and PERF-1. `API_SPEC.md` has always stated
`?limit=&cursor=` -> `{items, next_cursor}` as a convention for lists, and
exactly one endpoint implemented it. The rest returned every row: fine for the
campaign-scoped lists, which are bounded by how much work one campaign
accumulates, and not fine for `BrandRepository.list_all()` and
`CampaignRepository.list_all()`, which are organization-scoped and grow with a
tenant's whole history.

Extracted from `ProjectRepository`, which had it right, rather than reimplemented
per repository — three hand-rolled cursors is how the second page comes to behave
differently depending on what you are listing.

**Keyset on `(created_at, id)`, never offset.** An offset page is unstable under
inserts: a row created while someone reads page one reappears or disappears on
page two. The tiebreak on `id` matters because `created_at` is not unique — two
rows written in the same transaction share it, and without the tiebreak one of
them is silently skipped.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Entity
from app.errors import ValidationFailed

#: The default and the ceiling for `?limit=`. A ceiling rather than a suggestion:
#: an unbounded list is the defect, so a caller cannot ask for one.
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    #: `None` means this is the last page — not that the next one is empty.
    next_cursor: str | None


def encode_cursor(value: datetime | str, entity_id: uuid.UUID) -> str:
    """The sort key and the tiebreak, tagged with which kind of key it is.

    Tagged because the two kinds have to be decoded differently and a cursor is
    opaque to the caller, so there is nothing else to tell them apart.
    """
    if isinstance(value, datetime):
        raw = f"t:{value.isoformat()}|{entity_id}"
    else:
        raw = f"s:{value}|{entity_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime | str, uuid.UUID]:
    """Returns a real `datetime` for a timestamp key, not the string it was
    encoded as.

    Postgres will not compare `timestamptz > varchar`, so handing the raw string
    straight into the WHERE clause fails at the second page — which is exactly
    where nobody looks.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        kind, _, rest = raw.partition(":")
        key, _, entity_id = rest.rpartition("|")
        if kind == "t":
            return datetime.fromisoformat(key), uuid.UUID(entity_id)
        if kind == "s":
            return key, uuid.UUID(entity_id)
        raise ValueError(f"unknown cursor kind {kind!r}")
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValidationFailed("Invalid cursor.", details={"cursor": cursor}) from exc


async def keyset_page[RowT: Entity](
    session: AsyncSession,
    stmt: Select[Any],
    model: type[RowT],
    *,
    key: str = "created_at",
    descending: bool = False,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[RowT]:
    """One page of `stmt`, ordered by `(key, id)`.

    `key` and `descending` are parameters rather than a fixed ascending
    `created_at` so a list keeps the order it already had: brands read
    alphabetically, campaigns newest-first. Paging them both one way would have
    silently reordered a screen in order to fix a query nobody could see.

    Takes an already-scoped statement: organization scope belongs to the
    repository and must not be something this helper could forget.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    # By name, because the sort key differs per list. `model.id` is the one
    # column this function names directly, which is what binding to `Entity`
    # makes statically true (see `app/db/base.py`).
    column = getattr(model, key)
    stmt = stmt.order_by(
        *((column.desc(), model.id.desc()) if descending else (column.asc(), model.id.asc()))
    )
    if cursor:
        after, entity_id = decode_cursor(cursor)
        # A cursor is opaque, so nothing stops one minted for another list being
        # replayed here — and Postgres will not compare `text > timestamptz`, so
        # a mismatch is a 500 rather than a wrong page. Refused as a bad cursor,
        # which is what it is.
        expects_time = isinstance(column.type, DateTime)
        if expects_time is not isinstance(after, datetime):
            raise ValidationFailed("Invalid cursor for this list.", details={"cursor": cursor})
        # The comparison has to follow the order, or "the next page" walks
        # backwards and the same rows come round again for ever.
        stmt = stmt.where(
            or_(column < after, and_(column == after, model.id < entity_id))
            if descending
            else or_(column > after, and_(column == after, model.id > entity_id))
        )
    # One more than asked for, so "is there another page" is answered by the
    # query rather than by a second count that could disagree with it.
    rows = list((await session.execute(stmt.limit(limit + 1))).scalars().all())
    items = rows[:limit]
    last = items[-1] if items else None
    return Page(
        items=items,
        next_cursor=(
            encode_cursor(getattr(last, key), last.id)
            if last is not None and len(rows) > limit
            else None
        ),
    )
