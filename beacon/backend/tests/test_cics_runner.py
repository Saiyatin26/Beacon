import shlex
from types import SimpleNamespace

from certification import cics_runner
from certification.cics_runner import prepare_cics_source


def test_execute_compiled_cobol_quotes_user_values_and_uses_observed_output(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command[-1]
        return SimpleNamespace(
            returncode=0,
            stdout="OUT-ACTION:S\nOUT-MESSAGE:Account found\n",
            stderr="",
        )

    monkeypatch.setattr(cics_runner.subprocess, "run", fake_run)
    malicious_value = '100000001"; touch /tmp/beacon-marker; echo "'

    ok, outputs, stdout, _ = cics_runner.execute_compiled_cobol(
        "/tmp/beacon-cobol",
        {"acct_id": malicious_value},
    )

    assert ok is True
    assert outputs["ACTION"] == "S"
    assert outputs["MESSAGE"] == "Account found"
    assert stdout.startswith("OUT-ACTION:S")
    assert shlex.quote(f"BINP_ACCT={malicious_value}") in captured["command"]


def test_execute_compiled_cobol_rejects_runs_without_observed_business_outputs(monkeypatch):
    monkeypatch.setattr(
        cics_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="BEACON-OP:RETURN\n", stderr=""),
    )

    ok, outputs, _, _ = cics_runner.execute_compiled_cobol(
        "/tmp/beacon-cobol",
        {"acct_id": "100000001"},
    )

    assert ok is False
    assert "no recognized BEACON output markers" in outputs["error"]


def test_execute_compiled_cobol_does_not_report_input_values_as_observed_outputs(monkeypatch):
    monkeypatch.setattr(
        cics_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="OUT-XCTL:COMEN01C\n",
            stderr="",
        ),
    )

    ok, outputs, _, _ = cics_runner.execute_compiled_cobol(
        "/tmp/beacon-cobol",
        {"acct_id": "100000001", "active_status": "Y", "ACCT_BAL": "5000.00"},
    )

    assert ok is True
    assert outputs == {"XCTL_PROGRAM": "COMEN01C", "RETURN_TO_PREV": "Y"}


def test_prepare_cics_source_accepts_and_captures_simple_bms_map_fields(tmp_path):
    copybook_dir = tmp_path / "copybooks"
    copybook_dir.mkdir()
    (copybook_dir / "MAPCOPY.CPY").write_text(
        "       01 MAPIN.\n"
        "         02 ACCTI PIC X(11).\n"
        "       01 MAPOUT REDEFINES MAPIN.\n"
        "         02 ACCTO PIC X(11).\n",
        encoding="utf-8",
    )
    source = (
        "       PROGRAM-ID. MAPTEST.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       COPY MAPCOPY.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN.\n"
        "           EXEC CICS RECEIVE MAP('TEST') INTO(MAPIN) END-EXEC.\n"
        "           EXEC CICS SEND MAP('TEST') FROM(MAPOUT) END-EXEC.\n"
        "           EXEC CICS RETURN END-EXEC.\n"
    )

    prepared = prepare_cics_source(
        source,
        program_id="MAPTEST",
        copybook_dirs=[copybook_dir],
    )

    assert 'ACCEPT WS-BINP-MAP-0001 FROM ENVIRONMENT' in prepared
    assert '"BEACON_INP_ACCTI"' in prepared
    assert "MOVE WS-BINP-MAP-0001" in prepared
    assert "TO ACCTI OF MAPIN" in prepared
    assert "DISPLAY 'OUT-MAP-FIELD:' 'ACCTO:'" in prepared
    assert "ACCTO OF MAPOUT" in prepared


def test_execute_compiled_cobol_returns_captured_bms_fields(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command[-1]
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "OUT-MAP-FIELD:ACCTSIDO:00000000123\n"
                "OUT-MAP-FIELD:ACSTTUSO:Y\n"
                "OUT-MAP-FIELD:INFOMSGO:Account found\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(cics_runner.subprocess, "run", fake_run)

    ok, outputs, _, _ = cics_runner.execute_compiled_cobol(
        "/tmp/beacon-cobol",
        {"acct_id": "00000000123"},
    )

    assert ok is True
    assert outputs["MAP_FIELDS"] == {
        "ACCTSIDO": "00000000123",
        "ACSTTUSO": "Y",
        "INFOMSGO": "Account found",
    }
    assert outputs["ACCT_ID"] == "00000000123"
    assert outputs["ACCT_STATUS"] == "Y"
    assert outputs["MESSAGE"] == "Account found"
    assert "BEACON_INP_ACCTSIDI=00000000123" in captured["command"]


def test_execute_compiled_cobol_preserves_observed_empty_bms_fields(monkeypatch):
    monkeypatch.setattr(
        cics_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="OUT-MAP-FIELD:INFOMSGO:\n",
            stderr="",
        ),
    )

    ok, outputs, _, _ = cics_runner.execute_compiled_cobol(
        "/tmp/beacon-cobol",
        {"acct_id": "100000001"},
    )

    assert ok is True
    assert outputs["MAP_FIELDS"] == {"INFOMSGO": ""}
    assert outputs["MESSAGE"] == ""
    assert "ACCT_ID" not in outputs


def test_cobol_adapter_preserves_leading_zeroes_in_fixed_width_inputs(monkeypatch, tmp_path):
    from certification.adapters import CobolCicsAdapter

    source_file = tmp_path / "INPUTTEST.cbl"
    source_file.write_text("       PROGRAM-ID. INPUTTEST.\n", encoding="utf-8")
    adapter = CobolCicsAdapter(
        program_id="INPUTTEST",
        source_file=source_file,
        role="reference",
    )
    adapter._compiled_binary_path = "/tmp/inputtest"
    adapter.health_check = lambda: SimpleNamespace(is_ready=True, diagnostics="ready")
    captured = {}

    def fake_execute(binary_wsl_path, inputs):
        captured.update(inputs)
        return True, {"ACCT_ID": inputs["ACCT_ID"]}, "OUT-ACCT:value", ""

    monkeypatch.setattr("certification.adapters.execute_compiled_cobol", fake_execute)

    observation = adapter.execute({"ACCT_ID": "00100000001", "EIBCALEN": "100"})

    assert observation.execution_status == "SUCCESS"
    assert observation.normalized_inputs["ACCT_ID"] == "00100000001"
    assert captured["ACCT_ID"] == "00100000001"
    assert captured["EIBCALEN"] == "100"
