# Changelog

## Unreleased

- Added side-effect-free `route-task` JSON decisions; removed R0.03 execution, subprocess, and router-side outcome writing.
- Migrated automatic routing to GPT-6 Luna Medium and Sol Medium/High, with bounded Astra escalation; removed legacy Terra agents while retaining historical GPT-5.6 records.
- Matched accepted GPT-6 efforts to the local Codex catalog; xhigh, max, and ultra remain manual-only.
- Added deterministic local task-card classification with conservative routing-axis handoff.
- Added GPT-6 Astra as the final evidence-gated escalation tier with bounded Low, Medium, and High workers.
- Kept Astra xhigh/max manual-only in the previous routing generation.

## 0.1.0 - 2026-07-15

- Added deterministic routing across GPT-5.6 Luna, Terra, and Sol.
- Added five exact model-effort Codex project agents.
- Added phase-aware native, `codex exec`, direct, and disclosed fallback modes.
- Added evidence-gated history overrides and bounded failure escalation.
- Added sandbox, approval-policy, mutable-path, privacy, and execution-provenance safeguards.
- Added 41 unit and package-contract tests.
