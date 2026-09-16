"""BEACON V2 — Phase 10 Prompts Module."""

from .explanation_prompt import (
    EXPLANATION_SYSTEM_PROMPT,
    render_explanation_prompt,
)
from .qa_prompt import (
    QA_SYSTEM_PROMPT,
    render_qa_prompt,
)

__all__ = [
    "EXPLANATION_SYSTEM_PROMPT",
    "render_explanation_prompt",
    "QA_SYSTEM_PROMPT",
    "render_qa_prompt",
]
