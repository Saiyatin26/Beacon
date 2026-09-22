"""BEACON V2 — Targeted Test Suite for Source Ingestion, Scope Representation, Gemini Provider, and AI Grounding."""

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from application.models import (
    AnalysisScope,
    RepositoryExecutionSpec,
    SourceArtifact,
    SourceIngestionMode,
)
from application.repository_service import (
    RepositoryService,
    RepositorySourceSpec,
    RepositorySourceType,
    repository_service,
)
from ingestion.static_analyzer import CobolAnalyzer, PythonAnalyzer, get_analyzer
from intelligence.validation import GroundingValidator
from intelligence.models import GroundingClaim, GroundingClaimType, ExplanationContext
from llm.gemini_provider import GeminiProvider
from llm.manager import ProviderManager, get_provider_manager
from llm.base import LLMResponse


class TestSourceIngestionAndScope(unittest.TestCase):
    """Verifies file/directory source ingestion, deterministic identity, and scope-bound fingerprints."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = RepositoryService(cache_dir=Path(self.temp_dir.name) / "cache")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_uploaded_files_staging_and_identity(self):
        legacy_content = b"def legacy_calc(x):\n    return x * 2\n"
        modern_content = b"def modern_calc(x):\n    return x * 2\n"

        staged = self.service.stage_uploaded_sources(
            upload_id="test_upl_001",
            legacy_files=[("legacy_calc.py", legacy_content)],
            modern_files=[("modern_calc.py", modern_content)],
            preferred_scope="FILE",
        )

        self.assertEqual(staged["upload_id"], "test_upl_001")
        self.assertEqual(staged["analysis_scope"], "FILE")
        self.assertEqual(len(staged["legacy_artifacts"]), 1)
        self.assertEqual(len(staged["modern_artifacts"]), 1)

        leg_art = staged["legacy_artifacts"][0]
        self.assertEqual(leg_art["filename"], "legacy_calc.py")
        self.assertEqual(leg_art["language"], "python")
        self.assertEqual(leg_art["content_hash"], hashlib.sha256(legacy_content).hexdigest())
        self.assertEqual(leg_art["source_side"], "LEGACY")
        self.assertTrue(len(leg_art["artifact_id"]) > 0)

        # Verify pairing
        self.assertEqual(len(staged["source_pairings"]), 1)
        self.assertEqual(staged["source_pairings"][0]["pairing_status"], "EXPLICIT_PAIR")

    def test_archive_zip_unpacking_and_directory_scope(self):
        # Create a sample zip archive
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("module/sub1.py", "def f1(): return 1")
            zf.writestr("module/sub2.py", "def f2(): return 2")
        zip_bytes = zip_buf.getvalue()

        staged = self.service.stage_uploaded_sources(
            upload_id="test_upl_zip",
            legacy_files=[("legacy_pkg.zip", zip_bytes)],
            modern_files=[("modern_pkg.zip", zip_bytes)],
        )

        self.assertEqual(staged["analysis_scope"], "DIRECTORY")
        self.assertEqual(len(staged["legacy_artifacts"]), 2)
        self.assertEqual(len(staged["modern_artifacts"]), 2)

        # Verify relative path preservation
        rel_paths = {a["relative_path"] for a in staged["legacy_artifacts"]}
        self.assertIn("module/sub1.py", rel_paths)
        self.assertIn("module/sub2.py", rel_paths)

    def test_execution_fingerprint_changes_on_file_selection(self):
        """Requirement 13: Same repo + different selected files must produce distinct execution fingerprints."""
        spec1 = RepositoryExecutionSpec(
            specification_id="APP-1",
            source_mode=SourceIngestionMode.UPLOADED_FILES,
            analysis_scope=AnalysisScope.FILE,
            selected_artifacts=[
                {"source_side": "LEGACY", "relative_path": "payment.cbl", "content_hash": "hash_a1"},
                {"source_side": "MODERN", "relative_path": "payment.py", "content_hash": "hash_b1"},
            ],
            evaluation_mode="CONTROLLED",
        )
        fp1 = spec1.compute_fingerprint()

        # Different selected file
        spec2 = RepositoryExecutionSpec(
            specification_id="APP-1",
            source_mode=SourceIngestionMode.UPLOADED_FILES,
            analysis_scope=AnalysisScope.FILE,
            selected_artifacts=[
                {"source_side": "LEGACY", "relative_path": "account.cbl", "content_hash": "hash_a2"},
                {"source_side": "MODERN", "relative_path": "account.py", "content_hash": "hash_b2"},
            ],
            evaluation_mode="CONTROLLED",
        )
        fp2 = spec2.compute_fingerprint()

        self.assertNotEqual(fp1, fp2, "Different selected files MUST produce different fingerprints")

        # Different analysis scope
        spec3 = RepositoryExecutionSpec(
            specification_id="APP-1",
            source_mode=SourceIngestionMode.UPLOADED_FILES,
            analysis_scope=AnalysisScope.DIRECTORY,
            selected_artifacts=[
                {"source_side": "LEGACY", "relative_path": "payment.cbl", "content_hash": "hash_a1"},
                {"source_side": "MODERN", "relative_path": "payment.py", "content_hash": "hash_b1"},
            ],
            evaluation_mode="CONTROLLED",
        )
        fp3 = spec3.compute_fingerprint()
        self.assertNotEqual(fp1, fp3, "Different scope MUST produce different fingerprints")


class TestSourceAnalysisAndRuleExtraction(unittest.TestCase):
    """Verifies real static AST and COBOL rule extraction without fake data."""

    def test_cobol_analyzer_rule_and_paragraph_extraction(self):
        cobol_code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYMENT-PROCESSOR.
       PROCEDURE DIVISION.
       0001-PROCESS-PAYMENT.
           IF AMOUNT > 1000 THEN
               PERFORM 0002-FLAG-FRAUD
           ELSE
               PERFORM 0003-APPROVE
           END-IF.
       0002-FLAG-FRAUD.
           DISPLAY "FRAUD FLAGGED".
       0003-APPROVE.
           DISPLAY "PAYMENT APPROVED".
        """
        analyzer = get_analyzer("cobol")
        self.assertIsInstance(analyzer, CobolAnalyzer)

        result = analyzer.analyze(cobol_code, file_name="payment.cbl")
        self.assertEqual(result.language, "cobol")

        # Verify extracted paragraphs as functions/entrypoints
        para_names = [fn.name for fn in result.functions]
        self.assertIn("0001-PROCESS-PAYMENT", para_names)
        self.assertIn("0002-FLAG-FRAUD", para_names)
        self.assertIn("0003-APPROVE", para_names)

        # Verify extracted conditional invariant
        self.assertTrue(len(result.conditions) >= 1)
        self.assertTrue(any("AMOUNT > 1000" in c.expression for c in result.conditions))
        self.assertEqual(result.conditions[0].location.function, "0001-PROCESS-PAYMENT")

    def test_python_analyzer_comparisons(self):
        py_code = """
def check_limit(balance, limit):
    if balance >= limit:
        return False
    return True
"""
        analyzer = get_analyzer("python")
        res = analyzer.analyze(py_code, file_name="account.py")
        self.assertEqual(len(res.functions), 1)
        self.assertEqual(res.functions[0].name, "check_limit")
        self.assertTrue(len(res.comparisons) >= 1)
        self.assertEqual(res.comparisons[0].operator, ">=")


