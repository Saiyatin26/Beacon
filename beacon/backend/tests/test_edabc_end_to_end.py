from types import SimpleNamespace
import hashlib

from application.adapter_detector import AdapterDetector
from application.input_discovery import InputDiscoveryEngine
from application.repository_service import RepositoryAnalysisReport, RepositoryProvenance
from certification.adapters import compute_implementation_hash
from certification.certification_engine import CertificationEngine
from certification.models import (
    CertificationContext,
    CertificationPolicy,
    CertificationStatus,
    compute_input_set_canonical_hash,
)
from evaluation.engine import BehavioralEvaluationEngine
from evaluation.models import verify_evaluation_result_integrity
from execution.evidence_models import (
    EvidencePersistenceStatus,
    EvidenceRecord,
    EvidenceType,
)
from execution.evidence_normalizer import EvidenceNormalizer
from threshold.models import (
    DifferenceMetric,
    ThresholdResolution,
    ThresholdStatus,
    ThresholdStrategy,
)


class PairedSourceProvider:
    def __init__(self, modern_message):
        self.modern_message = modern_message

    def generate(self, prompt, **kwargs):
        if "Analyze the legacy/reference implementation independently" in prompt:
            rule = {
                "rule_id": "LEGACY-1",
                "description": "STATUS Y returns an APPROVED message.",
                "observable_effect": "MESSAGE is APPROVED for STATUS Y.",
                "input_fields": ["STATUS"],
                "input_condition": {"field": "STATUS", "operator": "==", "value": "Y"},
                "expected_output": {"field": "MESSAGE", "value": "APPROVED"},
                "source_path": "legacy.py",
                "source_line": 2,
                "source_excerpt": '    if inputs.get("STATUS") == "Y":',
                "effect_source_path": "legacy.py",
                "effect_source_line": 3,
                "effect_source_excerpt": '        return {"MESSAGE": "APPROVED"}',
            }
            parsed = {"rules": [rule], "gaps": []}
        elif "Analyze the modern/target implementation independently" in prompt:
            rule = {
                "rule_id": "MODERN-1",
                "description": "STATUS Y returns a message.",
                "observable_effect": f"MESSAGE is {self.modern_message} for STATUS Y.",
                "input_fields": ["STATUS"],
                "input_condition": {"field": "STATUS", "operator": "==", "value": "Y"},
                "expected_output": {"field": "MESSAGE", "value": self.modern_message},
                "source_path": "modern.py",
                "source_line": 2,
                "source_excerpt": '    if inputs.get("STATUS") == "Y":',
                "effect_source_path": "modern.py",
                "effect_source_line": 3,
                "effect_source_excerpt": f'        return {{"MESSAGE": "{self.modern_message}"}}',
            }
            parsed = {"rules": [rule], "gaps": []}
        elif "Align independently extracted" in prompt:
            parsed = {
                "alignments": [
                    {
                        "legacy_rule_id": "LEGACY-1",
                        "modern_rule_id": "MODERN-1",
                        "status": "MATCH",
                        "rationale": "Both source rules describe the same STATUS Y condition.",
                    }
                ]
            }
        else:
            parsed = {
                "test_cases": [
                    {"rule_id": "EDABC-001", "values": {"STATUS": "Y"}}
                ]
            }
        return SimpleNamespace(
            requested_provider=kwargs["preferred_provider"],
            provider_name="openrouter",
            model_name="test-model",
            fallback_occurred=False,
            error_category=None,
            success=True,
            parsed_json=parsed,
        )


def _repository_report(repo_id, root):
    return RepositoryAnalysisReport(
        repository_id=repo_id,
        provenance=RepositoryProvenance(
            source_url=str(root),
            source_type="directory",
            resolved_revision="test",
            content_hash=compute_implementation_hash(root),
            retrieval_timestamp="test",
            local_path=str(root),
        ),
        languages=["python"],
    )


