"""What a node is allowed to reach for.

Passing a bundle rather than letting nodes import providers is what keeps rule
2 enforceable: a node cannot name a vendor, because it never sees one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.base import EmbeddingProvider, LLMProvider, StorageProvider


@dataclass(frozen=True)
class NodeDeps:
    session: AsyncSession
    organization_id: uuid.UUID
    llm: LLMProvider
    embeddings: EmbeddingProvider
    #: Needed by the creative stage, which reads reference bytes through the
    #: Milestone 4 context service. Optional so discovery-only callers and
    #: unit tests need not supply one.
    storage: StorageProvider | None = None
    #: Hard cap on interview turns, from settings. Separate from the revision
    #: budget so a long interview cannot consume it (ARCHITECTURE_REVIEW C-2).
    max_interview_turns: int = 8
