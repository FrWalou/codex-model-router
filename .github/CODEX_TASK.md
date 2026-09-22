# R0.01 — Add Astra-aware routing in shadow mode

Status: IN PROGRESS

## Objective

Extend Codex Model Router so it can recommend GPT-6 Astra as the final escalation tier while preserving the existing deterministic routing model, safety boundaries, and evidence-gated escalation.

This brick is routing-only. It must not introduce automatic task classification from CODEX_TASK.md or Graphify yet.

## Allowed paths

- .agents/skills/codex-model-router/references/policy.json
- .agents/skills/codex-model-router/scripts/advisor.py
- .agents/skills/codex-model-router/tests/**
- .agents/skills/codex-model-router/SKILL.md
- .agents/skills/codex-model-router/README.md
- .codex/agents/pas_astra_*.toml
- README.md
- CHANGELOG.md

Do not modify unrelated files.

## Required behavior

### Model support

Add `gpt-6-astra` as a supported model.

Support Astra efforts:
- low
- medium
- high
- xhigh
- max

Do not make xhigh or max automatically selectable by static policy or history.

### Escalation policy

Preserve the existing low-cost path:
- Luna
- Terra
- Sol

Add Astra only after Sol for genuinely difficult or high-consequence work.

Astra must not become the default for ordinary high-risk work merely because `failcost=high`.

Initial automatic ladder should be conservative:
- Sol/high failure may escalate to Astra/low or Astra/medium depending on the existing escalation structure
- Astra/high is allowed only after named verification failure(s)
- Astra/xhigh and Astra/max remain explicit/manual-only options

Do not silently weaken existing Sol/Luna/Terra behavior.

### Astra agents

Add exact model-effort custom agents only for combinations that the automatic policy can legitimately dispatch.

At minimum provide bounded Astra workers for the automatic Astra tiers introduced by this brick.

Every Astra worker must preserve the current safety contract:
- exact mutable paths
- verification evidence
- no authority expansion
- same-or-stricter sandbox
- compact handoff
- no claims for checks not run

### History / registry

Verified history may record Astra outcomes.

Automatic history override must never promote or retain:
- Astra xhigh
- Astra max
- any model/effort pair without an exact registered worker

A verified failure must move through a bounded escalation chain and never loop.

### Shadow-safe behavior

This brick must not add any background execution or implicit model switch.

The advisor may recommend Astra, but execution remains subject to the existing dispatch mechanism and capability checks.

## Tests

Add focused tests covering at least:

- Astra accepted as a valid model
- Astra outcome can be recorded
- correct Astra agent mapping
- Sol failure escalates into Astra according to the new chain
- Astra failure escalates one bounded step
- xhigh/max are never selected by static policy
- xhigh/max are never selected by verified-history override
- unknown/unregistered Astra model-effort combinations cannot claim native custom-agent readiness
- existing Luna/Terra/Sol routing tests remain unchanged and passing
- escalation cannot loop
- package contract includes the new Astra agent definitions

## Validation

Run:

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
git diff --check
```

If `codex debug models` is available locally, inspect it and report whether `gpt-6-astra` and the intended effort levels are exposed. Do not fail the brick solely because a particular local account does not expose Astra; keep the code capability-gated and report the limitation.

## Commit

Commit exactly:

```
feat: add Astra routing tier
```

Push normally to `dev`. Never force-push.

Then STOP and report:
- files changed
- routing behavior added
- tests/checks run
- whether local Codex exposed Astra
- commit SHA
- push result
