"""AI-assisted, source-grounded rule extraction for paired implementations."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class SourceRuleExtractionError(RuntimeError):
    """Raised when source-grounded extraction cannot produce auditable evidence."""


_AI_PROVIDERS = {"openrouter", "gemini", "anthropic"}
_SOURCE_SUFFIXES = {
    ".c",
    ".cbl",
    ".cob",
    ".cpy",
    ".h",
    ".hpp",
    ".inc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".ts",
    ".tsx",
}
_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
    "vendor",
}
_MAX_SOURCE_FILES = 30
_MAX_FILE_CHARS = 10_000
_MAX_TOTAL_CHARS = 60_000


def _normalize_field(value: str) -> str:
    return re.sub(r"[-_]", "", value).casefold()


def _field_in_excerpt(field: str, excerpt: str) -> bool:
    expected = _normalize_field(field)
    return any(
        _normalize_field(token).endswith(expected)
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]*\b", excerpt)
    )


def _literal_in_excerpt(value: Any, excerpt: str) -> bool:
    if isinstance(value, str):
        return value.strip().strip("'\"").casefold() in excerpt.casefold()
    if isinstance(value, bool):
        return re.search(rf"\b{str(value).lower()}\b", excerpt, re.IGNORECASE) is not None
    if isinstance(value, (int, float)):
        return re.search(rf"(?<![A-Za-z0-9_.]){re.escape(str(value))}(?![A-Za-z0-9_.])", excerpt) is not None
    return False


def rule_input_matches(condition: dict[str, Any], inputs: dict[str, Any]) -> bool:
    """Deterministically checks that an input satisfies an extracted rule condition."""
    field = str(condition.get("field", ""))
    normalized_field = _normalize_field(field)
    value = next(
        (
            actual
            for key, actual in inputs.items()
            if isinstance(key, str) and _normalize_field(key) == normalized_field
        ),
        None,
    )
    if not any(
        isinstance(key, str) and _normalize_field(key) == normalized_field
        for key in inputs
    ):
        return False
    expected = condition.get("value")
    operator = condition.get("operator")
    if operator == "==":
        if isinstance(expected, str) and isinstance(value, str):
            return value.strip().casefold() == expected.strip().casefold()
        return type(value) is type(expected) and value == expected
    if operator == "!=":
        if isinstance(expected, str) and isinstance(value, str):
            return value.strip().casefold() != expected.strip().casefold()
        return type(value) is type(expected) and value != expected
    if isinstance(value, bool) or isinstance(expected, bool):
        return False
    try:
        if operator == "<":
            return value < expected
        if operator == "<=":
            return value <= expected
        if operator == ">":
            return value > expected
        if operator == ">=":
            return value >= expected
    except TypeError:
        return False
    return False


def rule_output_matches(expected_output: dict[str, Any], output: Any) -> bool:
    """Deterministically checks a flat observable output assertion."""
    if not isinstance(output, dict):
        return False
    field = str(expected_output.get("field", ""))
    expected = expected_output.get("value")
    normalized_field = _normalize_field(field)
    actual = next(
        (
            value
            for key, value in output.items()
            if isinstance(key, str) and _normalize_field(key) == normalized_field
        ),
        None,
    )
    if not any(
        isinstance(key, str) and _normalize_field(key) == normalized_field
        for key in output
    ):
        return False
    if isinstance(expected, str) and isinstance(actual, str):
        return actual.strip().casefold() == expected.strip().casefold()
    return type(actual) is type(expected) and actual == expected


def _source_files(root: Path, entrypoint: Path | None) -> list[Path]:
    if root.is_file():
        candidates = [root]
    elif root.is_dir():
        candidates = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in _SOURCE_SUFFIXES
            and not any(
                part.casefold() in _EXCLUDED_DIRS
                for part in path.relative_to(root).parts
            )
        ]
    else:
        raise SourceRuleExtractionError(f"Source root does not exist: {root}")

    unique = set(candidates)
    if entrypoint and entrypoint.is_file():
        unique.add(entrypoint)
    ordered = sorted(unique, key=lambda path: (path != entrypoint, str(path).casefold()))
    if len(ordered) > _MAX_SOURCE_FILES:
        raise SourceRuleExtractionError(
            f"Source tree contains {len(ordered)} relevant files; the extraction limit is {_MAX_SOURCE_FILES}."
        )
    return ordered


def _load_sources(root: Path, entrypoint: Path | None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    sources: list[dict[str, Any]] = []
    source_texts: dict[str, str] = {}
    total_chars = 0
    for path in _source_files(root, entrypoint):
        try:
            raw_source = path.read_bytes()
            text = raw_source.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SourceRuleExtractionError(f"Could not read source file '{path}': {exc}") from exc
        if not text.strip():
            continue
        if len(text) > _MAX_FILE_CHARS:
            raise SourceRuleExtractionError(
                f"Source file '{path}' exceeds the {_MAX_FILE_CHARS}-character extraction limit."
            )
        if total_chars + len(text) > _MAX_TOTAL_CHARS:
            raise SourceRuleExtractionError(
                f"Source tree exceeds the {_MAX_TOTAL_CHARS}-character extraction limit."
            )
        try:
            relative = path.relative_to(root).as_posix() if root.is_dir() else path.name
        except ValueError:
            relative = path.name
        sources.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(raw_source).hexdigest(),
                "content": text,
            }
        )
        source_texts[relative] = text
        total_chars += len(text)
    if not sources:
        raise SourceRuleExtractionError(f"No readable source files found under '{root}'.")
    return sources, source_texts


def _generate_json(prompt: str, provider_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from llm.manager import get_provider_manager

    manager = get_provider_manager()
    try:
        response = manager.generate(
            prompt,
            json_mode=True,
            preferred_provider=provider_name,
            allow_fallback=False,
        )
    except Exception as exc:
        raise SourceRuleExtractionError(
            f"AI provider request failed with {type(exc).__name__}: {exc}"
        ) from exc
    actual_provider = str(getattr(response, "provider_name", "")).strip().lower()
    metadata = {
        "requested_provider": getattr(response, "requested_provider", provider_name),
        "actual_provider": actual_provider,
        "model": getattr(response, "model_name", ""),
        "fallback_used": bool(getattr(response, "fallback_occurred", False)),
        "error_category": getattr(response, "error_category", None),
    }
    parsed = getattr(response, "parsed_json", None)
    if (
        not getattr(response, "success", False)
        or actual_provider not in _AI_PROVIDERS
        or metadata["fallback_used"]
        or not isinstance(parsed, dict)
    ):
        category = metadata["error_category"] or "INVALID_AI_RESPONSE"
        raise SourceRuleExtractionError(
            f"AI provider '{actual_provider or 'unknown'}' did not return an accepted JSON response ({category})."
        )
    return parsed, metadata


def _extract_one_side(
    role: str,
    sources: list[dict[str, Any]],
    provider_name: str,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    payload = [{"path": item["path"], "sha256": item["sha256"], "source": item["content"]} for item in sources]
    prompt = f"""Analyze the {role} implementation independently. Extract externally observable behavioral rules only.
