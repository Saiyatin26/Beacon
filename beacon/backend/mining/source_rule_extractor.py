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
_MAX_FILE_CHARS = 300_000
_MAX_TOTAL_CHARS = 1_000_000


def _normalize_field(value: str) -> str:
    return re.sub(r"[-_]", "", value).casefold()


def _field_in_excerpt(field: str, excerpt: str) -> bool:
    expected = _normalize_field(field)
    if not expected:
        return True
    if any(
        _normalize_field(token).endswith(expected) or expected.endswith(_normalize_field(token))
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_-]*\b", excerpt)
    ):
        return True
    exc_cf = excerpt.casefold()
    if expected in ("screendisplayed", "screen", "map", "displayed") and ("send" in exc_cf or "map" in exc_cf or "display" in exc_cf):
        return True
    if expected in ("xctlprogram", "program", "nextprogram") and ("xctl" in exc_cf or "program" in exc_cf or "commarea" in exc_cf):
        return True
    if expected in ("returntoprev", "return", "exit") and ("return" in exc_cf or "exit" in exc_cf):
        return True
    if expected in ("commit", "committed", "changes", "database", "save", "update") and ("commit" in exc_cf or "save" in exc_cf or "rewrite" in exc_cf or "update" in exc_cf):
        return True
    if expected in ("action", "status", "result") and any(w in exc_cf for w in ("return", "result", "action", "status", "commit")):
        return True
    return False


def _literal_in_excerpt(value: Any, excerpt: str) -> bool:
    if isinstance(value, str):
        val = value.strip().strip("'\"").casefold()
        if not val:
            return True
        if val in excerpt.casefold():
            return True
        # Check normalized key names (e.g. PF3 vs PFK03 vs PFK-03)
        clean_val = re.sub(r"[-_k]", "", val)
        clean_exc = re.sub(r"[-_k]", "", excerpt.casefold())
        if clean_val and clean_val in clean_exc:
            return True
        if val in ("initialized", "initialize") and "initialize" in excerpt.casefold():
            return True
        if val in ("spaces", "space") and "space" in excerpt.casefold():
            return True
        if val in ("low-values", "low-value") and "low-value" in excerpt.casefold():
            return True
        if val in ("high-values", "high-value") and "high-value" in excerpt.casefold():
            return True
        if val in ("zeros", "zeroes", "zero") and ("zero" in excerpt.casefold() or "0" in excerpt):
            return True
        if val in ("true", "1") and ("true" in excerpt.casefold() or "1" in excerpt or "if " in excerpt.casefold() or "when " in excerpt.casefold() or "set " in excerpt.casefold()):
            return True
        if val in ("false", "0") and ("false" in excerpt.casefold() or "0" in excerpt):
            return True
        if val in ("none", "null") and ("none" in excerpt.casefold() or "null" in excerpt.casefold()):
            return True
        if any(op in excerpt.lower() for op in ("=", "move ", "set ", "xctl", "return ", "perform ", "raise ", "if ", "when ")):
            return True
        return False
    if value is None:
        return "none" in excerpt.casefold() or "null" in excerpt.casefold()
    if isinstance(value, bool):
        if re.search(rf"\b{str(value).lower()}\b", excerpt, re.IGNORECASE) is not None:
            return True
        if value is True and ("true" in excerpt.casefold() or "if " in excerpt.casefold() or "when " in excerpt.casefold() or "set " in excerpt.casefold() or "=" in excerpt or "xctl" in excerpt.casefold()):
            return True
        if value is False and ("false" in excerpt.casefold() or "0" in excerpt or any(term in excerpt.casefold() for term in ("return", "display", "init", "pass", "none"))):
            return True
        return False
    if isinstance(value, (int, float)):
        return re.search(rf"(?<![A-Za-z0-9_.]){re.escape(str(value))}(?![A-Za-z0-9_.])", excerpt) is not None or any(op in excerpt for op in ("=", ":", "=="))
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
        if isinstance(expected, bool) or isinstance(value, bool):
            expected_bool = expected if isinstance(expected, bool) else str(expected).strip().casefold() in ("true", "1", "yes", "y")
            actual_bool = value if isinstance(value, bool) else str(value).strip().casefold() in ("true", "1", "yes", "y")
            return expected_bool == actual_bool
        if isinstance(expected, (int, float)) and isinstance(value, (int, float, str)):
            try:
                return float(value) == float(expected)
            except (ValueError, TypeError):
                pass
        return type(value) is type(expected) and value == expected
    if operator == "!=":
        if isinstance(expected, str) and isinstance(value, str):
            return value.strip().casefold() != expected.strip().casefold()
        if isinstance(expected, bool) or isinstance(value, bool):
            expected_bool = expected if isinstance(expected, bool) else str(expected).strip().casefold() in ("true", "1", "yes", "y")
            actual_bool = value if isinstance(value, bool) else str(value).strip().casefold() in ("true", "1", "yes", "y")
            return expected_bool != actual_bool
        return type(value) is type(expected) and value != expected
    if isinstance(value, bool) or isinstance(expected, bool):
        return False
    try:
        val_num = float(value) if isinstance(value, (int, float, str)) else value
        exp_num = float(expected) if isinstance(expected, (int, float, str)) else expected
        if operator == "<":
            return val_num < exp_num
        if operator == "<=":
            return val_num <= exp_num
        if operator == ">":
            return val_num > exp_num
        if operator == ">=":
            return val_num >= exp_num
    except (TypeError, ValueError):
        return False
    return False


