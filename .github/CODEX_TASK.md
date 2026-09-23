# R0.03 — Execute one routed task end-to-end

Status: IN PROGRESS

## Objective

Stop adding planning features and make the router actually useful.

Implement the smallest end-to-end execution path for ONE already-bounded task card:

```text
CODEX_TASK.md
    ↓
existing classifier
    ↓
existing GPT-6 router
    ↓
selected model + effort
    ↓
codex exec
    ↓
worker result
```

No raw-prompt input. No prompt decomposition. No Graphify. No learning. No stats aggregation.

The goal of this brick is simple: given a structured task card, the router must be able to select the right existing worker/model/effort and actually launch Codex to execute that bounded task.

## Allowed paths

- .agents/skills/codex-model-router/scripts/**
- .agents/skills/codex-model-router/tests/**
- .agents/skills/codex-model-router/SKILL.md
- .agents/skills/codex-model-router/README.md
- README.md
- CHANGELOG.md

Do not modify:
- policy.json
- .codex/agents/**
- CI
- .github/CODEX_TASK.md

## Required CLI

Add a single execution command, for example:

```bash
python3 .agents/skills/codex-model-router/scripts/advisor.py run-task \
  --task-file .github/CODEX_TASK.md \
  --phase build \
  --parent-sandbox workspace-write \
  --exec-sandbox workspace-write \
  --parent-approval-policy on-request \
  --approval-boundary-confirmed
```

Equivalent naming is acceptable, but keep the interface minimal.

The command must:

1. read the supplied task card
2. classify it with the existing R0.02 classifier
3. obtain the recommendation with the existing GPT-6 router
4. build the existing dispatch contract
5. refuse execution unless `codex_exec_ready=true`
6. launch exactly one bounded `codex exec` worker using the recommended model + effort
7. pass the task card content to the child as the bounded task
8. preserve the exact parent approval policy and same-or-stricter sandbox
9. capture the child exit code and compact result
10. return a machine-readable execution summary

Do not silently fall back to another model when the selected one cannot launch.

## Execution contract

The child prompt must clearly state:

- execute only the supplied bounded task
- honor the task card's allowed paths
- do not widen scope
- run the validation requested by the task card
- report changed paths and verification evidence
- stop on missing authority or unavailable capability

Do not add unrelated orchestration logic.

## Scope protection

Before execution:
- reject missing or malformed task files
- reject execution when approval/sandbox boundary is not explicit and safe
- reject execution when no exact worker/model-effort mapping exists

After execution:
- collect the worker-reported changed paths
- if the child output exposes changed paths outside the task card's allowed paths, mark the execution as rejected/out-of-scope

Do not attempt automatic rollback in this brick.

## Output

Return JSON containing at least:

- task_family
- classification
- model
- effort
- agent_name
- dispatch_mode
- child_exit_code
- execution_status: success | failed | blocked | out_of_scope
- changed_paths when reported
- verification_evidence when reported

Do not persist raw task contents.

## Outcome recording

Keep this minimal.

If the child completes and provides verification evidence:
- reuse the existing outcome registry format
- record the actual model, effort, phase, agent_name, dispatch_mode and verified result

If verification is missing or ambiguous:
- record `partial`, not `verified_pass`

Do not add stats.json or learning yet.

## Non-goals

Do NOT:
- accept arbitrary raw prompts
- decompose tasks into plan/build/test/qa
- call Graphify
- run multiple workers
- parallelize
- add auto-learning
- add contextual bandits
- add quota accounting
- add a scheduler
- change routing policy
- change worker definitions
- automatically commit or push unless the supplied task card itself explicitly requires it

## Tests

Add focused tests covering at least:

1. valid bounded task selects the expected GPT-6 model/effort
2. unsafe sandbox boundary blocks execution
3. missing approval policy blocks execution
4. missing task file fails safely
5. malformed task card fails safely
6. no exact registered worker blocks execution
7. child command pins recommended model
8. child command pins recommended effort
9. child command preserves exact approval policy
10. child command uses same-or-stricter sandbox
11. child non-zero exit -> failed
12. missing verification -> partial outcome
13. reported out-of-scope changed path -> out_of_scope
14. successful verified execution -> verified_pass record
15. raw task text is not written to the registry
16. existing 102+ tests remain passing
17. existing classify/recommend/dispatch CLI behavior remains backward compatible

Mock the child process in unit tests. Do not consume Codex quota in the automated test suite.

## Real smoke test

After unit tests pass, perform ONE real local smoke test with a tiny temporary task card that is:
- read-only or changes only a temporary fixture
- deterministic
- cheap
- explicitly bounded

The real smoke test must prove that:
- the router selected the model/effort
- `codex exec` actually launched
- the child returned
- the router produced the execution summary

Do not use Astra for the smoke test.

If running a real Codex child would consume an unreasonable remaining quota, report that and stop after the mocked integration tests instead of burning the quota.

## Validation

Run:

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
git diff --check
```

Compile any new Python module under `scripts/`.

## Commit

Commit exactly:

```
feat: execute routed Codex tasks
```

Push normally to `dev`. Never force-push.

Then STOP and report:
- files changed
- run-task CLI
- routing decision used in tests
- mocked integration results
- real smoke-test result, if executed
- outcome-recording behavior
- tests/checks
- commit SHA
- push result
