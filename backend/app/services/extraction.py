"""Text extraction and chunking.

Turns an uploaded document into page-attributed passages the Brand Brain can
embed. Pure functions over `bytes` — no database, no storage, no provider — so
the parsing rules are testable in isolation and a malformed file can be proved
harmless.

**No OCR.** A PDF of scanned pages yields no text, and this module says so
rather than inventing content. `ExtractionResult.needs_ocr` records that
honestly; silently returning empty text would let a document sit at
"COMPLETED" with nothing in it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Chunk sizing. Large enough to keep a brand rule with its context, small
#: enough that a retrieval hit points at something specific.
TARGET_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150
MIN_CHUNK_CHARS = 80

_WHITESPACE = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class ExtractionError(Exception):
    """The document could not be parsed. Carries a user-safe message."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class Passage:
    """One chunk, with the page it came from — that page number is what makes
    provenance useful later."""

    index: int
    content: str
    page: int | None = None


@dataclass
class ExtractionResult:
    text: str
    passages: list[Passage] = field(default_factory=list)
    page_count: int | None = None
    #: True when the file parsed but contained no extractable text — almost
    #: always a scanned PDF. Surfaced, never hidden.
    needs_ocr: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def normalise(text: str) -> str:
    """Collapse the whitespace noise PDF extraction produces, without joining
    lines that carry meaning (a list of do's and don'ts, for instance)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def extract_text_document(data: bytes) -> ExtractionResult:
    """A plain-text or Markdown upload."""
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError("That file is not valid UTF-8 text.", detail=str(exc)) from exc
    text = normalise(raw)
    return ExtractionResult(text=text, passages=chunk(text), page_count=None)


def extract_pdf(data: bytes) -> ExtractionResult:
    """A PDF, page by page, so every passage keeps its page number."""
    import fitz  # PyMuPDF

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - any parse failure is one failure
        raise ExtractionError(
            "That PDF could not be read. It may be corrupt or password-protected.",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    try:
        if document.needs_pass:
            raise ExtractionError("That PDF is password-protected.")
        pages: list[tuple[int, str]] = []
        for number, page in enumerate(document, start=1):
            try:
                pages.append((number, normalise(page.get_text("text"))))
            except Exception:  # noqa: BLE001 - one bad page must not lose the rest
                continue
        page_count = document.page_count
    finally:
        document.close()

    passages: list[Passage] = []
    for number, page_text in pages:
        for passage in chunk(page_text, start_index=len(passages)):
            passages.append(Passage(index=passage.index, content=passage.content, page=number))

    text = "\n\n".join(t for _, t in pages if t)
    return ExtractionResult(
        text=text,
        passages=passages,
        page_count=page_count,
        # Parsed fine, but produced nothing: a scanned document.
        needs_ocr=bool(page_count) and not text.strip(),
    )


def extract(data: bytes, *, mime_type: str) -> ExtractionResult:
    """Dispatch on the validated MIME type."""
    if mime_type == "application/pdf":
        return extract_pdf(data)
    if mime_type in {"text/plain", "text/markdown"}:
        return extract_text_document(data)
    raise ExtractionError(f"No text can be extracted from {mime_type}.")


def chunk(
    text: str,
    *,
    target: int = TARGET_CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
    start_index: int = 0,
) -> list[Passage]:
    """Split on paragraph boundaries, packing up to `target` characters.

    Paragraph-aware rather than fixed-width: a brand guideline usually *is* a
    paragraph, and cutting mid-sentence produces chunks that retrieve poorly.
    Oversized paragraphs fall back to a windowed split with overlap so a rule
    spanning the boundary is still findable from either side.
    """
    text = text.strip()
    if not text:
        return []

    out: list[str] = []
    buffer = ""
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        if len(paragraph) > target:
            if buffer:
                out.append(buffer)
                buffer = ""
            step = max(1, target - overlap)
            for start in range(0, len(paragraph), step):
                window = paragraph[start : start + target]
                if len(window) >= MIN_CHUNK_CHARS or not out:
                    out.append(window)
                if start + target >= len(paragraph):
                    break
        elif len(buffer) + len(paragraph) + 2 <= target:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        else:
            if buffer:
                out.append(buffer)
            buffer = paragraph
    if buffer:
        out.append(buffer)

    return [
        Passage(index=start_index + i, content=content)
        for i, content in enumerate(c.strip() for c in out)
        if content
    ]