def _run_edabc_case(
    tmp_path, monkeypatch, modern_message, *, stale_source=False, stale_input_set=False
):
    legacy_root = tmp_path / "legacy"
    modern_root = tmp_path / "modern"
    legacy_root.mkdir()
    modern_root.mkdir()
    legacy_file = legacy_root / "legacy.py"
    modern_file = modern_root / "modern.py"
    legacy_file.write_text(
        'def run_vector(inputs):\n'
        '    if inputs.get("STATUS") == "Y":\n'
        '        return {"MESSAGE": "APPROVED"}\n'
        '    return {"MESSAGE": "REJECTED"}\n',
        encoding="utf-8",
    )
    modern_file.write_text(
        'def run_vector(inputs):\n'
        '    if inputs.get("STATUS") == "Y":\n'
        f'        return {{"MESSAGE": "{modern_message}"}}\n'
        '    return {"MESSAGE": "REJECTED"}\n',
        encoding="utf-8",
    )
    source_tree_hashes = {
        "legacy": compute_implementation_hash(legacy_root),
        "modern": compute_implementation_hash(modern_root),
    }
    provider = PairedSourceProvider(modern_message)
    monkeypatch.setattr(
        "application.input_discovery.settings",
        SimpleNamespace(llm_provider="openrouter"),
    )
    monkeypatch.setattr("llm.manager.get_provider_manager", lambda: provider)
    discovery = InputDiscoveryEngine().discover_inputs(
        _repository_report("legacy", legacy_root),
        _repository_report("modern", modern_root),
        legacy_entrypoint_file=legacy_file,
        modern_entrypoint_file=modern_file,
    )
    assert discovery.status.value == "SUCCESS"

    detector = AdapterDetector()
    legacy_adapter = detector.load_authorized_adapter(
        legacy_file, "run_vector", "legacy", "reference", version="legacy-source"
    )
    modern_adapter = detector.load_authorized_adapter(
        modern_file, "run_vector", "modern", "target", version="modern-source"
    )
    test_input = discovery.test_inputs[0]
    legacy_observation = legacy_adapter.execute(test_input.values, input_id=test_input.input_id)
    modern_observation = modern_adapter.execute(test_input.values, input_id=test_input.input_id)

    records = [
        EvidenceRecord(
            evidence_id=f"EVID-{role.upper()}",
            session_id="edabc-test-session",
            execution_id=f"EXEC-{role.upper()}",
            application_id="edabc-test-app",
            role=role,
            input_id=test_input.input_id,
            evidence_type=EvidenceType.OUTPUT,
            payload={
                "raw_output": observation.raw_outputs,
                "normalized_output": observation.normalized_outputs,
                "execution_status": observation.execution_status,
                "duration_ms": observation.execution_time_ms,
            },
            persistence_status=EvidencePersistenceStatus.PERSISTED,
        )
        for role, observation in (
            ("reference", legacy_observation),
            ("target", modern_observation),
        )
    ]
    input_set_hash = compute_input_set_canonical_hash(discovery.test_inputs)
    bundle = EvidenceNormalizer.build_bundle(
        session_id="edabc-test-session",
        correlation_id="edabc-test-run",
        application_id="edabc-test-app",
        input_set_id="edabc-test-input-set",
        input_set_hash=input_set_hash,
        records=records,
        reference_execution_ids=["EXEC-REFERENCE"],
        target_execution_ids=["EXEC-TARGET"],
        persistence_status=EvidencePersistenceStatus.PERSISTED,
    )
    evaluation = BehavioralEvaluationEngine().evaluate_bundle(bundle)
    assert verify_evaluation_result_integrity(evaluation)

    if stale_source:
        modern_file.write_text(
            modern_file.read_text(encoding="utf-8").replace(modern_message, "CHANGED"),
            encoding="utf-8",
        )
    provider_calls = discovery.provenance["llm_provider"]["provider_calls"]
    source_rule = discovery.provenance["ai_mined_rules"][0]
    source_integrity = 1.0
    for role, root in (("legacy", legacy_root), ("modern", modern_root)):
        if compute_implementation_hash(root) != source_tree_hashes[role]:
            source_integrity = 0.0
        for evidence_key in (role, f"{role}_effect"):
            evidence = source_rule["source_evidence"][evidence_key]
            source_file = root / evidence["path"]
            current_lines = source_file.read_text(encoding="utf-8").splitlines()
            if (
                hashlib.sha256(source_file.read_bytes()).hexdigest() != evidence["file_hash"]
                or current_lines[evidence["line"] - 1].strip() != evidence["excerpt"]
            ):
                source_integrity = 0.0
    context = CertificationContext(
        evaluation_mode="FULL_BEACON",
        provider="openrouter",
        model="test-model",
        provider_metadata={"provider_calls": provider_calls},
        legacy_implementation_hash=source_tree_hashes["legacy"],
        modernized_implementation_hash=source_tree_hashes["modern"],
        source_rule_manifest_hash=discovery.provenance["rule_manifest_hash"],
        source_rule_coverage=1.0,
        source_rule_integrity=source_integrity,
        dual_source_alignment_complete=True,
        input_set_id="edabc-test-input-set",
        input_set_hash=("0" * 64 if stale_input_set else input_set_hash),
        source_rule_evidence={"rules": {source_rule["rule_id"]: source_rule}},
    )
    threshold = ThresholdResolution(
        resolution_id="edabc-test-threshold",
        metric=DifferenceMetric.ABSOLUTE_DIFF,
        strategy=ThresholdStrategy.FIXED,
        status=ThresholdStatus.RESOLVED,
        final_value=1.0,
        policy_id="edabc-test-policy",
        policy_version="1",
    )
    artifact = CertificationEngine().certify(
        application_id="edabc-test-app",
        context=context,
        policy=CertificationPolicy(
            evaluation_mode="FULL_BEACON",
            min_equivalence_score=0.8,
            min_oracle_coverage=0.8,
        ),
        evaluation_result=evaluation,
        threshold_resolution=threshold,
        test_inputs=discovery.test_inputs,
    )
    return artifact, evaluation, legacy_observation, modern_observation, source_rule


