"""BEACON V2 — Phase 9 Document Ingestion & Chunking Test Suite.

Verifies PDF and DOCX extraction, structural metadata preservation, text normalization,
deterministic chunk ID and fingerprint generation, and duplicate content detection.
"""

import io
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import docx
from knowledge.chunking import ChunkingConfigurationError, DeterministicChunker
from knowledge.extraction import (
    DOCXExtractor,
    EmptyDocumentError,
    PDFExtractor,
    TextNormalizer,
    extract_document_content,
)
from knowledge.models import (
    DocumentMetadata,
    DocumentStatus,
    DocumentType,
    ExtractedDocument,
)
from knowledge.service import KnowledgeService


def make_sample_pdf(text: str = "First Page Content.\nSecond Page Content.") -> bytes:
    pdf_str = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length {len(text) + 60} >>
stream
BT
/F1 12 Tf
72 712 Td
({text}) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000414 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
502
%%EOF"""
    return pdf_str.encode("latin-1")


def make_sample_docx(sections: list[tuple[str, str]]) -> bytes:
    doc = docx.Document()
    for heading, body in sections:
        doc.add_heading(heading, level=1)
        doc.add_paragraph(body)
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


class TestPhase9DocumentIngestion:
    """Detailed unit tests for ingestion, extraction, normalization, and chunking."""

    def test_text_normalizer_standardization(self):
        """TextNormalizer handles CRLF, tabs, excessive whitespace, and Unicode normalization."""
        raw_text = "  Hello   World  \r\n\r\n\r\nThis is a   test   with  weird   spacing.  \r\n"
        normalized = TextNormalizer.normalize(raw_text)
        assert "\r" not in normalized
        assert "\n\n\n" not in normalized
        assert "Hello World" in normalized
        assert "This is a test with weird spacing." in normalized

    def test_pdf_extraction_content_and_page_structure(self):
        """PDFExtractor extracts text with correct page metadata."""
        sample_text = "Standard Operating Procedure: Calibration of High-Precision Probes."
        pdf_bytes = make_sample_pdf(sample_text)
        extracted = PDFExtractor.extract(pdf_bytes)

        assert isinstance(extracted, ExtractedDocument)
        assert extracted.page_count == 1
        assert len(extracted.pages) == 1
        assert "Calibration of High-Precision Probes" in extracted.normalized_text
        assert extracted.pages[0].page_number == 1

    def test_docx_extraction_headings_and_sections(self):
        """DOCXExtractor captures heading hierarchy and associates sections."""
        docx_bytes = make_sample_docx([
            ("1. Overview", "This document describes the core architecture rules."),
            ("2. Compliance", "All transactions must be signed cryptographically."),
        ])
        extracted = DOCXExtractor.extract(docx_bytes)

        assert extracted.page_count >= 1
        assert len(extracted.sections) == 2
        assert extracted.sections[0].heading == "1. Overview"
        assert extracted.sections[1].heading == "2. Compliance"
        assert "All transactions must be signed cryptographically" in extracted.normalized_text

    def test_deterministic_chunking_and_fingerprints(self):
        """Chunker produces deterministic chunk IDs and identical fingerprints for same input."""
        doc_meta = DocumentMetadata(
            document_id="doc_det_001",
            application_id="app_test",
            filename="test.pdf",
            document_type=DocumentType.PDF,
            content_hash="abc123hash",
            size_bytes=1000,
        )
        sample_text = (
            "Paragraph One: Explaining the rules of behavioral equivalence in BEACON. " * 5
            + "\n\n"
            + "Paragraph Two: Explaining dynamic threshold resolution with variance bounds. " * 5
        )
        extracted = ExtractedDocument(
            raw_text=sample_text,
            normalized_text=TextNormalizer.normalize(sample_text),
            page_count=1,
            pages=[],
        )

        chunker = DeterministicChunker(chunk_size=200, chunk_overlap=50)
        chunks_run1 = chunker.chunk_document(extracted, doc_meta)
        chunks_run2 = chunker.chunk_document(extracted, doc_meta)

        assert len(chunks_run1) > 1
        assert len(chunks_run1) == len(chunks_run2)

        # Check determinism of IDs, fingerprints, and texts
        for c1, c2 in zip(chunks_run1, chunks_run2):
            assert c1.chunk_id == c2.chunk_id
            assert c1.fingerprint == c2.fingerprint
            assert c1.text == c2.text
            assert c1.metadata.document_id == doc_meta.document_id
            assert c1.metadata.application_id == doc_meta.application_id

    def test_chunker_rejects_invalid_configuration(self):
        """Chunker rejects negative or overlap >= chunk_size configurations."""
        with pytest.raises(ChunkingConfigurationError):
            DeterministicChunker(chunk_size=0, chunk_overlap=0)

        with pytest.raises(ChunkingConfigurationError):
            DeterministicChunker(chunk_size=100, chunk_overlap=-10)

        with pytest.raises(ChunkingConfigurationError):
            DeterministicChunker(chunk_size=100, chunk_overlap=100)

        with pytest.raises(ChunkingConfigurationError):
            DeterministicChunker(chunk_size=100, chunk_overlap=150)
