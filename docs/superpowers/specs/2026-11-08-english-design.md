# English edition design

Approved scope: user selected complete bilingual UI, existing articles and future automated articles after reviewing the two alternatives (full bilingual vs UI only).

Chinese remains the default at existing URLs; English lives under /en/. A language switch preserves page context where a translation exists. English has localized home, categories, articles, about, search, RSS and 404; each language uses its own search index and canonical URLs, with reciprocal hreflang only for actual counterparts. No forced redirects based on browser language.

One article/event stays one record. English text is stored in payload.translations.en, sharing dates, source IDs and evidence with Chinese; a source-content fingerprint makes stale translations unavailable after corrections. Withdrawal removes both languages. Old Chinese-only articles continue working during migration.

Future Codex draft calls produce Chinese and English together; the independent review checks both against evidence and one another. Do not publish new bilingual content with missing/invalid English when the feature is enabled. Keep 05:00/20:00 Beijing timers, two articles/day and two calls per normal batch. Longer output consumes more subscription allowance even though call count stays unchanged.

Backfill the existing three articles with one translation call and a separate review call, using current full Chinese article text and original evidence. Track this one-time migration separately, validate all results, then persist translations transactionally without changing slugs, article dates or publication counts. Never publish machine-made placeholder translations on failure.

Implementer choices: shared translated templates and an in-code message catalog, no new service or paid API. Administration remains Chinese; correctness and withdrawal apply across languages. New translation requests after later corrections may use the same bounded backfill command. Deploy after tests and backup, verify real English content, language switching, search, source links and mobile layout. Preserve current static-release rollback and render locking.