class TestGeminiProvider(unittest.TestCase):
    """Verifies Gemini first-class provider implementation, configuration, and fallback."""

    def test_gemini_unconfigured_fails_gracefully(self):
        provider = GeminiProvider(api_key="")
        self.assertFalse(provider.is_available())
        self.assertFalse(provider.check_connectivity())

        resp = provider.generate("Test prompt")
        self.assertFalse(resp.success)
        self.assertIn("not configured", resp.error)
        self.assertEqual(resp.provider_name, "gemini")

    def test_gemini_provider_metadata(self):
        provider = GeminiProvider(api_key="dummy_key", model="gemini-1.5-flash")
        meta = provider.get_metadata()
        self.assertEqual(meta["provider"], "gemini")
        self.assertEqual(meta["model"], "gemini-1.5-flash")
        self.assertTrue(meta["available"])

    @patch("urllib.request.urlopen")
    def test_gemini_successful_generation(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"summary": "Equivalence certified under boundary invariants."}'}]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 50,
                "candidatesTokenCount": 20,
            },
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = GeminiProvider(api_key="dummy_key", model="gemini-1.5-flash")
        resp = provider.generate("Summarize certification context", json_mode=True)

        self.assertTrue(resp.success)
        self.assertEqual(resp.provider_name, "gemini")
        self.assertEqual(resp.model_name, "gemini-1.5-flash")
        self.assertIsNotNone(resp.parsed_json)
        self.assertIn("summary", resp.parsed_json)

    def test_provider_manager_hierarchy_includes_gemini(self):
        pm = ProviderManager()
        self.assertIn("gemini", pm.providers)
        self.assertIn("gemini", pm.fallback_priority)
        self.assertEqual(pm.fallback_priority, ["openrouter", "gemini", "anthropic", "ollama", "offline"])

        status = pm.get_status()
        self.assertIn("gemini", status["providers"])
        self.assertEqual(status["providers"]["gemini"]["role"], "Supported Cloud Provider")

    def test_explicit_gemini_fallback_metadata(self):
        pm = ProviderManager()
        # Mock ollama so test doesn't spend 90 seconds waiting on localhost timeout
        with patch.object(pm.providers["ollama"], "generate", return_value=LLMResponse(provider_name="ollama", model_name="ollama", success=False, error="Ollama offline")):
            resp = pm.generate(
                prompt="Test prompt",
                preferred_provider="gemini",
            )
            self.assertEqual(resp.metadata.get("requested_provider"), "gemini")
            self.assertTrue(resp.fallback_occurred)
            self.assertEqual(resp.provider_name, "offline")


