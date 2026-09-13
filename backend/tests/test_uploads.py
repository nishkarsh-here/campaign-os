"""Upload validation.

The declared content type is attacker-controlled, so most of this is about
what happens when it disagrees with the bytes.
"""

from __future__ import annotations

import uuid

import pytest

from app.errors import ValidationFailed
from app.services.uploads import (
    IMAGE_MIMES,
    PDF_MIME,
    TEXT_MIMES,
    safe_filename,
    sniff_mime,
    storage_key_for,
    validate_upload,
)

pytestmark = pytest.mark.unit

ALLOWED = frozenset({PDF_MIME, *TEXT_MIMES, *IMAGE_MIMES})
MAX = 15 * 1024 * 1024

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


def _validate(data: bytes, mime: str, filename: str = "f.bin"):
    return validate_upload(
        data, declared_mime=mime, filename=filename, allowed=ALLOWED, max_bytes=MAX
    )


class TestMagicBytes:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [(PDF, PDF_MIME), (PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")],
    )
    def test_known_formats_are_recognised(self, data: bytes, expected: str) -> None:
        assert sniff_mime(data) == expected

    def test_unknown_bytes_sniff_to_none(self) -> None:
        assert sniff_mime(b"just some bytes") is None

    def test_a_binary_masquerading_as_pdf_is_refused(self) -> None:
        """The case that matters: a declared type the bytes contradict."""
        with pytest.raises(ValidationFailed) as exc:
            _validate(b"MZ\x90\x00 this is a windows executable", PDF_MIME, "invoice.pdf")
        assert exc.value.details["detected"] == "unknown"

    def test_a_png_declared_as_a_pdf_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            _validate(PNG, PDF_MIME, "logo.pdf")

    def test_a_pdf_declared_as_png_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            _validate(PDF, "image/png", "doc.png")


class TestTypeAndSize:
    def test_a_disallowed_type_is_refused(self) -> None:
        with pytest.raises(ValidationFailed) as exc:
            _validate(b"#!/bin/sh\n", "application/x-sh", "run.sh")
        assert "allowed" in exc.value.details

    def test_a_missing_content_type_is_refused(self) -> None:
        with pytest.raises(ValidationFailed):
            _validate(PDF, "", "x.pdf")

    def test_an_empty_file_is_refused(self) -> None:
        with pytest.raises(ValidationFailed, match="empty"):
            _validate(b"", PDF_MIME)

    def test_an_oversized_file_is_refused(self) -> None:
        with pytest.raises(ValidationFailed, match="larger than"):
            validate_upload(
                PDF + b"\x00" * 2048,
                declared_mime=PDF_MIME,
                filename="big.pdf",
                allowed=ALLOWED,
                max_bytes=1024,
            )

    def test_a_content_type_with_parameters_is_accepted(self) -> None:
        result = _validate(b"hello", "text/plain; charset=utf-8", "notes.txt")
        assert result.mime_type == "text/plain"

    def test_text_must_decode_as_utf8(self) -> None:
        with pytest.raises(ValidationFailed, match="UTF-8"):
            _validate(b"\xff\xfe\x00binary", "text/plain", "notes.txt")

    def test_a_valid_upload_reports_size_and_digest(self) -> None:
        result = _validate(PDF, PDF_MIME, "guide.pdf")
        assert result.size_bytes == len(PDF)
        assert len(result.sha256) == 64


class TestFilenameSafety:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("../../etc/passwd", "passwd"),
            ("C:\\Windows\\system32\\evil.dll", "evil.dll"),
            ("my brand guide.pdf", "my_brand_guide.pdf"),
            (None, "upload"),
            ("", "upload"),
            ("...", "upload"),
        ],
    )
    def test_filenames_are_reduced_to_something_safe(self, raw, expected: str) -> None:
        assert safe_filename(raw) == expected

    def test_a_very_long_filename_is_truncated(self) -> None:
        assert len(safe_filename("a" * 500 + ".pdf")) <= 120

    @pytest.mark.parametrize(
        "raw",
        [
            "<script>alert(1)</script>.pdf",
            'x" onerror="alert(1)".png',
            "a;rm -rf /.pdf",
            "file\x00.pdf",
        ],
    )
    def test_no_markup_or_shell_characters_survive(self, raw: str) -> None:
        """The filename is echoed back to the browser, so assert the property
        rather than an exact string — the exact result depends on where the
        path split falls, which is not what matters."""
        cleaned = safe_filename(raw)
        assert not set(cleaned) & set("<>\"'`;&|$(){}[]*?!\\ \x00")
        assert cleaned


class TestStorageKeys:
    def test_the_key_is_generated_not_taken_from_the_filename(self) -> None:
        org, brand = uuid.uuid4(), uuid.uuid4()
        key = storage_key_for(
            organization_id=org, brand_id=brand, kind="documents", extension="pdf"
        )
        assert key.startswith(f"org-{org}/brand-{brand}/documents/")
        assert key.endswith(".pdf")

    def test_two_uploads_never_collide(self) -> None:
        org, brand = uuid.uuid4(), uuid.uuid4()
        keys = {
            storage_key_for(organization_id=org, brand_id=brand, kind="documents", extension="pdf")
            for _ in range(50)
        }
        assert len(keys) == 50

    def test_a_hostile_extension_cannot_escape_the_key_shape(self) -> None:
        key = storage_key_for(
            organization_id=uuid.uuid4(),
            brand_id=uuid.uuid4(),
            kind="documents",
            extension="../../../etc/passwd",
        )
        assert ".." not in key
        assert key.count("/") == 3

    def test_the_key_is_accepted_by_the_storage_provider(self, tmp_path) -> None:
        """The generated shape must satisfy LocalStorageProvider's own rules."""
        from app.providers.local.storage import LocalStorageProvider

        provider = LocalStorageProvider(str(tmp_path))
        key = storage_key_for(
            organization_id=uuid.uuid4(),
            brand_id=uuid.uuid4(),
            kind="documents",
            extension="pdf",
        )
        provider._path_for(key)  # raises InvalidStorageKey if the shape is wrong
