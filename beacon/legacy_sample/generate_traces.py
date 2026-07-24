"""Stage 1 [MOCKED] — stands in for real mainframe instrumentation.

Runs legacy_loan_approval against a spread of inputs (including deliberate
boundary cases near credit_score=600 and debt_ratio=0.4, which is what lets
Stage 2's adversarial validation later confirm the rule holds at the edge)
and writes a structured trace log that backend/ingestion consumes.
"""

import json
import itertools
import random
from pathlib import Path

from legacy_loan_approval import evaluate_loan

random.seed(7)


def generate_traces(n_random: int = 300) -> list[dict]:
    traces = []

    # Deliberate boundary sweep around the hidden rule's edges.
    boundary_scores = [598, 599, 600, 601, 602]
    boundary_ratios = [0.38, 0.39, 0.40, 0.41, 0.42]
    for score, ratio in itertools.product(boundary_scores, boundary_ratios):
        inputs = {"credit_score": score, "debt_ratio": ratio, "annual_income": 45000.0}
        output = evaluate_loan(**inputs)
        traces.append({"inputs": inputs, "output": output})

    # Broad random sweep for general coverage / input diversity.
    for _ in range(n_random):
        inputs = {
            "credit_score": random.randint(400, 820),
            "debt_ratio": round(random.uniform(0.0, 0.9), 2),
            "annual_income": round(random.uniform(10000, 150000), 2),
        }
        output = evaluate_loan(**inputs)
        traces.append({"inputs": inputs, "output": output})

    return traces


if __name__ == "__main__":
    traces = generate_traces()
    out_path = Path(__file__).parent / "trace_log.json"
    out_path.write_text(json.dumps(traces, indent=2))
    print(f"Wrote {len(traces)} traces to {out_path}")
