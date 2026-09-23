import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ADVISOR_PATH = Path(__file__).resolve().parents[1] / "scripts" / "advisor.py"


def load_advisor():
    spec = importlib.util.spec_from_file_location("run_task_advisor", ADVISOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CARD = """# Tiny bounded fixture

## Objective
Check a single fixture without changing it.

## Allowed paths
- fixture.txt

## Acceptance criteria
The fixture contains the expected marker.

## Validation
python3 -m unittest discover -s tests
"""


def child_output(changed_paths=None, evidence=None):
    final = {"changed_paths": [] if changed_paths is None else changed_paths,
             "verification_evidence": evidence}
    return json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": json.dumps(final)}}) + "\n"


class RunTaskTests(unittest.TestCase):
    def setUp(self):
        self.advisor = load_advisor()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.card = self.root / "task.md"
        self.card.write_text(CARD, encoding="utf-8")
        self.args = argparse.Namespace(
            task_file=self.card, phase="build",
            parent_sandbox="workspace-write", exec_sandbox="read-only",
            parent_approval_policy="on-request", approval_boundary_confirmed=True,
            policy=self.advisor.DEFAULT_POLICY, registry=self.root / "outcomes.jsonl",
        )

    def run_mocked(self, *, returncode=0, changed_paths=None, evidence=None):
        child = subprocess.CompletedProcess(
            args=[], returncode=returncode,
            stdout=child_output(changed_paths, evidence), stderr="",
        )
        with mock.patch.object(self.advisor.subprocess, "run", return_value=child) as run:
            result = self.advisor.run_task(self.args)
        return result, run

    def test_valid_card_launches_one_luna_worker_with_pinned_boundary(self):
        result, run = self.run_mocked(evidence={"command": "fixture check", "result": "passed"})
        self.assertEqual((result["model"], result["effort"], result["agent_name"]),
                         ("gpt-6-luna", "medium", "pas_luna_worker"))
        self.assertEqual(result["dispatch_mode"], "codex_exec")
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["codex", "exec", "-m", "gpt-6-luna"])
        self.assertIn('model_reasoning_effort="medium"', command)
        self.assertIn('approval_policy="on-request"', command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(command[-1], "-")
        self.assertIn(CARD, run.call_args.kwargs["input"])
        self.assertEqual(result["execution_status"], "success")

    def test_unsafe_sandbox_blocks_without_launch(self):
        self.args.parent_sandbox = "read-only"
        self.args.exec_sandbox = "workspace-write"
        with mock.patch.object(self.advisor.subprocess, "run") as run:
            result = self.advisor.run_task(self.args)
        self.assertEqual(result["execution_status"], "blocked")
        self.assertIsNone(result["dispatch_mode"])
        run.assert_not_called()

    def test_missing_approval_policy_blocks_without_launch(self):
        self.args.parent_approval_policy = None
        with mock.patch.object(self.advisor.subprocess, "run") as run:
            result = self.advisor.run_task(self.args)
        self.assertEqual(result["execution_status"], "blocked")
        run.assert_not_called()

    def test_unconfirmed_approval_boundary_blocks_without_launch(self):
        self.args.approval_boundary_confirmed = False
        with mock.patch.object(self.advisor.subprocess, "run") as run:
            result = self.advisor.run_task(self.args)
        self.assertEqual(result["execution_status"], "blocked")
        run.assert_not_called()

    def test_missing_or_malformed_card_fails_safely(self):
        with mock.patch.object(self.advisor.subprocess, "run") as run:
            self.args.task_file = self.root / "missing.md"
            self.assertEqual(self.advisor.run_task(self.args)["execution_status"], "blocked")
            self.args.task_file = self.card
            self.card.write_text("# Unbounded task\nDo something.\n", encoding="utf-8")
            self.assertEqual(self.advisor.run_task(self.args)["execution_status"], "blocked")
        run.assert_not_called()

    def test_no_exact_worker_mapping_blocks_without_launch(self):
        with mock.patch.dict(self.advisor.MODEL_AGENTS, {}, clear=True):
            with mock.patch.object(self.advisor.subprocess, "run") as run:
                result = self.advisor.run_task(self.args)
        self.assertEqual(result["execution_status"], "blocked")
        run.assert_not_called()

    def test_nonzero_child_exit_is_failed(self):
        result, _ = self.run_mocked(returncode=7)
        self.assertEqual((result["execution_status"], result["child_exit_code"]),
                         ("failed", 7))
        self.assertEqual(result["recorded_outcome"], "partial")

    def test_missing_or_ambiguous_evidence_records_partial(self):
        result, _ = self.run_mocked(evidence={"command": "fixture check", "result": "maybe"})
        self.assertEqual(result["recorded_outcome"], "partial")
        self.assertIsNone(result["verification_evidence"])
        self.assertEqual(json.loads(self.args.registry.read_text())["outcome"], "partial")

    def test_out_of_scope_report_is_rejected(self):
        result, _ = self.run_mocked(
            changed_paths=["other.txt"],
            evidence={"command": "fixture check", "result": "passed"},
        )
        self.assertEqual(result["execution_status"], "out_of_scope")
        self.assertEqual(result["recorded_outcome"], "partial")

    def test_verified_success_records_exact_worker_without_raw_card(self):
        result, _ = self.run_mocked(
            changed_paths=["fixture.txt"],
            evidence={"command": "fixture check", "result": "passed"},
        )
        self.assertEqual(result["recorded_outcome"], "verified_pass")
        self.assertEqual(result["changed_paths"], ["fixture.txt"])
        registry_text = self.args.registry.read_text(encoding="utf-8")
        record = json.loads(registry_text)
        self.assertEqual((record["model"], record["effort"], record["phase"]),
                         ("gpt-6-luna", "medium", "build"))
        self.assertEqual((record["agent_name"], record["dispatch_mode"]),
                         ("pas_luna_worker", "codex_exec"))
        self.assertNotIn(CARD, registry_text)

    def test_child_cannot_store_raw_card_as_verification_command(self):
        result, _ = self.run_mocked(
            evidence={"command": CARD, "result": "passed"},
        )
        self.assertEqual(result["recorded_outcome"], "partial")
        self.assertNotIn(CARD, self.args.registry.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