Do not infer behavior not supported by these source files. Report unsupported or ambiguous behavior in gaps.
Each rule must state its input trigger and observable output, state change, or exception effect.
For this certifiable rule subset, provide a single machine-checkable input_condition
({{"field":"...","operator":"==","value":"..."}}) and expected_output
({{"field":"...","value":"..."}}). Use only a flat output field and a JSON scalar.
Rules involving only state changes, side effects, or exceptions must be reported as gaps instead.
Each rule must cite an exact condition source line and exact effect source line using 1-based line
numbers and excerpts, and provide a stable side-local rule_id. Do not assert equivalence with another implementation.
Return JSON only:
{{"rules":[{{"rule_id":"R1","description":"...","source_path":"...","source_line":1,
"source_excerpt":"exact condition line","effect_source_path":"...","effect_source_line":2,
"effect_source_excerpt":"exact effect line","input_fields":["..."],
"input_condition":{{"field":"...","operator":"==","value":"..."}},
"expected_output":{{"field":"...","value":"..."}},
"observable_effect":"..."}}],
"gaps":[{{"description":"...","source_path":"...","source_line":1,"source_excerpt":"..."}}]}}
Sources: {json.dumps(payload, ensure_ascii=True)}"""
    parsed, provider_meta = _generate_json(prompt, provider_name)
    sources_by_path = {item["path"]: item for item in sources}
    rules: list[dict[str, Any]] = []
    ids: set[str] = set()
    raw_rules = parsed.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise SourceRuleExtractionError(
            f"AI extraction for {role} returned no structured behavioral rules."
        )
    source_vocabulary = {
        re.sub(r"[-_]", "", token).casefold()
        for source in sources
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]*\b", source["content"])
    }
    for item in raw_rules:
        if not isinstance(item, dict):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned a malformed rule."
            )
        rule_id = str(item.get("rule_id", "")).strip()
        path = str(item.get("source_path", "")).strip()
        excerpt = str(item.get("source_excerpt", "")).strip()
        try:
            line_number = int(item.get("source_line", 0))
        except (TypeError, ValueError):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned an invalid source line."
            )
        source = sources_by_path.get(path)
        if not rule_id or rule_id in ids or not source or not excerpt:
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned a duplicate rule ID or missing source anchor."
            )
        lines = source["content"].splitlines()
        if line_number < 1 or line_number > len(lines):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} cited a source line outside '{path}'."
            )
        # Require an exact citation on the claimed line; no nearby-line match.
        if lines[line_number - 1].strip() != excerpt:
            raise SourceRuleExtractionError(
                f"AI extraction for {role} cited text that does not exactly match {path}:{line_number}."
            )
        description = str(item.get("description", "")).strip()
        effect = str(item.get("observable_effect", "")).strip()
        input_fields = item.get("input_fields", [])
        input_condition = item.get("input_condition")
        expected_output = item.get("expected_output")
        effect_path = str(item.get("effect_source_path", "")).strip()
        effect_excerpt = str(item.get("effect_source_excerpt", "")).strip()
        try:
            effect_line_number = int(item.get("effect_source_line", 0))
        except (TypeError, ValueError):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned an invalid effect source line."
            )
        effect_source = sources_by_path.get(effect_path)
        if not effect_source or not effect_excerpt:
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned a missing effect source anchor."
            )
        effect_lines = effect_source["content"].splitlines()
        if (
            effect_line_number < 1
            or effect_line_number > len(effect_lines)
            or effect_lines[effect_line_number - 1].strip() != effect_excerpt
        ):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} cited effect text that does not exactly match "
                f"{effect_path}:{effect_line_number}."
            )
        if not description or not effect or not isinstance(input_fields, list) or not input_fields:
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned a rule without a description, observable effect, or input fields."
            )
        if (
            not isinstance(input_condition, dict)
            or not isinstance(expected_output, dict)
            or not isinstance(input_condition.get("field"), str)
            or not isinstance(expected_output.get("field"), str)
            or "value" not in input_condition
            or "value" not in expected_output
            or input_condition.get("operator") not in {"==", "!=", "<", "<=", ">", ">="}
            or isinstance(input_condition.get("value"), (dict, list))
            or isinstance(expected_output.get("value"), (dict, list))
        ):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned a rule without an executable input/output contract."
            )
        fields = sorted({str(field).strip() for field in input_fields if str(field).strip()})
        if not fields or any(
            re.sub(r"[-_]", "", field).casefold() not in source_vocabulary
            for field in fields
        ):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} cited input fields not found in its source."
            )
        if (
            _normalize_field(input_condition["field"]) not in {_normalize_field(field) for field in fields}
            or not _field_in_excerpt(input_condition["field"], excerpt)
            or not _literal_in_excerpt(input_condition["value"], excerpt)
            or not _field_in_excerpt(expected_output["field"], effect_excerpt)
            or not _literal_in_excerpt(expected_output["value"], effect_excerpt)
        ):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned input/output assertions unsupported by its exact source anchors."
            )
        ids.add(rule_id)
        rules.append(
            {
                "rule_id": rule_id,
                "description": description,
                "observable_effect": effect,
                "input_fields": fields,
                "input_condition": input_condition,
                "expected_output": expected_output,
                "source": {
                    "role": role,
                    "rule_id": rule_id,
                    "path": path,
                    "line": line_number,
                    "excerpt": excerpt,
                    "file_hash": source["sha256"],
                },
                "effect_source": {
                    "role": role,
                    "rule_id": rule_id,
                    "path": effect_path,
                    "line": effect_line_number,
                    "excerpt": effect_excerpt,
                    "file_hash": effect_source["sha256"],
                },
            }
        )
    raw_gaps = parsed.get("gaps", [])
    validated_gaps: list[dict[str, Any]] = []
    if not isinstance(raw_gaps, list):
        raise SourceRuleExtractionError(
            f"AI extraction for {role} returned an invalid gaps collection."
        )
    for item in raw_gaps:
        if not isinstance(item, dict):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned a malformed evidence gap."
            )
        path = str(item.get("source_path", "")).strip()
        excerpt = str(item.get("source_excerpt", "")).strip()
        try:
            line_number = int(item.get("source_line", 0))
        except (TypeError, ValueError):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned an invalid evidence-gap source line."
            )
        source = sources_by_path.get(path)
        if not source or not excerpt:
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned an unanchored evidence gap."
            )
        lines = source["content"].splitlines()
        if (
            line_number < 1
            or line_number > len(lines)
            or lines[line_number - 1].strip() != excerpt
            or not str(item.get("description", "")).strip()
        ):
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned an invalid evidence-gap source anchor."
            )
        validated_gaps.append(
            {
                "description": str(item["description"]).strip(),
                "source": {
                    "role": role,
                    "path": path,
                    "line": line_number,
                    "excerpt": excerpt,
                    "file_hash": source["sha256"],
                },
            }
        )
    return rules, {item["path"]: item["sha256"] for item in sources}, {
        **provider_meta,
        "rejected_unanchored_rule_count": len(raw_rules) - len(rules),
        "gaps": validated_gaps,
    }


def extract_aligned_rules_and_tests(
    legacy_root: Path,
    modern_root: Path,
    legacy_entrypoint: Path | None,
    modern_entrypoint: Path | None,
    provider_name: str,
) -> dict[str, Any]:
    """Independently extract, source-check, align, then propose tests for both sides."""
    legacy_sources, _ = _load_sources(legacy_root, legacy_entrypoint)
    modern_sources, _ = _load_sources(modern_root, modern_entrypoint)
    legacy_rules, legacy_hashes, legacy_provider = _extract_one_side(
        "legacy/reference", legacy_sources, provider_name
    )
    modern_rules, modern_hashes, modern_provider = _extract_one_side(
        "modern/target", modern_sources, provider_name
    )
    if not legacy_rules or not modern_rules:
        raise SourceRuleExtractionError(
            "Both implementations must yield at least one locally source-anchored behavioral rule."
        )

    alignment_prompt = f"""Align independently extracted legacy and modern behavioral rule candidates.
