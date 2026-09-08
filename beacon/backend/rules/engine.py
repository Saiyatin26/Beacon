"""BEACON V2 — Phase 5 Controlled Mode Assessment Engine.

Coordinates the evaluation of user-defined business rules against Phase 3 EvidenceBundles
and Phase 4 Behavioral Evaluation results, assessing compliance independently for
Reference and Target implementations with strict three-valued applicability,
field-source isolation, comprehensive evidence sufficiency preconditions,
adaptation safety propagation, and cryptographic auditability.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import uuid
from typing import Any, Optional, Union

from evaluation.evidence_status import EvidenceSufficiency
from evaluation.input_adapter import evaluation_input_adapter
from evaluation.models import EvaluationResult, EvaluationVerdict
from execution.evidence_models import (
    EvidenceBundle,
    EvidenceCaptureStatus,
    EvidenceRecord,
    EvidenceType,
)

from .evaluator import _MISSING, TriState, rule_condition_evaluator
from .models import (
    BusinessRule,
    ControlledEvaluationResult,
    ControlledEvaluationSummary,
    ExpectedBehavior,
    ExpectedBehaviorType,
    RuleAssessment,
    RuleComplianceVerdict,
)
from .normalizer import rule_normalizer
from .validator import rule_validator

logger = logging.getLogger("beacon.rules.engine")


class ControlledAssessmentEngine:
    """Core evaluation engine assessing user-defined business rule compliance in Controlled Mode."""

    def evaluate_controlled_mode(
        self,
        rules: list[BusinessRule],
        bundle: Any,
        phase4_result: Optional[EvaluationResult] = None,
    ) -> ControlledEvaluationResult:
        """Evaluates a list of BusinessRules over a Phase 3 EvidenceBundle and optional Phase 4 EvaluationResult.

        Args:
            rules: User-defined business rules.
            bundle: Tamper-evident Phase 3 EvidenceBundle.
            phase4_result: Optional precomputed Phase 4 BehavioralEvaluationResult.

        Returns:
            ControlledEvaluationResult with per-rule, per-input assessments and overall compliance summary.
        """
        eval_id = f"ctrl_eval_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # 1. Normalize and validate all rules
        validated_rules: list[BusinessRule] = []
        for r in rules:
            is_val, errs = rule_validator.validate_rule(r)
            if not is_val:
                logger.warning(f"Rule '{r.rule_id}' failed validation: {errs}")
            # Ensure fingerprint is computed
            if not r.fingerprint:
                r.fingerprint = r.compute_fingerprint()
            validated_rules.append(r)

        # 2. Correlate Phase 3 evidence by input_id with adaptation failure propagation
        correlated_items, issues = evaluation_input_adapter.adapt_bundle(bundle=bundle, verify_integrity=False)

        # 3. Map Phase 4 input verdicts if provided
        phase4_input_verdicts: dict[str, EvaluationVerdict] = {}
        phase4_id = None
        if phase4_result:
            phase4_id = phase4_result.evaluation_id
            for inp_res in phase4_result.input_results:
                phase4_input_verdicts[inp_res.input_id] = inp_res.verdict

        assessments: list[RuleAssessment] = []

        # 4. Evaluate each rule across each correlated input
        for rule in validated_rules:
            # Check if rule failed validation statically
            is_valid, validation_errors = rule_validator.validate_rule(rule)

            for item in correlated_items:
                inp_id = item.input_id
                ref_eids = [r.evidence_id for r in item.reference_records if hasattr(r, "evidence_id")]
                tgt_eids = [r.evidence_id for r in item.target_records if hasattr(r, "evidence_id")]
                p4_verdict = phase4_input_verdicts.get(inp_id)

                if not is_valid:
                    assessments.append(
                        RuleAssessment(
                            assessment_id=f"assm_{uuid.uuid4().hex[:12]}",
                            rule_id=rule.rule_id,
                            rule_name=rule.name,
                            rule_version=rule.version,
                            rule_fingerprint=rule.fingerprint,
                            input_id=inp_id,
                            applicability="UNKNOWN",
                            condition_satisfied=False,
                            reference_compliance=RuleComplianceVerdict.ERROR,
                            target_compliance=RuleComplianceVerdict.ERROR,
                            overall_rule_status=RuleComplianceVerdict.ERROR,
                            behavioral_equivalence=p4_verdict,
                            reference_evidence_ids=ref_eids,
                            target_evidence_ids=tgt_eids,
                            phase4_evaluation_id=phase4_id,
                            explanation=f"Rule validation failed: {'; '.join(validation_errors)}",
                            observed_values={},
                        )
                    )
                    continue

                assessment = self._assess_rule_on_input(
                    rule=rule,
                    item=item,
                    phase4_verdict=p4_verdict,
                    phase4_id=phase4_id,
                )
                assessments.append(assessment)

        # 5. Aggregate overall summary
        summary = self._compute_summary(assessments, validated_rules)

        result = ControlledEvaluationResult(
            evaluation_id=eval_id,
            bundle_id=getattr(bundle, "bundle_id", None),
            application_id=getattr(bundle, "application_id", None),
            timestamp=now,
            overall_verdict=summary.overall_compliance_verdict,
            summary=summary,
            rule_assessments=assessments,
            rules_evaluated=validated_rules,
            phase4_evaluation_id=phase4_id,
            metadata={
                "total_rules": len(validated_rules),
                "total_inputs": len(correlated_items),
                "bundle_issues_count": len(issues),
            },
        )

        result.evaluation_fingerprint = self._compute_evaluation_fingerprint(result)
        return result

    def _assess_rule_on_input(
        self,
        rule: BusinessRule,
        item: Any,
        phase4_verdict: Optional[EvaluationVerdict],
        phase4_id: Optional[str],
    ) -> RuleAssessment:
        """Evaluates applicability and expected behavior compliance for a single rule and input.

        Follows strict three-valued logic and field-source isolation:
        - TRUE -> APPLICABLE -> Check Evidence Sufficiency -> Evaluate Behavior
        - FALSE -> NOT_APPLICABLE
        - UNKNOWN -> INCONCLUSIVE
        """
        inp_id = item.input_id
        ref_eids = [r.evidence_id for r in item.reference_records if hasattr(r, "evidence_id")]
        tgt_eids = [r.evidence_id for r in item.target_records if hasattr(r, "evidence_id")]

        # Build partitioned evaluation context (input, output, state, error, metadata)
        eval_context = self._build_evaluation_context(item)

        # 1. Evaluate Condition Applicability using three-valued logic & field-source isolation
        tri_state, cond_expl, observed_cond_values = rule_condition_evaluator.evaluate_condition(
            rule.condition, eval_context
        )

        # CASE A: Condition evaluates to FALSE -> NOT_APPLICABLE
        if tri_state == TriState.FALSE:
            return RuleAssessment(
                assessment_id=f"assm_{uuid.uuid4().hex[:12]}",
                rule_id=rule.rule_id,
                rule_name=rule.name,
                rule_version=rule.version,
                rule_fingerprint=rule.fingerprint,
                input_id=inp_id,
                applicability="NOT_APPLICABLE",
                condition_satisfied=False,
                reference_compliance=RuleComplianceVerdict.NOT_APPLICABLE,
                target_compliance=RuleComplianceVerdict.NOT_APPLICABLE,
                overall_rule_status=RuleComplianceVerdict.NOT_APPLICABLE,
                behavioral_equivalence=phase4_verdict,
                reference_evidence_ids=ref_eids,
                target_evidence_ids=tgt_eids,
                phase4_evaluation_id=phase4_id,
                explanation=f"Rule condition evaluated to FALSE (NOT_APPLICABLE): {cond_expl}",
                observed_values=observed_cond_values,
            )

        # CASE B: Condition evaluates to UNKNOWN -> INCONCLUSIVE
        if tri_state == TriState.UNKNOWN:
            return RuleAssessment(
                assessment_id=f"assm_{uuid.uuid4().hex[:12]}",
                rule_id=rule.rule_id,
                rule_name=rule.name,
                rule_version=rule.version,
                rule_fingerprint=rule.fingerprint,
                input_id=inp_id,
                applicability="UNKNOWN",
                condition_satisfied=False,
                reference_compliance=RuleComplianceVerdict.INCONCLUSIVE,
                target_compliance=RuleComplianceVerdict.INCONCLUSIVE,
                overall_rule_status=RuleComplianceVerdict.INCONCLUSIVE,
                behavioral_equivalence=phase4_verdict,
                reference_evidence_ids=ref_eids,
                target_evidence_ids=tgt_eids,
                phase4_evaluation_id=phase4_id,
                explanation=f"Rule condition applicability is UNKNOWN (INCONCLUSIVE due to missing referenced fields): {cond_expl}",
                observed_values=observed_cond_values,
            )

        # CASE C: Condition evaluates to TRUE -> APPLICABLE
        # Check evidence sufficiency BEFORE evaluating behavior compliance
        ref_sufficient, ref_suff_reason = self._check_evidence_sufficiency(item, is_reference=True, expected=rule.expected_behavior)
        tgt_sufficient, tgt_suff_reason = self._check_evidence_sufficiency(item, is_reference=False, expected=rule.expected_behavior)

        ref_obs = self._build_observation_context(item, is_reference=True)
        tgt_obs = self._build_observation_context(item, is_reference=False)

        # Evaluate Reference compliance
        if not ref_sufficient:
            ref_compliance = RuleComplianceVerdict.INCONCLUSIVE
            ref_expl = f"Reference evidence insufficient: {ref_suff_reason}"
            ref_vals = {}
        else:
            ref_compliance, ref_expl, ref_vals = self._evaluate_behavior_compliance(rule.expected_behavior, ref_obs)

        # Evaluate Target compliance
        if not tgt_sufficient:
            tgt_compliance = RuleComplianceVerdict.INCONCLUSIVE
            tgt_expl = f"Target evidence insufficient: {tgt_suff_reason}"
            tgt_vals = {}
        else:
            tgt_compliance, tgt_expl, tgt_vals = self._evaluate_behavior_compliance(rule.expected_behavior, tgt_obs)

        # Combine overall status for this rule and input
        if ref_compliance == RuleComplianceVerdict.ERROR or tgt_compliance == RuleComplianceVerdict.ERROR:
            overall_status = RuleComplianceVerdict.ERROR
        elif ref_compliance == RuleComplianceVerdict.FAIL or tgt_compliance == RuleComplianceVerdict.FAIL:
            overall_status = RuleComplianceVerdict.FAIL
        elif ref_compliance == RuleComplianceVerdict.INCONCLUSIVE or tgt_compliance == RuleComplianceVerdict.INCONCLUSIVE:
            overall_status = RuleComplianceVerdict.INCONCLUSIVE
        elif ref_compliance == RuleComplianceVerdict.PASS and tgt_compliance == RuleComplianceVerdict.PASS:
            overall_status = RuleComplianceVerdict.PASS
        else:
            overall_status = RuleComplianceVerdict.INCONCLUSIVE

        all_observed = dict(observed_cond_values)
        all_observed.update({f"ref.{k}": v for k, v in ref_vals.items()})
        all_observed.update({f"tgt.{k}": v for k, v in tgt_vals.items()})

        combined_expl = (
            f"Applicable ({cond_expl}). "
            f"Reference: {ref_compliance.value} ({ref_expl}). "
            f"Target: {tgt_compliance.value} ({tgt_expl})."
        )

        return RuleAssessment(
            assessment_id=f"assm_{uuid.uuid4().hex[:12]}",
            rule_id=rule.rule_id,
            rule_name=rule.name,
            rule_version=rule.version,
            rule_fingerprint=rule.fingerprint,
            input_id=inp_id,
            applicability="APPLICABLE",
            condition_satisfied=True,
            reference_compliance=ref_compliance,
            target_compliance=tgt_compliance,
            overall_rule_status=overall_status,
            behavioral_equivalence=phase4_verdict,
            reference_evidence_ids=ref_eids,
            target_evidence_ids=tgt_eids,
            phase4_evaluation_id=phase4_id,
            explanation=combined_expl,
            observed_values=all_observed,
            details={
                "reference_explanation": ref_expl,
                "target_explanation": tgt_expl,
                "reference_sufficient": ref_sufficient,
                "target_sufficient": tgt_sufficient,
            },
        )

    def _check_evidence_sufficiency(
        self, item: Any, is_reference: bool, expected: ExpectedBehavior
    ) -> tuple[bool, str]:
        """Checks if observation evidence for the given role is sufficient to evaluate the expected behavior."""
        recs = item.reference_records if is_reference else item.target_records
        role_str = "reference" if is_reference else "target"
        b_type = expected.behavior_type

        # 1. Check if there are AdaptationFailures for this role and relevant dimension
        if hasattr(item, "adaptation_failures") and item.adaptation_failures:
            for af in item.adaptation_failures:
                af_role = getattr(af, "role", "")
                if af_role == role_str:
                    af_type = str(getattr(af, "evidence_type", "")).lower()
                    if b_type in (ExpectedBehaviorType.ACCEPT, ExpectedBehaviorType.REJECT, ExpectedBehaviorType.RETURN_VALUE) and af_type in ("output", "http", "error"):
                        return False, f"Adaptation failure in {af_type}: {getattr(af, 'reason', '')}"
                    elif b_type in (ExpectedBehaviorType.RETURN_STATUS,) and af_type in ("http", "output"):
                        return False, f"Adaptation failure in {af_type}: {getattr(af, 'reason', '')}"
                    elif b_type in (ExpectedBehaviorType.STATE_CHANGE, ExpectedBehaviorType.NO_STATE_CHANGE) and af_type in ("database", "file"):
                        return False, f"Adaptation failure in {af_type}: {getattr(af, 'reason', '')}"
                    elif b_type in (ExpectedBehaviorType.WORKFLOW_STEP,) and af_type in ("trace",):
                        return False, f"Adaptation failure in trace: {getattr(af, 'reason', '')}"

        out = item.reference_output if is_reference else item.target_output
        err = item.reference_error if is_reference else item.target_error
        db = item.reference_database if is_reference else item.target_database
        fs = item.reference_file if is_reference else item.target_file
        http_ev = item.reference_http if is_reference else item.target_http
        tr = item.reference_trace if is_reference else item.target_trace

        out_status = getattr(item, f"{role_str}_output_status", None)
        db_status = getattr(item, f"{role_str}_database_status", None)
        fs_status = getattr(item, f"{role_str}_file_status", None)
        http_status = getattr(item, f"{role_str}_http_status", None)
        tr_status = getattr(item, f"{role_str}_trace_status", None)
        err_status = getattr(item, f"{role_str}_error_status", None)

        # 2. Check Dimension-Specific Statuses & Records
        if b_type == ExpectedBehaviorType.ACCEPT:
            if out_status and EvidenceSufficiency.is_insufficient(out_status):
                return False, f"Output evidence capture status '{out_status}' is insufficient"
            if http_status and EvidenceSufficiency.is_insufficient(http_status):
                return False, f"HTTP evidence capture status '{http_status}' is insufficient"

            for r in recs:
                if getattr(r, "evidence_type", None) in (EvidenceType.OUTPUT, EvidenceType.HTTP):
                    st = getattr(r, "capture_status", getattr(r, "status", None))
                    if st and EvidenceSufficiency.is_insufficient(st):
                        return False, f"Output/HTTP record capture status '{st}' is insufficient"

            if out is None and http_ev is None:
                has_out_rec = any(getattr(r, "evidence_type", None) in (EvidenceType.OUTPUT, EvidenceType.HTTP) for r in recs)
                if not has_out_rec:
                    return False, "Output and HTTP execution evidence are missing; cannot prove ACCEPT"
            if out is not None:
                st = getattr(out, "capture_status", EvidenceCaptureStatus.CAPTURED)
                if EvidenceSufficiency.is_insufficient(st):
                    return False, f"Output evidence capture status '{st}' is insufficient"

        elif b_type == ExpectedBehaviorType.REJECT:
            if out_status and EvidenceSufficiency.is_insufficient(out_status):
                return False, f"Output evidence capture status '{out_status}' is insufficient"
            if err_status and EvidenceSufficiency.is_insufficient(err_status):
                return False, f"Error evidence capture status '{err_status}' is insufficient"

            for r in recs:
                if getattr(r, "evidence_type", None) in (EvidenceType.OUTPUT, EvidenceType.ERROR, EvidenceType.HTTP):
                    st = getattr(r, "capture_status", getattr(r, "status", None))
                    if st and EvidenceSufficiency.is_insufficient(st):
                        return False, f"Execution record capture status '{st}' is insufficient"

            if out is None and err is None and http_ev is None:
                has_exec_rec = any(getattr(r, "evidence_type", None) in (EvidenceType.OUTPUT, EvidenceType.ERROR, EvidenceType.HTTP) for r in recs)
                if not has_exec_rec:
                    return False, "Execution evidence (output/error/HTTP) is missing; cannot evaluate REJECT"

        elif b_type == ExpectedBehaviorType.RETURN_VALUE:
            if out_status and EvidenceSufficiency.is_insufficient(out_status):
                return False, f"Output evidence capture status '{out_status}' is insufficient"

            for r in recs:
                if getattr(r, "evidence_type", None) == EvidenceType.OUTPUT:
                    st = getattr(r, "capture_status", getattr(r, "status", None))
                    if st and EvidenceSufficiency.is_insufficient(st):
                        return False, f"Output record capture status '{st}' is insufficient"

            if out is None:
                return False, "Output evidence is completely missing; cannot evaluate RETURN_VALUE"
            st = getattr(out, "capture_status", EvidenceCaptureStatus.CAPTURED)
            if EvidenceSufficiency.is_insufficient(st):
                return False, f"Output evidence capture status '{st}' is insufficient"

        elif b_type == ExpectedBehaviorType.RETURN_STATUS:
            if http_status and EvidenceSufficiency.is_insufficient(http_status):
                return False, f"HTTP evidence capture status '{http_status}' is insufficient"
            if out_status and EvidenceSufficiency.is_insufficient(out_status):
                return False, f"Output evidence capture status '{out_status}' is insufficient"

            if http_ev is None and out is None:
                return False, "HTTP and output evidence are missing; cannot evaluate RETURN_STATUS"
            if http_ev is not None:
                st = getattr(http_ev, "capture_status", EvidenceCaptureStatus.CAPTURED)
                if EvidenceSufficiency.is_insufficient(st):
                    return False, f"HTTP evidence capture status '{st}' is insufficient"

        elif b_type == ExpectedBehaviorType.STATE_CHANGE:
            if db_status and EvidenceSufficiency.is_insufficient(db_status):
                return False, f"Database capture status '{db_status}' is insufficient"
            if fs_status and EvidenceSufficiency.is_insufficient(fs_status):
                return False, f"File capture status '{fs_status}' is insufficient"

            for r in recs:
                if getattr(r, "evidence_type", None) in (EvidenceType.DATABASE, EvidenceType.FILESYSTEM):
                    st = getattr(r, "capture_status", getattr(r, "status", None))
                    if st and EvidenceSufficiency.is_insufficient(st):
                        return False, f"State record capture status '{st}' is insufficient"

            if db is None and fs is None and http_ev is None:
                return False, "Database and filesystem state evidence is missing; cannot evaluate STATE_CHANGE"
            if db is not None:
                st = getattr(db, "capture_status", EvidenceCaptureStatus.CAPTURED)
                if EvidenceSufficiency.is_insufficient(st):
                    return False, f"Database evidence capture status '{st}' is insufficient"

        elif b_type == ExpectedBehaviorType.NO_STATE_CHANGE:
            if db_status and EvidenceSufficiency.is_insufficient(db_status):
                return False, f"Database capture status '{db_status}' is insufficient"
            if fs_status and EvidenceSufficiency.is_insufficient(fs_status):
                return False, f"File capture status '{fs_status}' is insufficient"

            for r in recs:
                if getattr(r, "evidence_type", None) in (EvidenceType.DATABASE, EvidenceType.FILESYSTEM):
                    st = getattr(r, "capture_status", getattr(r, "status", None))
                    if st and EvidenceSufficiency.is_insufficient(st):
                        return False, f"State record capture status '{st}' is insufficient"

            if db is None and fs is None:
                return False, "State evidence is missing; cannot verify NO_STATE_CHANGE"
            if db is not None:
                st = getattr(db, "capture_status", EvidenceCaptureStatus.CAPTURED)
                if EvidenceSufficiency.is_insufficient(st):
                    return False, f"Database evidence capture status '{st}' is insufficient"
                if getattr(db, "snapshot_before", None) is None and getattr(db, "snapshot_after", None) is None and not hasattr(db, "delta_detected"):
                    return False, "Database snapshots are missing; insufficient to prove NO_STATE_CHANGE"

        elif b_type == ExpectedBehaviorType.WORKFLOW_STEP:
            if tr_status and EvidenceSufficiency.is_insufficient(tr_status):
                return False, f"Trace capture status '{tr_status}' is insufficient"

            for r in recs:
                if getattr(r, "evidence_type", None) == EvidenceType.TRACE:
                    st = getattr(r, "capture_status", getattr(r, "status", None))
                    if st and EvidenceSufficiency.is_insufficient(st):
                        return False, f"Trace record capture status '{st}' is insufficient"

            if tr is None:
                return False, "Trace evidence is missing; cannot evaluate WORKFLOW_STEP"
            st = getattr(tr, "capture_status", EvidenceCaptureStatus.CAPTURED)
            if EvidenceSufficiency.is_insufficient(st):
                return False, f"Trace evidence capture status '{st}' is insufficient"

        elif b_type == ExpectedBehaviorType.ERROR:
            if err_status and EvidenceSufficiency.is_insufficient(err_status):
                return False, f"Error capture status '{err_status}' is insufficient"

            if err is None and out is None and http_ev is None:
                return False, "Error and output evidence are missing; cannot evaluate ERROR behavior"

        return True, "Evidence is sufficient"

    def _evaluate_behavior_compliance(
        self, expected: ExpectedBehavior, obs_ctx: dict[str, Any]
    ) -> tuple[RuleComplianceVerdict, str, dict[str, Any]]:
        """Evaluates whether an observation context complies with the expected behavior."""
        b_type = expected.behavior_type
        observed: dict[str, Any] = {}

        # 1. ACCEPT: Execution succeeded without error
        if b_type == ExpectedBehaviorType.ACCEPT:
            exit_code = obs_ctx.get("exit_code")
            http_status = obs_ctx.get("http_status") if obs_ctx.get("http_status") is not None else obs_ctx.get("status_code")
            has_error = obs_ctx.get("has_error", False)

            observed["exit_code"] = exit_code
            observed["http_status"] = http_status
            observed["has_error"] = has_error

            if has_error or (exit_code is not None and exit_code != 0) or (http_status is not None and http_status >= 400):
                return RuleComplianceVerdict.FAIL, f"Expected ACCEPT but execution failed (exit_code={exit_code}, http_status={http_status})", observed
            return RuleComplianceVerdict.PASS, "Execution succeeded without error", observed

        # 2. REJECT: Execution failed / rejected
        elif b_type == ExpectedBehaviorType.REJECT:
            exit_code = obs_ctx.get("exit_code")
            http_status = obs_ctx.get("http_status") if obs_ctx.get("http_status") is not None else obs_ctx.get("status_code")
            has_error = obs_ctx.get("has_error", False)

            observed["exit_code"] = exit_code
            observed["http_status"] = http_status
            observed["has_error"] = has_error

            if has_error or (exit_code is not None and exit_code != 0) or (http_status is not None and http_status >= 400):
                return RuleComplianceVerdict.PASS, f"Execution was rejected as expected (exit_code={exit_code}, http_status={http_status})", observed
            return RuleComplianceVerdict.FAIL, "Expected REJECT but execution succeeded", observed

        # 3. ERROR: Specific error attributes produced
        elif b_type == ExpectedBehaviorType.ERROR:
            err_obj = obs_ctx.get("error") if isinstance(obs_ctx.get("error"), dict) else {}
            err_code = err_obj.get("error_code") or err_obj.get("code")
            status_code = obs_ctx.get("http_status") if obs_ctx.get("http_status") is not None else (obs_ctx.get("status_code") if obs_ctx.get("status_code") is not None else err_obj.get("status_code"))

            observed["error_code"] = err_code
            observed["status_code"] = status_code

            if expected.expected_error_code and err_code != expected.expected_error_code:
                return RuleComplianceVerdict.FAIL, f"Expected error_code '{expected.expected_error_code}', got '{err_code}'", observed
            if expected.expected_status_code is not None and status_code != expected.expected_status_code:
                return RuleComplianceVerdict.FAIL, f"Expected status_code {expected.expected_status_code}, got {status_code}", observed
            if not obs_ctx.get("has_error") and (status_code is None or status_code < 400):
                return RuleComplianceVerdict.FAIL, "Expected ERROR but execution succeeded without error", observed

            return RuleComplianceVerdict.PASS, "Expected error behavior matched", observed

        # 4. RETURN_VALUE: Specific output field matches expected value
        elif b_type == ExpectedBehaviorType.RETURN_VALUE:
            target_field = expected.target_field or "value"
            output_ctx = obs_ctx.get("output")
            if output_ctx is None:
                output_ctx = obs_ctx

            actual_val = rule_condition_evaluator.extract_field_value(output_ctx, target_field, field_source="auto")
            if actual_val is _MISSING and output_ctx is not obs_ctx:
                actual_val = rule_condition_evaluator.extract_field_value(obs_ctx, target_field, field_source="auto")

            observed[target_field] = None if actual_val is _MISSING else actual_val

            if actual_val is _MISSING:
                return RuleComplianceVerdict.FAIL, f"Output field '{target_field}' missing from execution output", observed
            if actual_val != expected.expected_value:
                return RuleComplianceVerdict.FAIL, f"Expected '{target_field}' == {expected.expected_value}, got {actual_val}", observed

            return RuleComplianceVerdict.PASS, f"Output field '{target_field}' == {expected.expected_value}", observed

        # 5. RETURN_STATUS: Status code matches
        elif b_type == ExpectedBehaviorType.RETURN_STATUS:
            status_code = obs_ctx.get("http_status") if obs_ctx.get("http_status") is not None else (obs_ctx.get("status_code") if obs_ctx.get("status_code") is not None else obs_ctx.get("exit_code"))
            observed["status_code"] = status_code

            if status_code is None:
                return RuleComplianceVerdict.INCONCLUSIVE, "Status code not present in observation", observed

            if expected.expected_status_code is not None and status_code != expected.expected_status_code:
                return RuleComplianceVerdict.FAIL, f"Expected status {expected.expected_status_code}, got {status_code}", observed
            return RuleComplianceVerdict.PASS, f"Status {status_code} matched expected", observed

        # 6. STATE_CHANGE / NO_STATE_CHANGE
        elif b_type == ExpectedBehaviorType.STATE_CHANGE:
            state_mutated = obs_ctx.get("state_mutated", False)
            observed["state_mutated"] = state_mutated
            if not state_mutated:
                return RuleComplianceVerdict.FAIL, "Expected STATE_CHANGE but no state mutation detected", observed
            return RuleComplianceVerdict.PASS, "State mutation detected as expected", observed

        elif b_type == ExpectedBehaviorType.NO_STATE_CHANGE:
            state_mutated = obs_ctx.get("state_mutated", False)
            observed["state_mutated"] = state_mutated
            if state_mutated:
                return RuleComplianceVerdict.FAIL, "Expected NO_STATE_CHANGE but state mutation occurred", observed
            return RuleComplianceVerdict.PASS, "No state mutation as expected", observed

        # 7. WORKFLOW_STEP
        elif b_type == ExpectedBehaviorType.WORKFLOW_STEP:
            events = obs_ctx.get("workflow_events", [])
            observed["workflow_events"] = events
            expected_step = expected.expected_workflow_event
            if expected_step and expected_step not in events:
                return RuleComplianceVerdict.FAIL, f"Expected workflow event '{expected_step}' missing from trace {events}", observed
            return RuleComplianceVerdict.PASS, f"Workflow step '{expected_step}' present in trace", observed

        return RuleComplianceVerdict.ERROR, f"Unsupported expected behavior type '{b_type}'", observed

    def _build_evaluation_context(self, item: Any) -> dict[str, Any]:
        """Assembles an isolated evaluation context partitioned by field sources: input, output, state, error, metadata."""
        input_dict: dict[str, Any] = {"input_id": item.input_id}
        output_dict: dict[str, Any] = {}
        state_dict: dict[str, Any] = {}
        error_dict: dict[str, Any] = {}
        metadata_dict: dict[str, Any] = {"input_id": item.input_id}

        all_recs = item.reference_records + item.target_records

        # 1. Populate metadata
        for rec in all_recs:
            if hasattr(rec, "metadata") and isinstance(rec.metadata, dict):
                metadata_dict.update(rec.metadata)
            if hasattr(rec, "provenance") and isinstance(rec.provenance, dict):
                metadata_dict.update(rec.provenance)

        # 2. Populate input dictionary strictly from input sources
        for rec in all_recs:
            ev_type = getattr(rec, "evidence_type", None)
            ev_str = ev_type.value if hasattr(ev_type, "value") else str(ev_type or "")
            if hasattr(rec, "payload") and isinstance(rec.payload, dict):
                p = rec.payload
                if ev_str.upper() == "INPUT":
                    input_dict.update(p)
                elif "input" in p and isinstance(p["input"], dict):
                    input_dict.update(p["input"])
                elif "arguments" in p and isinstance(p["arguments"], dict):
                    input_dict.update(p["arguments"])
                elif "parameters" in p and isinstance(p["parameters"], dict):
                    input_dict.update(p["parameters"])
                elif ev_type not in (EvidenceType.OUTPUT, EvidenceType.HTTP, EvidenceType.DATABASE, EvidenceType.FILESYSTEM, EvidenceType.TRACE, EvidenceType.ERROR):
                    # Generic input payload (e.g. RUNTIME, METADATA, or custom records)
                    input_dict.update(p)

        # If payload fields were directly attached to input records or item
        if hasattr(item, "input_data") and isinstance(item.input_data, dict):
            input_dict.update(item.input_data)

        # 3. Populate output dictionary strictly from output/http sources
        for out in (item.reference_output, item.target_output):
            if out is not None:
                norm = getattr(out, "normalized_output", None)
                raw = getattr(out, "raw_output", None)
                p_data = norm if (norm is not None and (norm or raw is None)) else raw
                if isinstance(p_data, dict):
                    output_dict.update(p_data)
                if getattr(out, "http_status", None) is not None:
                    output_dict["http_status"] = getattr(out, "http_status")
                if getattr(out, "exit_code", None) is not None:
                    output_dict["exit_code"] = getattr(out, "exit_code")

        for http_ev in (item.reference_http, item.target_http):
            if http_ev is not None and getattr(http_ev, "status_code", None) is not None:
                output_dict["http_status"] = getattr(http_ev, "status_code")
                output_dict["status_code"] = getattr(http_ev, "status_code")

        for rec in all_recs:
            if getattr(rec, "evidence_type", None) in (EvidenceType.OUTPUT, EvidenceType.HTTP) and isinstance(rec.payload, dict):
                p = rec.payload
                if "raw_output" in p and isinstance(p["raw_output"], dict):
                    output_dict.update(p["raw_output"])
                if "normalized_output" in p and isinstance(p["normalized_output"], dict):
                    output_dict.update(p["normalized_output"])
                # Also include top-level output fields if present in output record
                for k, v in p.items():
                    if k not in ("raw_output", "normalized_output", "input", "metadata"):
                        output_dict[k] = v

        # 4. Populate state dictionary strictly from database/file sources
        for db in (item.reference_database, item.target_database):
            if db is not None:
                if hasattr(db, "delta_detected"):
                    state_dict["delta_detected"] = getattr(db, "delta_detected")
                if hasattr(db, "row_count"):
                    state_dict["row_count"] = getattr(db, "row_count")
                if getattr(db, "queries", None):
                    state_dict["queries"] = getattr(db, "queries")

        for fs in (item.reference_file, item.target_file):
            if fs is not None and hasattr(fs, "delta_detected"):
                state_dict["file_delta_detected"] = getattr(fs, "delta_detected")

        for rec in all_recs:
            if getattr(rec, "evidence_type", None) in (EvidenceType.DATABASE, EvidenceType.FILESYSTEM) and isinstance(rec.payload, dict):
                state_dict.update(rec.payload)

        # 5. Populate error dictionary strictly from error sources
        for err in (item.reference_error, item.target_error):
            if err is not None:
                err_dump = err.model_dump() if hasattr(err, "model_dump") else (err if isinstance(err, dict) else {})
                error_dict.update(err_dump)

        for rec in all_recs:
            if getattr(rec, "evidence_type", None) == EvidenceType.ERROR and isinstance(rec.payload, dict):
                error_dict.update(rec.payload)

        return {
            "input": input_dict,
            "output": output_dict,
            "state": state_dict,
            "error": error_dict,
            "metadata": metadata_dict,
        }

    def _build_observation_context(self, item: Any, is_reference: bool) -> dict[str, Any]:
        """Extracts observation variables (output, error, state, workflow) for a specific role."""
        obs: dict[str, Any] = {"input_id": item.input_id}

        out = item.reference_output if is_reference else item.target_output
        err = item.reference_error if is_reference else item.target_error
        db = item.reference_database if is_reference else item.target_database
        fs = item.reference_file if is_reference else item.target_file
        http_ev = item.reference_http if is_reference else item.target_http
        tr = item.reference_trace if is_reference else item.target_trace

        # Output extraction
        if out is not None:
            norm = getattr(out, "normalized_output", None)
            raw = getattr(out, "raw_output", None)
            payload_data = norm if (norm is not None and (norm or raw is None)) else raw
            obs["output"] = payload_data
            if isinstance(payload_data, dict):
                obs.update(payload_data)

            http_st = getattr(out, "http_status", None) if getattr(out, "http_status", None) is not None else getattr(out, "status_code", None)
            if http_st is not None:
                obs["http_status"] = http_st
                obs["status_code"] = http_st
            if getattr(out, "exit_code", None) is not None:
                obs["exit_code"] = getattr(out, "exit_code")
            if getattr(out, "stdout", None) is not None:
                obs["stdout"] = getattr(out, "stdout")
            if getattr(out, "stderr", None) is not None:
                obs["stderr"] = getattr(out, "stderr")

        # HTTP evidence extraction
        if http_ev is not None:
            if getattr(http_ev, "status_code", None) is not None:
                obs["http_status"] = getattr(http_ev, "status_code")
                obs["status_code"] = getattr(http_ev, "status_code")

        # Error extraction
        has_error = False
        if err is not None:
            has_error = True
            err_dict = err.model_dump() if hasattr(err, "model_dump") else (err if isinstance(err, dict) else {})
            obs["error"] = err_dict
            if err_dict.get("status_code") is not None:
                obs["status_code"] = err_dict["status_code"]
                obs["http_status"] = err_dict["status_code"]

        if obs.get("exit_code") not in (0, None) or (obs.get("status_code") is not None and obs.get("status_code") >= 400):
            has_error = True

        obs["has_error"] = has_error

        # State mutation extraction
        state_mutated = False
        if db is not None:
            if getattr(db, "delta_detected", False) or getattr(db, "snapshot_after", None) != getattr(db, "snapshot_before", None):
                state_mutated = True
        if fs is not None:
            if getattr(fs, "delta_detected", False):
                state_mutated = True
        if http_ev is not None:
            calls = getattr(http_ev, "calls", [])
            if calls:
                state_mutated = True

        obs["state_mutated"] = state_mutated

        # Workflow trace extraction
        events: list[str] = []
        if tr is not None:
            raw_evs = getattr(tr, "events", []) or getattr(tr, "call_sequence", [])
            for e in raw_evs:
                if isinstance(e, str):
                    events.append(e)
                elif isinstance(e, dict):
                    name = e.get("name") or e.get("event") or ""
                    if name:
                        events.append(name)
                elif hasattr(e, "name"):
                    events.append(getattr(e, "name") or "")

        obs["workflow_events"] = events
        return obs

    def _compute_summary(
        self, assessments: list[RuleAssessment], rules: list[BusinessRule]
    ) -> ControlledEvaluationSummary:
        """Aggregates rule assessment metrics and computes conservative overall compliance verdict."""
        total_assm = len(assessments)
        app_count = sum(1 for a in assessments if a.applicability == "APPLICABLE")
        na_count = sum(1 for a in assessments if a.applicability == "NOT_APPLICABLE")
        unknown_app_count = sum(1 for a in assessments if a.applicability == "UNKNOWN")
        passed_count = sum(1 for a in assessments if a.overall_rule_status == RuleComplianceVerdict.PASS)
        failed_count = sum(1 for a in assessments if a.overall_rule_status == RuleComplianceVerdict.FAIL)
        inconcl_count = sum(1 for a in assessments if a.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE)
        error_count = sum(1 for a in assessments if a.overall_rule_status == RuleComplianceVerdict.ERROR)

        # Conservative aggregation: ERROR > FAIL > INCONCLUSIVE > PASS > NOT_APPLICABLE
        if error_count > 0:
            overall_verdict = RuleComplianceVerdict.ERROR
        elif failed_count > 0:
            overall_verdict = RuleComplianceVerdict.FAIL
        elif inconcl_count > 0:
            overall_verdict = RuleComplianceVerdict.INCONCLUSIVE
        elif app_count > 0 and (passed_count + na_count) == total_assm:
            overall_verdict = RuleComplianceVerdict.PASS
        elif total_assm > 0 and na_count == total_assm:
            overall_verdict = RuleComplianceVerdict.NOT_APPLICABLE
        else:
            overall_verdict = RuleComplianceVerdict.NOT_APPLICABLE if total_assm == 0 else RuleComplianceVerdict.INCONCLUSIVE

        # Breakdown summary by rule_id
        rule_summaries: dict[str, dict[str, Any]] = {}
        for r in rules:
            r_assms = [a for a in assessments if a.rule_id == r.rule_id]
            r_app = sum(1 for a in r_assms if a.applicability == "APPLICABLE")
            r_na = sum(1 for a in r_assms if a.applicability == "NOT_APPLICABLE")
            r_pass = sum(1 for a in r_assms if a.overall_rule_status == RuleComplianceVerdict.PASS)
            r_fail = sum(1 for a in r_assms if a.overall_rule_status == RuleComplianceVerdict.FAIL)
            r_inconcl = sum(1 for a in r_assms if a.overall_rule_status == RuleComplianceVerdict.INCONCLUSIVE)
            r_err = sum(1 for a in r_assms if a.overall_rule_status == RuleComplianceVerdict.ERROR)

            if r_err > 0:
                r_verd = RuleComplianceVerdict.ERROR
            elif r_fail > 0:
                r_verd = RuleComplianceVerdict.FAIL
            elif r_inconcl > 0:
                r_verd = RuleComplianceVerdict.INCONCLUSIVE
            elif r_app > 0 and (r_pass + r_na) == len(r_assms):
                r_verd = RuleComplianceVerdict.PASS
            else:
                r_verd = RuleComplianceVerdict.NOT_APPLICABLE

            rule_summaries[r.rule_id] = {
                "rule_name": r.name,
                "version": r.version,
                "fingerprint": r.fingerprint,
                "total_inputs": len(r_assms),
                "applicable": r_app,
                "passed": r_pass,
                "failed": r_fail,
                "inconclusive": r_inconcl,
                "error": r_err,
                "verdict": r_verd.value,
            }

        return ControlledEvaluationSummary(
            total_rules_evaluated=len(rules),
            applicable_rule_count=app_count,
            not_applicable_rule_count=na_count,
            passed_rule_count=passed_count,
            failed_rule_count=failed_count,
            inconclusive_rule_count=inconcl_count,
            error_rule_count=error_count,
            overall_compliance_verdict=overall_verdict,
            rules_summary_by_id=rule_summaries,
        )

    def _compute_evaluation_fingerprint(self, result: ControlledEvaluationResult) -> str:
        """Computes deterministic SHA-256 fingerprint over canonical assessment output."""
        canonical_assessments = []
        for a in result.rule_assessments:
            canonical_assessments.append({
                "rule_id": a.rule_id,
                "rule_version": a.rule_version,
                "rule_fingerprint": a.rule_fingerprint,
                "input_id": a.input_id,
                "applicability": a.applicability,
                "reference_compliance": a.reference_compliance.value,
                "target_compliance": a.target_compliance.value,
                "overall_rule_status": a.overall_rule_status.value,
            })
        canonical_assessments.sort(key=lambda x: (x["rule_id"], str(x["rule_version"]), x["input_id"]))

        canonical_dict = {
            "bundle_id": result.bundle_id or "",
            "application_id": result.application_id or "",
            "overall_verdict": result.overall_verdict.value,
            "total_rules": result.summary.total_rules_evaluated,
            "applicable_rules": result.summary.applicable_rule_count,
            "passed_rules": result.summary.passed_rule_count,
            "failed_rules": result.summary.failed_rule_count,
            "assessments": canonical_assessments,
        }
        canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


controlled_assessment_engine = ControlledAssessmentEngine()
