#!/usr/bin/env python3
"""Deterministic model/effort advice and evidence-gated outcome registry."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
DEFAULT_POLICY = HERE.parent / "references" / "policy.json"
VALID_MODELS = {
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-6-luna",
    "gpt-6-sol",
    "gpt-6-astra",
}
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
LEGACY_GPT_5_6_EFFORTS = {"low", "medium", "high", "max", "ultra"}
MODEL_EFFORTS = {
    "gpt-5.6-luna": LEGACY_GPT_5_6_EFFORTS,
    "gpt-5.6-terra": LEGACY_GPT_5_6_EFFORTS,
    "gpt-5.6-sol": LEGACY_GPT_5_6_EFFORTS,
    "gpt-6-luna": {"low", "medium", "high", "xhigh", "max"},
    "gpt-6-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-6-astra": {"low", "medium", "high", "xhigh", "max", "ultra"},
}
MODEL_VERSIONS = {
    "gpt-5.6-luna": "gpt-5.6",
    "gpt-5.6-terra": "gpt-5.6",
    "gpt-5.6-sol": "gpt-5.6",
    "gpt-6-luna": "gpt-6",
    "gpt-6-sol": "gpt-6",
    "gpt-6-astra": "gpt-6",
}
AUTOMATIC_FORBIDDEN_EFFORTS = {"xhigh", "max", "ultra"}
STATIC_MODEL_EFFORTS = {
    ("gpt-6-luna", "medium"),
    ("gpt-6-sol", "medium"),
    ("gpt-6-sol", "high"),
}
AUTOMATIC_MODEL_EFFORTS = {
    *STATIC_MODEL_EFFORTS,
    ("gpt-6-astra", "low"),
    ("gpt-6-astra", "medium"),
    ("gpt-6-astra", "high"),
}
VALID_OUTCOMES = {"verified_pass", "verified_fail", "partial"}
VALID_DISPATCH_MODES = {
    "native_custom_agent",
    "codex_exec",
    "main_task_fallback",
    "main_task_direct",
}
VALID_PHASES = {"plan", "build", "test", "qa"}
MODEL_AGENTS = {
    ("gpt-6-luna", "medium"): "pas_luna_worker",
    ("gpt-6-sol", "medium"): "pas_sol_worker",
    ("gpt-6-sol", "high"): "pas_sol_analyst",
    ("gpt-6-sol", "max"): "pas_sol_max_worker",
    ("gpt-6-astra", "low"): "pas_astra_low_worker",
    ("gpt-6-astra", "medium"): "pas_astra_medium_worker",
    ("gpt-6-astra", "high"): "pas_astra_high_worker",
}
LEGACY_RECORD_AGENTS = {
    ("gpt-5.6-luna", "medium"): "pas_luna_worker",
    ("gpt-5.6-terra", "medium"): "pas_terra_worker",
    ("gpt-5.6-terra", "high"): "pas_terra_builder",
    ("gpt-5.6-sol", "high"): "pas_sol_analyst",
    ("gpt-5.6-sol", "max"): "pas_sol_max_worker",
}
SANDBOX_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "danger-full-access": 2,
}
VALID_APPROVAL_POLICIES = {"untrusted", "on-failure", "on-request", "never"}
ESCALATION_CHAIN = {
    ("gpt-6-luna", "medium"): ("gpt-6-sol", "medium"),
    ("gpt-6-sol", "medium"): ("gpt-6-sol", "high"),
    ("gpt-6-sol", "high"): ("gpt-6-astra", "low"),
    ("gpt-6-astra", "low"): ("gpt-6-astra", "medium"),
    ("gpt-6-astra", "medium"): ("gpt-6-astra", "high"),
}
ALLOWED_RECORD_FIELDS = {
    "recorded_at",
    "task_family",
    "axes",
    "model",
    "effort",
    "outcome",
    "verification_command",
    "verification_result",
    "model_version",
    "policy_version",
    "session_id",
    "failure_type",
    "note",
    "phase",
    "agent_name",
    "dispatch_mode",
}
REQUIRED_RECORD_FIELDS = {
    "task_family",
    "axes",
    "model",
    "effort",
    "outcome",
    "model_version",
    "policy_version",
    "session_id",
}


def default_registry_path(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    explicit = values.get("CODEX_MODEL_ROUTER_REGISTRY", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    for parent in (HERE, *HERE.parents):
        harness = parent / "Harness"
        if harness.is_dir():
            return harness / "sink" / "model_effort_router" / "outcomes.jsonl"
    return Path.home() / ".codex" / "state" / "codex-model-router" / "outcomes.jsonl"


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"policy_version", "model_version", "rules", "fallback", "ultra"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"policy missing fields: {sorted(missing)}")
    return data


def _contains_any(text: str, signals: tuple[str, ...]) -> bool:
    return any(re.search(r"\b" + re.escape(signal) + r"\b", text) for signal in signals)


def _semantic_task_scope(task_text: str) -> tuple[str, bool]:
    """Return execution-relevant prose and explicit acceptance evidence.

    Markdown headings provide the semantic boundary. Validation, paths, and
    workstreams are intentionally handled by their dedicated parsers instead.
    """
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    current: dict[str, Any] | None = None
    fence_marker: str | None = None
    for line in task_text.splitlines():
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)[0]
            fence_marker = None if fence_marker == marker else marker
            continue
        if fence_marker:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            current = {
                "level": level,
                "title": title,
                "parents": tuple(stack),
                "lines": [],
            }
            sections.append(current)
            stack.append((level, title))
        elif current is not None:
            current["lines"].append(line)

    if not sections:
        return task_text, False

    def normalized(value: str) -> str:
        value = re.sub(r"[`*_]", "", value.lower())
        return re.sub(r"\s+", " ", value).strip(" :-")

    def is_execution_heading(value: str) -> bool:
        name = normalized(value)
        return any(
            name == candidate or name.startswith(candidate + ":")
            for candidate in (
                "objective",
                "required behavior",
                "acceptance",
                "acceptance criteria",
                "implementation",
                "implementation requirements",
                "requirements",
                "scope",
                "scope requirements",
            )
        )

    def is_acceptance_heading(value: str) -> bool:
        name = normalized(value)
        return name in {
            "required behavior",
            "requirements",
            "acceptance",
            "acceptance criteria",
        }

    def is_excluded_heading(value: str) -> bool:
        name = normalized(value)
        return bool(
            re.search(r"\b(?:tests?|validation|checks?|non[- ]goals?|examples?)\b", name)
            or re.fullmatch(r"(?:classifier\s+)?signals?(?:\s+documentation)?", name)
            or re.fullmatch(r"classifier\s+rules?(?:\s+documentation)?", name)
            or re.search(r"\b(?:completion|reporting?|commit)\b", name)
            or re.search(r"\b(?:allowed|mutable)\s+paths?\b", name)
            or re.search(r"\bworkstreams?\b", name)
        )

    def semantic_rule_text(value: str) -> str:
        """Remove an explicit axis mapping while retaining genuine work prose."""
        line = normalized(value)
        mapping = re.search(
            r"=>[^\n]*(?:failcost|depth(?:\s+(?:floor|at least))?|architecture depth)",
            line,
        )
        if not mapping:
            return value
        prefix = value.split("=>", 1)[0]
        if prefix.lstrip().startswith(("-", "*")):
            return ""
        if ";" in prefix:
            prefix = prefix.rsplit(";", 1)[0]
        if re.search(
            r"\b(?:implement|enforce|protect|prevent|add|update|change|fix|preserve|retain|require)\b",
            prefix,
            flags=re.IGNORECASE,
        ):
            return prefix
        return ""

    def is_meta_label_or_path(value: str) -> bool:
        line = normalized(value)
        if re.match(
            r"^(?:tests?|validation|checks?|non[- ]goals?|examples?|signals?|"
            r"completion|reporting?|commit)\s*:",
            line,
        ):
            return True
        return bool(re.match(r"^\s*-\s+`?[^`\s]+`?\s*$", value)) and (
            "/" in value or "." in value
        )

    acceptance = any(
        is_acceptance_heading(section["title"])
        and not any(
            is_excluded_heading(title)
            for level, title in section["parents"]
        )
        for section in sections
    )
    semantic_lines: list[str] = []
    for section in sections:
        ancestry = (*section["parents"], (section["level"], section["title"]))
        if any(is_excluded_heading(title) for level, title in ancestry):
            continue
        selected = section["level"] == 1 or any(
            is_execution_heading(title) for _, title in ancestry
        )
        if not selected:
            continue
        for candidate in [section["title"], *section["lines"]]:
            semantic_line = semantic_rule_text(candidate)
            if semantic_line.strip() and not is_meta_label_or_path(semantic_line):
                semantic_lines.append(semantic_line)
    return "\n".join(semantic_lines), acceptance


def _has_validation_evidence(task_text: str) -> bool:
    """Prefer an executable-looking validation section over prose mentions."""
    sections: dict[str, list[str]] = {"validation": [], "test": [], "check": []}
    seen_sections: set[str] = set()
    current: str | None = None
    section_level: int | None = None
    for line in task_text.splitlines():
        heading = re.match(
            r"^(#{1,6})\s+(validation|tests?|checks?)\b", line, flags=re.IGNORECASE
        )
        if heading:
            name = heading.group(2).lower()
            current = (
                "validation"
                if name == "validation"
                else "test"
                if name.startswith("test")
                else "check"
            )
            section_level = len(heading.group(1))
            seen_sections.add(current)
            continue
        other_heading = re.match(r"^(#{1,6})\s+", line)
        if other_heading and current and len(other_heading.group(1)) <= (section_level or 6):
            current = None
            section_level = None
        elif current and not other_heading:
            sections[current].append(line)
    section_lines = (
        sections["validation"]
        if "validation" in seen_sections
        else sections["test"]
        if "test" in seen_sections
        else sections["check"]
    )
    command_patterns = (
        re.compile(
            r"^python\d*\s+(?:-m\s+(?:unittest|pytest|compileall|py_compile|doctest|mypy|ruff)"
            r"(?:\s|$)|\S+\.py(?:\s|$))"
        ),
        re.compile(r"^pytest(?:\s|$)"),
        re.compile(
            r"^npm\s+(?:test|run\s+(?:test|lint|typecheck|check|build|validate)|"
            r"exec\s+(?:pytest|eslint|tsc))(?:\s|$)"
        ),
        re.compile(r"^go\s+(?:test|vet|build)\b"),
        re.compile(r"^cargo\s+(?:test|check|clippy|build)\b"),
        re.compile(r"^make(?:\s|$)"),
        re.compile(r"^git\s+diff\b.*--check\b"),
        re.compile(r"^(?:bash|sh)\s+\S+"),
        re.compile(r"^\./\S+"),
    )
    for line in section_lines:
        candidate = re.sub(r"^\s*(?:[-*]\s+)?(?:\$\s+)?", "", line.lower())
        candidate = candidate.strip()
        if candidate.startswith("`") and candidate.endswith("`"):
            candidate = candidate[1:-1].strip()
        if _contains_any(
            candidate,
            (
                "manual review",
                "unavailable",
                "not available",
                "not installed",
                "do not run",
                "no deterministic validation",
                "without validation",
                "will not be run",
                "would not be run",
                "won't be run",
            ),
        ) or re.search(
            r"\b(?:will|would|should|must|may|can|could)\s+not\b", candidate
        ):
            continue
        if re.match(r"^pytest\s+(?:--version|--help)(?:\s|$)", candidate):
            continue
        if any(pattern.match(candidate) for pattern in command_patterns):
            return True
    return False


def _task_card_paths(task_text: str) -> list[str]:
    """Return path bullets, preferring an explicit allowed/mutable-path section."""
    lines = task_text.splitlines()
    scoped_lines: list[str] = []
    in_scope = False
    found_scope = False
    for line in lines:
        if re.match(
            r"^#{1,6}\s+(allowed|mutable)\s+paths?\b", line, flags=re.IGNORECASE
        ):
            in_scope = True
            found_scope = True
            continue
        if in_scope and re.match(r"^#{1,6}\s+", line):
            break
        if in_scope:
            scoped_lines.append(line)

    paths = []
    for line in scoped_lines if found_scope else lines:
        match = re.match(r"^\s*-\s+`?([^`\s]+)`?\s*$", line)
        if match and ("/" in match.group(1) or "." in match.group(1)):
            paths.append(match.group(1))
    return paths


def _named_independent_workstreams(task_text: str) -> int:
    """Count named entries only in an explicitly independent Workstreams section."""
    lines = task_text.splitlines()
    in_workstreams = False
    section: list[str] = []
    for line in lines:
        if re.match(r"^#{1,6}\s+.*\bworkstreams?\b", line, flags=re.IGNORECASE):
            in_workstreams = True
            section.append(line)
            continue
        if in_workstreams and re.match(r"^#{1,6}\s+", line):
            break
        if in_workstreams:
            section.append(line)
    section_text = "\n".join(section).lower()
    negated_independence = re.search(
        r"\b(?:no|not|cannot|can't|isn't|aren't|without)\b[^\n]{0,40}"
        r"\b(?:independent|independently|parallel)\b|\bnon[- ]independent\b",
        section_text,
    )
    if not section or negated_independence or _contains_any(section_text, ("sequential",)):
        return 1
    independently_verifiable = _contains_any(
        section_text,
        (
            "independently verifiable",
            "independent and verifiable",
            "parallel and verifiable",
        ),
    )
    if not independently_verifiable or _contains_any(
        section_text,
        (
            "subjective review",
            "manual review",
            "manually",
            "no deterministic checks",
            "no automated checks",
            "no automated validation",
            "not verifiable",
            "independent checks are impossible",
            "depend on each other",
        ),
    ):
        return 1
    entries = [
        line for line in section[1:]
        if re.match(r"^(?:-|\d+[.)])\s+\S.+", line)
    ]
    return len(entries) if len(entries) >= 2 else 1


def classify_task_text(task_text: str) -> dict[str, Any]:
    """Classify one task card with local, reviewable signals only.

    The returned reasons are stable signal labels; task prose is intentionally
    never copied into the result.
    """
    if not isinstance(task_text, str) or not task_text.strip():
        raise ValueError("task text must be a non-empty string")
    semantic_text, acceptance = _semantic_task_scope(task_text)
    text = semantic_text.lower()
    reasons: list[str] = []
    paths = _task_card_paths(task_text)
    path_roots = {path.split("/", 1)[0] for path in paths}

    validation = _has_validation_evidence(task_text)
    sensitive = _contains_any(
        text,
        (
            "security", "auth", "authentication", "credential", "credentials", "tenant",
            "privacy", "deletion", "destructive migration", "migration", "remediation", "external-write",
            "external write",
        ),
    )
    concurrent = _contains_any(text, ("concurrency", "concurrent", "race", "distributed", "invariant"))
    architectural = _contains_any(text, ("architecture", "architectural", "cross-cutting", "cross package", "cross-package"))
    docs_or_config = bool(paths) and all(
        path.endswith((".md", ".rst", ".txt", ".toml", ".yaml", ".yml", ".json", ".ini"))
        for path in paths
    )

    if sensitive:
        task_family = "security-sensitive-change" if _contains_any(text, ("security", "auth", "credential", "tenant", "privacy")) else "migration-or-remediation"
        failcost = "high"
        reasons.append("sensitive-change-floor")
    elif docs_or_config:
        task_family = "documentation-or-config-change"
        failcost = "low"
        reasons.append("docs-config-only-scope")
    elif concurrent:
        task_family = "concurrency-change"
        failcost = "mid"
        reasons.append("concurrency-depth-floor")
    else:
        task_family = "bounded-implementation"
        failcost = "mid"

    depth = "shallow" if docs_or_config else "medium"
    volume = "low" if docs_or_config else "mid"
    if concurrent and depth == "shallow":
        depth = "medium"
    if concurrent and depth == "medium":
        reasons.append("concurrency-depth-floor") if "concurrency-depth-floor" not in reasons else None
    if len(paths) >= 4 or len(path_roots) >= 2:
        if depth == "shallow":
            depth = "medium"
        if volume == "low":
            volume = "mid"
        reasons.append("mutable-path-spread")
    if architectural and (len(paths) >= 2 or len(path_roots) >= 2):
        depth = "deep"
        reasons.append("architecture-depth-floor")
    elif len(paths) >= 8 or len(path_roots) >= 4:
        volume = "high"
        reasons.append("large-mutable-scope")

    if validation:
        verifiable = "yes" if acceptance else "partial"
        reasons.append("deterministic-validation")
    else:
        verifiable = "partial" if acceptance else "no"
        reasons.append("validation-missing")

    workstreams = _named_independent_workstreams(task_text)
    if workstreams >= 2:
        reasons.append("independent-workstreams")
    decomposable = "yes" if workstreams >= 2 else "no"

    confidence = "high" if validation and acceptance and paths else "medium" if validation or acceptance else "low"
    if not paths:
        confidence = "low"
        reasons.append("mutable-scope-missing")
    if not acceptance:
        reasons.append("acceptance-ambiguous")
    if confidence == "low":
        # Ambiguity must not create a cheaper recommendation downstream.
        verifiable = "partial" if verifiable == "yes" else verifiable
        failcost = "high" if failcost == "high" else "mid"
        volume = "mid" if volume == "low" else volume
        depth = "medium" if depth == "shallow" else depth
        reasons.append("low-confidence-conservative-fallback")

    return {
        "task_family": task_family,
        "verifiable": verifiable,
        "failcost": failcost,
        "volume": volume,
        "depth": depth,
        "decomposable": decomposable,
        "workstreams": workstreams,
        "confidence": confidence,
        "reasons": sorted(set(reasons)),
    }


def classify_task_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("task file must be an existing regular file")
    try:
        task_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("task file must be UTF-8 text") from error
    if not re.search(r"^#{1,6}\s+", task_text, flags=re.MULTILINE):
        raise ValueError("task file must contain a structured heading")
    return classify_task_text(task_text)


def _matches(rule_match: Mapping[str, list[Any]], axes: Mapping[str, Any]) -> bool:
    return all(axes.get(key) in allowed for key, allowed in rule_match.items())


def recommend(
    policy: Mapping[str, Any],
    *,
    task_family: str,
    axes: Mapping[str, Any],
) -> dict[str, Any]:
    selected = policy["fallback"]
    for rule in policy["rules"]:
        if _matches(rule.get("match", {}), axes):
            selected = rule
            break

    selected_combo = (str(selected["model"]), str(selected["effort"]))
    if selected["effort"] in AUTOMATIC_FORBIDDEN_EFFORTS:
        raise ValueError("static policy must not automatically select xhigh, max, or ultra")
    if selected_combo not in STATIC_MODEL_EFFORTS:
        raise ValueError("static policy selected an unsupported automatic model and effort")

    ultra = policy["ultra"]
    ultra_eligible = (
        axes.get("decomposable") == ultra["required_decomposable"]
        and int(axes.get("workstreams", 0)) >= int(ultra["minimum_workstreams"])
        and axes.get("depth") == ultra["required_depth"]
        and axes.get("failcost") == ultra["required_failcost"]
    )
    return {
        "task_family": task_family,
        "axes": dict(axes),
        "model": selected["model"],
        "effort": selected["effort"],
        "rule_id": selected["id"],
        "escalation": selected["escalation"],
        "ultra_eligible": ultra_eligible,
        "ultra_note": ultra["note"],
        "model_version": policy["model_version"],
        "policy_version": policy["policy_version"],
    }


def current_session(env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if env is None else env
    for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_TASK_ID"):
        value = values.get(key, "").strip()
        if value:
            return {"session_id": value, "source": f"env:{key}"}
    return {"session_id": "unknown", "source": "unavailable"}


def select_dispatch_mode(
    native_agent_available: bool,
    codex_exec_available: bool,
) -> str:
    if native_agent_available:
        return "native_custom_agent"
    if codex_exec_available:
        return "codex_exec"
    return "main_task_fallback"


def build_dispatch(
    recommendation: Mapping[str, Any],
    *,
    phase: str,
    task_scope: str,
    parent_sandbox: str | None = None,
    exec_sandbox: str | None = None,
    parent_approval_policy: str | None = None,
    approval_boundary_confirmed: bool = False,
) -> dict[str, Any]:
    model = str(recommendation["model"])
    effort = str(recommendation["effort"])
    dispatch_blocked = bool(recommendation.get("dispatch_blocked"))
    dispatch_required = task_scope != "micro" and not dispatch_blocked
    boundary_known = parent_sandbox in SANDBOX_RANK and exec_sandbox in SANDBOX_RANK
    sandbox_safe = boundary_known and SANDBOX_RANK[str(exec_sandbox)] <= SANDBOX_RANK[str(parent_sandbox)]
    approval_policy_known = parent_approval_policy in VALID_APPROVAL_POLICIES
    codex_exec_ready = bool(
        dispatch_required
        and sandbox_safe
        and approval_policy_known
        and approval_boundary_confirmed
    )
    if not approval_boundary_confirmed:
        codex_exec_blocker = "approval boundary is not explicitly confirmed"
    elif not approval_policy_known:
        codex_exec_blocker = "parent approval policy must be explicit"
    elif not boundary_known:
        codex_exec_blocker = "parent and child sandbox modes must be explicit"
    elif not sandbox_safe:
        codex_exec_blocker = "child sandbox must be the same or stricter than the parent sandbox"
    else:
        codex_exec_blocker = ""
    fallback_command = None
    if codex_exec_ready:
        fallback_command = [
            "codex",
            "exec",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-c",
            f'approval_policy="{parent_approval_policy}"',
            "--sandbox",
            str(exec_sandbox),
            "--json",
        ]
    return {
        **recommendation,
        "phase": phase,
        "task_scope": task_scope,
        "agent_name": MODEL_AGENTS.get((model, effort)),
        "native_custom_agent_ready": (model, effort) in MODEL_AGENTS and not dispatch_blocked,
        "dispatch_required": dispatch_required,
        "dispatch_blocked": dispatch_blocked,
        "dispatch_mode": "main_task_direct" if task_scope == "micro" else None,
        "codex_exec_ready": codex_exec_ready,
        "codex_exec_blocker": codex_exec_blocker,
        "parent_sandbox": parent_sandbox,
        "exec_sandbox": exec_sandbox,
        "parent_approval_policy": parent_approval_policy,
        "allowed_dispatch_modes": [
            "native_custom_agent",
            "codex_exec",
            "main_task_fallback",
        ],
        "fallback_command": fallback_command,
    }


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def append_record(
    path: Path,
    record: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    unsupported = set(record) - ALLOWED_RECORD_FIELDS
    if unsupported:
        raise ValueError(f"unsupported record fields: {sorted(unsupported)}")
    missing = REQUIRED_RECORD_FIELDS - set(record)
    if missing:
        raise ValueError(f"record missing fields: {sorted(missing)}")
    if record["model"] not in VALID_MODELS:
        raise ValueError(f"unsupported model: {record['model']}")
    expected_model_version = MODEL_VERSIONS[str(record["model"])]
    if record["model_version"] != expected_model_version:
        raise ValueError(
            f"model_version {record['model_version']!r} does not match "
            f"model {record['model']!r} ({expected_model_version!r})"
        )
    if record["effort"] not in VALID_EFFORTS:
        raise ValueError(f"unsupported effort: {record['effort']}")
    if record["effort"] not in MODEL_EFFORTS[str(record["model"])]:
        raise ValueError(
            f"unsupported effort {record['effort']!r} for model {record['model']!r}"
        )
    if record["outcome"] not in VALID_OUTCOMES:
        raise ValueError(f"unsupported outcome: {record['outcome']}")
    dispatch_mode = str(record.get("dispatch_mode", "")).strip()
    if dispatch_mode and dispatch_mode not in VALID_DISPATCH_MODES:
        raise ValueError(f"unsupported dispatch mode: {dispatch_mode}")
    phase = str(record.get("phase", "")).strip()
    if dispatch_mode and phase not in VALID_PHASES:
        raise ValueError("dispatch records require a valid phase")
    if dispatch_mode in {"native_custom_agent", "codex_exec"}:
        agent_name = str(record.get("agent_name", "")).strip()
        if not agent_name:
            raise ValueError("external worker dispatch records require agent_name")
        combo = (str(record["model"]), str(record["effort"]))
        expected_agent = MODEL_AGENTS.get(combo) or LEGACY_RECORD_AGENTS.get(combo)
        if expected_agent is None:
            raise ValueError("external worker model and effort have no registered agent_name")
        if agent_name != expected_agent:
            raise ValueError(
                f"agent_name {agent_name!r} does not match model worker {expected_agent!r}"
            )
    if record["outcome"].startswith("verified_") and not (
        str(record.get("verification_command", "")).strip()
        and str(record.get("verification_result", "")).strip()
    ):
        raise ValueError("verified outcomes require verification evidence")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", str(record["task_family"])):
        raise ValueError("task_family must be a non-sensitive hyphen-case label")

    timestamp = now or datetime.now(timezone.utc)
    payload = {key: record[key] for key in ALLOWED_RECORD_FIELDS if key in record}
    payload["recorded_at"] = str(record.get("recorded_at") or timestamp.isoformat())
    payload.setdefault("verification_command", "")
    payload.setdefault("verification_result", "")
    payload.setdefault("failure_type", "")
    payload.setdefault("note", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload


def query_records(
    path: Path,
    *,
    task_family: str,
    model_version: str,
    max_age_days: int,
    axes: Mapping[str, Any] | None = None,
    phase: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=max_age_days)
    matches: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            record = json.loads(line)
            recorded_at = _parse_timestamp(record["recorded_at"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if recorded_at < cutoff:
            continue
        if record.get("task_family") != task_family:
            continue
        if record.get("model_version") != model_version:
            continue
        if phase and record.get("phase") != phase:
            continue
        if axes and any(record.get("axes", {}).get(key) != value for key, value in axes.items()):
            continue
        matches.append(record)
    return sorted(matches, key=lambda item: _parse_timestamp(item["recorded_at"]), reverse=True)


def apply_history(
    recommendation: Mapping[str, Any], records: list[Mapping[str, Any]]
) -> dict[str, Any]:
    result = dict(recommendation)
    target_model_version = result.get(
        "model_version", MODEL_VERSIONS.get(str(result.get("model")))
    )
    generation_records = [
        record
        for record in records
        if MODEL_VERSIONS.get(str(record.get("model"))) == target_model_version
        and record.get("model_version", target_model_version) == target_model_version
    ]
    passes = Counter(
        (record.get("model"), record.get("effort"))
        for record in generation_records
        if record.get("outcome") == "verified_pass"
    )
    failures = {
        (record.get("model"), record.get("effort"))
        for record in generation_records
        if record.get("outcome") == "verified_fail"
    }
    stable = [
        (count, model, effort)
        for (model, effort), count in passes.items()
        if count >= 2
        and (model, effort) in AUTOMATIC_MODEL_EFFORTS
        and (model, effort) in MODEL_AGENTS
        and MODEL_VERSIONS.get(str(model))
        == result.get("model_version", MODEL_VERSIONS.get(str(result.get("model"))))
        and effort not in {"xhigh", "max", "ultra"}
        and (model, effort) not in failures
    ]
    if stable:
        count, model, effort = max(stable)
        result.update(
            {
                "model": model,
                "effort": effort,
                "model_version": MODEL_VERSIONS[str(model)],
                "rule_id": "verified-history",
                "history_basis": f"{count} recent verified passes",
            }
        )
    elif (result["model"], result["effort"]) in failures:
        failed_combo = (str(result["model"]), str(result["effort"]))
        next_combo = ESCALATION_CHAIN.get(failed_combo)
        visited = {failed_combo}
        while next_combo is not None:
            if next_combo not in AUTOMATIC_MODEL_EFFORTS or next_combo not in MODEL_AGENTS:
                next_combo = None
                break
            if next_combo not in failures:
                break
            if next_combo in visited:
                next_combo = None
                break
            visited.add(next_combo)
            next_combo = ESCALATION_CHAIN.get(next_combo)
        if next_combo is None:
            result["dispatch_blocked"] = True
            result["history_basis"] = "verified failure exhausted the automatic escalation chain"
        else:
            result.update(
                {
                    "model": next_combo[0],
                    "effort": next_combo[1],
                    "model_version": MODEL_VERSIONS[next_combo[0]],
                    "rule_id": "verified-failure-escalation",
                    "history_basis": (
                        f"verified failure for {failed_combo[0]} · {failed_combo[1]}"
                    ),
                }
            )
    else:
        result["history_basis"] = "no stable verified-history override"
    result["avoid_combos"] = sorted(f"{model} · {effort}" for model, effort in failures)
    return result


def _recommend_command(args: argparse.Namespace, *, phase: str | None = None) -> dict[str, Any]:
    policy = load_policy(args.policy)
    axes = {
        "verifiable": args.verifiable,
        "failcost": args.failcost,
        "volume": args.volume,
        "depth": args.depth,
        "decomposable": args.decomposable,
        "workstreams": args.workstreams,
    }
    base = recommend(policy, task_family=args.task_family, axes=axes)
    history = []
    for model_version in policy.get("supported_model_versions", [policy["model_version"]]):
        history.extend(
            query_records(
                args.registry,
                task_family=args.task_family,
                model_version=model_version,
                max_age_days=int(policy.get("max_record_age_days", 90)),
                axes=axes,
                phase=phase,
            )
        )
    return apply_history(base, history)


def _recommend_from_task_command(args: argparse.Namespace, *, phase: str | None = None) -> dict[str, Any]:
    classification = classify_task_file(args.task_file)
    axes = {key: classification[key] for key in (
        "verifiable", "failcost", "volume", "depth", "decomposable", "workstreams",
    )}
    proxy = argparse.Namespace(
        policy=args.policy,
        registry=args.registry,
        task_family=classification["task_family"],
        **axes,
    )
    result = _recommend_command(proxy, phase=phase)
    return {**result, "classification": classification}


def _execution_allowed_paths(task_text: str) -> list[str]:
    """Require an explicit, narrow allowed-path section for executable cards."""
    section = re.search(
        r"^#{1,6}\s+Allowed paths\s*$\n(.*?)(?=^#{1,6}\s+|\Z)",
        task_text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if section is None:
        raise ValueError("task card needs an explicit Allowed paths section")
    paths = _task_card_paths(task_text)
    if not paths:
        raise ValueError("task card needs at least one allowed path")
    for path in paths:
        core = path[:-3] if path.endswith("/**") else path
        if (
            not core or core.startswith("/") or "\\" in core
            or any(part in {"", ".", ".."} for part in core.split("/"))
            or any(char in core for char in "*?[]")
        ):
            raise ValueError("task card contains an unsafe allowed path")
    return paths


def _reported_result(stdout: str) -> dict[str, Any]:
    """Take the last structured agent message from Codex JSONL output."""
    result: dict[str, Any] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item", {})
        if not isinstance(item, dict):
            continue
        if event.get("type") != "item.completed" or item.get("type") != "agent_message":
            continue
        raw_message = item.get("text", "")
        if not isinstance(raw_message, str):
            continue
        message = raw_message.strip()
        if message.startswith("```json") and message.endswith("```"):
            message = message[7:-3].strip()
        try:
            candidate = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(candidate, dict):
            result = candidate
    return result


def _within_allowed_path(path: str, allowed: list[str]) -> bool:
    if (
        not path or path.startswith("/") or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        return False
    return any(
        path == rule or (rule.endswith("/**") and path.startswith(rule[:-2]))
        for rule in allowed
    )


def run_task(args: argparse.Namespace) -> dict[str, Any]:
    """Run one classified, bounded task through the existing Codex dispatch."""
    summary: dict[str, Any] = {
        "task_family": None, "classification": None, "model": None,
        "effort": None, "agent_name": None, "dispatch_mode": None,
        "child_exit_code": None, "execution_status": "blocked",
        "changed_paths": [], "verification_evidence": None,
    }
    try:
        classification = classify_task_file(args.task_file)
        task_text = args.task_file.read_text(encoding="utf-8")
        allowed_paths = _execution_allowed_paths(task_text)
        recommendation = _recommend_from_task_command(args, phase=args.phase)
        dispatch = build_dispatch(
            recommendation, phase=args.phase, task_scope="phase",
            parent_sandbox=args.parent_sandbox, exec_sandbox=args.exec_sandbox,
            parent_approval_policy=args.parent_approval_policy,
            approval_boundary_confirmed=args.approval_boundary_confirmed,
        )
    except (OSError, ValueError) as error:
        summary["blocker"] = str(error)
        return summary
    summary.update({
        "task_family": recommendation["task_family"],
        "classification": classification,
        "model": dispatch["model"], "effort": dispatch["effort"],
        "agent_name": dispatch["agent_name"],
    })
    if not dispatch["codex_exec_ready"] or not dispatch["agent_name"] or dispatch["dispatch_blocked"]:
        summary["blocker"] = dispatch["codex_exec_blocker"] or "no exact executable worker mapping"
        return summary
    prompt = (
        "Execute only the supplied bounded task card. Honor its Allowed paths; do not widen "
        "scope. Run the validation requested by the card. Stop on missing authority or "
        "unavailable capability. Do not commit or push unless the task card explicitly "
        "requires it. Return a final JSON object only, with changed_paths as a list of "
        "workspace-relative paths and verification_evidence as an object containing "
        "command and result; use null for missing evidence.\n\n"
        "<bounded_task_card>\n" + task_text + "\n</bounded_task_card>"
    )
    try:
        child = subprocess.run(
            [*dispatch["fallback_command"], "-"], input=prompt,
            text=True, capture_output=True, check=False,
        )
    except OSError as error:
        summary.update(execution_status="failed", blocker=f"Codex could not launch: {error}")
        return summary
    summary["dispatch_mode"] = "codex_exec"
    summary["child_exit_code"] = child.returncode
    if child.returncode != 0:
        error_text = child.stderr.strip()
        if not error_text:
            for line in child.stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") in {"error", "turn.failed"}:
                    error_text = str(event.get("message") or event.get("error") or "")
        if error_text:
            summary["child_error"] = error_text.replace(task_text, "[task card redacted]")[:300]
    reported = _reported_result(child.stdout)
    changed = reported.get("changed_paths")
    if isinstance(changed, list) and all(isinstance(path, str) for path in changed):
        summary["changed_paths"] = changed
    evidence = reported.get("verification_evidence")
    if isinstance(evidence, dict):
        command, result = evidence.get("command"), evidence.get("result")
        if (
            isinstance(command, str) and isinstance(result, str)
            and command.strip() and len(command) <= 512
            and "\n" not in command and "\r" not in command
            and task_text.strip() not in command
            and result.strip().lower() in {"passed", "failed"}
        ):
            summary["verification_evidence"] = {
                "command": command, "result": result.strip().lower(),
            }
    if isinstance(changed, list) and any(
        not isinstance(path, str) or not _within_allowed_path(path, allowed_paths)
        for path in changed
    ):
        summary["execution_status"] = "out_of_scope"
    elif child.returncode != 0:
        summary["execution_status"] = "failed"
    else:
        summary["execution_status"] = "success"
    outcome = "partial"
    if (
        summary["execution_status"] == "success"
        and isinstance(changed, list)
        and summary["verification_evidence"]
        and summary["verification_evidence"]["result"] == "passed"
    ):
        outcome = "verified_pass"
    elif (
        summary["execution_status"] == "failed"
        and summary["verification_evidence"]
        and summary["verification_evidence"]["result"] == "failed"
    ):
        outcome = "verified_fail"
    record = {
        "task_family": recommendation["task_family"], "axes": recommendation["axes"],
        "model": dispatch["model"], "effort": dispatch["effort"],
        "outcome": outcome, "model_version": recommendation["model_version"],
        "policy_version": recommendation["policy_version"],
        "session_id": current_session()["session_id"], "phase": args.phase,
        "agent_name": dispatch["agent_name"], "dispatch_mode": "codex_exec",
        "verification_command": (summary["verification_evidence"] or {}).get("command", ""),
        "verification_result": (summary["verification_evidence"] or {}).get("result", ""),
    }
    append_record(args.registry, record)
    summary["recorded_outcome"] = outcome
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    commands = parser.add_subparsers(dest="command", required=True)
    recommend_parser = commands.add_parser("recommend")
    recommend_parser.add_argument("--task-family", required=True)
    recommend_parser.add_argument("--verifiable", choices=("yes", "partial", "no"), required=True)
    recommend_parser.add_argument("--failcost", choices=("low", "mid", "high"), required=True)
    recommend_parser.add_argument("--volume", choices=("low", "mid", "high"), required=True)
    recommend_parser.add_argument("--depth", choices=("shallow", "medium", "deep"), required=True)
    recommend_parser.add_argument("--decomposable", choices=("yes", "no"), default="no")
    recommend_parser.add_argument("--workstreams", type=int, default=1)

    classify_parser = commands.add_parser("classify")
    classify_parser.add_argument("--task-file", type=Path, required=True)

    recommend_task_parser = commands.add_parser("recommend-from-task")
    recommend_task_parser.add_argument("--task-file", type=Path, required=True)

    dispatch_task_parser = commands.add_parser("dispatch-from-task")
    dispatch_task_parser.add_argument("--task-file", type=Path, required=True)
    dispatch_task_parser.add_argument("--phase", choices=("plan", "build", "test", "qa"), required=True)
    dispatch_task_parser.add_argument("--task-scope", choices=("micro", "phase", "workflow"), required=True)
    dispatch_task_parser.add_argument("--parent-sandbox", choices=tuple(SANDBOX_RANK))
    dispatch_task_parser.add_argument("--exec-sandbox", choices=tuple(SANDBOX_RANK))
    dispatch_task_parser.add_argument(
        "--parent-approval-policy", choices=tuple(sorted(VALID_APPROVAL_POLICIES))
    )
    dispatch_task_parser.add_argument("--approval-boundary-confirmed", action="store_true")

    run_task_parser = commands.add_parser("run-task")
    run_task_parser.add_argument("--task-file", type=Path, required=True)
    run_task_parser.add_argument("--phase", choices=("plan", "build", "test", "qa"), required=True)
    run_task_parser.add_argument("--parent-sandbox", choices=tuple(SANDBOX_RANK))
    run_task_parser.add_argument("--exec-sandbox", choices=tuple(SANDBOX_RANK))
    run_task_parser.add_argument(
        "--parent-approval-policy", choices=tuple(sorted(VALID_APPROVAL_POLICIES))
    )
    run_task_parser.add_argument("--approval-boundary-confirmed", action="store_true")

    dispatch_parser = commands.add_parser("dispatch")
    dispatch_parser.add_argument("--task-family", required=True)
    dispatch_parser.add_argument("--phase", choices=("plan", "build", "test", "qa"), required=True)
    dispatch_parser.add_argument("--task-scope", choices=("micro", "phase", "workflow"), required=True)
    dispatch_parser.add_argument("--verifiable", choices=("yes", "partial", "no"), required=True)
    dispatch_parser.add_argument("--failcost", choices=("low", "mid", "high"), required=True)
    dispatch_parser.add_argument("--volume", choices=("low", "mid", "high"), required=True)
    dispatch_parser.add_argument("--depth", choices=("shallow", "medium", "deep"), required=True)
    dispatch_parser.add_argument("--decomposable", choices=("yes", "no"), default="no")
    dispatch_parser.add_argument("--workstreams", type=int, default=1)
    dispatch_parser.add_argument(
        "--parent-sandbox",
        choices=tuple(SANDBOX_RANK),
    )
    dispatch_parser.add_argument(
        "--exec-sandbox",
        choices=tuple(SANDBOX_RANK),
    )
    dispatch_parser.add_argument(
        "--parent-approval-policy",
        choices=tuple(sorted(VALID_APPROVAL_POLICIES)),
    )
    dispatch_parser.add_argument("--approval-boundary-confirmed", action="store_true")

    record_parser = commands.add_parser("record")
    record_parser.add_argument("--task-family", required=True)
    record_parser.add_argument("--axes-json", required=True)
    record_parser.add_argument("--model", choices=sorted(VALID_MODELS), required=True)
    record_parser.add_argument("--effort", choices=sorted(VALID_EFFORTS), required=True)
    record_parser.add_argument("--outcome", choices=sorted(VALID_OUTCOMES), required=True)
    record_parser.add_argument("--verification-command", default="")
    record_parser.add_argument("--verification-result", default="")
    record_parser.add_argument("--session-id", default="")
    record_parser.add_argument("--failure-type", default="")
    record_parser.add_argument("--note", default="")
    record_parser.add_argument("--phase", choices=("plan", "build", "test", "qa"), default="")
    record_parser.add_argument("--agent-name", default="")
    record_parser.add_argument("--dispatch-mode", choices=sorted(VALID_DISPATCH_MODES), default="")

    query_parser = commands.add_parser("query")
    query_parser.add_argument("--task-family", required=True)
    query_parser.add_argument("--max-age-days", type=int)

    commands.add_parser("session")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "recommend":
        print(json.dumps(_recommend_command(args), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "classify":
        print(json.dumps(classify_task_file(args.task_file), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "recommend-from-task":
        print(json.dumps(_recommend_from_task_command(args), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "dispatch-from-task":
        recommendation = _recommend_from_task_command(args, phase=args.phase)
        payload = build_dispatch(
            recommendation,
            phase=args.phase,
            task_scope=args.task_scope,
            parent_sandbox=args.parent_sandbox,
            exec_sandbox=args.exec_sandbox,
            parent_approval_policy=args.parent_approval_policy,
            approval_boundary_confirmed=args.approval_boundary_confirmed,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "run-task":
        payload = run_task(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload["execution_status"] == "success" else 1
    if args.command == "dispatch":
        recommendation = _recommend_command(args, phase=args.phase)
        payload = build_dispatch(
            recommendation,
            phase=args.phase,
            task_scope=args.task_scope,
            parent_sandbox=args.parent_sandbox,
            exec_sandbox=args.exec_sandbox,
            parent_approval_policy=args.parent_approval_policy,
            approval_boundary_confirmed=args.approval_boundary_confirmed,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "record":
        policy = load_policy(args.policy)
        axes = json.loads(args.axes_json)
        if not isinstance(axes, dict):
            raise ValueError("axes-json must decode to an object")
        session_id = args.session_id.strip() or current_session()["session_id"]
        saved = append_record(
            args.registry,
            {
                "task_family": args.task_family,
                "axes": axes,
                "model": args.model,
                "effort": args.effort,
                "outcome": args.outcome,
                "verification_command": args.verification_command,
                "verification_result": args.verification_result,
                "model_version": MODEL_VERSIONS[args.model],
                "policy_version": policy["policy_version"],
                "session_id": session_id,
                "failure_type": args.failure_type,
                "note": args.note,
                "phase": args.phase,
                "agent_name": args.agent_name,
                "dispatch_mode": args.dispatch_mode,
            },
        )
        print(json.dumps(saved, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "query":
        policy = load_policy(args.policy)
        records = []
        for model_version in policy.get("supported_model_versions", [policy["model_version"]]):
            records.extend(
                query_records(
                    args.registry,
                    task_family=args.task_family,
                    model_version=model_version,
                    max_age_days=args.max_age_days
                    or int(policy.get("max_record_age_days", 90)),
                )
            )
        records.sort(key=lambda item: _parse_timestamp(item["recorded_at"]), reverse=True)
        print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "session":
        print(json.dumps(current_session(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
