# R0.02.1 — Migrate automatic routing to GPT-6 Sol and Luna

Status: IN PROGRESS

## Objective

Migrate the router's normal automatic path from GPT-5.6 Luna/Terra/Sol to the current GPT-6 family while preserving the R0.02 classifier, safety boundaries, history isolation, and bounded Astra escalation.

Target automatic family:

```text
GPT-6 Luna -> GPT-6 Sol -> GPT-6 Astra
```

This brick is a model-generation migration only. Do not add prompt decomposition, Graphify, learning, quota accounting, or prompt execution orchestration yet.

## Codex runtime catalog is authoritative

This router targets Codex workers, not the public API model surface.

The local `codex debug models` catalog is therefore the runtime source of truth for:
- model slugs
- reasoning-effort values available in Codex
- custom-agent compatibility

Do NOT hard-code an API documentation capability matrix when it differs from the local Codex catalog.

Observed on the current local Codex installation:
- `gpt-6-luna` is present and does NOT list `none`
- `gpt-6-sol` is present and does NOT list `none`
- `gpt-6-sol` lists `ultra`
- `gpt-6-astra` lists `ultra`

Before changing model mappings, run `codex debug models` again and capture the complete exact effort list for each of:
- `gpt-6-luna`
- `gpt-6-sol`
- `gpt-6-astra`

If any required automatic tier from this task is unavailable locally, STOP and report.
Extra locally exposed manual tiers such as `ultra` are NOT a stop condition.

## Allowed paths

