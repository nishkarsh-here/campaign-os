"""Mock providers — first-class, not an afterthought (CLAUDE.md rule 5).

The entire test suite and the offline demo run on these. They are deterministic
(seeded by a hash of the request, never random) and can be told to fail on
demand so error paths are exercised rather than assumed.

Lands in Milestone 6: `llm.py`, `image.py`, `embedding.py`, `search.py`.
"""
