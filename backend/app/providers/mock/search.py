"""Null search provider.

`SEARCH_PROVIDER=none` is the default and the only option Milestone 2 uses:
live web research is explicitly not assigned to this milestone. Market
intelligence degrades cleanly when this returns nothing (GRAPH_SPEC §2).
"""

from __future__ import annotations

from app.providers.base import SearchResult


class NullSearchProvider:
    name = "none"

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        return []
