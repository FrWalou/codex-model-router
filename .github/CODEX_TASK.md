# R0.03 — Prompt input and deterministic phase planning

Status: IN PROGRESS

## Objective

Add the first user-facing prompt entry point for the router.

The router must accept either a raw prompt or a structured task card, deterministically decompose the requested work into a small set of bounded execution phases, classify each phase with the existing R0.02 classifier, and attach the existing GPT-6 model/effort recommendation to each phase.

This brick PLANS routing only. It must not launch Codex workers yet.

Target flow:

```text
prompt / task card
      ↓
deterministic phase planner
      ↓
bounded phases
      ↓
existing classifier per phase
      ↓
existing advisor per phase
      ↓
machine-readable routing plan
```

Keep this brick intentionally smaller than the full R0.03 vision. Graphify enrichment will be the next sub-brick after this planner is stable.

## Allowed paths

- .agents/skills/codex-model-router/scripts/**
- .agents/skills/codex-model-router/tests/**
- .agents/skills/codex-model-router/SKILL.md
- .agents/skills/codex-model-router/README.md
- README.md
- CHANGELOG.md

Do not modify:
- policy.json
- any .codex/agents/*.toml
- CI
- .github/CODEX_TASK.md

## Prompt entry points

Add a deterministic CLI entry point that accepts exactly one of:

```bash
python3 .agents/skills/codex-model-router/scripts/advisor.py plan-prompt \
  --prompt "Implement the change, add tests, and review auth safety."
```

or:

```bash
python3 .agents/skills/codex-model-router/scripts/advisor.py plan-prompt \
  --task-file .github/CODEX_TASK.md
```

An equivalent small interface is acceptable, but:
- raw prompt input must be supported
- task-file input must be supported
- the two inputs must be mutually exclusive
- malformed/empty input must fail safely
- no external dependency may be added

Do not persist raw prompts.

## Phase model

Use only the existing execution phase vocabulary:

- `plan`
- `build`
- `test`
- `qa`

A routing plan may contain more than one bounded `build` phase only when the prompt/task card names independently separable workstreams.

Every phase object must contain at least:

- `phase_id`: stable deterministic ID within the plan
- `phase`: plan | build | test | qa
- `task_family`
- `classification`
- `model`
- `effort`
- `rule_id`
- `reason_labels`: compact non-sensitive labels
- `depends_on`: phase IDs
- `parallelizable`: boolean

Do not include hidden reasoning or copied sensitive/raw prompt content in the machine-readable plan.

## Deterministic phase-planning rules

Use explicit reviewable rules, not an LLM.

### Build

Create a `build` phase for implementation/change work.

Documentation/config-only work still uses `build`; the existing classifier may route it cheaply.

### Test

Create a `test` phase when:
- the task has deterministic validation/test commands; or
- the task explicitly asks to add/run tests/checks.

The test phase should be independently classified. It should not inherit high failcost merely because the build phase is security-sensitive, unless the test work itself carries that risk.

### QA

Create a `qa` phase when:
- the task explicitly asks for review/audit/QA; or
- execution-relevant content is security/auth/credential/tenant/privacy/remediation/destructive-migration sensitive; or
- the build classification has high failcost.

QA should preserve the relevant safety floor and normally depend on build + test where both exist.

### Plan

Create a `plan` phase only when planning materially helps, such as:
- architecture/cross-cutting work
- deep scope
- multiple independent workstreams
- explicitly requested design/planning

Do not add a planning phase to every trivial task.

## Workstream decomposition

If the supplied structured task card contains multiple explicitly named independently verifiable workstreams using the existing R0.02 workstream semantics:

- produce one bounded build phase per workstream
- preserve deterministic ordering
- mark truly independent build phases `parallelizable=true`
- make test/QA dependencies explicit

Do not infer arbitrary parallel workstreams from prose.

For raw prompts without explicit structured workstreams, default to one build phase.

## Phase classification

Reuse the R0.02 classifier rather than implementing a second risk model.

Phase-specific classification must avoid semantic leakage between phases.

Examples:
- build auth change -> high failcost
- deterministic test execution -> should not automatically become high failcost just because the build phase touched auth
- QA of auth change -> retain high safety relevance
- docs-only build -> shallow/low when appropriate

The existing R0.02 section-aware semantics and conservative fallback remain authoritative.

## Routing

For each phase:
1. derive phase-specific classification
2. call the existing recommendation path
3. attach exact GPT-6 model + effort recommendation

Expected examples under the current R0.02.1 policy may include:
- repeatable validation/test work -> GPT-6 Luna Medium
- normal bounded build -> GPT-6 Sol Medium
- deep/high-risk build or QA -> GPT-6 Sol High
- Astra must NOT be selected statically

Do not implement verified-failure escalation inside planning; escalation still requires an actual recorded failure.

## Dependencies

The plan must encode execution order.

Examples:

```text
plan -> build -> test -> qa
```

or for independent workstreams:

```text
plan
  ├─ build-1
  └─ build-2
       ↓
      test
       ↓
       qa
```

Do not mark write phases parallelizable unless workstreams are explicitly independently verifiable.

## Privacy / persistence

- Do not write raw prompts to outcomes.jsonl or any state file.
- Do not add automatic persistence in this brick.
- Machine-readable reason labels must not echo prompt text.
- Existing registry privacy contracts remain unchanged.

## Non-goals

Do NOT:
- call Graphify yet
- launch Codex/custom agents
- call `codex exec`
- mutate repository files from the planner
- add outcome aggregation or stats.json
- add auto-learning/contextual bandits
- measure quota
- change GPT-6 routing policy
- alter worker definitions
- automatically select Astra
- add unrestricted autonomous execution

## Tests

Add focused tests covering at least:

1. raw ordinary implementation -> one build phase -> GPT-6 Sol Medium
2. raw implementation + explicit tests -> build + test
3. security/auth implementation -> build + qa, with relevant high safety classification
4. deep architecture task -> plan + build
5. structured card with validation -> test phase
6. explicit review/audit -> qa phase
7. independently verifiable named workstreams -> multiple build phases with deterministic IDs
8. non-independent workstreams -> single build phase
9. phase dependencies are deterministic and acyclic
10. no static phase selects Astra
11. test phase does not inherit unrelated build security keywords
12. QA preserves relevant security floor
13. identical prompt -> identical JSON-equivalent plan
14. empty prompt fails safely
15. missing task file fails safely
16. --prompt and --task-file together fail safely
17. reason labels do not echo a secret-looking token from input
18. existing 102+ repository tests remain passing
19. existing explicit-axis/classify/recommend/dispatch CLIs remain backwards compatible

## Demonstration

Demonstrate machine-readable plans for:

### A. Simple implementation

```text
Add a deterministic helper and run its unit tests.
```

### B. Security-sensitive implementation

```text
Add tenant-scoped credential validation, add deterministic tests, and perform a security review.
```

### C. Structured multi-workstream task card

Use a temporary fixture with two explicitly independently verifiable workstreams and show the dependency graph in JSON.

Report the exact model + effort chosen for every phase.

## Validation

Run:

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
git diff --check
```

Compile any new Python module added under `scripts/`.

## Commit

Commit exactly:

```
feat: plan routed phases from prompts
```

Push normally to `dev`. Never force-push.

Then STOP and report:
- files changed
- prompt input interface
- phase-planning rules
- demonstration plans
- tests/checks
- commit SHA
- push result
