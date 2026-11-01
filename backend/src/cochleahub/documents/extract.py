"""Text extraction and chunking for uploaded documents (D25).

- Tables are kept as Markdown tables instead of being flattened into running text. Converting a
  guideline's non-text content (tables, figures) into text the model can read was part of what
  lifted RAG answers on clinical guidelines from 43 % to 99 % accuracy [Kresevic2024].
- Passages follow the document's own structure: pages for PDF, headings for DOCX and Markdown.
  Each passage carries the document and page/section title, as in MedRAG's paragraph snippets
  with prepended headings [Xiong2024]. Long pages are split at paragraph boundaries.
- Every passage keeps its page, so answers can cite "document › page N" [Zakka2024].

Supported: PDF (text layer; scanned PDFs without text are rejected, no OCR), DOCX, TXT, MD.
"""

import io
import re
from dataclasses import dataclass

from cochleahub.assistant.retrieval import MAX_CHUNK_CHARS, Chunk, chunk_markdown

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"  # DOCX is a zip container
TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


class ExtractionError(ValueError):
    """The file cannot be turned into text; the message is shown to the user."""


@dataclass
class Section:
    label: str  # "page 3", or a heading
    text: str
    page: int | None = None


def file_type(filename: str, data: bytes) -> str:
    """Extension and content must agree; returns the extension."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in TYPES:
        raise ExtractionError(f"Unsupported file type '{ext or filename}'. Use PDF, DOCX, TXT "
                              "or MD.")
    if ext == ".pdf" and not data.startswith(PDF_MAGIC):
        raise ExtractionError("The file is named .pdf but is not a PDF.")
    if ext == ".docx" and not data.startswith(ZIP_MAGIC):
        raise ExtractionError("The file is named .docx but is not a Word document.")
    if ext in (".txt", ".md"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ExtractionError("Text files must be UTF-8.") from e
    return ext


def table_markdown(rows: list[list[str | None]]) -> str:
    rows = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in rows if any(r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def pdf_sections(data: bytes) -> list[Section]:
    import pdfplumber

    sections = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            # text outside the tables, then each table as Markdown
            outside = page
            for t in tables:
                outside = outside.outside_bbox(t.bbox)
            body = (outside.extract_text() or "").strip()
            parts = [body] if body else []
            parts += [md for t in tables if (md := table_markdown(t.extract()))]
            if parts:
                sections.append(Section(f"page {number}", "\n\n".join(parts), page=number))
    if not sections:
        raise ExtractionError("No text found in the PDF. Scanned documents need OCR, which "
                              "CochleaHub does not do.")
    return sections


def docx_sections(data: bytes) -> list[Section]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    sections: list[Section] = []
    label, parts = "Introduction", []

    def flush():
        if any(p.strip() for p in parts):
            sections.append(Section(label, "\n\n".join(p for p in parts if p.strip())))

    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(block, document)
            if p.style is not None and p.style.name.lower().startswith("heading") and p.text.strip():
                flush()
                label, parts = p.text.strip(), []
            else:
                parts.append(p.text)
        elif tag == "tbl":
            t = Table(block, document)
            parts.append(table_markdown([[c.text for c in row.cells] for row in t.rows]))
    flush()
    if not sections:
        raise ExtractionError("The Word document contains no text.")
    return sections


def split(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split at paragraph boundaries; a single paragraph longer than the limit is cut at
    sentence ends."""
    out, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        pieces = [para]
        if len(para) > limit:
            pieces, buf = [], ""
            for sentence in re.split(r"(?<=[.!?])\s+", para):
                if buf and len(buf) + len(sentence) > limit:
                    pieces.append(buf)
                    buf = sentence
                else:
                    buf = f"{buf} {sentence}".strip()
            pieces.append(buf)
        for piece in pieces:
            if current and len(current) + len(piece) > limit:
                out.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current.strip():
        out.append(current)
    return out


def to_chunks(doc_id: int, title: str, filename: str, data: bytes) -> tuple[list[Chunk], int]:
    """Extract and chunk a file. Returns (chunks, number of pages or sections)."""
    ext = file_type(filename, data)
    key = f"upload:{doc_id}"
    if ext == ".md":
        chunks = chunk_markdown(key, data.decode("utf-8"))
        # chunk_markdown titles passages with the document's own H1; name the upload instead
        for c in chunks:
            c.title = title + (" › " + c.title.split(" › ", 1)[1] if " › " in c.title else "")
        return chunks, len(chunks)
    if ext == ".txt":
        sections = [Section("text", data.decode("utf-8"))]
    elif ext == ".pdf":
        sections = pdf_sections(data)
    else:
        sections = docx_sections(data)
    chunks = []
    for s in sections:
        for i, part in enumerate(split(s.text), start=1):
            anchor = f"p{s.page}" if s.page else re.sub(r"[^a-z0-9]+", "-", s.label.lower())[:60]
            cid = f"{key}#{anchor}" + (f"-{i}" if i > 1 else "")
            label = s.label if ext != ".txt" else ""
            chunks.append(Chunk(cid, key, f"{title} › {label}" if label else title, part))
    if not chunks:
        raise ExtractionError("No text could be extracted.")
    return chunks, len(sections)