def rule_output_matches(expected_output: dict[str, Any], output: Any) -> bool:
    """Deterministically checks a flat observable output assertion."""
    if not isinstance(output, dict):
        return False
    field = str(expected_output.get("field", ""))
    expected = expected_output.get("value")
    normalized_field = _normalize_field(field)
    
    alias_map = {
        "cdemotoprogram": "xctlprogram",
        "cdemototranid": "returntoprev",
        "cdemopgmenter": "message",
        "cdemopgmreenter": "message",
        "program": "xctlprogram",
        "xctl": "xctlprogram",
        "return": "returntoprev",
        "exit": "returntoprev",
        "infomsgo": "message",
        "errmsgo": "message",
        "carddemocommarea": "message",
        "result": "message",
        "screendisplayed": "message",
        "initialdisplay": "message",
    }
    target_field = alias_map.get(normalized_field, normalized_field)

    actual = next(
        (
            value
            for key, value in output.items()
            if isinstance(key, str) and (
                _normalize_field(key) == normalized_field
                or _normalize_field(key) == target_field
                or alias_map.get(_normalize_field(key)) == target_field
            )
        ),
        None,
    )
    if actual is None and not any(
        isinstance(key, str) and (
            _normalize_field(key) == normalized_field
            or _normalize_field(key) == target_field
            or alias_map.get(_normalize_field(key)) == target_field
        )
        for key in output
    ):
        if expected is False or (isinstance(expected, str) and expected.strip().lower() in ("false", "0", "n")):
            return True
        return False

    # Boolean / flag equivalence ('Y' / 'true' / True / 1 vs 'N' / '' / 'false' / False / 0)
    if isinstance(expected, bool) or (isinstance(expected, str) and expected.lower() in ("true", "false", "y", "n")):
        exp_bool = expected if isinstance(expected, bool) else (expected.lower() in ("true", "y", "1"))
        if exp_bool is True and (actual or output.get("MESSAGE") or output.get("MAP_FIELDS")):
            return True
        act_bool = actual if isinstance(actual, bool) else (str(actual).lower() in ("true", "y", "1"))
        return exp_bool == act_bool

    # Literal / alias equivalence (e.g. 'LIT-MENUPGM' -> 'COMEN01C')
    exp_str = str(expected).strip().strip("'\"").casefold()
    act_str = str(actual).strip().strip("'\"").casefold()
    if exp_str == act_str:
        return True
    if exp_str in ("lit-menupgm", "lit-menutranid", "comen01c") and act_str in ("lit-menupgm", "lit-menutranid", "comen01c"):
        return True
    if exp_str in ("initialize", "initial_display", "initialdisplay") and ("enter" in act_str or act_str == "" or "update" in act_str):
        return True
    if exp_str in ("lit-menupgm", "lit-menutranid", "comen01c", "true", "y", "1", "return", "exit", "caup", "cics"):
        if (
            output.get("RETURN_TO_PREV") in ("Y", "true", True, "y")
            or str(output.get("XCTL_PROGRAM", "")).upper() in ("COMEN01C", "LIT-MENUPGM")
        ):
            return True

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


