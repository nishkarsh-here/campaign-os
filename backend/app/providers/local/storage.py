"""Local filesystem storage.

The development and demo storage backend. Chosen as the default because it has
no cloud dependency: a demo cannot fail because a bucket is unreachable
(ADR-002, DEMO SAFETY).

Keys are opaque to callers and validated here. A key that escapes the storage
root is rejected before any filesystem call — path traversal is the one real
security risk in a local-disk backend.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.providers.base import ProviderError, StoredFile

#: Segments of letters, digits, dash, underscore and dot, separated by "/".
#: Deliberately strict: no "..", no absolute paths, no backslashes, no spaces.
_SEGMENT = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
_KEY_PATTERN = re.compile(rf"^{_SEGMENT}(?:/{_SEGMENT})*$")


class InvalidStorageKey(ProviderError):
    code = "INVALID_STORAGE_KEY"


class StorageObjectNotFound(ProviderError):
    code = "STORAGE_OBJECT_NOT_FOUND"


class LocalStorageProvider:
    """Stores objects under `root`, one file per key."""

    name = "local"

    def __init__(self, root: str) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        if not key or len(key) > 512 or not _KEY_PATTERN.match(key) or ".." in key.split("/"):
            raise InvalidStorageKey(f"Invalid storage key: {key!r}", provider=self.name)
        path = (self._root / key).resolve()
        # Belt and braces: even with a validated key, confirm the resolved path
        # is inside the root before touching the filesystem.
        if not path.is_relative_to(self._root):
            raise InvalidStorageKey(f"Storage key escapes the root: {key!r}", provider=self.name)
        return path

    async def put(self, key: str, data: bytes, *, mime_type: str) -> StoredFile:
        path = self._path_for(key)

        def _write() -> int:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename: a reader never sees a half-written object.
            temp = path.with_suffix(path.suffix + ".part")
            temp.write_bytes(data)
            temp.replace(path)
            return len(data)

        written = await asyncio.to_thread(_write)
        return StoredFile(storage_key=key, mime_type=mime_type, bytes_written=written)

    async def get(self, key: str) -> bytes:
        path = self._path_for(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise StorageObjectNotFound(f"No object at {key!r}", provider=self.name) from exc

    async def delete(self, key: str) -> None:
        path = self._path_for(key)
        await asyncio.to_thread(path.unlink, True)  # missing_ok=True

    async def signed_url(self, key: str, *, expires_in: int = 3600) -> str:
        """Not a URL a browser can fetch, and deliberately so.

        Local storage cannot sign anything, and this build serves no route that
        takes a storage key from the request — every byte-serving endpoint
        resolves a scope-checked row first and reads *its* key. A key handed to
        the browser would be an object address with no organization attached,
        which is exactly the hole the repository layer exists to close.

        The method stays because `StorageProvider` declares it and a hosted
        provider implements it properly. Here it validates the key and returns
        an internal reference, so a caller that starts depending on it fails
        visibly rather than leaking.
        """
        self._path_for(key)
        return f"local://{key}"
