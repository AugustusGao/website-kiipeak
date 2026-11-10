/* Cloudflare supplies the visitor's IP region; only the language is retained. */
(async () => {
  const key = 'kiipeak-language';
  const valid = value => value === 'en' || value === 'zh-CN';
  const current = document.documentElement.lang;
  const page = document.querySelector('meta[name="kiipeak-page"]');
  const link = document.querySelector('a.language-switch');
  // Includes localized 404 responses served at a different request URL.
  if (!link || !page || page.content !== location.pathname) return;

  const url = new URL(location.href);
  let preference = url.searchParams.get('lang');
  if (valid(preference)) {
    try {
      localStorage.setItem(key, preference);
      url.searchParams.delete('lang');
      history.replaceState(null, '', url.href);
    } catch (_) { /* Keep the parameter when persistent storage is blocked. */ }
  } else {
    try { preference = localStorage.getItem(key); } catch (_) { preference = null; }
  }

  const target = new URL(link.href, location.origin);
  target.search = url.search;
  target.hash = url.hash;
  const manualTarget = new URL(target.href);
  manualTarget.searchParams.set('lang', link.lang);
  link.href = manualTarget.href;
  let manualSelected = false;
  link.addEventListener('click', () => {
    manualSelected = true;
    try { localStorage.setItem(key, link.lang); } catch (_) { /* URL carries choice. */ }
  });

  let language = valid(preference) ? preference : 'en';
  if (!valid(preference)) {
    try {
      const response = await fetch('/cdn-cgi/trace', {
        cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(1500),
      });
      if (response.ok) {
        const trace = await response.text();
        const country = /^loc=([A-Z]{2})\r?$/m.exec(trace)?.[1];
        language = ['CN', 'HK', 'MO', 'TW'].includes(country) ? 'zh-CN' : 'en';
      }
    } catch (_) { /* Unavailable region detection defaults to English. */ }
  }
  if (!manualSelected && language !== current && language === link.lang) {
    // Automatic navigation must never turn a region result into a manual preference.
    if (!valid(preference)) target.searchParams.delete('lang');
    location.replace(target.href);
  }
})();
