# IP language implementation

1. Add executable JavaScript regression tests and observe missing-feature failure.
2. Implement same-origin geo selection and persistent manual override; integrate
   shared template, English x-default and missing-page guard.
3. Run Node and Python tests, inspect diff, back up live release, deploy changed
   files, rebuild under existing render lock, verify public assets and geo endpoint.

Completed 2026-11-10: 19 Node tests and 68 Python tests pass. Independent review
found a blocked-storage manual-choice bounce; regression reproduced and fix verified.
Deployed only language.js, base.html and render.py, rebuilt static release with the
existing render lock. Backup: /var/backups/kiipeak-language-20261110T132721Z.
Public Chrome with actual geo response navigated root to /en/ with no page errors.
Public Chrome with controlled trace responses checked CN/HK/TW Chinese, US/XX English,
query/fragment preservation, manual Chinese choice surviving reload on US IP,
and English fallback after lookup failure. These region cases simulate Cloudflare's
response; they are not requests physically sent from each tested region.