class TestGroundingAndCertificationAuthority(unittest.TestCase):
    """Verifies that AI explanations remain strictly grounded and downstream of certification."""

    def test_grounding_validator_accepts_supported_claims(self):
        validator = GroundingValidator()
        context = ExplanationContext(
            certification_id="CERT-TEST-001",
            project_id="test_proj",
            overall_verdict="CERTIFIED",
            equivalence_score=1.0,
            threshold_value=0.99,
            valid_input_ids=["input_1", "input_2"],
            valid_rule_ids=["RULE-001"],
            differences_summary=[
                {"input_id": "input_1", "reference_value": 100, "target_value": 100}
            ],
        )
        claim = GroundingClaim(
            claim_type=GroundingClaimType.NUMERIC_VALUE,
            statement="Target returned 100 for input_1",
            input_id="input_1",
            role="TARGET",
            value=100,
        )
        valid, errors, validated = validator.validate_claims([claim], context)
        self.assertTrue(valid)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(validated), 1)

    def test_grounding_validator_rejects_unsupported_numeric_claim(self):
        validator = GroundingValidator()
        context = ExplanationContext(
            certification_id="CERT-TEST-001",
            project_id="test_proj",
            overall_verdict="CERTIFIED",
            equivalence_score=0.95,
            threshold_value=0.99,
            valid_input_ids=["input_1"],
            differences_summary=[
                {"input_id": "input_1", "reference_value": 100, "target_value": 100}
            ],
        )
        claim = GroundingClaim(
            claim_type=GroundingClaimType.NUMERIC_VALUE,
            statement="Target returned 999 for input_1",
            input_id="input_1",
            role="TARGET",
            value=999,
        )
        valid, errors, validated = validator.validate_claims([claim], context)
        self.assertFalse(valid)
        self.assertTrue(any("NUMERIC_VALUE_MISMATCH" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
