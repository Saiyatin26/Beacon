"""Stage 2a — LLM Prompt & Context Builder (Phase 6).

Converts a SelectedEvidenceContext into a structured, evidence-grounded prompt for Claude.
Enforces strict instructions that the LLM is generating unconfirmed hypotheses, must strictly
adhere to supplied evidence, must not hallucinate variables or thresholds, and must output
structured JSON.
"""

import json
from .evidence_selector import SelectedEvidenceContext

PROMPT_VERSION = "v1.0"

SYSTEM_INSTRUCTIONS = """You are BEACON's AI Candidate Invariant Miner.
Your sole role is to propose 1 to 5 candidate business-rule hypotheses from the provided legacy system evidence.

CRITICAL INSTRUCTIONS & GUARDRAILS:
1. HYPOTHESIS GENERATOR ONLY: You are proposing hypotheses that will be independently subjected to adversarial property testing and statistical validation by BEACON. You are NOT a verifier and you do NOT determine invariant confidence.
2. STRICT EVIDENCE GROUNDING: You MUST use ONLY the input variables, numerical thresholds, logical operators, observed output values, evidence IDs, and source lines explicitly provided in the evidence summary below.
3. NO HALLUCINATION: DO NOT invent variables, unobserved thresholds (e.g. do not invent 650 if only 600 was observed), nonexistent evidence IDs, or unobserved outputs. Any rule referencing ungrounded facts will be automatically rejected by BEACON's grounding checker.
4. STRUCTURED JSON OUTPUT: Return ONLY a valid JSON array of objects. Do NOT include any markdown preamble, conversational text, or postamble.

JSON Array Output Schema:
[
  {
    "condition": "<valid boolean expression over input fields, e.g. 'credit_score < 600 and debt_ratio > 0.4'>",
    "consequence": "<exact output value/decision when condition holds, e.g. 'REJECT'>",
    "domain": "<business domain, e.g. 'Loan approval'>",
    "severity": "critical|high|medium|low",
    "rationale": "<explanation citing supporting static and dynamic evidence IDs>",
    "supporting_evidence_ids": ["EV-S-xxx", "EV-D-yyy"],
    "source_lines": [14]
  }
]
"""


def build_mining_prompt(context: SelectedEvidenceContext) -> str:
    """Constructs the complete formatted prompt text from a SelectedEvidenceContext."""

    # 1. Format Correlated Evidence
    correlated_data = []
    for c in context.correlated_conditions:
        static_id = c.static_item.evidence_id if c.static_item else "None"
        correlated_data.append({
            "condition": c.condition_expr,
            "static_evidence_id": static_id,
            "source_locations": c.source_locations,
            "runtime_observations": c.runtime_observations,
            "unique_inputs_count": c.unique_inputs,
            "boundary_cases_count": c.boundary_cases,
            "observed_outcomes_distribution": c.observed_outcomes,
            "sample_execution_ids": c.execution_ids[:5],
        })

    # 2. Format Static Evidence Items
    static_data = []
    for s in context.static_items:
        static_data.append({
            "evidence_id": s.evidence_id,
            "type": s.type,
            "condition": s.condition,
            "line": s.line,
            "function": s.function,
            "source_location": s.source_location_id,
        })

    # 3. Format Representative Dynamic Traces
    dynamic_data = []
    for d in context.dynamic_items:
        dynamic_data.append({
            "evidence_id": d.evidence_id,
            "execution_id": d.execution_id,
            "inputs": d.inputs,
            "output": d.output,
            "evaluated_branches": d.branch_results,
        })

    evidence_summary = {
        "target_source_file": context.source_file,
        "language": context.language,
        "correlated_business_rules": correlated_data,
        "static_ast_facts": static_data,
        "sample_dynamic_executions": dynamic_data,
    }

    formatted_summary = json.dumps(evidence_summary, indent=2)

    prompt = f"""{SYSTEM_INSTRUCTIONS}

EVIDENCE PACKAGE SUMMARY:
{formatted_summary}

Propose 1 to 5 candidate invariant hypotheses that best explain the legacy system's business logic based strictly on the above evidence. Return ONLY the JSON array:"""

    return prompt
