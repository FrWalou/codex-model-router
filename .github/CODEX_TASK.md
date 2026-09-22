# R0.01 — Astra-aware routing

Status: CORRECTION REQUIRED

## Review finding

The implementation commit `45ecfb4b24f79575876e7873b9f8e93a173c8784` adds three Astra agent TOML files, increasing the project-agent count from 5 to 8.

The existing GitHub Actions contract in `.github/workflows/ci.yml` still contains:

```python
assert len(files) == 5, files
```

Therefore the `validate-agents` CI job will fail on a pull request or on `main`, even though the focused unit tests pass.

This mismatch was not in the original R0.01 allowed paths. Fix only this integration contract.

## Allowed paths

- .github/workflows/ci.yml

Do not modify routing code, policy, agents, tests, docs, or any other file.

## Required change

Update the CI custom-agent validation so it accepts the current expected package shape with 8 `pas_*.toml` agent definitions.

Keep the check strict: do not remove the count assertion and do not weaken TOML parsing.

## Validation

Run:

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
python3 - <<'PY'
from pathlib import Path
import tomllib

files = sorted(Path(".codex/agents").glob("pas_*.toml"))
assert len(files) == 8, files
for path in files:
    tomllib.loads(path.read_text(encoding="utf-8"))
print(f"validated {len(files)} agent definitions")
PY
git diff --check
```

## Commit

Commit exactly:

```
fix: align CI with Astra agents
```

Push normally to `dev`. Never force-push.

Then STOP and report:
- file changed
- validations and results
- commit SHA
- push result