Do not assume equivalence. Mark each correspondence MATCH only when the observable behavior is
the same, CONFLICT when the source evidence describes different behavior, LEGACY_ONLY or MODERN_ONLY
when the rule has no counterpart, and AMBIGUOUS when evidence is insufficient.
Return JSON only: {{"alignments":[{{"legacy_rule_id":"...","modern_rule_id":"...",
"status":"MATCH|CONFLICT|LEGACY_ONLY|MODERN_ONLY|AMBIGUOUS","rationale":"..."}}]}}
Legacy: {json.dumps(legacy_rules, ensure_ascii=True)}
Modern: {json.dumps(modern_rules, ensure_ascii=True)}"""
    alignments_raw, alignment_provider = _generate_json(alignment_prompt, provider_name)
    legacy_by_id = {rule["rule_id"]: rule for rule in legacy_rules}
    modern_by_id = {rule["rule_id"]: rule for rule in modern_rules}
    alignments: list[dict[str, Any]] = []
    used_legacy: set[str] = set()
    used_modern: set[str] = set()
    aligned_rules: list[dict[str, Any]] = []
    for item in alignments_raw.get("alignments", []):
        if not isinstance(item, dict):
            continue
        left = str(item.get("legacy_rule_id", ""))
        right = str(item.get("modern_rule_id", ""))
        status = str(item.get("status", "")).upper()
        if status not in {"MATCH", "CONFLICT", "LEGACY_ONLY", "MODERN_ONLY", "AMBIGUOUS"}:
            continue
        if status == "MATCH" and (not left or not right):
            continue
        if status == "LEGACY_ONLY" and (not left or right):
            continue
        if status == "MODERN_ONLY" and (left or not right):
            continue
        if status in {"CONFLICT", "AMBIGUOUS"} and (not left or not right):
            continue
        if status not in {"MODERN_ONLY"} and left not in legacy_by_id:
            continue
        if status not in {"LEGACY_ONLY"} and right not in modern_by_id:
            continue
        if left and left in used_legacy or right and right in used_modern:
            continue
        if left:
            used_legacy.add(left)
        if right:
            used_modern.add(right)
        rationale = str(item.get("rationale", "")).strip()
        if not rationale:
            continue
        alignment = {
            "legacy_rule_id": left or None,
            "modern_rule_id": right or None,
            "status": status,
            "rationale": rationale,
        }
        alignments.append(alignment)
        if status == "MATCH":
            aligned_rules.append(
                {
                    "rule_id": f"EDABC-{len(aligned_rules) + 1:03d}",
                    "legacy_rule_id": left,
                    "modern_rule_id": right,
                    "description": legacy_by_id[left]["description"],
                    "observable_effect": legacy_by_id[left]["observable_effect"],
                    "input_fields": sorted(
                        set(legacy_by_id[left]["input_fields"])
                        | set(modern_by_id[right]["input_fields"])
                    ),
                    "expected_behavior": {
                        "legacy": {
                            "input_condition": legacy_by_id[left]["input_condition"],
                            "expected_output": legacy_by_id[left]["expected_output"],
                        },
                        "modern": {
                            "input_condition": modern_by_id[right]["input_condition"],
                            "expected_output": modern_by_id[right]["expected_output"],
                        },
                    },
                    "alignment_status": status,
                    "alignment_rationale": alignment["rationale"],
                    "source_evidence": {
                        "legacy": legacy_by_id[left]["source"],
                        "modern": modern_by_id[right]["source"],
                        "legacy_effect": legacy_by_id[left]["effect_source"],
                        "modern_effect": modern_by_id[right]["effect_source"],
                    },
                }
            )

    for rule_id in sorted(set(legacy_by_id) - used_legacy):
        alignments.append(
            {"legacy_rule_id": rule_id, "modern_rule_id": None, "status": "LEGACY_ONLY", "rationale": "No valid alignment was returned."}
        )
    for rule_id in sorted(set(modern_by_id) - used_modern):
        alignments.append(
            {"legacy_rule_id": None, "modern_rule_id": rule_id, "status": "MODERN_ONLY", "rationale": "No valid alignment was returned."}
        )

    unresolved = [item for item in alignments if item["status"] != "MATCH"]
    source_gaps = {
        "legacy": legacy_provider["gaps"],
        "modern": modern_provider["gaps"],
    }
    if unresolved or any(source_gaps.values()):
        return {
            "rules": aligned_rules,
            "alignments": alignments,
            "test_cases": [],
            "complete": False,
            "providers": {
                "legacy": legacy_provider,
                "modern": modern_provider,
                "alignment": alignment_provider,
            },
            "source_hashes": {"legacy": legacy_hashes, "modern": modern_hashes},
            "gaps": source_gaps,
        }

    test_prompt = f"""Generate rule-directed test inputs for the aligned behavior rules below.
