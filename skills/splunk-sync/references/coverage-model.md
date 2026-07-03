# Coverage Model — splunk-sync (moved)

> **This skill has been renamed to `$splunk-detector-publish`.**
>
> The detector coverage model now lives at its canonical location:
> [`../../splunk-detector-publish/references/coverage-model.md`](../../splunk-detector-publish/references/coverage-model.md).

`splunk-sync` is a deprecated compatibility stub (see this skill's `SKILL.md`).
Its behavior is identical to `splunk-detector-publish`; only the name changed. To
avoid a duplicate that silently drifts from the canonical model, this file is
intentionally a pointer, not a copy. Read the canonical `coverage-model.md` under
`splunk-detector-publish/references/` for the COVERED / GAP / UNCERTAIN matching
rules, the AutoDetect advisory, the idempotency (diff-before-create + 409
tolerance) model, and worked examples.
