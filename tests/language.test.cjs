const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function visit(options = {}) {
  const current = options.current || 'zh-CN';
  const url = new URL(options.url || `https://kiipeak.com/${current === 'en' ? 'en/' : ''}`);
  const data = new Map(options.preference ? [['kiipeak-language', options.preference]] : []);
  const storage = {
    getItem: key => {if (options.blocked) throw Error('blocked'); return data.get(key) || null;},
    setItem: (key, value) => {if (options.blocked) throw Error('blocked'); data.set(key, value);},
  };
  let click, redirected, requests = 0;
  const link = {lang: current === 'en' ? 'zh-CN' : 'en',
    href: `https://kiipeak.com/${current === 'en' ? '' : 'en/'}about/`,
    addEventListener: (_, callback) => {click = callback;}};
  const context = {
    URL, AbortSignal, localStorage: storage,
    location: {href: url.href, pathname: url.pathname, search: url.search, hash: url.hash,
      origin: url.origin, replace: value => {redirected = value;}},
    history: {replaceState() {}},
    document: {documentElement: {lang: current},
      querySelector: selector => {
        if (selector === 'a.language-switch') return options.missing ? null : link;
        if (selector === 'meta[name="kiipeak-page"]') return {content: options.mismatch ? '/404.html' : url.pathname};
        return null;
      }},
    fetch: async (path, init) => {
      requests++;
      assert.equal(path, '/cdn-cgi/trace');
      assert.equal(init.cache, 'no-store');
      if (options.race) click({preventDefault() {}});
      if (options.failure) throw Error('network');
      return {ok: !options.httpError, text: async () => `ip=discarded\nloc=${options.country || 'US'}\n`};
    },
  };
  await vm.runInNewContext(fs.readFileSync('static/language.js', 'utf8'), context);
  return {redirected, requests, data, click, link};
}

for (const country of ['CN', 'HK', 'MO', 'TW']) {
  test(`${country} selects Chinese`, async () => {
    assert.equal((await visit({country, current: 'en'})).redirected, 'https://kiipeak.com/about/');
  });
}
for (const country of ['US', 'GB', 'JP', 'SG', 'XX', 'T1']) {
  test(`${country} selects English`, async () => {
    assert.equal((await visit({country})).redirected, 'https://kiipeak.com/en/about/');
  });
}
test('unknown region and network failures default to English', async () => {
  for (const options of [{failure: true}, {httpError: true}, {country: 'garbage'}]) {
    assert.equal((await visit(options)).redirected, 'https://kiipeak.com/en/about/');
  }
});
test('already correct language does not navigate', async () => {
  assert.equal((await visit({current: 'en'})).redirected, undefined);
  assert.equal((await visit({country: 'CN'})).redirected, undefined);
});
test('manual preference wins without querying region', async () => {
  const result = await visit({preference: 'zh-CN'});
  assert.equal(result.requests, 0);
  assert.equal(result.redirected, undefined);
});
test('preserves search and fragment', async () => {
  assert.equal((await visit({url: 'https://kiipeak.com/about/?q=robot#sources'})).redirected,
    'https://kiipeak.com/en/about/?q=robot#sources');
});
test('untranslated articles and 404 pages never redirect', async () => {
  for (const options of [{missing: true}, {mismatch: true}]) {
    assert.equal((await visit(options)).redirected, undefined);
  }
});
test('manual click during region lookup wins and is saved', async () => {
  const result = await visit({current: 'en', country: 'CN', race: true});
  assert.equal(result.data.get('kiipeak-language'), 'zh-CN');
  assert.equal(result.redirected, undefined);
  assert.match(result.link.href, /lang=zh-CN/);
});
test('manual language parameter prevents bouncing when storage is blocked', async () => {
  const result = await visit({blocked: true, country: 'US', url: 'https://kiipeak.com/?lang=zh-CN'});
  assert.equal(result.redirected, undefined);
  assert.equal(result.requests, 0);
});
test('blocked storage does not prevent region selection', async () => {
  assert.equal((await visit({blocked: true})).redirected, 'https://kiipeak.com/en/about/');
});
test('blocked storage preserves explicit choice across an opposite-language URL', async () => {
  assert.equal((await visit({blocked: true, current: 'en', country: 'US',
    url: 'https://kiipeak.com/en/?lang=zh-CN'})).redirected,
    'https://kiipeak.com/about/?lang=zh-CN');
});