Inputs are candidates, not expected outputs. Do not invent expected results. Return at least one distinct,
minimal input object per rule and name the rule_id it exercises. Include boundary, normal, and exceptional
paths where source permits. Return JSON only:
{{"test_cases":[{{"rule_id":"EDABC-001","values":{{"field":"value"}}}}]}}
Rules: {json.dumps(aligned_rules, ensure_ascii=True)}"""
    tests_raw, test_provider = _generate_json(test_prompt, provider_name)
    shared_vocabulary = {
        re.sub(r"[-_]", "", token).casefold()
        for source in legacy_sources + modern_sources
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]*\b", source["content"])
    }
    allowed_rule_ids = {rule["rule_id"] for rule in aligned_rules}
    accepted_tests: list[dict[str, Any]] = []
    for test_case in tests_raw.get("test_cases", []):
        if not isinstance(test_case, dict):
            continue
        rule_id = str(test_case.get("rule_id", ""))
        values = test_case.get("values")
        if rule_id not in allowed_rule_ids or not isinstance(values, dict) or not values:
            continue
        rule = next(rule for rule in aligned_rules if rule["rule_id"] == rule_id)
        rule_fields = {
            re.sub(r"[-_]", "", field).casefold()
            for field in rule["input_fields"]
        }
        if not all(
            isinstance(key, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key)
            and re.sub(r"[-_]", "", key).casefold() in rule_fields
            and re.sub(r"[-_]", "", key).casefold() in shared_vocabulary
            for key in values
        ):
            continue
        provided_fields = {
            re.sub(r"[-_]", "", key).casefold()
            for key in values
        }
        if not rule_fields.issubset(provided_fields):
            continue
        if not all(
            rule_input_matches(role_contract["input_condition"], values)
            for role_contract in rule["expected_behavior"].values()
        ):
            continue
        accepted_tests.append({"rule_id": rule_id, "values": values})

    tests_by_rule = {item["rule_id"] for item in accepted_tests}
    if tests_by_rule != allowed_rule_ids:
        missing = sorted(allowed_rule_ids - tests_by_rule)
        raise SourceRuleExtractionError(
            f"No source-validated targeted input was generated for rule(s): {', '.join(missing)}."
        )
    return {
        "rules": aligned_rules,
        "alignments": alignments,
        "test_cases": accepted_tests,
        "complete": True,
        "providers": {
            "legacy": legacy_provider,
            "modern": modern_provider,
            "alignment": alignment_provider,
            "test_generation": test_provider,
        },
        "source_hashes": {"legacy": legacy_hashes, "modern": modern_hashes},
        "gaps": source_gaps,
    }
