"""Unit tests for Phase 4 dynamic runtime tracer and trace providers."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "backend"))
sys.path.append(str(ROOT / "legacy_sample"))

import legacy_loan_approval
from common.models import TraceEvent
from ingestion.runtime_tracer import PythonRuntimeTracer
from ingestion.trace_providers import RuntimeTraceProvider, SyntheticTraceProvider


def sample_target_func(credit_score: int, debt_ratio: float) -> dict:
    decision = "APPROVE"
    if credit_score < 600:
        if debt_ratio > 0.4:
            decision = "REJECT"
    return {"decision": decision}


def failing_target_func(val: int) -> dict:
    if val == 0:
        raise ValueError("val cannot be zero")
    return {"result": 10 / val}


def test_runtime_tracer_executes_function():
    tracer = PythonRuntimeTracer()
    inputs = {"credit_score": 580, "debt_ratio": 0.47}
    event = tracer.trace_execution(sample_target_func, inputs)

    assert isinstance(event, TraceEvent)
    assert event.function == "sample_target_func"


def test_inputs_and_output_captured():
    tracer = PythonRuntimeTracer()
    inputs = {"credit_score": 580, "debt_ratio": 0.47}
    event = tracer.trace_execution(sample_target_func, inputs)

    assert event.inputs == {"credit_score": 580, "debt_ratio": 0.47}
    assert event.output == {"decision": "REJECT"}


def test_execution_id_and_timestamp_generated():
    tracer = PythonRuntimeTracer()
    event = tracer.trace_execution(sample_target_func, {"credit_score": 700, "debt_ratio": 0.2})

    assert event.execution_id is not None
    assert event.execution_id.startswith("EX-")
    assert event.timestamp is not None
    assert "T" in event.timestamp  # ISO format string timestamp check


def test_branch_information_captured():
    tracer = PythonRuntimeTracer()
    event = tracer.trace_execution(sample_target_func, {"credit_score": 580, "debt_ratio": 0.47})

    assert len(event.branch_path) > 0
    assert len(event.executed_branches) > 0

    # Verify structural branch evaluation
    branch_entry = event.executed_branches[0]
    assert "credit_score < 600" in branch_entry
    assert branch_entry["credit_score < 600"] is True


def test_variable_state_captured():
    tracer = PythonRuntimeTracer()
    event = tracer.trace_execution(sample_target_func, {"credit_score": 580, "debt_ratio": 0.47})

    assert len(event.variable_states) > 0
    var_state = event.variable_states[0]
    assert var_state["function"] == "sample_target_func"
    assert "variables" in var_state
    assert var_state["variables"]["credit_score"] == 580


def test_multiple_executions_captured():
    tracer = PythonRuntimeTracer()
    batch = [
        {"credit_score": 550, "debt_ratio": 0.50},
        {"credit_score": 750, "debt_ratio": 0.20},
    ]
    events = tracer.trace_batch(sample_target_func, batch)

    assert len(events) == 2
    assert events[0].output == {"decision": "REJECT"}
    assert events[1].output == {"decision": "APPROVE"}
    assert events[0].execution_id != events[1].execution_id


def test_exception_handling_does_not_crash_tracer():
    tracer = PythonRuntimeTracer()

    # Should trace normal execution without error
    normal_event = tracer.trace_execution(failing_target_func, {"val": 2})
    assert normal_event.output == {"result": 5.0}
    assert normal_event.exception is None

    # Should trace failing execution gracefully without throwing unhandled exception
    fail_event = tracer.trace_execution(failing_target_func, {"val": 0})
    assert fail_event.exception is not None
    assert "ValueError" in fail_event.exception
    assert "error" in fail_event.output


def test_trace_event_model_conformance():
    tracer = PythonRuntimeTracer()
    event = tracer.trace_execution(sample_target_func, {"credit_score": 650, "debt_ratio": 0.3})

    dumped = event.model_dump(mode="json")
    reconstructed = TraceEvent.model_validate(dumped)

    assert reconstructed.inputs == event.inputs
    assert reconstructed.output == event.output
    assert reconstructed.execution_id == event.execution_id


def test_runtime_trace_provider_with_legacy_loan_app():
    """Phase 4 Acceptance Test: Run legacy loan application through RuntimeTraceProvider."""
    provider = RuntimeTraceProvider(target_func=legacy_loan_approval.evaluate_loan)
    traces = provider.get_traces()

    assert len(traces) > 0

    # Find execution for EX-001 (credit_score=580, debt_ratio=0.47)
    ex_580 = next(t for t in traces if t.inputs.get("credit_score") == 580 and t.inputs.get("debt_ratio") == 0.47)

    assert ex_580.inputs == {"credit_score": 580, "debt_ratio": 0.47, "annual_income": 50000.0}
    assert ex_580.output == {"decision": "REJECT"}
    assert ex_580.execution_id is not None
    assert ex_580.timestamp is not None

    # Check Machine-Readable Branch Evaluations
    branch_records = ex_580.executed_branches
    assert len(branch_records) > 0
    record = branch_records[0]
    assert record.get("credit_score < 500") is False
    assert record.get("credit_score < 600") is True
    assert record.get("debt_ratio > 0.4") is True


def test_synthetic_trace_provider_coexistence():
    """Ensure SyntheticTraceProvider works seamlessly alongside RuntimeTraceProvider."""
    sample_file = ROOT / "legacy_sample" / "trace_log.json"
    synth_provider = SyntheticTraceProvider(sample_file)
    synth_traces = synth_provider.get_traces()

    assert len(synth_traces) > 0
    assert isinstance(synth_traces[0], TraceEvent)
