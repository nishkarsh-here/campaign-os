"""Checkpoint serialization allowlist.

LangGraph serializes `CampaignState` into Postgres with msgpack. By default it
will deserialize *any* type and merely warn:

    Deserializing unregistered type app.domain.common.Channel from checkpoint.
    This will be blocked in a future version.

Two problems with leaving that alone. The obvious one is that a LangGraph
upgrade would start blocking our own domain types and break resume — the single
mechanism every human-approval gate depends on. The subtler one is that a
permissive deserializer will instantiate whatever a checkpoint row names, so
anyone who can write to the checkpoint table can choose what gets constructed.

So we declare the types we actually store, and run strict. An unregistered type
then fails loudly in development instead of silently on a library bump.
Found by the R-2 spike; see `docs/R2_CHECKPOINT_SPIKE.md`.
"""

from __future__ import annotations

import enum
import inspect
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

import app.domain as domain
from app.graph.state import CampaignState


def _domain_types() -> tuple[type, ...]:
    """Every Pydantic model and enum exported by `app.domain`.

    Derived rather than hand-listed: a hand-written list silently rots the
    first time someone adds a field whose type is new, and the failure would
    surface as a broken resume months later.
    """
    found: list[type] = []
    for name in domain.__all__:
        obj = getattr(domain, name, None)
        if inspect.isclass(obj) and issubclass(obj, BaseModel | enum.Enum):
            found.append(obj)
    return tuple(found)


def allowlisted_types() -> tuple[type, ...]:
    return (CampaignState, *_domain_types())


def build_serde() -> JsonPlusSerializer:
    """The serializer every checkpointer must be constructed with.

    The allowlist is passed to the **constructor**, not merged in afterwards.
    `JsonPlusSerializer()` defaults to a permissive allow-everything list
    unless `LANGGRAPH_STRICT_MSGPACK` happens to be set in `os.environ`, and
    `with_msgpack_allowlist()` short-circuits on a permissive base — it returns
    the same object unchanged. The result was an allow-all serializer that
    looked restrictive. Worse, `LANGGRAPH_STRICT_MSGPACK=true` in `backend/.env`
    does not help: pydantic-settings reads that file into `Settings`, never
    into `os.environ`, so the running server never saw it.

    Constructing with the list makes the restriction unconditional.
    `tests/test_checkpoint_serde.py` asserts it holds with the variable unset.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=allowlisted_types())


def checkpointer_kwargs() -> dict[str, Any]:
    """Spread into `AsyncPostgresSaver.from_conn_string(...)`.

    Exists so there is exactly one way to build a checkpointer, and no call
    site can forget the allowlist.
    """
    return {"serde": build_serde()}
