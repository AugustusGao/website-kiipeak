(() => {
  const input = document.getElementById('query'), results = document.getElementById('results'), status = document.getElementById('search-status');
  const english = input.dataset.lang === 'en';
  const prompt = english ? 'Enter a keyword to search published stories.' : '输入关键词，搜索已发布的精选解读。';
  let items = [];
  const show = () => {
    const q = input.value.trim().toLocaleLowerCase();
    const found = q ? items.filter(x => (x.title + x.summary + x.category).toLocaleLowerCase().includes(q)) : [];
    results.replaceChildren();
    status.textContent = q ? (english ? `${found.length} ${found.length === 1 ? 'story' : 'stories'} found` : `找到 ${found.length} 篇精选解读`) : prompt;
    found.forEach(x => {
      const card = document.createElement('article'); card.className = 'story';
      const label = document.createElement('span'); label.className = 'tag'; label.textContent = x.category;
      const h = document.createElement('h3'), link = document.createElement('a');
      if (!/^\/(?:en\/)?articles\/[a-z0-9-]+\/$/.test(x.url)) return;
      if (english !== x.url.startsWith('/en/')) return;
      link.href = x.url; link.textContent = x.title; h.append(link);
      const p = document.createElement('p'); p.textContent = x.summary;
      const date = document.createElement('div'); date.className = 'meta'; date.textContent = x.date;
      card.append(label, h, p, date); results.append(card);
    });
  };
  fetch(input.dataset.index || '/search.json').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(data => { items = data; show(); }).catch(() => { status.textContent = english ? 'Search is temporarily unavailable. Refresh or browse the topics.' : '搜索内容暂时无法载入，请稍后刷新或通过分类浏览。'; });
  input.addEventListener('input', show);
})();
