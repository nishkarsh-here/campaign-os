"""Regenerate the field columns of the GRAPH_SPEC node table from NODE_CONTRACTS.

The documentation explains the graph; `app/graph/contracts.py` enforces it. This
script keeps the two in step so a contract change cannot silently leave the spec
describing a system that no longer exists.

Run from `backend/` after changing any node contract:

    uv run python scripts/sync_graph_spec.py

Only the reads/writes columns are generated. The failure-mode prose is
hand-written and is left alone.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.contracts import NODE_CONTRACTS  # noqa: E402

SPEC = Path(__file__).resolve().parents[2] / "docs" / "GRAPH_SPEC.md"
ROW = re.compile(r"^\| (\d+) \| `([a-z_]+)` \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$")


def format_fields(fields: Iterable[str]) -> str:
    """`status` is written by most nodes; omit it unless it is the only output."""
    names = sorted(f for f in fields if f != "status") or sorted(fields)
    return ", ".join(f"`{n}`" for n in names) or "—"


def main() -> int:
    lines = SPEC.read_text().split("\n")
    rewritten: list[str] = []
    unknown: list[str] = []

    for i, line in enumerate(lines):
        match = ROW.match(line)
        if not match:
            continue
        number, node, _reads, _writes, interrupts, failure = match.groups()
        contract = NODE_CONTRACTS.get(node)
        if contract is None:
            unknown.append(node)
            continue
        updated = (
            f"| {number} | `{node}` | {format_fields(contract.reads)} | "
            f"{format_fields(contract.writes)} | {interrupts} | {failure} |"
        )
        if updated != line:
            lines[i] = updated
            rewritten.append(node)

    SPEC.write_text("\n".join(lines))
    print(f"rewritten: {rewritten or 'none'}")
    if unknown:
        print(f"WARNING — rows with no contract: {unknown}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
