import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .editor import CATEGORIES

ROOT = Path(__file__).resolve().parents[1]


def safe_link(url):
    try:
        p = urlsplit(url)
        return url if p.scheme in ('https', 'http') and p.hostname and not p.username else '#'
    except ValueError:
        return '#'


def write_page(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


def build(c, output_root, base_url='https://kiipeak.com'):
    from .worker import lock
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    # All callers (including administration) serialize before selecting their snapshot.
    with lock(root / 'render.lock', blocking=True):
        return _build(c, root, base_url)


def _build(c, output_root, base_url):
    from . import db
    root = Path(output_root)
    releases = root / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / (datetime.now().strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:8])
    release.mkdir()
    activated = False
    env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape(['html', 'xml']))
    env.filters['safe_link'] = safe_link
    articles = []
    c.execute('BEGIN')
    snapshot_revision = db.setting(c, 'content_revision', 0)
    for row in c.execute("SELECT * FROM articles WHERE status='published' ORDER BY published_at DESC"):
        item = dict(row)
        item['data'] = json.loads(item['payload'])
        item['sources'] = json.loads(item['evidence'])
        item['url'] = '/articles/' + item['slug'] + '/'
        item['date'] = item['local_day']
        item['reading'] = max(2, round(sum(len(s['text']) for s in item['data']['sections']) / 350))
        articles.append(item)
    c.commit()
    common = dict(categories=CATEGORIES, base_url=base_url, articles=articles,
                  year=datetime.now().year, updated=articles[0]['date'] if articles else None)
    def page(name, path, **context):
        write_page(release / path, env.get_template(name).render(**(common | context)))
    try:
        shutil.copytree(ROOT / 'static', release / 'assets')
        page('home.html', 'index.html', title='看懂全球机器人前沿', selected=None)
        for key, label in CATEGORIES.items():
            page('home.html', f'category/{key}/index.html', title=label, selected=key,
                 articles=[a for a in articles if a['category'] == key])
        for item in articles:
            page('article.html', item['url'].strip('/') + '/index.html', title=item['title'], article=item)
        page('about.html', 'about/index.html', title='关于与编辑准则')
        page('search.html', 'search/index.html', title='搜索精选')
        page('404.html', '404.html', title='页面未找到')
        search = [{'title': a['title'], 'summary': a['data']['summary'], 'url': a['url'],
                   'category': CATEGORIES[a['category']], 'date': a['date']} for a in articles]
        write_page(release / 'search.json', json.dumps(search, ensure_ascii=False))
        rss = ET.Element('rss', version='2.0')
        channel = ET.SubElement(rss, 'channel')
        for k, v in [('title', 'KiiPeak · 全球机器人前沿'), ('link', base_url), ('description', '面向科技爱好者的机器人精选解读'), ('language', 'zh-CN')]:
            ET.SubElement(channel, k).text = v
        for a in articles[:50]:
            item = ET.SubElement(channel, 'item')
            for k, v in [('title', a['title']), ('link', base_url + a['url']), ('guid', base_url + a['url']), ('description', a['data']['summary'])]:
                ET.SubElement(item, k).text = v
        write_page(release / 'feed.xml', '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(rss, encoding='unicode'))
        sitemap = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
        for path in ['/', '/about/', '/search/'] + [f'/category/{k}/' for k in CATEGORIES] + [a['url'] for a in articles]:
            ET.SubElement(ET.SubElement(sitemap, 'url'), 'loc').text = base_url + path
        write_page(release / 'sitemap.xml', ET.tostring(sitemap, encoding='unicode'))
        write_page(release / 'robots.txt', f'User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n')
        if os.name != 'nt':
            # The orchestrator may run as root to switch to the isolated AI identity.
            # Published files remain owned by the publisher and readable by Nginx.
            owner = None
            if os.geteuid() == 0 and root == Path('/var/www/kiipeak'):
                import pwd
                account = pwd.getpwnam('kiipeak')
                owner = (account.pw_uid, account.pw_gid)
            for path in [release] + list(release.rglob('*')):
                path.chmod(0o755 if path.is_dir() else 0o644)
                if owner:
                    os.chown(path, *owner)
        current = root / 'current'
        if os.name == 'nt':
            # Windows preview without the symbolic-link privilege; production uses atomic symlinks.
            temp = root / 'current-next'
            if temp.exists():
                shutil.rmtree(temp)
            shutil.copytree(release, temp)
            previous = root / 'previous'
            if previous.exists():
                shutil.rmtree(previous)
            if current.exists():
                current.rename(previous)
            try:
                temp.rename(current)
            except Exception:
                if previous.exists():
                    previous.rename(current)
                raise
        else:
            temporary_link = root / ('next-' + uuid.uuid4().hex)
            temporary_link.symlink_to(release, target_is_directory=True)
            os.replace(temporary_link, current)
        activated = True
        c.execute("INSERT OR REPLACE INTO settings VALUES ('rendered_revision',?)", (str(snapshot_revision),))
        c.execute("""UPDATE settings SET value='false' WHERE key='render_pending'
            AND COALESCE((SELECT CAST(value AS INTEGER) FROM settings WHERE key='content_revision'),0)=?""", (snapshot_revision,))
        c.commit()
        try:
            for old in sorted(releases.iterdir(), reverse=True)[4:]:
                if old != release:
                    shutil.rmtree(old)
        except OSError:
            db.log(c, 'render', 'warning', '旧版本清理未完成，当前在线版本已保留')
        return release
    except Exception:
        if not activated:
            shutil.rmtree(release, ignore_errors=True)
        raise
