import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
AGENT_DIR = REPO_ROOT / ".codex" / "agents"
SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "codex-model-router"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
README_PATH = SKILL_ROOT / "README.md"
EXPECTED_AGENTS = {
    "pas_luna_worker.toml": ("pas_luna_worker", "gpt-5.6-luna", "medium"),
    "pas_terra_worker.toml": ("pas_terra_worker", "gpt-5.6-terra", "medium"),
    "pas_terra_builder.toml": ("pas_terra_builder", "gpt-5.6-terra", "high"),
    "pas_sol_analyst.toml": ("pas_sol_analyst", "gpt-5.6-sol", "high"),
    "pas_sol_max_worker.toml": ("pas_sol_max_worker", "gpt-5.6-sol", "max"),
    "pas_astra_low_worker.toml": ("pas_astra_low_worker", "gpt-6-astra", "low"),
    "pas_astra_medium_worker.toml": ("pas_astra_medium_worker", "gpt-6-astra", "medium"),
    "pas_astra_high_worker.toml": ("pas_astra_high_worker", "gpt-6-astra", "high"),
}


class ProjectAgentContractTests(unittest.TestCase):
    def test_project_agents_exist_with_expected_models(self):
        for filename, (name, model, effort) in EXPECTED_AGENTS.items():
            with self.subTest(filename=filename):
                text = (AGENT_DIR / filename).read_text(encoding="utf-8")
                self.assertIn(f'name = "{name}"', text)
                self.assertIn(f'model = "{model}"', text)
                self.assertIn(f'model_reasoning_effort = "{effort}"', text)

    def test_project_agents_require_scope_and_evidence_reporting(self):
        for filename in EXPECTED_AGENTS:
            with self.subTest(filename=filename):
                text = (AGENT_DIR / filename).read_text(encoding="utf-8")
                self.assertIn("mutable paths", text.lower())
                self.assertIn("verification evidence", text.lower())
                self.assertIn("missing authority", text.lower())

    def test_astra_agents_require_same_or_stricter_sandbox(self):
        for filename in EXPECTED_AGENTS:
            if not filename.startswith("pas_astra_"):
                continue
            with self.subTest(filename=filename):
                text = (AGENT_DIR / filename).read_text(encoding="utf-8")
                self.assertIn("same-or-stricter sandbox", text.lower())


class SkillDocumentationContractTests(unittest.TestCase):
    def test_skill_requires_capability_gated_actual_dispatch(self):
        text = SKILL_PATH.read_text(encoding="utf-8")
        for required in (
            "dispatch_mode",
            "native_custom_agent",
            "codex_exec",
            "main_task_fallback",
            "main_task_direct",
        ):
            self.assertIn(required, text)
        self.assertIn("Do not claim the active task changed models", text)

    def test_skill_keeps_micro_tasks_in_main_task(self):
        text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("task_scope=micro", text)
        self.assertIn("main task", text.lower())

    def test_skill_enforces_parent_boundary_and_rejects_scope_violations(self):
        text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("same or stricter", text.lower())
        self.assertIn("codex_exec_ready", text)
        self.assertIn("Reject the worker result", text)
        self.assertIn("out-of-scope", text)

    def test_readme_covers_public_installation_operation_and_limits(self):
        text = README_PATH.read_text(encoding="utf-8")
        for heading in (
            "## Installation",
            "## How automatic routing works",
            "## Triggering the router",
            "## Safety boundaries",
            "## Limitations",
            "## Testing",
        ):
            self.assertIn(heading, text)
        self.assertIn(".agents/skills/codex-model-router", text)
        self.assertIn(".codex/agents", text)
        self.assertIn("does not silently switch", text.lower())
        self.assertIn("operator-enforced", text.lower())
        self.assertIn("same or stricter", text.lower())


if __name__ == "__main__":
    unittest.main()
