from certification.models import (
    CertificationTestInput,
    compute_input_set_canonical_hash,
)


def test_input_set_hash_detects_changed_case_values():
    original_inputs = [
        CertificationTestInput(input_id="INP-1", values={"field": "value1"}),
        CertificationTestInput(input_id="INP-2", values={"field": "value2"}),
    ]
    changed_inputs = [
        CertificationTestInput(input_id="INP-1", values={"field": "altered"}),
        original_inputs[1],
    ]

    original_hash = compute_input_set_canonical_hash(original_inputs)
    changed_hash = compute_input_set_canonical_hash(changed_inputs)

    assert original_hash != changed_hash
