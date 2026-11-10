# IP language selection

User requests IP-based Chinese/English selection, with English as the default.
Use the existing site's Cloudflare /cdn-cgi/trace loc field: CN/HK/MO/TW
select zh-CN, all other or unavailable locations select en. Manual selection
takes precedence and persists in localStorage. Do not store IP addresses.

Approaches: origin redirects require proxy trust and per-visitor cache handling;
an external geo API adds a dependency and sends visitor information elsewhere.
Use a same-origin browser request to Cloudflare instead, preserving static caching.
This may briefly display the original language before navigation; without JS the
explicit language URLs and manual links still work.

Redirect only to an existing reciprocal language link, keeping query and hash.
Never redirect missing pages or articles lacking a translation. Abort geo lookup
after 1.5 seconds and fall back to English. Manual clicks during lookup win.
Use a language query parameter on manual switches so blocked storage cannot
cause an immediate bounce. Change x-default alternate to English.

Validation: execute routing script in Node with browser stubs for region mapping,
fallback, manual preference, disabled storage, race, query/hash and missing pages;
run Python suite; deploy only changed source/assets, rebuild, check public output.
