#!/usr/bin/env python3
"""Deterministic model/effort advice and evidence-gated outcome registry."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
DEFAULT_POLICY = HERE.parent / "references" / "policy.json"
VALID_MODELS = {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra"}
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
LEGACY_GPT_5_6_EFFORTS = {"low", "medium", "high", "max", "ultra"}
MODEL_EFFORTS = {
    "gpt-5.6-luna": LEGACY_GPT_5_6_EFFORTS,
    "gpt-5.6-terra": LEGACY_GPT_5_6_EFFORTS,
    "gpt-5.6-sol": LEGACY_GPT_5_6_EFFORTS,
    "gpt-6-astra": {"low", "medium", "high", "xhigh", "max"},
}
MODEL_VERSIONS = {
    "gpt-5.6-luna": "gpt-5.6",
    "gpt-5.6-terra": "gpt-5.6",
    "gpt-5.6-sol": "gpt-5.6",
    "gpt-6-astra": "gpt-6",
}
AUTOMATIC_FORBIDDEN_EFFORTS = {"xhigh", "max", "ultra"}
VALID_OUTCOMES = {"verified_pass", "verified_fail", "partial"}
VALID_DISPATCH_MODES = {
    "native_custom_agent",
    "codex_exec",
    "main_task_fallback",
    "main_task_direct",
}
VALID_PHASES = {"plan", "build", "test", "qa"}
MODEL_AGENTS = {
    ("gpt-5.6-luna", "medium"): "pas_luna_worker",
    ("gpt-5.6-terra", "medium"): "pas_terra_worker",
    ("gpt-5.6-terra", "high"): "pas_terra_builder",
    ("gpt-5.6-sol", "high"): "pas_sol_analyst",
    ("gpt-5.6-sol", "max"): "pas_sol_max_worker",
    ("gpt-6-astra", "low"): "pas_astra_low_worker",
    ("gpt-6-astra", "medium"): "pas_astra_medium_worker",
    ("gpt-6-astra", "high"): "pas_astra_high_worker",
}
SANDBOX_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "danger-full-access": 2,
}
VALID_APPROVAL_POLICIES = {"untrusted", "on-failure", "on-request", "never"}
ESCALATION_CHAIN = {
    ("gpt-5.6-luna", "low"): ("gpt-5.6-luna", "medium"),
    ("gpt-5.6-luna", "medium"): ("gpt-5.6-terra", "medium"),
    ("gpt-5.6-terra", "medium"): ("gpt-5.6-terra", "high"),
    ("gpt-5.6-terra", "high"): ("gpt-5.6-sol", "high"),
    ("gpt-5.6-sol", "high"): ("gpt-6-astra", "low"),
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

    if selected["effort"] in AUTOMATIC_FORBIDDEN_EFFORTS:
        raise ValueError("static policy must not automatically select xhigh, max, or ultra")

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
        expected_agent = MODEL_AGENTS.get((str(record["model"]), str(record["effort"])))
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
    passes = Counter(
        (record.get("model"), record.get("effort"))
        for record in records
        if record.get("outcome") == "verified_pass"
    )
    failures = {
        (record.get("model"), record.get("effort"))
        for record in records
        if record.get("outcome") == "verified_fail"
    }
    stable = [
        (count, model, effort)
        for (model, effort), count in passes.items()
        if count >= 2
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
        while next_combo in failures:
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
