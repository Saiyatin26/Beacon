"""Stage 1 — loads the trace_log.json produced by legacy_sample/generate_traces.py
into TraceEvent objects for Stage 2 to consume."""

import json
from pathlib import Path
from common.models import TraceEvent


def load_traces(path: str | Path) -> list[TraceEvent]:
    raw = json.loads(Path(path).read_text())
    return [TraceEvent(inputs=r["inputs"], output=r["output"]) for r in raw]
