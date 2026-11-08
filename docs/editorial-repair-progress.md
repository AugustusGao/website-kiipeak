# Editorial repair progress
Plan: docs/superpowers/plans/2026-11-08-editorial-repair.md

User authorized automatic revision/review/publication and morning/evening coverage. Existing checkout retained.

- Implemented durable phase/article/feedback state, legacy call attribution, eight calls per slot/sixteen per date, one revision per topic and alternative selection, plus a 15-minute eligible retry service.
- Regression suite expanded from54 to68 tests; new feedback revision, quota resume, independent budgets, skip/fresh-evidence retry, crash recovery, schema dates and unpublished correction normalization pass locally.
- Fresh review confirmed three Important issues: unrelated evidence exclusion after invalid draft, feedback lost before logging, no-topic decisions exhausting topic slots. All reproduced and fixed with regression tests. Also fixed committed-publication crash idempotence with a failing test.
- Live first repair revealed the model returning timestamps in date-only fields; added explicit YYYY-MM-DD prompt and schema pattern. A further live validation caught an English internal-edit notice on an unpublished draft; deterministic preparation now clears that non-public notice, preserving new independent review.
- Recovered the held morning state after date-format correction, archived prior technical state, and kept all calls charged to the actual batch. No quota bypass or unreviewed publication.
- Morning batch 2026-11-08-0500 published through the new flow after eight recorded calls total (including its original draft/review). Article: https://kiipeak.com/articles/2026-11-08-2e523aa48e/ . Evening reserves its own eight calls.
- Final VPS Linux suite: 68 passed. Both public article language URLs return 200; batch is published, render_pending=false, and completed-batch replay makes no AI calls. Evening eligibility confirmed with eight calls available; edition/retry timers active and enabled.

- Date schema/causality prompt and non-public correction normalization are deployed. Codex execution timeouts now terminate the whole process group before retry; regression passed. All source changes committed on existing feat/kiipeak.
