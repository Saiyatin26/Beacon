from pathlib import Path
from types import SimpleNamespace

from application.adapter_detector import AdapterDetector
from intelligence import cobol_plan


def test_authorized_cobol_adapter_loading_uses_local_plan_generation(monkeypatch, tmp_path: Path):
    source = tmp_path / "TESTPROG.cbl"
    source.write_text("       PROGRAM-ID. TESTPROG.\n", encoding="utf-8")
    calls = {}

    def fake_generate_execution_plan(source_text, **kwargs):
        calls["source_text"] = source_text
        calls.update(kwargs)
        return SimpleNamespace(program_id="TESTPROG", cics_operations=[])

    monkeypatch.setattr(cobol_plan, "generate_cobol_execution_plan", fake_generate_execution_plan)

    adapter = AdapterDetector.load_authorized_adapter(
        file_path=source,
        fn_name="TESTPROG",
        adapter_name="test-cobol",
        role="reference",
    )

    assert adapter.program_id == "TESTPROG"
    assert calls["allow_external_llm"] is False
