"""BEACON V2 — Phase 9 Document Content Extraction & Text Normalization.

Provides robust, safe, and deterministic text and structure extraction for
PDF and DOCX company documents, preserving page and heading provenance metadata.
"""

import io
import logging
import re
from typing import Optional
import unicodedata

from .models import (
    DocumentPage,
    DocumentSection,
    DocumentType,
    ExtractedDocument,
)
from .security import sanitize_untrusted_text

logger = logging.getLogger("beacon.knowledge.extraction")


class DocumentExtractionError(Exception):
    """Raised when parsing or extracting text from a document payload fails."""
    pass


class EmptyDocumentError(DocumentExtractionError):
    """Raised when an ingested document contains zero extractable text."""
    pass


class TextNormalizer:
    """Deterministic text normalizer preserving semantic paragraph and section structure."""

    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""

        # 1. Unicode NFC normalization
        normalized = unicodedata.normalize("NFC", text)

        # 2. Sanitize control characters
        normalized = sanitize_untrusted_text(normalized)

        # 3. Standardize line endings to \n
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")

        # 4. Collapse trailing/multiple spaces per line (keep indentation structure intact)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]

        # 5. Collapse excessive consecutive newlines (max 2 consecutive newlines)
        joined = "\n".join(lines)
        joined = re.sub(r"\n{3,}", "\n\n", joined)

        return joined.strip()


class PDFExtractor:
    """Extracts text and page structure from PDF document bytes using pypdf."""

    @classmethod
    def extract(cls, content: bytes) -> ExtractedDocument:
        try:
            import pypdf
        except ImportError as exc:
            raise DocumentExtractionError("pypdf library is required for PDF document extraction.") from exc

        try:
            stream = io.BytesIO(content)
            reader = pypdf.PdfReader(stream)

            if reader.is_encrypted:
                try:
                    # Attempt decrypt with empty password for standard protected PDFs
                    reader.decrypt("")
                except Exception as dec_err:
                    raise DocumentExtractionError("PDF document is password-protected and cannot be parsed.") from dec_err

            pages: list[DocumentPage] = []
            all_raw_text_parts: list[str] = []

            for idx, page in enumerate(reader.pages):
                page_num = idx + 1
                try:
                    page_text = page.extract_text() or ""
                except Exception as p_exc:
                    logger.warning(f"Error extracting page {page_num} in PDF: {p_exc}")
                    page_text = ""

                cleaned_page_text = TextNormalizer.normalize(page_text)
                pages.append(
                    DocumentPage(
                        page_number=page_num,
                        text=cleaned_page_text,
                        character_count=len(cleaned_page_text),
                    )
                )
                if cleaned_page_text:
                    all_raw_text_parts.append(cleaned_page_text)

            combined_raw = "\n\n".join(all_raw_text_parts)
            combined_normalized = TextNormalizer.normalize(combined_raw)

            if len(combined_normalized) < 5:
                raise EmptyDocumentError("PDF document contains no extractable text or is purely image-based.")

            return ExtractedDocument(
                raw_text=combined_raw,
                normalized_text=combined_normalized,
                page_count=len(pages),
                pages=pages,
                sections=[],
                metadata={"extractor": "pypdf", "page_count": len(pages)},
            )
        except EmptyDocumentError:
            raise
        except Exception as exc:
            logger.error(f"Failed to extract PDF document: {exc}")
            raise DocumentExtractionError(f"PDF extraction failed: {exc}") from exc


class DOCXExtractor:
    """Extracts text, headings, and table data from DOCX documents using python-docx."""

    @classmethod
    def extract(cls, content: bytes) -> ExtractedDocument:
        try:
            import docx
        except ImportError as exc:
            raise DocumentExtractionError("python-docx library is required for DOCX document extraction.") from exc

        try:
            stream = io.BytesIO(content)
            doc = docx.Document(stream)

            sections: list[DocumentSection] = []
            all_text_parts: list[str] = []
            current_heading: Optional[str] = None
            current_section_texts: list[str] = []

            # 1. Extract paragraphs and headings
            for p in doc.paragraphs:
                text = p.text.strip()
                if not text:
                    continue

                style_name = p.style.name.lower() if p.style and p.style.name else ""
                if "heading" in style_name or style_name.startswith("title"):
                    # Save previous section if present
                    if current_heading and current_section_texts:
                        sections.append(
                            DocumentSection(
                                heading=current_heading,
                                text=TextNormalizer.normalize("\n".join(current_section_texts)),
                            )
                        )
                        current_section_texts = []
                    current_heading = text
                else:
                    current_section_texts.append(text)
                
                all_text_parts.append(text)

            # Flush last section
            if current_heading and current_section_texts:
                sections.append(
                    DocumentSection(
                        heading=current_heading,
                        text=TextNormalizer.normalize("\n".join(current_section_texts)),
                    )
                )

            # 2. Extract tables
            for t_idx, table in enumerate(doc.tables):
                table_rows: list[str] = []
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        table_rows.append(" | ".join(row_cells))
                if table_rows:
                    table_text = "\n".join(table_rows)
                    all_text_parts.append(f"[Table {t_idx + 1}]\n{table_text}")
                    sections.append(
                        DocumentSection(
                            heading=f"Table {t_idx + 1}",
                            text=table_text,
                        )
                    )

            combined_raw = "\n\n".join(all_text_parts)
            combined_normalized = TextNormalizer.normalize(combined_raw)

            if len(combined_normalized) < 5:
                raise EmptyDocumentError("DOCX document contains no extractable text content.")

            # Synthetic single-page or section-based page count for DOCX
            doc_page = DocumentPage(
                page_number=1,
                text=combined_normalized,
                character_count=len(combined_normalized),
            )

            return ExtractedDocument(
                raw_text=combined_raw,
                normalized_text=combined_normalized,
                page_count=1,
                pages=[doc_page],
                sections=sections,
                metadata={"extractor": "docx", "section_count": len(sections)},
            )
        except EmptyDocumentError:
            raise
        except Exception as exc:
            logger.error(f"Failed to extract DOCX document: {exc}")
            raise DocumentExtractionError(f"DOCX extraction failed: {exc}") from exc


def extract_document_content(content: bytes, doc_type: DocumentType) -> ExtractedDocument:
    """Routes document binary bytes to the appropriate extractor based on document type."""
    if doc_type == DocumentType.PDF:
        return PDFExtractor.extract(content)
    elif doc_type == DocumentType.DOCX:
        return DOCXExtractor.extract(content)
    else:
        raise DocumentExtractionError(f"Unsupported document type: {doc_type}. Only PDF and DOCX are supported.")
