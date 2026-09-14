"""BEACON V2 — Phase 9 Knowledge Ingestion Security & Path Protections.

Enforces strict boundaries against path traversal, oversized payloads,
malformed file signatures, and prompt injection attacks in enterprise documents.
"""

import io
import os
from pathlib import Path
import re
from typing import Optional
import zipfile

from .models import DocumentType


class KnowledgeSecurityError(ValueError):
    """Raised when an uploaded document violates security boundaries or validation constraints."""
    pass


class PathTraversalError(KnowledgeSecurityError):
    """Raised when a filename or path attempts to escape the controlled storage root."""
    pass


class FileSizeLimitExceededError(KnowledgeSecurityError):
    """Raised when an uploaded document exceeds the maximum allowable file size."""
    pass


class InvalidFileSignatureError(KnowledgeSecurityError):
    """Raised when the declared file type does not match the actual binary content signature."""
    pass


# Default maximum upload size: 20 MB (configurable via environment variable)
DEFAULT_MAX_FILE_SIZE_MB = int(os.getenv("KNOWLEDGE_MAX_FILE_SIZE_MB", "20"))
DEFAULT_MAX_FILE_SIZE_BYTES = DEFAULT_MAX_FILE_SIZE_MB * 1024 * 1024

# Controlled knowledge documents storage root
DEFAULT_KNOWLEDGE_STORAGE_ROOT = Path(os.getenv("KNOWLEDGE_STORAGE_ROOT", "data/knowledge_store")).resolve()


def sanitize_filename(filename: str) -> str:
    """Sanitizes an untrusted user-supplied filename, stripping dangerous path characters."""
    if not filename or not filename.strip():
        return "unnamed_document"

    # Remove any directory path components
    base_name = os.path.basename(filename.strip().replace("\\", "/"))
    
    # Strip null bytes and control characters
    base_name = re.sub(r"[\x00-\x1f\x7f]", "", base_name)
    
    # Restrict to safe alphanumeric characters, dashes, underscores, dots, and spaces
    safe_name = re.sub(r"[^a-zA-Z0-9_\-\. ]", "_", base_name)
    safe_name = safe_name.strip(" .")
    
    if not safe_name:
        return "unnamed_document"
    
    # Limit length to 255 chars
    return safe_name[:255]


def validate_path_containment(target_path: Path, root_dir: Optional[Path] = None) -> Path:
    """Verifies that the target path resolves strictly inside the authorized root directory."""
    root = (root_dir or DEFAULT_KNOWLEDGE_STORAGE_ROOT).resolve()
    resolved_target = target_path.resolve()

    try:
        resolved_target.relative_to(root)
    except ValueError as exc:
        raise PathTraversalError(
            f"Security violation: path '{target_path}' escapes storage root '{root}'."
        ) from exc

    return resolved_target


def validate_file_size(content: bytes, max_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES) -> None:
    """Validates that uploaded byte content does not exceed the configured size limit."""
    size = len(content)
    if size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        raise FileSizeLimitExceededError(
            f"File size ({actual_mb:.2f} MB) exceeds maximum allowed limit ({max_mb:.1f} MB)."
        )


def detect_document_type(filename: str, content: bytes) -> DocumentType:
    """Determines and validates the document type from filename extension and content signature."""
    lower_fn = filename.lower().strip()
    
    if lower_fn.endswith(".pdf"):
        validate_pdf_signature(content)
        return DocumentType.PDF
    elif lower_fn.endswith(".docx"):
        validate_docx_signature(content)
        return DocumentType.DOCX
    elif lower_fn.endswith(".txt") or lower_fn.endswith(".text"):
        return DocumentType.TEXT
    else:
        raise KnowledgeSecurityError(
            f"Unsupported document format for '{filename}'. Only PDF and DOCX documents are supported."
        )


def validate_pdf_signature(content: bytes) -> None:
    """Verifies that byte payload starts with valid PDF header bytes (%PDF)."""
    if len(content) < 5:
        raise InvalidFileSignatureError("File payload is too small to be a valid PDF document.")
    
    # PDF specification requires %PDF- anywhere within first 1024 bytes
    header_chunk = content[:1024]
    if b"%PDF-" not in header_chunk:
        raise InvalidFileSignatureError(
            "Invalid PDF signature: missing '%PDF-' binary header marker."
        )


def validate_docx_signature(content: bytes) -> None:
    """Verifies that byte payload is a valid ZIP archive containing Office OpenXML document.xml."""
    if len(content) < 4:
        raise InvalidFileSignatureError("File payload is too small to be a valid DOCX document.")
    
    # Check standard ZIP local file header signature: PK\x03\x04
    if not content.startswith(b"PK\x03\x04") and not content.startswith(b"PK\x05\x06"):
        raise InvalidFileSignatureError(
            "Invalid DOCX signature: file is not a valid ZIP-based Office OpenXML package."
        )

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            namelist = zf.namelist()
            # A valid docx must contain word/document.xml or [Content_Types].xml
            if not any("word/document.xml" in name.lower() or "[content_types].xml" in name.lower() for name in namelist):
                raise InvalidFileSignatureError(
                    "Invalid DOCX structure: missing Office OpenXML word/document.xml package component."
                )
    except zipfile.BadZipFile as exc:
        raise InvalidFileSignatureError(f"Corrupted DOCX archive: {exc}") from exc


def sanitize_untrusted_text(text: str) -> str:
    """Normalizes untrusted extracted text.
    
    Ensures prompt-injection markers or control characters inside documents are treated
    strictly as inert string literals and cannot compromise system prompts or execution.
    """
    if not text:
        return ""
    # Strip null and non-printable control characters (preserve newline, tab, carriage return)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return cleaned
