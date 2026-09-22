# R0.02 — Deterministic task classification

Status: IN PROGRESS

## Objective

Add a local, zero-LLM classifier that can read a structured Codex task card and derive the routing axes required by the existing advisor.

This brick automates classification of ONE bounded task/phase. It does not yet decompose a multi-phase prompt, invoke Graphify, launch workers, or measure quota.

The classifier must be deterministic, explainable, conservative, and safe to run before Codex spends model quota.

## Allowed paths

- .agents/skills/codex-model-router/scripts/**
- .agents/skills/codex-model-router/tests/**
- .agents/skills/codex-model-router/SKILL.md
- .agents/skills/codex-model-router/README.md
- README.md
- CHANGELOG.md

Do not modify policy.json or any existing agent TOML in this brick.

## Required behavior

### New classifier

Add a deterministic classifier that accepts either:
- a task-card file path; or
- explicit task text via a testable function boundary.

It must derive the existing routing axes:
- task_family
- verifiable: yes | partial | no
- failcost: low | mid | high
- volume: low | mid | high
- depth: shallow | medium | deep
- decomposable: yes | no
- workstreams: integer >= 1

Also return:
- confidence: low | medium | high
- reasons: compact non-sensitive signal labels, not copied task prose

### Signals

Use explicit, reviewable rules. At minimum consider:

- validation/tests/check commands -> stronger verifiability
- docs/config-only scope -> lower depth/failcost unless contradicted
- auth/credentials/tenant/privacy/security/deletion/migration/remediation/external-write signals -> failcost floor
- concurrency/race/distributed/cross-package/architecture signals -> depth floor
- number and spread of allowed mutable paths -> depth/volume signals
- multiple independent named workstreams -> decomposability/workstream count
- missing/ambiguous acceptance or validation -> lower confidence / weaker verifiability

Do not infer secrets, customer data, or business-specific semantics from arbitrary prose.

### Safety floors

The classifier must be conservative:
- security/auth/credential/tenant-isolation/remediation/destructive migration => failcost=high
- concurrency/race/distributed invariants => depth at least medium
- architecture/cross-cutting changes => depth=deep when scope supports it
- no deterministic validation => verifiable cannot be yes
- low confidence must never cause a cheaper route than a conservative fallback

Do not automatically choose a model inside the classifier. It produces axes only; the existing advisor remains the routing authority.

### CLI integration

Expose a CLI path that can classify a task card and emit machine-readable JSON.

Preferred shape:

```bash
python3 .agents/skills/codex-model-router/scripts/advisor.py classify --task-file .github/CODEX_TASK.md
```

or an equally small compatible interface.

Do not add an external dependency.

### Advisor handoff

Provide a deterministic way to feed the classification result into the existing recommendation/dispatch flow without manually retyping all axes.

This may be:
- a new advisor subcommand; or
- a shared function used by classify + dispatch-from-task.

Keep current explicit-axis CLI behavior backwards compatible.

### Tests

Add focused tests covering at least:

- docs-only task -> low/shallow/verifiable when validation exists
- ordinary bounded implementation -> mid/medium
- auth/tenant/security task -> high failcost
- concurrency/race task -> medium-or-deep depth floor
- destructive migration/remediation/external-write task -> high failcost
- no validation -> not fully verifiable
- allowed-path spread affects depth conservatively
- low-confidence classification cannot under-route below conservative fallback
- deterministic identical input -> identical JSON-equivalent output
- reasons contain signal labels and do not echo sensitive/raw task prose
- malformed/missing task file fails safely
- existing explicit-axis advisor CLI/tests remain passing

## Non-goals

Do NOT:
- decompose one prompt into plan/build/test/qa phases yet
- integrate Graphify yet
- call Luna/Qwen/Jev/any model
- launch Codex workers automatically
- change Astra escalation policy
- add quota accounting yet
- inspect arbitrary repository files beyond the explicitly supplied task card

## Validation

Run:

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
git diff --check
```

If a new Python script is added under scripts/, compile it too.

Demonstrate classification on the current task card and include the resulting axes in the completion report.

## Commit

Commit exactly:

```
feat: classify task cards for routing
```

Push normally to `dev`. Never force-push.

Then STOP and report:
- files changed
- classification rules added
- current task-card classification result
- tests/checks run
- commit SHA
- push result