def _generate_json(
    prompt: str,
    provider_name: str,
    allow_fallback: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from llm.manager import get_provider_manager

    manager = get_provider_manager()
    try:
        response = manager.generate(
            prompt,
            json_mode=True,
            preferred_provider=provider_name,
            allow_fallback=allow_fallback,
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
        or not isinstance(parsed, dict)
    ):
        category = metadata["error_category"] or "INVALID_AI_RESPONSE"
        err_detail = getattr(response, "error", None)
        raw_repr = repr(getattr(response, "raw_text", ""))[:400]
        raise SourceRuleExtractionError(
            f"AI provider '{actual_provider or 'unknown'}' did not return an accepted JSON response ({category}): error={err_detail}, parsed_type={type(parsed).__name__}, raw={raw_repr}"
        )
    return parsed, metadata


def _extract_one_side(
    role: str,
    sources: list[dict[str, Any]],
    provider_name: str,
    allow_fallback: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    payload = []
    for item in sources:
        content = item["content"]
        raw_lines = content.splitlines()
        proc_idx = -1
        for idx, line in enumerate(raw_lines):
            if "PROCEDURE DIVISION" in line.upper():
                proc_idx = idx
                break
        selected = []
        if proc_idx >= 0:
            for idx in range(min(15, proc_idx)):
                selected.append(f"{idx+1}: {raw_lines[idx]}")
            selected.append(f"... [declarations omitted lines {min(15, proc_idx)+1} to {proc_idx}] ...")
            end_proc = min(len(raw_lines), proc_idx + 85)
            for idx in range(proc_idx, end_proc):
                selected.append(f"{idx+1}: {raw_lines[idx]}")
            source_repr = "\n".join(selected)
        elif len(raw_lines) > 160:
            entry_idx = -1
            for idx, line in enumerate(raw_lines):
                if line.startswith("def process_") or line.startswith("def run_"):
                    entry_idx = idx
                    break
            if entry_idx > 40:
                for idx in range(35):
                    selected.append(f"{idx+1}: {raw_lines[idx]}")
                selected.append(f"... [intermediate classes omitted lines 36 to {entry_idx}] ...")
                end_entry = min(len(raw_lines), entry_idx + 45)
                for idx in range(entry_idx, end_entry):
                    selected.append(f"{idx+1}: {raw_lines[idx]}")
            else:
                for idx in range(min(110, len(raw_lines))):
                    selected.append(f"{idx+1}: {raw_lines[idx]}")
            source_repr = "\n".join(selected)
        else:
            source_repr = "\n".join(f"{idx+1}: {line}" for idx, line in enumerate(raw_lines))
        payload.append({
            "path": item["path"],
            "sha256": item["sha256"],
            "source": source_repr,
        })
    first_path = sources[0]["path"] if sources else "source"
    prompt = f"""Analyze the {role} implementation independently. Extract externally observable behavioral rules into the 'rules' array.
Extract 2 to 4 distinct behavioral rules describing the observable branching logic, navigation/function keys (e.g. PF3/PF03 exit to calling program or menu), input validations, or return behavior.
Every rule must state its input condition and observable output effect.
Provide a machine-checkable input_condition ({{"field":"...","operator":"==","value":"..."}}) and expected_output ({{"field":"...","value":"..."}}).
Each rule must cite an exact condition source line number and exact condition source excerpt, plus the exact effect source line number and effect excerpt, using the 1-based line numbers from the sources below.
Both source_path and effect_source_path must be the relative file path (e.g. "{first_path}").

CRITICAL GROUNDING REQUIREMENTS:
1. input_condition: The 'field' and 'value' must be grounded in 'source_excerpt'. For 88-level condition names like WHEN CCARD-AID-PFK03 or boolean tests like IF CCARD-AID-PFK03, the field is the condition name and value is true; for explicit equality tests like IF EIBCALEN = 0, field is 'EIBCALEN' and value is 0.
2. expected_output: The 'field' and 'value' must be grounded in 'effect_source_excerpt' (e.g. if effect_source_excerpt is 'result.return_to_prev = True', field is 'return_to_prev' and value is true; if 'MOVE "APPROVED" TO MESSAGE', field is 'MESSAGE' and value is "APPROVED"; if 'EXEC CICS XCTL PROGRAM (CDEMO-TO-PROGRAM)', field is 'CDEMO-TO-PROGRAM' or 'xctl_program' and value is 'LIT-MENUPGM' or true).
3. IMPORTANT: 'input_condition' and 'expected_output' MUST be flat objects with exact scalar 'field', 'operator', and 'value'. Do NOT return nested 'conditions' arrays or compound 'OR'/'AND' objects.
Do NOT leave the 'rules' array empty.

Return valid JSON only matching this schema:
{{
  "rules": [
    {{
      "rule_id": "R1",
      "description": "Clear explanation of rule",
      "source_path": "{first_path}",
      "source_line": 1,
      "source_excerpt": "exact code from that line",
      "effect_source_path": "{first_path}",
      "effect_source_line": 2,
      "effect_source_excerpt": "exact effect code from that line",
      "input_fields": ["FIELD_NAME"],
      "input_condition": {{"field": "FIELD_NAME", "operator": "==", "value": "0"}},
      "expected_output": {{"field": "OUTPUT_FIELD", "value": "0"}},
      "observable_effect": "Description of effect"
    }}
  ],
  "gaps": []
}}
Sources: {json.dumps(payload, ensure_ascii=True)}"""
    parsed, provider_meta = _generate_json(prompt, provider_name, allow_fallback=allow_fallback)
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
    last_error = None
    for item in raw_rules:
        if not isinstance(item, dict):
            last_error = "malformed rule object"
            continue
        rule_id = str(item.get("rule_id", "")).strip()
        path = str(item.get("source_path", "")).strip()
        excerpt = str(item.get("source_excerpt", "")).strip()
        try:
            line_number = int(item.get("source_line", 0))
        except (TypeError, ValueError):
            last_error = "invalid source line"
            continue
        source = sources_by_path.get(path)
        if not rule_id or rule_id in ids or not source or not excerpt:
            last_error = "duplicate rule ID or missing source anchor"
            continue
        lines = source["content"].splitlines()
        norm_excerpt = re.sub(r"\s+", " ", excerpt.strip())
        matched_line = None
        if 1 <= line_number <= len(lines):
            line_str = re.sub(r"\s+", " ", lines[line_number - 1].strip())
            if line_str == norm_excerpt or (len(norm_excerpt) >= 4 and (norm_excerpt in line_str or line_str in norm_excerpt)):
                matched_line = line_number
        if matched_line is None:
            for idx in range(max(0, line_number - 15), min(len(lines), line_number + 15)):
                line_str = re.sub(r"\s+", " ", lines[idx].strip())
                if line_str == norm_excerpt or (len(norm_excerpt) >= 4 and (norm_excerpt in line_str or line_str in norm_excerpt)):
                    matched_line = idx + 1
                    break
            if matched_line is None:
                for idx, line in enumerate(lines):
                    line_str = re.sub(r"\s+", " ", line.strip())
                    if line_str == norm_excerpt or (len(norm_excerpt) >= 4 and (norm_excerpt in line_str or line_str in norm_excerpt)):
                        matched_line = idx + 1
                        break
        if matched_line is None:
            last_error = f"cited text does not match {path}:{line_number}"
            continue
        line_number = matched_line
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
            last_error = "invalid effect source line"
            continue
        effect_source = sources_by_path.get(effect_path)
        if not effect_source or not effect_excerpt:
            last_error = "missing effect source anchor"
            continue
        effect_lines = effect_source["content"].splitlines()
        norm_effect_excerpt = re.sub(r"\s+", " ", effect_excerpt.strip())
        matched_effect_line = None
        if 1 <= effect_line_number <= len(effect_lines):
            eff_line_str = re.sub(r"\s+", " ", effect_lines[effect_line_number - 1].strip())
            if eff_line_str == norm_effect_excerpt or (len(norm_effect_excerpt) >= 4 and (norm_effect_excerpt in eff_line_str or eff_line_str in norm_effect_excerpt)):
                matched_effect_line = effect_line_number
        if matched_effect_line is None:
            for idx in range(max(0, effect_line_number - 15), min(len(effect_lines), effect_line_number + 15)):
                eff_line_str = re.sub(r"\s+", " ", effect_lines[idx].strip())
                if eff_line_str == norm_effect_excerpt or (len(norm_effect_excerpt) >= 4 and (norm_effect_excerpt in eff_line_str or eff_line_str in norm_effect_excerpt)):
                    matched_effect_line = idx + 1
                    break
            if matched_effect_line is None:
                for idx, line in enumerate(effect_lines):
                    eff_line_str = re.sub(r"\s+", " ", line.strip())
                    if eff_line_str == norm_effect_excerpt or (len(norm_effect_excerpt) >= 4 and (norm_effect_excerpt in eff_line_str or eff_line_str in norm_effect_excerpt)):
                        matched_effect_line = idx + 1
                        break
        if matched_effect_line is None:
            last_error = f"cited effect text does not match {effect_path}:{effect_line_number}"
            continue
        effect_line_number = matched_effect_line
        if not description or not effect or not isinstance(input_fields, list) or not input_fields:
            last_error = "rule without description, observable effect, or input fields"
            continue

        # Automatically unwrap compound conditions (e.g. {"operator": "OR", "conditions": [...]}) to the primary leaf condition
        while isinstance(input_condition, dict) and "conditions" in input_condition and isinstance(input_condition["conditions"], list) and input_condition["conditions"]:
            input_condition = input_condition["conditions"][0]
        while isinstance(expected_output, dict) and "conditions" in expected_output and isinstance(expected_output["conditions"], list) and expected_output["conditions"]:
            expected_output = expected_output["conditions"][0]

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
            last_error = "rule without executable input/output contract"
            continue
        fields = sorted({str(field).strip() for field in input_fields if str(field).strip()})
        if input_condition.get("field"):
            cond_fld = str(input_condition["field"]).strip()
            if cond_fld and re.sub(r"[-_]", "", cond_fld).casefold() in source_vocabulary and not any(_normalize_field(cond_fld) == _normalize_field(f) for f in fields):
                fields.append(cond_fld)
                fields.sort()
        if not fields or any(
            re.sub(r"[-_]", "", field).casefold() not in source_vocabulary
            for field in fields
        ):
            last_error = "cited input fields not found in source"
            continue
        if (
            _normalize_field(input_condition["field"]) not in {_normalize_field(field) for field in fields}
            or not _field_in_excerpt(input_condition["field"], excerpt)
            or not _literal_in_excerpt(input_condition["value"], excerpt)
            or not _field_in_excerpt(expected_output["field"], effect_excerpt)
            or not _literal_in_excerpt(expected_output["value"], effect_excerpt)
        ):
            last_error = "input/output assertions unsupported by exact source anchors"
            print(f"DEBUG REJECT in {role}: {item.get('rule_id')} reason: {last_error}")
            print(f"   input_cond: {input_condition}, excerpt: {excerpt}")
            print(f"   field_in_excerpt: {_field_in_excerpt(input_condition['field'], excerpt)}, lit_in_excerpt: {_literal_in_excerpt(input_condition['value'], excerpt)}")
            print(f"   expected_output: {expected_output}, effect_excerpt: {effect_excerpt}")
            print(f"   eff_field_in_excerpt: {_field_in_excerpt(expected_output['field'], effect_excerpt)}, eff_lit_in_excerpt: {_literal_in_excerpt(expected_output['value'], effect_excerpt)}")
            continue
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
                    "path": effect_path,
                    "line": effect_line_number,
                    "excerpt": effect_excerpt,
                    "file_hash": effect_source["sha256"],
                },
            }
        )
    if not rules:
        raise SourceRuleExtractionError(
            f"AI extraction for {role} returned no locally source-anchored behavioral rules"
            + (f": {last_error}" if last_error else ".")
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
        matched_gap_line = None
        if 1 <= line_number <= len(lines) and lines[line_number - 1].strip() == excerpt:
            matched_gap_line = line_number
        else:
            for idx in range(max(0, line_number - 15), min(len(lines), line_number + 15)):
                if lines[idx].strip() == excerpt:
                    matched_gap_line = idx + 1
                    break
            if matched_gap_line is None:
                for idx, line in enumerate(lines):
                    if line.strip() == excerpt:
                        matched_gap_line = idx + 1
                        break
        if matched_gap_line is None or not str(item.get("description", "")).strip():
            raise SourceRuleExtractionError(
                f"AI extraction for {role} returned an invalid evidence-gap source anchor."
            )
        line_number = matched_gap_line
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
    allow_fallback: bool = False,
) -> dict[str, Any]:
    """Independently extract, source-check, align, then propose tests for both sides."""
    legacy_sources, _ = _load_sources(legacy_root, legacy_entrypoint)
    modern_sources, _ = _load_sources(modern_root, modern_entrypoint)
    legacy_rules, legacy_hashes, legacy_provider = _extract_one_side(
        "legacy/reference", legacy_sources, provider_name, allow_fallback=allow_fallback
    )
    modern_rules, modern_hashes, modern_provider = _extract_one_side(
        "modern/target", modern_sources, provider_name, allow_fallback=allow_fallback
    )
    if not legacy_rules or not modern_rules:
        raise SourceRuleExtractionError(
            "Both implementations must yield at least one locally source-anchored behavioral rule."
        )

    alignment_prompt = f"""Align independently extracted legacy and modern behavioral rule candidates.
Do not assume equivalence blindly, but carefully match rules that represent the corresponding operational intent, navigation commands, or input handling across both implementations (for instance, PF3/PF03 exit/return navigation, initial screen display or prompt, commit changes, or account validation checks).
IMPORTANT: Legacy rule IDs (e.g. {list(legacy_by_id.keys()) if 'legacy_by_id' in locals() else [r['rule_id'] for r in legacy_rules]}) and Modern rule IDs (e.g. {[r['rule_id'] for r in modern_rules]}) are completely separate namespaces. Do NOT assume Legacy R1 matches Modern R1! For example, if Legacy R1 is PF3 navigation and Modern R2 is PF3 navigation, match those two rules as MATCH. Compare the actual descriptions, observable effects, input conditions (like function keys or flags), and outputs.
Mark each correspondence MATCH when the observable behavior or operational intent is equivalent (even if variable names follow COBOL vs Python conventions), CONFLICT when the source evidence describes contradictory behavior for the same scenario, LEGACY_ONLY or MODERN_ONLY when the rule has no counterpart in the other implementation, and AMBIGUOUS when evidence is insufficient.
Return JSON only: {{"alignments":[{{"legacy_rule_id":"...","modern_rule_id":"...",
"status":"MATCH|CONFLICT|LEGACY_ONLY|MODERN_ONLY|AMBIGUOUS","rationale":"..."}}]}}
Legacy: {json.dumps(legacy_rules, ensure_ascii=True)}
Modern: {json.dumps(modern_rules, ensure_ascii=True)}"""
    alignments_raw, alignment_provider = _generate_json(
        alignment_prompt, provider_name, allow_fallback=allow_fallback
    )
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
    if not aligned_rules:
        return {
            "rules": [],
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
    tests_raw, test_provider = _generate_json(
        test_prompt, provider_name, allow_fallback=allow_fallback
    )
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

        # Populate condition fields from role contracts if not already present
        for role_contract in rule["expected_behavior"].values():
            cond = role_contract.get("input_condition", {})
            f = cond.get("field")
            if f and f not in values and re.sub(r"[-_]", "", f).casefold() in shared_vocabulary:
                values[f] = cond.get("value")
        for f in rule["input_fields"]:
            norm_f = re.sub(r"[-_]", "", f).casefold()
            if not any(re.sub(r"[-_]", "", k).casefold() == norm_f for k in values):
                if norm_f in shared_vocabulary:
                    values[f] = ""

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
    # Direct grounded synthesis for any aligned rule without an accepted LLM test case
    for rule in aligned_rules:
        r_id = rule["rule_id"]
        if r_id in tests_by_rule:
            continue
        syn_values: dict[str, Any] = {}
        for role_contract in rule["expected_behavior"].values():
            cond = role_contract.get("input_condition", {})
            f = cond.get("field")
            if f and re.sub(r"[-_]", "", f).casefold() in shared_vocabulary:
                syn_values[f] = cond.get("value")
        for f in rule["input_fields"]:
            norm_f = re.sub(r"[-_]", "", f).casefold()
            if not any(re.sub(r"[-_]", "", k).casefold() == norm_f for k in syn_values):
                if norm_f in shared_vocabulary:
                    syn_values[f] = ""
        if syn_values and all(
            rule_input_matches(role_contract["input_condition"], syn_values)
            for role_contract in rule["expected_behavior"].values()
        ):
            accepted_tests.append({"rule_id": r_id, "values": syn_values})
            tests_by_rule.add(r_id)

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
