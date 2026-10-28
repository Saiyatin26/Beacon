"""Automated Test Suite for BEACON Independent Benchmark (Masquerade CBTRN02C).

Verifies:
1. GnuCOBOL 3.1.2.0 native compilation of CBTRN02C in WSL.
2. Behavioral equivalence of clean candidate on canonical transactions.
3. Accurate detection of defective candidate mutants.
4. 100% precision (0 false alarms) on semantics-preserving equivalent controls.
5. Table XXV schema and empirical metric consistency.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest
import sys

sys.path.insert(0, ".")
MASQUERADE_PATH = Path("c:/Users/Navaneeth Motamarry/masquerade-cobol/pipeline")
if str(MASQUERADE_PATH) not in sys.path:
    sys.path.insert(0, str(MASQUERADE_PATH))

from experiments.masquerade_runner import run_cbtrn02c_reference, classify_cbtrn02c_rules


def test_wsl_gnucobol_compiles_cbtrn02c():
    """Confirms that legacy CBTRN02C.cbl compiles cleanly under WSL GnuCOBOL 3.1.2.0."""
    cbl_path = "/mnt/c/Users/Navaneeth Motamarry/masquerade-cobol/test-codebases/carddemo/app/cbl/CBTRN02C.cbl"
    cpy_path = "/mnt/c/Users/Navaneeth Motamarry/masquerade-cobol/test-codebases/carddemo/app/cpy"
    out_bin = "/mnt/c/Users/Navaneeth Motamarry/Beacon/Beacon/beacon/scratch/test_cbtrn02c_bin"

    cmd = f'cobc -x -std=ibm -I "{cpy_path}" -o "{out_bin}" "{cbl_path}"'
    res = subprocess.run(
        ["wsl", "-d", "Ubuntu", "--", "bash", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"Compilation failed: {res.stderr}"
    assert Path("scratch/test_cbtrn02c_bin").exists()


def test_reference_runner_valid_transaction():
    """Confirms reference runner posts a valid transaction and updates balances."""
    inp = {
        "tran_id": "0000000000000001",
        "tran_card_num": "1111222233334444",
        "tran_amt": "50.00",
        "tran_type_cd": "01",
        "tran_cat_cd": 1,
        "tran_orig_ts": "2024-05-01 10:00:00",
    }
    out = run_cbtrn02c_reference(inp)
    assert out["status"] == "SUCCESS"
    assert out["return_code"] == 0
    assert out["posted_count"] == 1
    assert out["reject_count"] == 0
    assert out["acct1_cyc_credit"] == "150.00"  # 100 base + 50
    assert out["tcat1_balance"] == "150.00"


def test_reference_runner_rejection_rules():
    """Confirms reference runner triggers each of the 4 rejection rules."""
    # 1. Invalid card (Rule 100)
    out1 = run_cbtrn02c_reference({"tran_card_num": "9999999999999999", "tran_amt": "10.00"})
    assert out1["reject_count"] == 1
    assert out1["reject_details"][0]["reason"] == 100

    # 2. Missing account (Rule 101)
    out2 = run_cbtrn02c_reference({"tran_card_num": "8888888888888888", "tran_amt": "10.00"})
    assert out2["reject_count"] == 1
    assert out2["reject_details"][0]["reason"] == 101

    # 3. Overlimit (Rule 102) - acct limit is 1000, current bal is 950 + 100 = 1050 > 1000
    out3 = run_cbtrn02c_reference({"tran_card_num": "2222333344445555", "tran_amt": "100.00"})
    assert out3["reject_count"] == 1
    assert out3["reject_details"][0]["reason"] == 102

    # 4. Expired account (Rule 103) - expired 2022-01-01
    out4 = run_cbtrn02c_reference({
        "tran_card_num": "3333444455556666",
        "tran_amt": "10.00",
        "tran_orig_ts": "2024-05-01 10:00:00",
    })
    assert out4["reject_count"] == 1
    assert out4["reject_details"][0]["reason"] == 103


def test_candidate_equivalent_controls_zero_divergence():
    """Confirms equivalent controls produce zero mismatches against reference runner."""
    from experiments.masquerade_mutants.candidate_MASQ_EQ_01 import run_candidate as run_eq01
    from experiments.masquerade_mutants.candidate_MASQ_EQ_06 import run_candidate as run_eq06

    test_inputs = [
        {"tran_card_num": "1111222233334444", "tran_amt": "25.00"},
        {"tran_card_num": "2222333344445555", "tran_amt": "100.00"},
        {"tran_card_num": "9999999999999999", "tran_amt": "50.00"},
    ]
    for inp in test_inputs:
        ref_out = run_cbtrn02c_reference(inp)
        assert run_eq01(inp) == ref_out, "MASQ_EQ_01 diverged from reference"
        assert run_eq06(inp) == ref_out, "MASQ_EQ_06 diverged from reference"


def test_candidate_defective_mutant_detection():
    """Confirms defective mutants produce observable mismatches."""
    from experiments.masquerade_mutants.candidate_MASQ_VAL_01 import run_candidate as run_val01
    from experiments.masquerade_mutants.candidate_MASQ_FLOW_03 import run_candidate as run_flow03

    # Unknown card should be rejected by reference, but accepted by bypass mutant MASQ_VAL_01
    inp_unknown = {"tran_card_num": "9999999999999999", "tran_amt": "10.00"}
    ref_out = run_cbtrn02c_reference(inp_unknown)
    val01_out = run_val01(inp_unknown)
    assert val01_out != ref_out, "MASQ_VAL_01 failed to mismatch on invalid card"

    # Transaction count mutant MASQ_FLOW_03 omits transaction count
    inp_normal = {"tran_card_num": "1111222233334444", "tran_amt": "20.00"}
    ref_normal = run_cbtrn02c_reference(inp_normal)
    flow03_out = run_flow03(inp_normal)
    assert flow03_out != ref_normal, "MASQ_FLOW_03 failed to mismatch on transaction count"


def test_table25_artifact_consistency():
    """Validates Table XXV JSON schema and empirical count consistency."""
    t25_path = Path("results/05_scaling/table25_independent_benchmark.json")
    assert t25_path.exists()

    with open(t25_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "complete"
    assert "carddemo_benchmark" in data
    assert "masquerade_benchmark" in data

    masq = data["masquerade_benchmark"]
    assert masq["total_cases"] == masq["defective_cases"] + masq["control_cases"]
    assert masq["defects_detected"] + masq["defects_missed"] == masq["defective_cases"]
    assert masq["precision"] == 1.0  # 0 false alarms on equivalent controls
    assert masq["false_alarm_rate"] == 0.0
    assert masq["recall"] > 0.50
