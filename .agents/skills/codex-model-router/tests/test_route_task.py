import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "advisor.py"


def load_advisor():
    spec = importlib.util.spec_from_file_location("route_task_advisor", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


NORMAL = """# Bounded implementation
## Objective
Implement one small feature. Secret marker: cobalt-pine-731.
## Allowed paths
- src/feature.py
## Acceptance criteria
The feature works.
## Validation
python3 -m unittest discover -s tests
"""
REPEATABLE = """# Update docs
## Objective
Update one documentation fixture.
## Allowed paths
- README.md
## Acceptance criteria
The README title is exactly Codex Model Router.
## Validation
python3 -m unittest discover -s tests
"""
HIGH_RISK = """# Security migration
## Objective
Implement a deep security architecture migration.
## Allowed paths
- src/auth.py
- tests/test_auth.py
## Acceptance criteria
The migration preserves the security invariant.
## Validation
python3 -m unittest discover -s tests
"""


class RouteTaskTests(unittest.TestCase):
    def setUp(self):
        self.advisor = load_advisor()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.card = self.root / "task.md"
        self.registry = self.root / "outcomes.jsonl"
        self.args = argparse.Namespace(
            task_file=self.card, phase="build", policy=self.advisor.DEFAULT_POLICY,
            registry=self.registry, parent_sandbox=None, exec_sandbox=None,
            parent_approval_policy=None, approval_boundary_confirmed=False,
        )

    def route(self, card=NORMAL):
        self.card.write_text(card, encoding="utf-8")
        return self.advisor.route_task(self.args)

    def add_history(self, model, effort, outcome, *, model_version="gpt-6"):
        classification = self.advisor.classify_task_file(self.card)
        axes = {key: classification[key] for key in (
            "verifiable", "failcost", "volume", "depth", "decomposable", "workstreams",
        )}
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "task_family": classification["task_family"], "axes": axes,
            "model": model, "effort": effort, "outcome": outcome,
            "model_version": model_version, "phase": self.args.phase,
        }
        with self.registry.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def test_normal_bounded_card_routes_to_sol_medium_with_exact_agent(self):
        result = self.route()
        self.assertEqual((result["model"], result["effort"], result["agent_name"]),
                         ("gpt-6-sol", "medium", "pas_sol_worker"))
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["phase"], "build")
        self.assertTrue(result["automatic"])
        self.assertEqual(result["next_escalation"], {"model": "gpt-6-sol", "effort": "high"})
        self.assertTrue(result["dispatch_capability"]["exact_worker_registered"])
        self.assertNotIn("fallback_command", result["dispatch_capability"])

    def test_repeatable_card_routes_to_luna_medium(self):
        result = self.route(REPEATABLE)
        self.assertEqual((result["model"], result["effort"], result["agent_name"]),
                         ("gpt-6-luna", "medium", "pas_luna_worker"))
        self.assertEqual(result["next_escalation"], {"model": "gpt-6-sol", "effort": "medium"})

    def test_deep_high_risk_card_routes_to_sol_high_not_astra(self):
        result = self.route(HIGH_RISK)
        self.assertEqual((result["model"], result["effort"], result["agent_name"]),
                         ("gpt-6-sol", "high", "pas_sol_analyst"))
        self.assertEqual(result["next_escalation"], {"model": "gpt-6-astra", "effort": "low"})

    def test_evidence_gated_chain_and_astra_high_terminal(self):
        self.route(REPEATABLE)
        chain = [
            ("gpt-6-luna", "medium", "gpt-6-sol", "medium"),
            ("gpt-6-sol", "medium", "gpt-6-sol", "high"),
            ("gpt-6-sol", "high", "gpt-6-astra", "low"),
            ("gpt-6-astra", "low", "gpt-6-astra", "medium"),
            ("gpt-6-astra", "medium", "gpt-6-astra", "high"),
        ]
        for failed_model, failed_effort, next_model, next_effort in chain:
            with self.subTest(failed=(failed_model, failed_effort)):
                self.add_history(failed_model, failed_effort, "verified_fail")
                result = self.advisor.route_task(self.args)
                self.assertEqual((result["model"], result["effort"]), (next_model, next_effort))
        self.assertIsNone(result["next_escalation"])
        self.assertEqual(result["agent_name"], "pas_astra_high_worker")

    def test_legacy_history_and_manual_efforts_do_not_override_gpt_6(self):
        initial = self.route()
        for _ in range(2):
            self.add_history("gpt-5.6-sol", "high", "verified_pass", model_version="gpt-5.6")
            self.add_history("gpt-6-sol", "max", "verified_pass")
            self.add_history("gpt-6-astra", "ultra", "verified_pass")
        result = self.advisor.route_task(self.args)
        self.assertEqual((result["model"], result["effort"]),
                         (initial["model"], initial["effort"]))
        self.assertTrue(result["automatic"])

    def test_same_inputs_have_json_equivalent_output_without_raw_prose(self):
        first = self.route()
        second = self.advisor.route_task(self.args)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertNotIn("cobalt-pine-731", json.dumps(first))
        self.assertTrue(all(isinstance(label, str) for label in first["reason_labels"]))

    def test_route_is_read_only_and_never_calls_subprocess(self):
        self.card.write_text(NORMAL, encoding="utf-8")
        before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in self.root.iterdir()}
        with mock.patch("subprocess.run", side_effect=AssertionError("process launched")):
            self.advisor.route_task(self.args)
        after = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in self.root.iterdir()}
        self.assertEqual(before, after)
        self.assertFalse(self.registry.exists())

    def test_route_does_not_append_existing_history(self):
        self.route()
        self.add_history("gpt-5.6-sol", "high", "verified_fail", model_version="gpt-5.6")
        before = self.registry.read_bytes()
        self.advisor.route_task(self.args)
        self.assertEqual(before, self.registry.read_bytes())

    def test_missing_and_malformed_cards_fail_without_writes(self):
        with self.assertRaisesRegex(ValueError, "existing regular file"):
            self.advisor.route_task(self.args)
        self.card.write_text("not a structured card", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "structured heading"):
            self.advisor.route_task(self.args)
        self.assertFalse(self.registry.exists())

    def test_cli_emits_routing_json_without_execution(self):
        self.card.write_text(REPEATABLE, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--registry", str(self.registry),
             "route-task", "--task-file", str(self.card), "--phase", "test"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["model"], payload["effort"]), ("gpt-6-luna", "medium"))
        self.assertEqual(payload["phase"], "test")
        self.assertFalse(self.registry.exists())

    def test_production_module_has_no_process_import_or_invocation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)
        self.assertNotIn("Popen(", source)
        self.assertNotIn("run-task", source)
        self.assertNotIn("append_record", source)
        self.assertNotIn('commands.add_parser("record")', source)


if __name__ == "__main__":
    unittest.main()
