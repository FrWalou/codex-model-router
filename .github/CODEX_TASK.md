# R0.02 — Deterministic task classification

Status: CORRECTION REQUIRED

## Review finding

The implementation commit `e2457a00a09355e43317b031290bc19b8c140058` passes the requested tests, but the demonstrated classification exposes a semantic-scoping bug:

```json
{
  "task_family": "security-sensitive-change",
  "failcost": "high",
  "depth": "deep"
}
```

R0.02 itself is not a security-sensitive change. The classifier is matching words such as `security`, `auth`, `tenant`, `migration`, `concurrency`, and `architecture` from meta-specification sections that merely describe classifier rules/tests/non-goals.

This will systematically over-route task cards that discuss sensitive keywords as examples or requirements for the classifier rather than as properties of the implementation being performed.

Fix only this semantic-scope issue.

## Allowed paths

- .agents/skills/codex-model-router/scripts/advisor.py
- .agents/skills/codex-model-router/tests/test_advisor.py
- .agents/skills/codex-model-router/SKILL.md
- .agents/skills/codex-model-router/README.md
- README.md
- CHANGELOG.md

Do not modify policy.json, agent TOML files, CI, or unrelated files.

## Required behavior

### Section-aware semantic classification

For a structured task card, semantic risk/depth signals must come from execution-relevant task content, not from the entire Markdown document.

Prefer task content from sections such as:
- title
- Objective
- Required behavior
- Acceptance criteria / acceptance
- explicit implementation/scope requirements when present

Do NOT let the following sections raise semantic failcost/depth merely because they mention keywords as examples or meta-rules:
- Tests
- Validation
- Non-goals
- examples
- classifier signal/rule documentation
- completion/reporting instructions
- commit instructions

Allowed/mutable paths must continue to influence scope/depth separately.
Validation sections must continue to influence verifiability separately.
Workstreams sections must continue to influence decomposability separately.

For unstructured/minimally structured input where no execution-relevant section can be identified, preserve a conservative fallback rather than silently treating the task as cheap.

### Acceptance/confidence scoping

Do not infer acceptance merely because words such as `must` appear in tests, non-goals, reporting, or other meta sections.

A real Required behavior / Acceptance section should still count as acceptance evidence.

### Safety preservation

Real sensitive work must still floor correctly:
- `auth`, `credential`, `tenant`, `privacy`, `security` in Objective/Required behavior => failcost high
- destructive migration/remediation/external-write in execution-relevant content => failcost high
- concurrency/race/distributed invariants in execution-relevant content => depth at least medium
- architecture/cross-cutting signals in execution-relevant content => existing architecture depth floor

Do not weaken the existing conservative low-confidence fallback.

## Regression tests

Add focused tests covering at least:

1. A meta task that lists `security/auth/tenant/migration/concurrency/architecture` only under Signals/Tests/Non-goals does NOT become `security-sensitive-change` solely from those mentions.
2. `Non-goals: do not touch auth or tenant isolation` does NOT raise failcost by itself.
3. A real `Required behavior` containing auth/tenant/security still yields failcost=high.
4. A real `Required behavior` containing race/concurrency still applies the depth floor.
5. Validation commands remain detected after semantic scoping.
6. Allowed-path spread still affects depth/volume.
7. Low-confidence/unstructured text remains conservative.
8. Existing 74 tests continue to pass.

Use a regression fixture representative of the current R0.02 task card and demonstrate that its classification is no longer falsely security-sensitive.

The expected exact task family/depth need not be hard-coded if other legitimate scope signals apply, but failcost must not become high solely from meta keyword mentions.

## Validation

Run:

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
git diff --check
```

Then classify the current task card and report the result.

## Commit

Commit exactly:

```
fix: scope task classifier signals
```

Push normally to `dev`. Never force-push.

Then STOP and report:
- files changed
- semantic section-scoping behavior
- regression classification result
- tests/checks run
- commit SHA
- push result
