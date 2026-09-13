"""Text extraction and chunking.

A malformed upload must fail as a typed error, never as a crash or as a
document that silently claims success with no content.
"""

from __future__ import annotations

import pytest

from app.services.extraction import (
    MIN_CHUNK_CHARS,
    TARGET_CHUNK_CHARS,
    ExtractionError,
    chunk,
    extract,
    extract_pdf,
    extract_text_document,
    normalise,
)

pytestmark = pytest.mark.unit


def _make_pdf(pages: list[str]) -> bytes:
    """A real PDF built with PyMuPDF, so these are not fixture-shaped fakes."""
    import fitz

    document = fitz.open()
    for body in pages:
        page = document.new_page()
        page.insert_text((72, 96), body, fontsize=11)
    data: bytes = document.tobytes()
    document.close()
    return data


def _empty_pdf(page_count: int = 2) -> bytes:
    import fitz

    document = fitz.open()
    for _ in range(page_count):
        document.new_page()
    data: bytes = document.tobytes()
    document.close()
    return data


class TestNormalise:
    def test_runs_of_spaces_collapse(self) -> None:
        assert normalise("a  \t  b") == "a b"

    def test_paragraph_breaks_survive(self) -> None:
        """Brand guidelines are lists; joining their lines destroys meaning."""
        assert normalise("do this\n\ndo not do that") == "do this\n\ndo not do that"

    def test_excess_blank_lines_collapse_to_one_break(self) -> None:
        assert normalise("a\n\n\n\n\nb") == "a\n\nb"

    def test_windows_line_endings_are_handled(self) -> None:
        assert normalise("a\r\n\r\nb") == "a\n\nb"


class TestTextDocuments:
    def test_plain_text_is_extracted_and_chunked(self) -> None:
        result = extract_text_document(b"Our voice is confident.\n\nWe avoid hype.")
        assert "confident" in result.text
        assert len(result.passages) == 1
        assert result.is_empty is False

    def test_invalid_utf8_is_a_typed_error(self) -> None:
        with pytest.raises(ExtractionError, match="UTF-8"):
            extract_text_document(b"\xff\xfe\x00\x00binary")

    def test_whitespace_only_input_is_reported_empty_not_crashing(self) -> None:
        result = extract_text_document(b"   \n\n  \t ")
        assert result.is_empty
        assert result.passages == []


class TestPdfExtraction:
    def test_a_real_pdf_yields_text_and_page_count(self) -> None:
        result = extract_pdf(_make_pdf(["Brand voice is confident.", "Never say indestructible."]))
        assert result.page_count == 2
        assert "confident" in result.text
        assert "indestructible" in result.text

    def test_every_passage_carries_its_page_number(self) -> None:
        """Page numbers are what make provenance useful later."""
        result = extract_pdf(_make_pdf(["Page one content here.", "Page two content here."]))
        pages = {p.page for p in result.passages}
        assert pages == {1, 2}

    def test_passage_indexes_are_contiguous_across_pages(self) -> None:
        result = extract_pdf(_make_pdf(["First page text.", "Second page text."]))
        assert [p.index for p in result.passages] == list(range(len(result.passages)))

    def test_a_pdf_with_no_text_reports_needs_ocr_rather_than_claiming_success(self) -> None:
        """A scanned document must not sit at COMPLETED with nothing in it."""
        result = extract_pdf(_empty_pdf())
        assert result.is_empty
        assert result.needs_ocr is True
        assert result.page_count == 2

    def test_a_corrupt_pdf_is_a_typed_error_not_a_crash(self) -> None:
        with pytest.raises(ExtractionError, match="could not be read"):
            extract_pdf(b"%PDF-1.7\nthis is not really a pdf at all")

    def test_random_bytes_are_a_typed_error(self) -> None:
        with pytest.raises(ExtractionError):
            extract_pdf(b"\x00\x01\x02\x03" * 100)

    def test_an_empty_byte_string_is_a_typed_error(self) -> None:
        with pytest.raises(ExtractionError):
            extract_pdf(b"")

    def test_the_user_message_never_leaks_the_library_error(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            extract_pdf(b"%PDF-1.7 broken")
        assert "fitz" not in exc.value.message.lower()
        assert "traceback" not in exc.value.message.lower()
        assert exc.value.detail is not None  # kept for the log


class TestDispatch:
    def test_pdf_dispatches_to_the_pdf_parser(self) -> None:
        assert extract(_make_pdf(["hello"]), mime_type="application/pdf").page_count == 1

    def test_markdown_is_treated_as_text(self) -> None:
        assert "heading" in extract(b"# heading", mime_type="text/markdown").text

    def test_an_image_is_refused_rather_than_silently_ocred(self) -> None:
        with pytest.raises(ExtractionError, match="No text can be extracted"):
            extract(b"\x89PNG\r\n\x1a\n", mime_type="image/png")


class TestChunking:
    def test_empty_text_produces_no_chunks(self) -> None:
        assert chunk("") == []
        assert chunk("   \n\n  ") == []

    def test_short_paragraphs_are_packed_together(self) -> None:
        text = "\n\n".join(["Short paragraph."] * 5)
        assert len(chunk(text)) == 1

    def test_chunks_respect_the_target_size(self) -> None:
        text = "\n\n".join([f"Paragraph number {i} with some body text." for i in range(200)])
        assert all(len(p.content) <= TARGET_CHUNK_CHARS for p in chunk(text))

    def test_an_oversized_paragraph_is_windowed_with_overlap(self) -> None:
        """A rule spanning a boundary must stay findable from either side."""
        text = "word " * 2000
        passages = chunk(text)
        assert len(passages) > 1
        assert all(len(p.content) <= TARGET_CHUNK_CHARS for p in passages)

    def test_windowed_chunks_actually_overlap(self) -> None:
        passages = chunk("abcdefghij" * 400)
        first_tail = passages[0].content[-50:]
        assert first_tail in passages[1].content

    def test_no_content_is_lost_across_chunks(self) -> None:
        text = "\n\n".join([f"Distinct sentence {i}." for i in range(60)])
        joined = " ".join(p.content for p in chunk(text))
        for i in range(60):
            assert f"Distinct sentence {i}." in joined

    def test_indexes_are_sequential_and_start_where_told(self) -> None:
        passages = chunk("\n\n".join(["Body text here."] * 40), start_index=7)
        assert [p.index for p in passages] == list(range(7, 7 + len(passages)))

    def test_no_chunk_is_blank(self) -> None:
        passages = chunk("a\n\n\n\nb\n\n\n\n\n\nc")
        assert all(p.content.strip() for p in passages)

    def test_tiny_trailing_windows_are_not_emitted_as_noise(self) -> None:
        passages = chunk("x" * (TARGET_CHUNK_CHARS + 10))
        assert all(len(p.content) >= MIN_CHUNK_CHARS for p in passages)
