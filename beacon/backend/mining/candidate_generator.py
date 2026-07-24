"""Stage 2a — Candidate invariant generation.

Feeds correlated (source snippet, trace slice) pairs to Claude and asks it to
propose a candidate business-rule invariant in structured form. This is
intentionally the *only* stage where the LLM's output is trusted as little as
possible — everything downstream (evidence, validation, confidence) exists to
check this stage's work.
"""

import json
import uuid
from anthropic import Anthropic
from common.config import settings
from common.models import CandidateInvariant

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


PROMPT_TEMPLATE = """You are analyzing a legacy system to find undocumented business rules.

Source code:
```
{source}
```

A sample of observed execution traces (inputs -> outputs):
{traces}

Propose ONE candidate business-rule invariant that explains a pattern in the
traces which is not obviously stated in a comment. Respond with ONLY a JSON
object, no other text:
{{"condition": "<readable boolean condition over input fields>",
  "consequence": "<the output field value the condition implies>",
  "severity": "critical|high|medium|low"}}
"""


def propose_candidate(source_code: str, trace_sample: list[dict]) -> CandidateInvariant:
    prompt = PROMPT_TEMPLATE.format(
        source=source_code,
        traces=json.dumps(trace_sample[:40], indent=2),
    )
    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(text)

    return CandidateInvariant(
        invariant_id=str(uuid.uuid4())[:8],
        condition=parsed["condition"],
        consequence=parsed["consequence"],
        severity=parsed.get("severity", "medium"),
    )