def test_full_beacon_runs_source_extraction_execution_and_genuine_passing_certificate(
    tmp_path, monkeypatch
):
    artifact, evaluation, legacy_observation, modern_observation, source_rule = _run_edabc_case(
        tmp_path, monkeypatch, "APPROVED"
    )

    assert evaluation.summary.equivalent_inputs == 1
    assert legacy_observation.normalized_outputs == {"MESSAGE": "APPROVED"}
    assert modern_observation.normalized_outputs == {"MESSAGE": "APPROVED"}
    assert source_rule["expected_behavior"]["legacy"]["expected_output"]["value"] == "APPROVED"
    assert artifact.status == CertificationStatus.CERTIFIED, (
        f"{artifact.blocking_reasons}; gates={artifact.metrics.evidence_gate_results}"
    )
    assert artifact.certified is True
    assert artifact.metrics.evidence_gate_results
    assert all(artifact.metrics.evidence_gate_results.values())
    tampered_evaluation = evaluation.model_copy(deep=True)
    tampered_evaluation.summary.behavioral_score = 0.0
    assert not verify_evaluation_result_integrity(tampered_evaluation)


def test_full_beacon_blocks_pair_with_real_behavioral_mismatch(tmp_path, monkeypatch):
    artifact, evaluation, _, modern_observation, _ = _run_edabc_case(
        tmp_path, monkeypatch, "DENIED"
    )

    assert evaluation.summary.different_inputs == 1
    assert modern_observation.normalized_outputs == {"MESSAGE": "DENIED"}
    assert artifact.status == CertificationStatus.NOT_CERTIFIED
    assert artifact.certified is False
    assert any("Behavioral mismatches" in reason for reason in artifact.blocking_reasons)


def test_full_beacon_blocks_source_changed_after_rule_extraction(tmp_path, monkeypatch):
    artifact, _, _, _, _ = _run_edabc_case(
        tmp_path, monkeypatch, "APPROVED", stale_source=True
    )

    assert artifact.certified is False
    assert artifact.metrics.evidence_gate_results["source_rule_integrity"] is False
    assert any("source rule anchors" in reason.lower() for reason in artifact.blocking_reasons)


def test_full_beacon_blocks_input_set_changed_after_execution(tmp_path, monkeypatch):
    artifact, _, _, _, _ = _run_edabc_case(
        tmp_path, monkeypatch, "APPROVED", stale_input_set=True
    )

    assert artifact.certified is False
    assert artifact.metrics.evidence_gate_results["input_set_integrity"] is False
    assert any("input-set integrity" in reason.lower() for reason in artifact.blocking_reasons)
