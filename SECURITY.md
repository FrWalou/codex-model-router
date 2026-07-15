# Security Policy

## Supported versions

Security fixes are applied to the latest commit on `main`. Tagged releases may be added after the public API and policy format stabilize.

## Reporting a vulnerability

Do not open a public issue for vulnerabilities, credential exposure, sandbox escapes, or approval-boundary bypasses. Use the repository's GitHub private vulnerability reporting or security advisory interface.

Include the affected version or commit, reproduction steps, expected boundary, actual behavior, and whether sensitive data was exposed. Please remove credentials, customer names, source documents, and raw prompts from the report.

## Security model

- The router never silently changes the active conversation model.
- `codex exec` requires an explicit parent approval policy and a same-or-stricter sandbox.
- Worker diffs outside declared mutable paths must be rejected.
- Outcome records are operational metadata, not a place for prompts, secrets, or customer content.

These controls reduce accidental privilege expansion but do not replace Codex sandboxing, repository permissions, code review, or organization policy.
