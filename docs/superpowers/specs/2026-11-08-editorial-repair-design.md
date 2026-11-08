# Automatic editorial correction and morning/evening coverage

User request: automatically revise rejected drafts, verify again and publish, targeting one morning and one evening story. Existing 05:00/20:00 Asia/Shanghai starts and bilingual integrity remain.

Rejected feedback must be saved with the batch and supplied to a revision call that edits both Chinese and English. Every changed draft gets a fresh independent review against the original evidence; deterministic validation still applies. One revision per topic, then switch to another candidate; at most two topics/eight calls per batch. Normal success remains two calls. The previous four-call daily cap is replaced by eight reserved calls per slot (16 per date) so morning failures cannot exhaust the evening allowance. Calls gain batch attribution; historical calls are conservatively attributed using their recorded start timestamps.

Persist phase/article/review feedback/excluded source IDs across process restarts and quota/network failures. Resume a held current batch from its saved draft. Approval must be strict boolean true with empty issues. Never treat review failure as authorization to lower evidence standards. Rejected candidates may be replaced by another recent source, without publishing duplicate events.

A root-owned systemd retry service checks every 15 minutes under the existing pipeline lock. Retry only the active same-day slot (not before the first slot, and not after midnight), until success, capacity exhausted, pause or next slot. Respect retry-after/cooldown; repeated no-topic results wait for newer candidates. Completed slots are idempotent. Each day remains at most two articles, each batch at most one. Real shared subscription exhaustion or absent usable evidence can still delay publication.

Deploy with database backup; migrate current held batch and call attribution without consuming new selection calls. Run the morning repair through actual Codex and review; publish only on success and verify both public languages. Keep unrelated services untouched. Log revisions, topic switches and remaining limits for management.
