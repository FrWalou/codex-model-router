# Codex Model Router

[![CI](https://github.com/capitalparser/codex-model-router/actions/workflows/ci.yml/badge.svg)](https://github.com/capitalparser/codex-model-router/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)

codex-model-router = routing decision engine only. It reads a bounded task card, classifies it locally, applies GPT-6 policy and eligible read-only history, then returns routing JSON. It never launches Codex, runs tests, inspects Git, writes outcomes, or changes the active conversation model.

## Composition

```text
task/planner -> router -> routing JSON -> executor -> validator/outcome collector -> history/stats
```

The executor owns worker launch, sandbox and approval enforcement, mutable-path checks, and actual dispatch reporting. The validator/outcome collector owns verification and outcome writing. Graph inspection, learning, decomposition, and orchestration are separate components.

## Installation

Copy the skill and the seven exact GPT-6 agent definitions into a repository:

```bash
mkdir -p /path/to/your-repository/.agents/skills
mkdir -p /path/to/your-repository/.codex/agents
cp -R .agents/skills/codex-model-router /path/to/your-repository/.agents/skills/
cp .codex/agents/pas_*.toml /path/to/your-repository/.codex/agents/
```

Repository-scoped installation is recommended. Python 3.9+ is required for the advisor. Check your Codex account's model catalog with `codex debug models`; the GPT-6 model slugs and efforts are runtime-dependent. The package was tested with Codex CLI `0.156.1`.

## Triggering the router

Invoke `$codex-model-router` for a bounded model/effort choice, or use the CLI directly:

```bash
python3 .agents/skills/codex-model-router/scripts/advisor.py route-task \
  --task-file .github/CODEX_TASK.md --phase build
```

`route-task` is side-effect free. It reads the structured card and optional existing registry, but does not create a registry or execute the card. It does not accept raw-prompt input. Missing or malformed cards fail before a decision is emitted.

The JSON contract contains `schema_version`, `task_family`, `classification`, `phase`, `model`, `effort`, `model_version`, `policy_version`, `rule_id`, `agent_name` (or null), `automatic`, `next_escalation` (or null), `reason_labels`, and `dispatch_capability`. It never echoes task prose. `dispatch_capability` is advisory metadata, not proof of launch. Optional sandbox and approval flags can evaluate a proposed child boundary without executing it.

`classify`, `recommend-from-task`, `dispatch-from-task`, and explicit-axis `recommend`/`dispatch` remain available for compatibility. The legacy dispatch command may include a `fallback_command` suggestion; no router code executes it. `query` reads historical records.

## How automatic routing works

| Task shape | Static choice | Exact worker |
|---|---|---|
| Clear repeatable or verifiable high-volume | GPT-6 Luna Medium | `pas_luna_worker` |
| Balanced bounded implementation | GPT-6 Sol Medium | `pas_sol_worker` |
| Judgment, complex build, or deep/high-risk | GPT-6 Sol High | `pas_sol_analyst` |

The deterministic classifier uses verifiability, failure cost, volume, depth, decomposability, independent workstreams, validation evidence, and allowed-path spread. It returns stable signal labels, not task text. The exact automatic escalation chain is Luna Medium → Sol Medium → Sol High → Astra Low → Astra Medium → Astra High → blocked. Astra is never a static default. A verified failure of the exact current model/effort pair is required to advance. xhigh, max, and ultra are manual-only.

The selected `agent_name` is an exact registered mapping. The package also includes `pas_sol_max_worker` for explicit manual use and Astra Low/Medium/High workers for bounded escalation. A recommendation does not mean a worker ran.

## History read boundary

The router reads existing JSONL outcome records from `CODEX_MODEL_ROUTER_REGISTRY`, a repository ancestor's `Harness/sink/model_effort_router/outcomes.jsonl`, or `~/.codex/state/codex-model-router/outcomes.jsonl`. The router does not create or append this file. The standalone `record` command was removed; an external outcome collector must produce records.

History overrides require matching task family, axes, phase, and model generation, plus two recent verified passes for an exact automatic worker mapping and no verified failure. Historical GPT-5.6 records remain readable but cannot change GPT-6 recommendations. Manual-only efforts never become automatic through history. The router still accepts locally cataloged GPT-6 efforts as metadata, while automatic choices stay within the chain above.

## Safety boundaries

- A routing decision is not authorization to execute, modify files, commit, or push.
- The router never spawns a process or runs validation commands from the card.
- Actual execution must preserve the parent approval policy and a same-or-stricter sandbox.
- An external executor must enforce mutable paths and reject out-of-scope worker results.
- A separate collector must keep raw prompts, credentials, and sensitive source text out of outcome records; privacy is operator-enforced.
- The router never infers the current task from the globally newest rollout.
- Missing authority or ambiguous product decisions cannot be repaired by model escalation.

## Limitations

Model availability and custom-agent support depend on the Codex account and runtime. `codex_exec_ready` only states that supplied boundary metadata meets the advisor's checks; it does not assert that Codex is installed, available, or launched. This package has no executor, validator, stats aggregator, scheduler, Graphify integration, or learning engine.

## CLI reference

```bash
python3 .agents/skills/codex-model-router/scripts/advisor.py route-task --help
python3 .agents/skills/codex-model-router/scripts/advisor.py classify --help
python3 .agents/skills/codex-model-router/scripts/advisor.py recommend --help
python3 .agents/skills/codex-model-router/scripts/advisor.py query --help
```

## Testing

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
```
