# Contributing

Contributions are welcome when they preserve truthful execution provenance and bounded worker authority.

## Development

1. Create a focused branch from `main`.
2. Add or update a failing regression test before changing routing behavior.
3. Run the complete standard-library test suite.
4. Validate every custom-agent TOML against the current Codex model catalog.
5. Keep documentation explicit about native-agent, `codex exec`, and main-task fallback behavior.

```bash
python3 -m unittest discover -s .agents/skills/codex-model-router/tests -v
python3 -m py_compile .agents/skills/codex-model-router/scripts/advisor.py
codex debug models
```

## Pull requests

Explain the failure mechanism, behavior change, verification evidence, and security impact. Do not add automatic Ultra routing, recursive fan-out, overlapping write workers, hidden model switching, or a broader child permission boundary.

Never commit outcome registries, session logs, credentials, customer identifiers, raw prompts, or confidential source material.
