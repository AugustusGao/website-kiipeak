# Editorial repair implementation plan

Use superpowers:executing-plans inline in existing checkout.
Spec: docs/superpowers/specs/2026-11-08-editorial-repair-design.md
Goal: durable review-feedback revision, fallback topics and independent morning/evening budgets.
Architecture: persisted batch state in settings; batch attribution in calls; structured revision schema; reusable editorial execution; systemd retry unit.

1. Write regression tests for feedback→revision→approval, repeated rejection→alternate, restart after quota→resume, distinct slot budgets, strict rejection and daily/idempotency limits. Observe failures.
2. Implement state/budget migration, revision prompts/schema, atomic call reservation, finite per-topic attempts and saved feedback; retry eligibility and fresh review for every rewrite. Keep render recovery.
3. Add retry CLI/service/timer, extend per-service timeout to accommodate bounded calls, prevent paused/expired retry, and update management copy/docs. Run full tests.
4. Back up/deploy; associate existing morning calls, seed held draft safely and trigger repair. Fresh independent review; fix significant issues with regression tests. Verify actual morning article in both languages and timer state, commit and report measured outcome.

Review focus: restart replay, quota/network partial steps, midnight/slot change, review schema and evidence identity, per-slot budget isolation, source freshness and publication timestamps.