- .agents/skills/codex-model-router/references/policy.json
- .agents/skills/codex-model-router/scripts/advisor.py
- .agents/skills/codex-model-router/tests/**
- .agents/skills/codex-model-router/SKILL.md
- .agents/skills/codex-model-router/README.md
- .codex/agents/**
- .github/workflows/ci.yml
- README.md
- CHANGELOG.md

Do not modify .github/CODEX_TASK.md.

## Required static routing

Preserve rule IDs and classifier semantics where possible, but migrate model targets conservatively:

- `verifiable-high-volume` -> `gpt-6-luna` / `medium`
- `clear-repeatable-work` -> `gpt-6-luna` / `medium`
- `balanced-default` -> `gpt-6-sol` / `medium`
- `judgment-and-analysis` -> `gpt-6-sol` / `high`
- `complex-build` -> `gpt-6-sol` / `high`
- high-risk deep/ambiguous rules -> `gpt-6-sol` / `high`

Do not statically select Astra.

Do not automatically select `xhigh`, `max`, or `ultra` in this brick.
Do not require or use `none` automatically.

The R0.02 task classifier must remain semantically unchanged.

## Automatic escalation chain

Use a bounded, acyclic automatic chain:

```text
gpt-6-luna / medium
    -> gpt-6-sol / medium
    -> gpt-6-sol / high
    -> gpt-6-astra / low
    -> gpt-6-astra / medium
    -> gpt-6-astra / high
    -> blocked
```

No automatic transition may enter:
- any locally available `none`
- `xhigh`
- `max`
- `ultra`

Escalation remains evidence-gated: a stronger tier is chosen only after a verified failure of the current exact model/effort pair.

## Model/effort support

Add exact GPT-6 model metadata for:
- `gpt-6-luna`
- `gpt-6-sol`
- existing `gpt-6-astra`

For each GPT-6 model, the accepted effort set in the router must match the current local Codex catalog observed during this brick.

Important:
- locally supported manual efforts may be recorded and validated
- catalog support does NOT imply automatic routing eligibility
- `xhigh`, `max`, and `ultra` remain manual-only in this brick
- if `none` is not exposed by local Codex, do not add it merely because another OpenAI surface supports it

Document this distinction clearly.

## Agent migration

Automatic workers must match the new exact model/effort pairs.

Required automatic workers:
- `pas_luna_worker` -> `gpt-6-luna` / medium
- add `pas_sol_worker` -> `gpt-6-sol` / medium
- `pas_sol_analyst` -> `gpt-6-sol` / high
- existing Astra low/medium/high workers remain GPT-6 Astra

`pas_sol_max_worker` may be migrated to `gpt-6-sol` / max if max is in the local catalog, but stays explicit/manual-only.

Do not add automatic xhigh/max/ultra workers.

The two GPT-5.6 Terra workers are no longer part of the automatic path. Prefer removing them from the package if no compatibility contract requires them. If retained, clearly mark them legacy/manual-only and ensure neither static routing nor history can select them for GPT-6 tasks.

Do not rename a Terra worker while leaving Terra semantics behind.

Update docs and CI strict agent-count contract to the final package shape.

## History and generation safety

Do not delete existing outcome data or support for reading historical GPT-5.6 records.

Requirements:
- GPT-5.6 history must never override a GPT-6 recommendation.
- A GPT-5.6 verified failure must not escalate a GPT-6 recommendation.
- GPT-6 Luna/Sol/Astra records must use `model_version = "gpt-6"`.
- history override remains limited to an exact registered automatic model/effort worker.
- manual-only xhigh/max/ultra combinations never become automatic because of historical passes.
- if the local catalog exposes another manual-only effort, it must also stay out of automatic history override unless policy explicitly allows it.
- failure escalation remains cycle-protected.

## Backward compatibility

Preserve:
- explicit-axis `recommend`
- explicit-axis `dispatch`
- `classify`
- `recommend-from-task`
- `dispatch-from-task`
- registry/query behavior for valid historical GPT-5.6 records
- sandbox / approval / mutable-path / evidence contracts

Do not alter R0.02 semantic-scoping rules.

## Tests

Add/update focused tests covering at least:

1. clear repeatable work -> GPT-6 Luna Medium
2. verifiable high-volume work -> GPT-6 Luna Medium
3. fallback/default -> GPT-6 Sol Medium
4. judgment/complex build -> GPT-6 Sol High
5. high-risk deep/ambiguous -> GPT-6 Sol High
6. Luna Medium verified failure -> Sol Medium
7. Sol Medium verified failure -> Sol High
8. Sol High verified failure -> Astra Low
9. Astra Low -> Medium -> High -> blocked still works
10. no automatic xhigh/max/ultra
11. no automatic use of any locally unsupported effort
12. GPT-5.6 history cannot override GPT-6 recommendation
13. GPT-5.6 failure cannot alter GPT-6 escalation
14. every locally supported GPT-6 manual effort record validates correctly
15. locally unsupported effort records fail safely
16. unregistered manual combinations cannot claim native custom-agent readiness
17. exact worker mappings match the new GPT-6 model/effort pairs
18. Terra workers are absent from automatic routing; if retained, prove legacy/manual-only status
19. CI strict package count matches the actual agent set
20. all R0.02 classifier tests remain unchanged and passing
21. escalation remains acyclic and exhausts to blocked

## Demonstration

After tests, demonstrate machine-readable dispatch/recommendation output for:
- simple validator-backed task
- normal bounded implementation
- deep/high-risk task
- a synthetic verified Sol High failure leading to Astra Low

Report exact model + effort for each.

## Validation

Run:

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
git diff --check
```

Parse every `.codex/agents/pas_*.toml` with Python 3.12 `tomllib` and assert the exact final agent count used by CI.

## Non-goals

Do NOT:
- change classifier semantics
- add Graphify
- decompose prompts into phases
- execute arbitrary user prompts
- add outcomes aggregation/stats.json yet
- add learning or contextual bandits
- claim quota savings without measurement
- automatically use xhigh/max/ultra
- force API-documented effort values into the Codex runtime catalog

## Commit

Commit exactly:

```
feat: migrate routing to GPT-6 Sol and Luna
```

Push normally to `dev`. Never force-push.

Then STOP and report:
- files changed
- exact local Codex model catalog result for Luna/Sol/Astra
- final accepted effort set per GPT-6 model
- final automatic routing table
- final escalation chain
- legacy Terra handling
- final agent count
- tests/checks
- demonstration outputs
- commit SHA
- push result
