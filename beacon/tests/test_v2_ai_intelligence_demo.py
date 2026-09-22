"""BEACON V2 — AI & Intelligence Layer Faculty Demo Test Suite.

Verifies end-to-end functionality of:
1. Real certification context construction & bounds enforcement
2. OpenRouter provider live request behavior and error reporting
3. Structured LLM response schema validation & grounding
4. Scoped RAG ingestion, indexing, and lexical retrieval with provenance
5. Immutable authority boundary (LLM cannot alter verdict, threshold, or evidence)
6. Clean deterministic fallback identification
7. Execution fingerprint binding
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from common.contracts import compute_canonical_input_hash
from evaluation.models import (
    BehaviorDifference,
    BehaviorDimension,
    DifferenceType,
    EvaluationResult,
    EvaluationVerdict,
)
from execution.evidence_models import (
    EvidenceBundle,
    EvidenceRecord,
    EvidenceType,
)
from intelligence.context_builder import ExplanationContextBuilder
from intelligence.deterministic_generator import DeterministicExplanationGenerator
from intelligence.engine import IntelligenceEngine
from intelligence.models import (
    ExplanationContext,
    ExplanationRequest,
    GenerationMetadata,
    GroundingClaim,
    GroundingClaimType,
)
from intelligence.validation import GroundingValidator
from knowledge.models import (
    ChunkMetadata,
    DocumentMetadata,
    DocumentStatus,
    DocumentType,
    KnowledgeChunk,
)
from knowledge.persistence import KnowledgePersistenceStore
from knowledge.retrieval import DeterministicLexicalRetriever
from knowledge.service import KnowledgeService, knowledge_service
from llm.base import LLMResponse
from llm.manager import ProviderManager
from llm.openrouter_provider import OpenRouterProvider


class TestV2AIIntelligenceLayer(unittest.TestCase):
    """Targeted tests for BEACON V2 AI Layer Requirements 1-16 + End-to-End Flow."""

    def setUp(self):
        self.context_builder = ExplanationContextBuilder()
        self.det_generator = DeterministicExplanationGenerator()
        self.validator = GroundingValidator()
        self.retriever = DeterministicLexicalRetriever()

    # 1. Real certification context can be constructed
    def test_01_real_certification_context_construction(self):
        evid_rec = EvidenceRecord(
            evidence_id="EVID-TEST-001",
            session_id="SESS-001",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            source="calc.py",
            payload={"result": 42},
        )
        eval_res = EvaluationResult(
            evaluation_id="EVAL-001",
            application_id="app_calculator",
            verdict=EvaluationVerdict.EQUIVALENT,
            dimensions_evaluated=[BehaviorDimension.OUTPUT],
            differences=[],
        )
        context = self.context_builder.build_context(
            certification_id="CERT-DEMO-001",
            evidence_records=[evid_rec],
            evaluation_result=eval_res,
            use_company_knowledge=False,
        )
        self.assertEqual(context.certification_id, "CERT-DEMO-001")
        self.assertEqual(context.application_id, "app_calculator")
        self.assertEqual(context.authoritative_verdict, "EQUIVALENT")
        self.assertIn("EVID-TEST-001", context.valid_evidence_ids)

    # 2. Missing certification context fails closed
    def test_02_missing_certification_context_fails(self):
        context = self.context_builder.build_context(
            certification_id="",
            artifact=None,
            evaluation_result=None,
            execution_mode="v2",
            use_company_knowledge=False,
        )
        self.assertEqual(context.authoritative_verdict, "INCONCLUSIVE")
        self.assertIsNone(context.equivalence_score)
        self.assertTrue(any(m.dimension == BehaviorDimension.OUTPUT for m in context.missing_evidence))

    # 3. OpenRouter provider actually calls provider when configured
    def test_03_openrouter_provider_calls_endpoint_when_configured(self):
        provider = OpenRouterProvider(api_key="sk-or-test-valid-key")
        self.assertTrue(provider.is_configured())

        fake_api_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "executive_summary": "Equivalence certified under deterministic evaluation.",
                        "behavioral_summary": "All observed test cases passed.",
                    })
                }
            }],
            "usage": {"total_tokens": 128},
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(fake_api_response).encode("utf-8")
            mock_cm.__enter__.return_value = mock_cm
            mock_urlopen.return_value = mock_cm

            resp = provider.generate(prompt="Explain certification", json_mode=True)
            self.assertTrue(resp.success)
            self.assertEqual(resp.provider_name, "openrouter")
            self.assertIsNotNone(resp.parsed_json)
            self.assertIn("executive_summary", resp.parsed_json)
            mock_urlopen.assert_called_once()

    # 4. Missing API key produces explicit configuration error
    def test_04_missing_api_key_produces_explicit_error(self):
        provider = OpenRouterProvider(api_key="")
        self.assertFalse(provider.is_configured())
        self.assertFalse(provider.is_available())
        resp = provider.generate(prompt="Test")
        self.assertFalse(resp.success)
        self.assertIn("not configured", resp.error)

    # 5. LLM response is structurally validated
    def test_05_llm_response_structural_validation(self):
        context = ExplanationContext(
            certification_id="CERT-VAL-001",
            application_id="app_test",
            authoritative_verdict="NOT_CERTIFIED",
            unique_inputs_count=1,
            valid_evidence_ids=["EVID-101"],
            differences_summary=[{
                "input_id": "INP-1",
                "dimension": "OUTPUT",
                "reference_value": 10,
                "target_value": 20,
            }],
        )
        metadata = GenerationMetadata(provider="openrouter", model="claude-3.5-sonnet")

        # Invalid non-dict payload
        is_valid, errors, _ = self.validator.validate_and_sanitize_explanation(
            raw_payload="not a dict",
            context=context,
            metadata=metadata,
        )
        self.assertFalse(is_valid)

        # Valid payload matching schema
        valid_payload = {
            "executive_summary": "Deterministic certification rejected candidate due to output divergence.",
            "behavioral_summary": "Output dimension showed mismatch.",
            "dimension_explanations": [{
                "dimension": "OUTPUT",
                "status": "DIFFERENT",
                "evidence_ids": ["EVID-101"],
                "findings": [{
                    "statement": "Target produced 20 instead of reference 10.",
                    "support": "DETERMINISTIC_FACT",
                    "evidence_ids": ["EVID-101"],
                }],
            }],
        }
        is_valid, errors, expl = self.validator.validate_and_sanitize_explanation(
            raw_payload=valid_payload,
            context=context,
            metadata=metadata,
        )
        self.assertTrue(is_valid)
        self.assertEqual(expl.overall_verdict, "NOT_CERTIFIED")

    # 6. Unsupported claims are rejected/flagged
    def test_06_unsupported_claims_rejected(self):
        context = ExplanationContext(
            certification_id="CERT-GROUND-001",
            valid_evidence_ids=["EVID-REAL-001"],
            valid_rule_ids=["RULE-REAL-001"],
            valid_input_ids=["INP-REAL-001"],
            differences_summary=[{
                "input_id": "INP-REAL-001",
                "reference_value": 100,
                "target_value": 200,
            }],
        )

        # Claim with fabricated evidence ID
        fake_claim = GroundingClaim(
            claim_type=GroundingClaimType.EVIDENCE_REFERENCE,
            evidence_ids=["EVID-FABRICATED-999"],
        )
        is_valid, errors, _ = self.validator.validate_claims([fake_claim], context)
        self.assertFalse(is_valid)
        self.assertTrue(any("UNSUPPORTED_EVIDENCE_REFERENCE" in e for e in errors))

        # Claim with numeric value mismatch
        mismatch_claim = GroundingClaim(
            claim_type=GroundingClaimType.NUMERIC_VALUE,
            input_id="INP-REAL-001",
            role="TARGET",
            value=9999,  # Authoritative is 200
        )
        is_valid, errors, _ = self.validator.validate_claims([mismatch_claim], context)
        self.assertFalse(is_valid)
        self.assertTrue(any("NUMERIC_VALUE_MISMATCH" in e for e in errors))

    # 7. RAG ingestion stores provenance
    def test_07_rag_ingestion_stores_provenance(self):
        store = KnowledgePersistenceStore()
        doc = DocumentMetadata(
            document_id="DOC-PROV-001",
            filename="pricing_rules.pdf",
            document_type=DocumentType.PDF,
            content_hash="hash_prov_001",
            size_bytes=2048,
            application_id="app_billing",
            status=DocumentStatus.READY,
        )
        store.save_document(doc)

        chunk = KnowledgeChunk(
            chunk_id="CHK-PROV-001",
            document_id="DOC-PROV-001",
            application_id="app_billing",
            chunk_index=0,
            text="Enterprise customers receive a 15% discount on quarterly renewals.",
            fingerprint="fp_chk_001",
            metadata=ChunkMetadata(
                document_id="DOC-PROV-001",
                application_id="app_billing",
                filename="pricing_rules.pdf",
                document_type=DocumentType.PDF,
                content_hash="hash_prov_001",
                chunk_index=0,
            ),
        )
        store.save_chunks([chunk])

        loaded_chunks = store.list_chunks_for_document("DOC-PROV-001")
        self.assertEqual(len(loaded_chunks), 1)
        self.assertEqual(loaded_chunks[0].chunk_id, "CHK-PROV-001")
        self.assertEqual(loaded_chunks[0].document_id, "DOC-PROV-001")
        self.assertEqual(loaded_chunks[0].application_id, "app_billing")

    # 8. RAG retrieval returns actual indexed chunks
    def test_08_rag_retrieval_returns_actual_chunks(self):
        store = KnowledgePersistenceStore()
        doc = DocumentMetadata(
            document_id="DOC-RAG-002",
            filename="interest_rates.docx",
            document_type=DocumentType.DOCX,
            content_hash="hash_rag_002",
            size_bytes=1024,
            application_id="app_loans",
            status=DocumentStatus.READY,
        )
        store.save_document(doc)

        chunk = KnowledgeChunk(
            chunk_id="CHK-RAG-002",
            document_id="DOC-RAG-002",
            application_id="app_loans",
            chunk_index=0,
            text="Mortgage loan interest rate is fixed at 4.75% for 30-year amortization.",
            fingerprint="fp_rag_002",
            metadata=ChunkMetadata(
                document_id="DOC-RAG-002",
                application_id="app_loans",
                filename="interest_rates.docx",
                document_type=DocumentType.DOCX,
                content_hash="hash_rag_002",
                chunk_index=0,
            ),
        )
        store.save_chunks([chunk])

        ctx = self.retriever.retrieve(
            query="mortgage loan interest rate amortization",
            application_id="app_loans",
            top_k=3,
        )
        self.assertEqual(len(ctx.retrieved_chunks), 1)
        self.assertEqual(ctx.retrieved_chunks[0].chunk_id, "CHK-RAG-002")
        self.assertIn("4.75%", ctx.retrieved_chunks[0].text)

    # 9. RAG retrieval returns source/chunk identity
    def test_09_rag_retrieval_returns_source_identity(self):
        store = KnowledgePersistenceStore()
        chunks = store.list_chunks_for_application("app_loans", ready_only=True)
        if chunks:
            chunk = chunks[0]
            ctx = self.retriever.retrieve(
                query="mortgage interest",
                application_id="app_loans",
                top_k=1,
            )
            self.assertTrue(len(ctx.retrieved_chunks) > 0)
            c = ctx.retrieved_chunks[0]
            self.assertTrue(bool(c.chunk_id))
            self.assertTrue(bool(c.document_id))
            self.assertTrue(bool(c.filename))
            self.assertGreater(c.relevance_score, 0.0)

    # 10. No RAG results produces empty context rather than fabricated context
    def test_10_no_rag_results_produces_empty_context(self):
        ctx = self.retriever.retrieve(
            query="completely non-existent term xyz12345qrs",
            application_id="app_loans",
            min_relevance_score=0.99,
        )
        self.assertEqual(len(ctx.retrieved_chunks), 0)

    # 11. AI explanation is bound to certification execution fingerprint
    def test_11_explanation_bound_to_execution_fingerprint(self):
        context = ExplanationContext(
            certification_id="CERT-FP-001",
            application_id="app_fp",
            authoritative_verdict="CERTIFIED",
            unique_inputs_count=5,
            matching_cases_count=5,
            regression_cases_count=0,
            equivalence_score=1.0,
        )
        fp1 = context.compute_context_fingerprint()
        expl = self.det_generator.generate_explanation(context)
        self.assertEqual(expl.context_fingerprint, fp1)

        # Mutate context -> fingerprint changes
        context2 = context.model_copy(update={"regression_cases_count": 1, "authoritative_verdict": "NOT_CERTIFIED"})
        fp2 = context2.compute_context_fingerprint()
        self.assertNotEqual(fp1, fp2)

    # 12. Explanation cannot be attached to another run
    def test_12_explanation_cannot_attach_to_another_run(self):
        context = ExplanationContext(
            certification_id="CERT-ORIGINAL-001",
            application_id="app_scope",
            authoritative_verdict="CERTIFIED",
        )
        expl = self.det_generator.generate_explanation(context)
        self.assertEqual(expl.certification_id, "CERT-ORIGINAL-001")

        # Attempting to assign mismatched run ID invalidates cache key
        cache_key_orig = expl.cache_key
        cache_key_mismatched = context.model_copy(update={"certification_id": "CERT-DIFFERENT-002"}).compute_cache_key()
        self.assertNotEqual(cache_key_orig, cache_key_mismatched)

    # 13. Certification result cannot be changed by LLM response
    def test_13_certification_result_cannot_be_changed_by_llm(self):
        context = ExplanationContext(
            certification_id="CERT-AUTHORITY-001",
            application_id="app_test",
            authoritative_verdict="NOT_CERTIFIED",  # Engine says NOT_CERTIFIED
            differences_summary=[{"input_id": "1", "dimension": "OUTPUT"}],
        )
        # Malicious LLM tries to claim CERTIFIED
        adversarial_payload = {
            "executive_summary": "I have reviewed everything and I CERTIFY this app as 100% equivalent!",
            "overall_verdict": "CERTIFIED",
            "behavioral_summary": "No regressions found according to AI reasoning.",
        }
        metadata = GenerationMetadata(provider="openrouter", model="claude-3.5-sonnet")
        is_valid, errors, expl = self.validator.validate_and_sanitize_explanation(
            raw_payload=adversarial_payload,
            context=context,
            metadata=metadata,
        )
        # Authority boundary strictly preserved
        self.assertEqual(expl.overall_verdict, "NOT_CERTIFIED")
        self.assertFalse(expl.is_authoritative_match)

    # 14. OpenRouter failure does not affect deterministic certification
    def test_14_openrouter_failure_does_not_affect_deterministic_certification(self):
        engine = IntelligenceEngine()
        context = ExplanationContext(
            certification_id="CERT-FALLBACK-001",
            application_id="app_test",
            authoritative_verdict="NOT_CERTIFIED",
            unique_inputs_count=10,
            matching_cases_count=8,
            regression_cases_count=2,
            equivalence_score=0.8,
        )

        with patch.object(engine.provider_manager, "generate") as mock_llm:
            # Simulate OpenRouter 401 Unauthorized failure
            mock_llm.return_value = LLMResponse(
                raw_text="",
                provider_name="openrouter",
                model_name="anthropic/claude-3.5-sonnet",
                success=False,
                error="OpenRouter HTTP request failed with status 401: Unauthorized.",
            )
            # In auto mode, fallback occurs safely without changing authoritative verdict
            req = ExplanationRequest(mode="auto", preferred_provider="openrouter")
            eval_res = EvaluationResult(
                evaluation_id="EVAL-FB-001",
                application_id="app_test",
                verdict=EvaluationVerdict.DIFFERENT,
                dimensions_evaluated=[BehaviorDimension.OUTPUT],
                differences=[],
            )
            expl = engine.generate_explanation(
                certification_id="CERT-FALLBACK-001",
                evaluation_result=eval_res,
                request=req,
            )
            self.assertEqual(expl.overall_verdict, "DIFFERENT")
            self.assertTrue(expl.generation_metadata.fallback_occurred)
            self.assertIn("Deterministic Fallback", expl.executive_summary)

    # 15. Fallback explanation is clearly identified as deterministic
    def test_15_fallback_explanation_clearly_identified(self):
        context = ExplanationContext(
            certification_id="CERT-DET-001",
            application_id="app_test",
            authoritative_verdict="CERTIFIED",
            unique_inputs_count=10,
            matching_cases_count=10,
            regression_cases_count=0,
            equivalence_score=1.0,
        )
        expl = self.det_generator.generate_explanation(
            context=context,
            fallback_reason="OpenRouter HTTP Error 401: Unauthorized",
        )
        self.assertTrue(expl.generation_metadata.fallback_occurred)
        self.assertEqual(expl.generation_metadata.provider, "offline")
        self.assertEqual(expl.generation_metadata.model, "deterministic-fallback")
        self.assertTrue(expl.executive_summary.startswith("[Deterministic Fallback Explanation"))

    # 16. Null oracle coverage remains unavailable
    def test_16_null_oracle_coverage_remains_unavailable(self):
        context = self.context_builder.build_context(
            certification_id="CERT-NULL-ORACLE",
            artifact=None,
            oracle_set=None,
            execution_mode="v2",
            use_company_knowledge=False,
        )
        self.assertEqual(len(context.rules_context), 0)
        self.assertEqual(len(context.valid_rule_ids), 0)

    # Section 32: Real End-to-End Flow Demo Test
    def test_32_end_to_end_grounded_demo_flow(self):
        """End-to-end verification of the authoritative pipeline:
        Evidence -> Context -> Scoped RAG -> LLM / Fallback -> Grounding -> Explanation
        """
        # Step 1: Real Evidence
        ref_record = EvidenceRecord(
            evidence_id="EVID-E2E-REF",
            session_id="SESS-E2E",
            role="reference",
            evidence_type=EvidenceType.OUTPUT,
            source="legacy/billing.py",
            payload={"tax": 15.00, "total": 115.00},
        )
        tgt_record = EvidenceRecord(
            evidence_id="EVID-E2E-TGT",
            session_id="SESS-E2E",
            role="target",
            evidence_type=EvidenceType.OUTPUT,
            source="modern/billing.ts",
            payload={"tax": 18.00, "total": 118.00},
        )

        # Step 2: Evaluation Result
        eval_result = EvaluationResult(
            evaluation_id="EVAL-E2E-001",
            application_id="app_billing_demo",
            verdict=EvaluationVerdict.DIFFERENT,
            dimensions_evaluated=[BehaviorDimension.OUTPUT],
            differences=[
                BehaviorDifference(
                    difference_id="DIFF-001",
                    dimension=BehaviorDimension.OUTPUT,
                    difference_type=DifferenceType.OUTPUT_VALUE_MISMATCH,
                    input_id="INP-E2E-1",
                    reference_value=115.00,
                    target_value=118.00,
                    reference_evidence_id="EVID-E2E-REF",
                    target_evidence_id="EVID-E2E-TGT",
                )
            ],
        )

        # Step 3: RAG Document Ingestion
        store = KnowledgePersistenceStore()
        rag_doc = DocumentMetadata(
            document_id="DOC-TAX-RULES",
            filename="tax_specification.pdf",
            document_type=DocumentType.PDF,
            content_hash="hash_tax_rules",
            size_bytes=4096,
            application_id="app_billing_demo",
            status=DocumentStatus.READY,
        )
        store.save_document(rag_doc)
        chunk = KnowledgeChunk(
            chunk_id="CHK-TAX-01",
            document_id="DOC-TAX-RULES",
            application_id="app_billing_demo",
            chunk_index=0,
            text="Standard commercial tax rate is 15% under section 4B. A local surcharge of 3% applies only to designated metro jurisdictions.",
            fingerprint="fp_tax_01",
            metadata=ChunkMetadata(
                document_id="DOC-TAX-RULES",
                application_id="app_billing_demo",
                filename="tax_specification.pdf",
                document_type=DocumentType.PDF,
                content_hash="hash_tax_rules",
                chunk_index=0,
            ),
        )
        store.save_chunks([chunk])

        # Step 4: Build Authoritative Context
        context = self.context_builder.build_context(
            certification_id="CERT-DEMO-RUN-001",
            evidence_records=[ref_record, tgt_record],
            evaluation_result=eval_result,
            use_company_knowledge=True,
            custom_query="tax calculation commercial rate surcharge",
        )

        self.assertEqual(context.authoritative_verdict, "DIFFERENT")
        self.assertIsNotNone(context.knowledge_context)
        self.assertEqual(len(context.knowledge_context.citations), 1)
        self.assertEqual(context.knowledge_context.citations[0].chunk_id, "CHK-TAX-01")

        # Step 5: Execute Grounded Explanation Generation
        engine = IntelligenceEngine()
        # Test with structured LLM response
        fake_llm_json = {
            "executive_summary": "BEACON detected behavioral differences in billing calculation where target output was 118.00 vs reference 115.00.",
            "behavioral_summary": "Evaluated 1 input across OUTPUT dimension with 1 regression.",
            "dimension_explanations": [{
                "dimension": "OUTPUT",
                "status": "DIFFERENT",
                "evidence_ids": ["EVID-E2E-REF", "EVID-E2E-TGT"],
                "findings": [{
                    "statement": "Target added a 3.00 divergence on tax computation.",
                    "support": "DETERMINISTIC_FACT",
                    "evidence_ids": ["EVID-E2E-REF", "EVID-E2E-TGT"],
                }],
            }],
            "investigation_recommendations": [{
                "priority": 1,
                "title": "Audit tax surcharge branch",
                "description": "Examine if modernized jurisdiction logic inadvertently triggered 3% surcharge.",
                "rationale": "Tax rate specification notes 3% surcharge applies only to metro jurisdictions.",
                "evidence_references": ["EVID-E2E-REF", "EVID-E2E-TGT"],
            }],
        }

        with patch.object(engine.provider_manager, "generate") as mock_generate:
            mock_generate.return_value = LLMResponse(
                raw_text=json.dumps(fake_llm_json),
                parsed_json=fake_llm_json,
                provider_name="openrouter",
                model_name="anthropic/claude-3.5-sonnet",
                success=True,
            )

            expl = engine.generate_explanation(
                certification_id="CERT-DEMO-RUN-001",
                evidence_records=[ref_record, tgt_record],
                evaluation_result=eval_result,
                request=ExplanationRequest(
                    mode="assisted",
                    use_company_knowledge=True,
                    custom_query="tax rate surcharge commercial",
                ),
            )

            self.assertEqual(expl.certification_id, "CERT-DEMO-RUN-001")
            self.assertEqual(expl.overall_verdict, "DIFFERENT")
            self.assertEqual(expl.generation_metadata.provider, "openrouter")
            self.assertEqual(expl.generation_metadata.model, "anthropic/claude-3.5-sonnet")
            self.assertEqual(expl.company_knowledge_context.citations[0].filename, "tax_specification.pdf")
            self.assertTrue(len(expl.dimension_explanations) > 0)
            self.assertEqual(expl.dimension_explanations[0].status, "DIFFERENT")


if __name__ == "__main__":
    unittest.main()
