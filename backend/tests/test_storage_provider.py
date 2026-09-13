"""LocalStorageProvider.

Mostly a security test. A local-disk backend's one real risk is a key that
escapes the storage root, so that is what most of this covers.
"""

from __future__ import annotations

import pytest

from app.providers.base import StorageProvider
from app.providers.local.storage import (
    InvalidStorageKey,
    LocalStorageProvider,
    StorageObjectNotFound,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path / "store"))


class TestProtocolConformance:
    def test_it_satisfies_the_storage_protocol(self, storage) -> None:
        assert isinstance(storage, StorageProvider)


class TestRoundTrip:
    async def test_put_then_get_returns_the_same_bytes(self, storage) -> None:
        result = await storage.put("brands/logo.png", b"\x89PNG-data", mime_type="image/png")
        assert result.bytes_written == 9
        assert await storage.get("brands/logo.png") == b"\x89PNG-data"

    async def test_put_overwrites_cleanly(self, storage) -> None:
        await storage.put("a/b.txt", b"first", mime_type="text/plain")
        await storage.put("a/b.txt", b"second", mime_type="text/plain")
        assert await storage.get("a/b.txt") == b"second"

    async def test_no_partial_file_is_left_behind(self, storage, tmp_path) -> None:
        """Writes go to a temp file and are renamed, so a reader never sees a
        half-written object."""
        await storage.put("a/b.txt", b"data", mime_type="text/plain")
        assert list((tmp_path / "store" / "a").glob("*.part")) == []

    async def test_missing_object_raises_a_typed_error(self, storage) -> None:
        with pytest.raises(StorageObjectNotFound):
            await storage.get("nope/missing.png")

    async def test_delete_is_idempotent(self, storage) -> None:
        await storage.put("x.txt", b"x", mime_type="text/plain")
        await storage.delete("x.txt")
        await storage.delete("x.txt")  # must not raise


class TestKeyValidation:
    @pytest.mark.parametrize(
        "key",
        [
            "../escape.txt",
            "a/../../escape.txt",
            "/absolute/path.txt",
            "..",
            "a/../..",
            "back\\slash.txt",
            "has space.txt",
            "trailing/",
            "",
            "a" * 600,
        ],
    )
    async def test_dangerous_keys_are_refused(self, storage, key: str) -> None:
        with pytest.raises(InvalidStorageKey):
            await storage.put(key, b"x", mime_type="text/plain")

    async def test_traversal_cannot_read_outside_the_root(self, storage, tmp_path) -> None:
        (tmp_path / "secret.txt").write_bytes(b"should never be readable")
        with pytest.raises(InvalidStorageKey):
            await storage.get("../secret.txt")

    @pytest.mark.parametrize(
        "key", ["logo.png", "brands/b1/logo.png", "a/b/c/d.tar.gz", "UPPER_case-99.webp"]
    )
    async def test_reasonable_keys_are_accepted(self, storage, key: str) -> None:
        await storage.put(key, b"x", mime_type="application/octet-stream")
        assert await storage.get(key) == b"x"


class TestSignedUrl:
    async def test_it_is_not_a_url_a_browser_could_fetch(self, storage) -> None:
        """Local storage cannot sign anything, and this build serves no route
        that takes a storage key from the request — every byte-serving endpoint
        resolves a scope-checked row and reads *its* key.

        So the returned value is deliberately not fetchable. A key handed to a
        browser would be an object address with no organization attached, which
        is the hole the repository layer exists to close; a caller that starts
        relying on this fails visibly instead.
        """
        url = await storage.signed_url("brands/logo.png")
        assert url == "local://brands/logo.png"
        assert not url.startswith(("http://", "https://", "/", "file:"))
        assert "tmp" not in url, "the filesystem path must never leak"

    async def test_signing_still_validates_the_key(self, storage) -> None:
        with pytest.raises(InvalidStorageKey):
            await storage.signed_url("../escape.png")
