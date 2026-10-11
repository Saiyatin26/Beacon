from pathlib import Path

from application.repository_service import RepositoryProvenance, RepositoryService


COBOL_SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. UPLOADTEST.
       DATA DIVISION.
       PROCEDURE DIVISION.
           GOBACK.
"""

PYTHON_SOURCE = """def run_vector(values):
    return {"result": values.get("value", "")}
"""


def test_upload_infers_conventional_extensions_for_extensionless_sources(tmp_path: Path):
    service = RepositoryService(cache_dir=tmp_path / "repo_cache")

    staged = service.stage_uploaded_sources(
        upload_id="extensionless-test",
        legacy_files=[("legacy", COBOL_SOURCE.encode())],
        modern_files=[("modern", PYTHON_SOURCE.encode())],
    )

    assert staged["legacy_artifacts"][0]["filename"] == "legacy.cbl"
    assert staged["legacy_artifacts"][0]["language"] == "cobol"
    assert staged["legacy_artifacts"][0]["source_provenance"]["original_filename"] == "legacy"
    assert staged["modern_artifacts"][0]["filename"] == "modern.py"
    assert staged["modern_artifacts"][0]["language"] == "python"


def test_existing_extensionless_staged_upload_is_normalized_before_analysis(tmp_path: Path):
    service = RepositoryService(cache_dir=tmp_path / "repo_cache")
    source_dir = tmp_path / "staged" / "legacy"
    source_dir.mkdir(parents=True)
    extensionless = source_dir / "legacy"
    extensionless.write_text(COBOL_SOURCE, encoding="utf-8")

    renamed = service.normalize_extensionless_sources(source_dir)
    provenance = RepositoryProvenance(
        source_url=str(source_dir),
        canonical_source_url=str(source_dir),
        source_type="directory",
        resolved_revision="test",
        content_hash="test",
        retrieval_timestamp="test",
        local_path=str(source_dir),
    )
    analysis = service.analyze_repository(source_dir, provenance)

    assert renamed == [source_dir / "legacy.cbl"]
    assert not extensionless.exists()
    assert analysis.languages == ["cobol"]
    assert [candidate.name for candidate in analysis.entrypoint_candidates] == ["UPLOADTEST"]
