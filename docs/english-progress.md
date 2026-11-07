# English edition progress

Plan: docs/superpowers/plans/2026-11-08-english.md
Scope: user selected complete bilingual site and existing/future articles.

- Task 1 and 2: implemented; 52 local tests pass, including language routes, source binding, stale exclusion, withdrawal and atomic independently reviewed backfill.
- Fresh code review of 3fb6af3..778470c found no Critical/Important issue; empty English Correction box finding was reproduced and corrected, verified by a regression assertion.
- Live first backfill translated successfully but its review rejected ambiguous year omission; no article payload changed. Refined translation dates and supplied the full rendered English article (including shared event metadata) to review; regression verifies metadata is included.
- Second live backfill and its independent review succeeded for all three articles. Full bilingual publication is enabled and payload fingerprints are valid.
- Public Chinese and English routes, English RSS/search/category/about/article all return 200; missing English route returns localized 404 with status 404.
- Browser English search finds the real Ctrl-F article. Native link navigation and language switching preserve the article slug in both directions. English mobile article has width375/scrollWidth375, correct original source and no empty Correction box. Desktop screenshot saved at artifacts/english-home-desktop.png.
- Final suite: 54 tests passed on Windows and VPS Linux. Database has three published articles and three valid English translations; both search indexes and RSS feeds each contain three items.
- Timers remain 05:00/20:00 Asia/Shanghai with no randomized delay; normal per-batch two-call flow unchanged. One-time backfill used two attempts (four recorded calls), with the rejected first attempt publishing nothing.
- No unresolved functional review findings. Live checks covered the reviewer-deferred routing and layout; translation fidelity was independently reviewed before publishing and manually spot-checked on the full Ctrl-F article.
- Management remains Chinese as scoped; project stays on existing feat/kiipeak branch and is deployed on the VPS.
