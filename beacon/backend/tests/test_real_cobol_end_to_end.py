import subprocess
from pathlib import Path

import pytest

from application.adapter_detector import AdapterDetector
from certification.cics_runner import compile_cobol_program, execute_compiled_cobol


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PAIR = (
    PROJECT_ROOT
    / "data"
    / "data"
    / "staged_sources"
    / "upl_1d779dd67884"
)


def _wsl_gnucobol_available() -> bool:
    try:
        result = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu", "--", "cobc", "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@pytest.fixture(scope="module")
def actual_implementation_adapters():
    if not _wsl_gnucobol_available():
        pytest.skip("Install GnuCOBOL in the Ubuntu WSL distro to run real COBOL tests")

    return (
        AdapterDetector.load_authorized_adapter(
            SOURCE_PAIR / "legacy" / "COACTUPC.cbl",
            "COACTUPC",
            "legacy-COACTUPC",
            "reference",
        ),
        AdapterDetector.load_authorized_adapter(
            SOURCE_PAIR / "modern" / "coactupc.py",
            "run_vector",
            "modern-COACTUPC",
            "target",
        ),
    )


def test_real_cobol_and_modern_pair_match_on_pf3_return(actual_implementation_adapters):
    legacy, modern = actual_implementation_adapters
    inputs = {"EIBCALEN": "100", "EIBAID": "PF3"}

    legacy_observation = legacy.execute(inputs, input_id="PF3-RETURN")
    modern_observation = modern.execute(inputs, input_id="PF3-RETURN")

    assert legacy_observation.execution_status == "SUCCESS"
    assert modern_observation.execution_status == "SUCCESS"
    assert legacy_observation.provenance["real_cobol_execution"] is True
    observed_control_flow = ("XCTL_PROGRAM", "RETURN_TO_PREV")
    assert {
        key: legacy_observation.normalized_outputs[key]
        for key in observed_control_flow
    } == {
        key: modern_observation.normalized_outputs[key]
        for key in observed_control_flow
    } == {"XCTL_PROGRAM": "COMEN01C", "RETURN_TO_PREV": "Y"}


def test_real_pair_exposes_eibcalen_control_flow_mismatch(actual_implementation_adapters):
    legacy, modern = actual_implementation_adapters
    inputs = {"EIBCALEN": "0", "EIBAID": "PF3"}

    legacy_observation = legacy.execute(inputs, input_id="ZERO-CALEN-PF3")
    modern_observation = modern.execute(inputs, input_id="ZERO-CALEN-PF3")

    assert legacy_observation.execution_status == "SUCCESS"
    assert modern_observation.execution_status == "SUCCESS"
    assert legacy_observation.normalized_outputs["XCTL_PROGRAM"] == "COMEN01C"
    assert modern_observation.normalized_outputs["XCTL_PROGRAM"] == "COSGN00C"


def test_real_cobol_without_beacon_markers_fails_closed(tmp_path):
    if not _wsl_gnucobol_available():
        pytest.skip("Install GnuCOBOL in the Ubuntu WSL distro to run real COBOL tests")

    source_file = tmp_path / "EVIDENCELESS.cbl"
    source_file.write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. EVIDENCELESS.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-VALUE PIC X VALUE SPACE.\n"
        "       COPY DFHAID.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           DISPLAY 'PROGRAM RAN WITHOUT BUSINESS OUTPUT'.\n"
        "           STOP RUN.\n",
        encoding="utf-8",
    )
    compiled, binary_path, diagnostics = compile_cobol_program(
        source_file,
        [],
        "EVIDENCELESS",
    )

    assert compiled, diagnostics
    observed, outputs, stdout, _ = execute_compiled_cobol(
        binary_path,
        {"EIBCALEN": "100"},
    )

    assert observed is False
    assert "PROGRAM RAN WITHOUT BUSINESS OUTPUT" in stdout
    assert "no recognized BEACON output markers" in outputs["error"]
