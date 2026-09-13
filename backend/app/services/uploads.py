"""Upload validation.

`CLAUDE.md` §8 requires file type, magic bytes and size to be checked on every
upload. A declared `Content-Type` is attacker-controlled, so it is treated as a
hint and the bytes decide.

Kept as pure functions over `bytes` so the rules are testable without HTTP, a
database, or a filesystem.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

from app.errors import ValidationFailed

PDF_MIME = "application/pdf"
TEXT_MIMES = frozenset({"text/plain", "text/markdown"})
IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})

#: Leading bytes that identify a format. Checked against the declared type so a
#: .exe renamed to .pdf is refused before it is ever written to storage.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", PDF_MIME),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ValidatedUpload:
    data: bytes
    mime_type: str
    filename: str
    size_bytes: int
    sha256: str


def sniff_mime(data: bytes) -> str | None:
    """The format the bytes actually are, or None if unrecognised."""
    for signature, mime in _MAGIC:
        if data.startswith(signature):
            return mime
    # WEBP is RIFF....WEBP — the marker is at offset 8, not 0.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_filename(raw: str | None) -> str:
    """Reduce a user-supplied filename to something safe to store and display.

    Never used to build a storage path — storage keys are generated — but a
    filename is echoed back to the browser, so it is stripped of anything that
    could be read as a path or as markup.
    """
    candidate = (raw or "upload").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    candidate = _SAFE_FILENAME.sub("_", candidate).strip("._") or "upload"
    return candidate[:120]


def validate_upload(
    data: bytes,
    *,
    declared_mime: str | None,
    filename: str | None,
    allowed: frozenset[str],
    max_bytes: int,
) -> ValidatedUpload:
    """Validate size, declared type and magic bytes together.

    Raises `ValidationFailed` with a message a user can act on — never a raw
    library error.
    """
    if not data:
        raise ValidationFailed("That file is empty.", details={"field": "file"})
    if len(data) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValidationFailed(
            f"That file is larger than the {limit_mb} MB limit.", details={"field": "file"}
        )

    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared not in allowed:
        raise ValidationFailed(
            f"{declared or 'That file type'} is not supported here.",
            details={"field": "file", "allowed": sorted(allowed)},
        )

    sniffed = sniff_mime(data)
    if declared == PDF_MIME or declared in IMAGE_MIMES:
        # Binary formats must prove themselves. A mismatch is the interesting
        # case: it means the declared type was wrong or deliberately misleading.
        if sniffed != declared:
            raise ValidationFailed(
                "That file's contents do not match its type.",
                details={"field": "file", "declared": declared, "detected": sniffed or "unknown"},
            )
    elif declared in TEXT_MIMES:
        # Text has no signature; require it to decode as UTF-8 instead, which
        # also rejects binary masquerading as text.
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationFailed(
                "That file is not valid UTF-8 text.", details={"field": "file"}
            ) from exc

    return ValidatedUpload(
        data=data,
        mime_type=declared,
        filename=safe_filename(filename),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def storage_key_for(
    *, organization_id: uuid.UUID, brand_id: uuid.UUID, kind: str, extension: str
) -> str:
    """Generate the storage key. Never derived from a user-supplied filename.

    The organization prefix is defence in depth, not the access control — that
    stays in the scoped repositories. It means a key alone reveals its owner,
    so a mis-scoped read is obvious in logs rather than silent.
    """
    suffix = _SAFE_FILENAME.sub("", extension.lower()).strip(".")[:8] or "bin"
    return f"org-{organization_id}/brand-{brand_id}/{kind}/{uuid.uuid4().hex}.{suffix}"
