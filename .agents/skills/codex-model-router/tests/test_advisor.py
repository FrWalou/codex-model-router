import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "advisor.py"
POLICY_PATH = SKILL_ROOT / "references" / "policy.json"


def load_advisor():
    spec = importlib.util.spec_from_file_location("codex_model_router_advisor", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AdvisorPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.advisor = load_advisor()
        cls.policy = cls.advisor.load_policy(POLICY_PATH)

    def test_routes_verifiable_high_volume_work_to_luna_medium(self):
        result = self.advisor.recommend(
            self.policy,
            task_family="structured-extraction",
            axes={
                "verifiable": "yes",
                "failcost": "mid",
                "volume": "high",
                "depth": "shallow",
                "decomposable": "no",
                "workstreams": 1,
            },
        )

        self.assertEqual(result["model"], "gpt-5.6-luna")
        self.assertEqual(result["effort"], "medium")
        self.assertEqual(result["rule_id"], "verifiable-high-volume")

    def test_routes_ambiguous_high_risk_deep_work_to_sol_high(self):
        result = self.advisor.recommend(
            self.policy,
            task_family="architecture-migration",
            axes={
                "verifiable": "partial",
                "failcost": "high",
                "volume": "low",
                "depth": "deep",
                "decomposable": "no",
                "workstreams": 1,
            },
        )

        self.assertEqual(result["model"], "gpt-5.6-sol")
        self.assertEqual(result["effort"], "high")

    def test_routes_partially_verifiable_medium_depth_analysis_to_terra_high(self):
        result = self.advisor.recommend(
            self.policy,
            task_family="domain-analysis",
            axes={
                "verifiable": "partial",
                "failcost": "mid",
                "volume": "mid",
                "depth": "medium",
                "decomposable": "no",
                "workstreams": 1,
            },
        )

        self.assertEqual(result["model"], "gpt-5.6-terra")
        self.assertEqual(result["effort"], "high")
        self.assertEqual(result["rule_id"], "judgment-and-analysis")

    def test_ultra_is_eligible_but_never_automatic(self):
        result = self.advisor.recommend(
            self.policy,
            task_family="multi-module-review",
            axes={
                "verifiable": "partial",
                "failcost": "high",
                "volume": "low",
                "depth": "deep",
                "decomposable": "yes",
                "workstreams": 3,
            },
        )

        self.assertEqual(result["effort"], "high")
        self.assertTrue(result["ultra_eligible"])
        self.assertIn("explicit", result["ultra_note"].lower())

    def test_static_policy_never_selects_xhigh_or_max(self):
        for selected in [*self.policy["rules"], self.policy["fallback"]]:
            with self.subTest(rule=selected["id"]):
                self.assertNotIn(selected["effort"], {"xhigh", "max"})

    def test_unknown_session_is_reported_instead_of_scanning_rollouts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_home = Path(temp_dir)
            rollout = fake_home / "sessions" / "rollout-newest.jsonl"
            rollout.parent.mkdir(parents=True)
            rollout.write_text('{"model":"gpt-5.6-sol","effort":"ultra"}\n')

            result = self.advisor.current_session({"CODEX_HOME": str(fake_home)})

        self.assertEqual(result, {"session_id": "unknown", "source": "unavailable"})

    def test_session_uses_runtime_provided_thread_id(self):
        result = self.advisor.current_session({"CODEX_THREAD_ID": "thread-456"})

        self.assertEqual(result, {"session_id": "thread-456", "source": "env:CODEX_THREAD_ID"})

    def test_explicit_registry_path_wins(self):
        result = self.advisor.default_registry_path(
            {"CODEX_MODEL_ROUTER_REGISTRY": "/tmp/router-outcomes.jsonl"}
        )

        self.assertEqual(result, Path("/tmp/router-outcomes.jsonl"))

    def test_dispatch_maps_recommendation_to_model_specific_agent(self):
        recommendation = {
            "model": "gpt-5.6-luna",
            "effort": "medium",
            "rule_id": "clear-repeatable-work",
        }

        result = self.advisor.build_dispatch(
            recommendation,
            phase="test",
            task_scope="phase",
            parent_sandbox="workspace-write",
            exec_sandbox="read-only",
            parent_approval_policy="on-request",
            approval_boundary_confirmed=True,
        )

        self.assertEqual(result["agent_name"], "pas_luna_worker")
        self.assertEqual(result["phase"], "test")
        self.assertTrue(result["dispatch_required"])
        self.assertIsNone(result["dispatch_mode"])
        self.assertTrue(result["codex_exec_ready"])
        self.assertEqual(result["fallback_command"][0:4], ["codex", "exec", "-m", "gpt-5.6-luna"])
        self.assertIn("read-only", result["fallback_command"])
        self.assertIn('approval_policy="on-request"', result["fallback_command"])
        self.assertIn("--json", result["fallback_command"])

    def test_native_agent_matches_the_recommended_effort(self):
        terra = self.advisor.build_dispatch(
            {"model": "gpt-5.6-terra", "effort": "medium"},
            phase="build",
            task_scope="phase",
        )
        sol = self.advisor.build_dispatch(
            {"model": "gpt-5.6-sol", "effort": "max"},
            phase="qa",
            task_scope="phase",
        )

        self.assertEqual(terra["agent_name"], "pas_terra_worker")
        self.assertEqual(sol["agent_name"], "pas_sol_max_worker")

    def test_astra_automatic_tiers_map_to_exact_workers(self):
        for effort, agent_name in (
            ("low", "pas_astra_low_worker"),
            ("medium", "pas_astra_medium_worker"),
            ("high", "pas_astra_high_worker"),
        ):
            with self.subTest(effort=effort):
                result = self.advisor.build_dispatch(
                    {"model": "gpt-6-astra", "effort": effort},
                    phase="qa",
                    task_scope="phase",
                )
                self.assertEqual(result["agent_name"], agent_name)
                self.assertTrue(result["native_custom_agent_ready"])

    def test_unregistered_astra_efforts_cannot_claim_native_agent_readiness(self):
        for effort in ("xhigh", "max"):
            with self.subTest(effort=effort):
                result = self.advisor.build_dispatch(
                    {"model": "gpt-6-astra", "effort": effort},
                    phase="qa",
                    task_scope="phase",
                )
                self.assertIsNone(result["agent_name"])
                self.assertFalse(result["native_custom_agent_ready"])

    def test_exec_fallback_is_blocked_without_explicit_boundary_confirmation(self):
        result = self.advisor.build_dispatch(
            {"model": "gpt-5.6-terra", "effort": "high"},
            phase="build",
            task_scope="phase",
            parent_sandbox="workspace-write",
            exec_sandbox="workspace-write",
            parent_approval_policy="on-request",
            approval_boundary_confirmed=False,
        )

        self.assertFalse(result["codex_exec_ready"])
        self.assertIsNone(result["fallback_command"])
        self.assertIn("approval", result["codex_exec_blocker"])

    def test_exec_fallback_rejects_a_more_permissive_sandbox(self):
        result = self.advisor.build_dispatch(
            {"model": "gpt-5.6-terra", "effort": "high"},
            phase="build",
            task_scope="phase",
            parent_sandbox="read-only",
            exec_sandbox="workspace-write",
            parent_approval_policy="on-request",
            approval_boundary_confirmed=True,
        )

        self.assertFalse(result["codex_exec_ready"])
        self.assertIsNone(result["fallback_command"])
        self.assertIn("same or stricter", result["codex_exec_blocker"])

    def test_exec_fallback_requires_an_explicit_parent_approval_policy(self):
        result = self.advisor.build_dispatch(
            {"model": "gpt-5.6-terra", "effort": "high"},
            phase="build",
            task_scope="phase",
            parent_sandbox="workspace-write",
            exec_sandbox="workspace-write",
            approval_boundary_confirmed=True,
        )

        self.assertFalse(result["codex_exec_ready"])
        self.assertIsNone(result["fallback_command"])
        self.assertIn("approval policy", result["codex_exec_blocker"])

    def test_micro_task_stays_in_main_task(self):
        result = self.advisor.build_dispatch(
            {"model": "gpt-5.6-luna", "effort": "medium"},
            phase="build",
            task_scope="micro",
        )

        self.assertFalse(result["dispatch_required"])
        self.assertEqual(result["dispatch_mode"], "main_task_direct")

    def test_dispatch_mode_prefers_native_then_exec_then_main_fallback(self):
        self.assertEqual(self.advisor.select_dispatch_mode(True, True), "native_custom_agent")
        self.assertEqual(self.advisor.select_dispatch_mode(False, True), "codex_exec")
        self.assertEqual(self.advisor.select_dispatch_mode(False, False), "main_task_fallback")


class AdvisorRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.advisor = load_advisor()

    def test_verified_pass_requires_verification_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            with self.assertRaisesRegex(ValueError, "verification evidence"):
                self.advisor.append_record(
                    path,
                    {
                        "task_family": "structured-extraction",
                        "axes": {"verifiable": "yes"},
                        "model": "gpt-5.6-luna",
                        "effort": "medium",
                        "outcome": "verified_pass",
                        "model_version": "gpt-5.6",
                        "policy_version": "2026-07-15.v1",
                        "session_id": "task-123",
                    },
                )

    def test_registry_does_not_store_raw_prompt_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            with self.assertRaisesRegex(ValueError, "unsupported record fields"):
                self.advisor.append_record(
                    path,
                    {
                        "task_family": "structured-extraction",
                        "raw_prompt": "Client Alpha confidential ledger",
                        "axes": {"verifiable": "yes"},
                        "model": "gpt-5.6-luna",
                        "effort": "medium",
                        "outcome": "partial",
                        "model_version": "gpt-5.6",
                        "policy_version": "2026-07-15.v1",
                        "session_id": "task-123",
                    },
                )

    def test_query_excludes_stale_and_other_model_generation_records(self):
        now = datetime(2026, 7, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            records = [
                {
                    "recorded_at": (now - timedelta(days=5)).isoformat(),
                    "task_family": "structured-extraction",
                    "axes": {"verifiable": "yes"},
                    "model": "gpt-5.6-luna",
                    "effort": "medium",
                    "outcome": "verified_pass",
                    "verification_command": "pytest",
                    "verification_result": "pass",
                    "model_version": "gpt-5.6",
                    "policy_version": "2026-07-15.v1",
                    "session_id": "recent",
                },
                {
                    "recorded_at": (now - timedelta(days=120)).isoformat(),
                    "task_family": "structured-extraction",
                    "axes": {"verifiable": "yes"},
                    "model": "gpt-5.6-luna",
                    "effort": "medium",
                    "outcome": "verified_pass",
                    "verification_command": "pytest",
                    "verification_result": "pass",
                    "model_version": "gpt-5.6",
                    "policy_version": "2026-07-15.v1",
                    "session_id": "stale",
                },
                {
                    "recorded_at": (now - timedelta(days=2)).isoformat(),
                    "task_family": "structured-extraction",
                    "axes": {"verifiable": "yes"},
                    "model": "gpt-5.5",
                    "effort": "high",
                    "outcome": "verified_pass",
                    "verification_command": "pytest",
                    "verification_result": "pass",
                    "model_version": "gpt-5.5",
                    "policy_version": "2026-06-01.v1",
                    "session_id": "old-model",
                },
            ]
            path.write_text("".join(json.dumps(item) + "\n" for item in records))

            result = self.advisor.query_records(
                path,
                task_family="structured-extraction",
                model_version="gpt-5.6",
                max_age_days=90,
                now=now,
            )

        self.assertEqual([item["session_id"] for item in result], ["recent"])

    def test_query_can_isolate_verified_history_by_phase(self):
        now = datetime(2026, 7, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            records = [
                {
                    "recorded_at": now.isoformat(),
                    "task_family": "feature-work",
                    "axes": {"verifiable": "yes"},
                    "model": "gpt-5.6-terra",
                    "effort": "high",
                    "outcome": "verified_pass",
                    "model_version": "gpt-5.6",
                    "phase": "build",
                    "session_id": "build-worker",
                },
                {
                    "recorded_at": now.isoformat(),
                    "task_family": "feature-work",
                    "axes": {"verifiable": "yes"},
                    "model": "gpt-5.6-sol",
                    "effort": "high",
                    "outcome": "verified_pass",
                    "model_version": "gpt-5.6",
                    "phase": "qa",
                    "session_id": "qa-worker",
                },
            ]
            path.write_text("".join(json.dumps(item) + "\n" for item in records))

            result = self.advisor.query_records(
                path,
                task_family="feature-work",
                model_version="gpt-5.6",
                max_age_days=90,
                phase="build",
                now=now,
            )

        self.assertEqual([item["session_id"] for item in result], ["build-worker"])

    def test_two_verified_passes_override_static_policy(self):
        recommendation = {
            "model": "gpt-5.6-terra",
            "effort": "high",
            "rule_id": "judgment-and-analysis",
        }
        records = [
            {"model": "gpt-5.6-luna", "effort": "medium", "outcome": "verified_pass"},
            {"model": "gpt-5.6-luna", "effort": "medium", "outcome": "verified_pass"},
        ]

        result = self.advisor.apply_history(recommendation, records)

        self.assertEqual(result["model"], "gpt-5.6-luna")
        self.assertEqual(result["effort"], "medium")
        self.assertEqual(result["rule_id"], "verified-history")

    def test_verified_failure_blocks_history_override_and_is_reported(self):
        recommendation = {
            "model": "gpt-5.6-terra",
            "effort": "high",
            "rule_id": "judgment-and-analysis",
        }
        records = [
            {"model": "gpt-5.6-luna", "effort": "medium", "outcome": "verified_pass"},
            {"model": "gpt-5.6-luna", "effort": "medium", "outcome": "verified_pass"},
            {"model": "gpt-5.6-luna", "effort": "medium", "outcome": "verified_fail"},
        ]

        result = self.advisor.apply_history(recommendation, records)

        self.assertEqual(result["model"], "gpt-5.6-terra")
        self.assertIn("gpt-5.6-luna · medium", result["avoid_combos"])

    def test_ultra_history_never_becomes_an_automatic_override(self):
        recommendation = {
            "model": "gpt-5.6-sol",
            "effort": "high",
            "rule_id": "ambiguous-high-risk",
        }
        records = [
            {"model": "gpt-5.6-sol", "effort": "ultra", "outcome": "verified_pass"},
            {"model": "gpt-5.6-sol", "effort": "ultra", "outcome": "verified_pass"},
        ]

        result = self.advisor.apply_history(recommendation, records)

        self.assertEqual(result["effort"], "high")
        self.assertEqual(result["rule_id"], "ambiguous-high-risk")

    def test_max_history_never_becomes_an_automatic_override(self):
        recommendation = {
            "model": "gpt-5.6-sol",
            "effort": "high",
            "rule_id": "high-risk-deep-work",
        }
        records = [
            {"model": "gpt-5.6-sol", "effort": "max", "outcome": "verified_pass"},
            {"model": "gpt-5.6-sol", "effort": "max", "outcome": "verified_pass"},
        ]

        result = self.advisor.apply_history(recommendation, records)

        self.assertEqual(result["effort"], "high")
        self.assertEqual(result["rule_id"], "high-risk-deep-work")

    def test_astra_xhigh_and_max_history_never_become_automatic_overrides(self):
        recommendation = {
            "model": "gpt-5.6-sol",
            "effort": "high",
            "rule_id": "high-risk-deep-work",
        }
        for effort in ("xhigh", "max"):
            with self.subTest(effort=effort):
                result = self.advisor.apply_history(
                    recommendation,
                    [
                        {"model": "gpt-6-astra", "effort": effort, "outcome": "verified_pass"},
                        {"model": "gpt-6-astra", "effort": effort, "outcome": "verified_pass"},
                    ],
                )
                self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))

    def test_astra_outcome_can_be_recorded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            saved = self.advisor.append_record(
                path,
                {
                    "task_family": "architecture-migration",
                    "axes": {"verifiable": "partial"},
                    "model": "gpt-6-astra",
                    "effort": "low",
                    "outcome": "verified_pass",
                    "verification_command": "python3 -m unittest",
                    "verification_result": "pass",
                    "model_version": "gpt-6",
                    "policy_version": "2026-09-22.v3",
                    "session_id": "worker-456",
                    "phase": "qa",
                    "agent_name": "pas_astra_low_worker",
                    "dispatch_mode": "native_custom_agent",
                },
            )

        self.assertEqual((saved["model"], saved["effort"]), ("gpt-6-astra", "low"))

    def test_astra_ultra_outcome_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unsupported effort"):
                self.advisor.append_record(
                    Path(temp_dir) / "outcomes.jsonl",
                    {
                        "task_family": "architecture-migration",
                        "axes": {"verifiable": "partial"},
                        "model": "gpt-6-astra",
                        "effort": "ultra",
                        "outcome": "partial",
                        "model_version": "gpt-6",
                        "policy_version": "2026-09-22.v3",
                        "session_id": "worker-456",
                    },
                )

    def test_astra_record_rejects_mismatched_model_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "does not match model"):
                self.advisor.append_record(
                    Path(temp_dir) / "outcomes.jsonl",
                    {
                        "task_family": "architecture-migration",
                        "axes": {"verifiable": "partial"},
                        "model": "gpt-6-astra",
                        "effort": "low",
                        "outcome": "partial",
                        "model_version": "gpt-5.6",
                        "policy_version": "2026-09-22.v3",
                        "session_id": "worker-456",
                    },
                )

    def test_astra_passes_do_not_override_a_gpt_5_6_recommendation(self):
        recommendation = {
            "model": "gpt-5.6-sol",
            "effort": "high",
            "model_version": "gpt-5.6",
            "rule_id": "high-risk-deep-work",
        }
        records = [
            {"model": "gpt-6-astra", "effort": "medium", "outcome": "verified_pass"},
            {"model": "gpt-6-astra", "effort": "medium", "outcome": "verified_pass"},
        ]

        result = self.advisor.apply_history(recommendation, records)

        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))

    def test_xhigh_does_not_expand_legacy_model_efforts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for model in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"):
                with self.subTest(model=model), self.assertRaisesRegex(
                    ValueError, "unsupported effort"
                ):
                    self.advisor.append_record(
                        Path(temp_dir) / "outcomes.jsonl",
                        {
                            "task_family": "legacy-compatibility",
                            "axes": {"verifiable": "yes"},
                            "model": model,
                            "effort": "xhigh",
                            "outcome": "partial",
                            "model_version": "gpt-5.6",
                            "policy_version": "2026-09-22.v3",
                            "session_id": "worker-456",
                        },
                    )

    def test_unregistered_model_effort_history_never_overrides_policy(self):
        recommendation = {
            "model": "gpt-5.6-sol",
            "effort": "high",
            "rule_id": "high-risk-deep-work",
        }
        records = [
            {"model": "gpt-5.6-sol", "effort": "medium", "outcome": "verified_pass"},
            {"model": "gpt-5.6-sol", "effort": "medium", "outcome": "verified_pass"},
        ]

        result = self.advisor.apply_history(recommendation, records)

        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))
        self.assertEqual(result["rule_id"], "high-risk-deep-work")

    def test_verified_failure_escalates_away_from_the_failed_static_combo(self):
        recommendation = {
            "model": "gpt-5.6-terra",
            "effort": "high",
            "rule_id": "complex-build",
        }
        records = [
            {"model": "gpt-5.6-terra", "effort": "high", "outcome": "verified_fail"},
        ]

        result = self.advisor.apply_history(recommendation, records)

        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))
        self.assertNotIn(
            f'{result["model"]} · {result["effort"]}',
            result["avoid_combos"],
        )
        self.assertEqual(result["rule_id"], "verified-failure-escalation")

    def test_sol_failure_escalates_to_astra_then_astra_escalates_one_step(self):
        sol_failure = self.advisor.apply_history(
            {"model": "gpt-5.6-sol", "effort": "high", "rule_id": "high-risk-deep-work"},
            [{"model": "gpt-5.6-sol", "effort": "high", "outcome": "verified_fail"}],
        )
        astra_failure = self.advisor.apply_history(
            {"model": "gpt-6-astra", "effort": "low", "rule_id": "verified-failure-escalation"},
            [{"model": "gpt-6-astra", "effort": "low", "outcome": "verified_fail"}],
        )

        self.assertEqual((sol_failure["model"], sol_failure["effort"]), ("gpt-6-astra", "low"))
        self.assertEqual(sol_failure["model_version"], "gpt-6")
        self.assertEqual((astra_failure["model"], astra_failure["effort"]), ("gpt-6-astra", "medium"))

    def test_escalation_cycle_is_blocked_instead_of_looping(self):
        original_chain = self.advisor.ESCALATION_CHAIN
        self.advisor.ESCALATION_CHAIN = {
            ("gpt-5.6-sol", "high"): ("gpt-6-astra", "low"),
            ("gpt-6-astra", "low"): ("gpt-5.6-sol", "high"),
        }
        try:
            result = self.advisor.apply_history(
                {
                    "model": "gpt-5.6-sol",
                    "effort": "high",
                    "model_version": "gpt-5.6",
                    "rule_id": "high-risk-deep-work",
                },
                [
                    {"model": "gpt-5.6-sol", "effort": "high", "outcome": "verified_fail"},
                    {"model": "gpt-6-astra", "effort": "low", "outcome": "verified_fail"},
                ],
            )
        finally:
            self.advisor.ESCALATION_CHAIN = original_chain

        self.assertTrue(result["dispatch_blocked"])

    def test_exhausted_escalation_chain_blocks_every_dispatch_path(self):
        recommendation = self.advisor.apply_history(
            {
                "model": "gpt-5.6-sol",
                "effort": "high",
                "rule_id": "high-risk-deep-work",
            },
            [
                {"model": "gpt-5.6-sol", "effort": "high", "outcome": "verified_fail"},
                {"model": "gpt-6-astra", "effort": "low", "outcome": "verified_fail"},
                {"model": "gpt-6-astra", "effort": "medium", "outcome": "verified_fail"},
                {"model": "gpt-6-astra", "effort": "high", "outcome": "verified_fail"},
            ],
        )

        result = self.advisor.build_dispatch(
            recommendation,
            phase="qa",
            task_scope="phase",
            parent_sandbox="workspace-write",
            exec_sandbox="workspace-write",
            parent_approval_policy="on-request",
            approval_boundary_confirmed=True,
        )

        self.assertTrue(result["dispatch_blocked"])
        self.assertFalse(result["dispatch_required"])
        self.assertFalse(result["codex_exec_ready"])
        self.assertIsNone(result["fallback_command"])

    def test_successful_record_contains_only_controlled_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            saved = self.advisor.append_record(
                path,
                {
                    "task_family": "structured-extraction",
                    "axes": {"verifiable": "yes"},
                    "model": "gpt-5.6-luna",
                    "effort": "medium",
                    "outcome": "verified_pass",
                    "verification_command": "pytest -q",
                    "verification_result": "12 passed",
                    "model_version": "gpt-5.6",
                    "policy_version": "2026-07-15.v1",
                    "session_id": "thread-456",
                },
                now=datetime(2026, 7, 15, tzinfo=timezone.utc),
            )

            persisted = json.loads(path.read_text())

        self.assertEqual(saved, persisted)
        self.assertNotIn("raw_prompt", persisted)
        self.assertEqual(persisted["verification_result"], "12 passed")

    def test_record_persists_actual_dispatch_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            saved = self.advisor.append_record(
                path,
                {
                    "task_family": "feature-build",
                    "axes": {"verifiable": "yes"},
                    "model": "gpt-5.6-terra",
                    "effort": "high",
                    "outcome": "verified_pass",
                    "verification_command": "pytest -q",
                    "verification_result": "20 passed",
                    "model_version": "gpt-5.6",
                    "policy_version": "2026-07-15.v2",
                    "session_id": "worker-123",
                    "phase": "build",
                    "agent_name": "pas_terra_builder",
                    "dispatch_mode": "native_custom_agent",
                },
            )

        self.assertEqual(saved["phase"], "build")
        self.assertEqual(saved["agent_name"], "pas_terra_builder")
        self.assertEqual(saved["dispatch_mode"], "native_custom_agent")

    def test_record_rejects_unknown_dispatch_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            with self.assertRaisesRegex(ValueError, "dispatch mode"):
                self.advisor.append_record(
                    path,
                    {
                        "task_family": "feature-build",
                        "axes": {"verifiable": "yes"},
                        "model": "gpt-5.6-terra",
                        "effort": "high",
                        "outcome": "partial",
                        "model_version": "gpt-5.6",
                        "policy_version": "2026-07-15.v2",
                        "session_id": "worker-123",
                        "phase": "build",
                        "agent_name": "pas_terra_builder",
                        "dispatch_mode": "pretend-native",
                    },
                )

    def test_dispatched_record_requires_phase(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            with self.assertRaisesRegex(ValueError, "phase"):
                self.advisor.append_record(
                    path,
                    {
                        "task_family": "feature-build",
                        "axes": {"verifiable": "yes"},
                        "model": "gpt-5.6-terra",
                        "effort": "high",
                        "outcome": "partial",
                        "model_version": "gpt-5.6",
                        "policy_version": "2026-07-15.v2",
                        "session_id": "worker-123",
                        "agent_name": "pas_terra_builder",
                        "dispatch_mode": "codex_exec",
                    },
                )

    def test_external_worker_record_requires_agent_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outcomes.jsonl"
            with self.assertRaisesRegex(ValueError, "agent_name"):
                self.advisor.append_record(
                    path,
                    {
                        "task_family": "feature-build",
                        "axes": {"verifiable": "yes"},
                        "model": "gpt-5.6-terra",
                        "effort": "high",
                        "outcome": "partial",
                        "model_version": "gpt-5.6",
                        "policy_version": "2026-07-15.v2",
                        "session_id": "worker-123",
                        "phase": "build",
                        "dispatch_mode": "native_custom_agent",
                    },
                )


class AdvisorCliTests(unittest.TestCase):
    def test_recommend_command_emits_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "outcomes.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--registry",
                    str(registry),
                    "recommend",
                    "--task-family",
                    "structured-extraction",
                    "--verifiable",
                    "yes",
                    "--failcost",
                    "mid",
                    "--volume",
                    "high",
                    "--depth",
                    "shallow",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["model"], "gpt-5.6-luna")
        self.assertEqual(payload["history_basis"], "no stable verified-history override")

    def test_record_and_query_commands_round_trip_controlled_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "outcomes.jsonl"
            record = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--registry",
                    str(registry),
                    "record",
                    "--task-family",
                    "structured-extraction",
                    "--axes-json",
                    '{"verifiable":"yes"}',
                    "--model",
                    "gpt-5.6-luna",
                    "--effort",
                    "medium",
                    "--outcome",
                    "verified_pass",
                    "--verification-command",
                    "pytest -q",
                    "--verification-result",
                    "13 passed",
                    "--session-id",
                    "thread-456",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            query = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--registry",
                    str(registry),
                    "query",
                    "--task-family",
                    "structured-extraction",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(record.returncode, 0, record.stderr)
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertEqual(len(json.loads(query.stdout)), 1)
        self.assertEqual(json.loads(record.stdout)["session_id"], "thread-456")

    def test_record_command_accepts_actual_dispatch_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "outcomes.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--registry",
                    str(registry),
                    "record",
                    "--task-family",
                    "feature-build",
                    "--axes-json",
                    '{"verifiable":"yes"}',
                    "--model",
                    "gpt-5.6-terra",
                    "--effort",
                    "high",
                    "--outcome",
                    "verified_pass",
                    "--verification-command",
                    "pytest -q",
                    "--verification-result",
                    "24 passed",
                    "--phase",
                    "build",
                    "--agent-name",
                    "pas_terra_builder",
                    "--dispatch-mode",
                    "native_custom_agent",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["phase"], "build")
        self.assertEqual(payload["agent_name"], "pas_terra_builder")
        self.assertEqual(payload["dispatch_mode"], "native_custom_agent")

    def test_session_command_reports_runtime_identity(self):
        env = dict(os.environ)
        env["CODEX_THREAD_ID"] = "thread-cli-789"
        result = subprocess.run(
            [sys.executable, str(MODULE_PATH), "session"],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"session_id": "thread-cli-789", "source": "env:CODEX_THREAD_ID"},
        )

    def test_dispatch_command_emits_worker_contract(self):
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "dispatch",
                "--task-family",
                "feature-build",
                "--phase",
                "build",
                "--task-scope",
                "phase",
                "--verifiable",
                "yes",
                "--failcost",
                "mid",
                "--volume",
                "mid",
                "--depth",
                "deep",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["model"], "gpt-5.6-terra")
        self.assertEqual(payload["agent_name"], "pas_terra_builder")
        self.assertEqual(payload["phase"], "build")
        self.assertTrue(payload["dispatch_required"])


if __name__ == "__main__":
    unittest.main()
