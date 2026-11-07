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
    from . import editor, i18n
    by_language = {'zh-CN': articles, 'en': []}
    for item in articles:
        translated = editor.english_for(item['data'])
        if translated:
            words = sum(len(section['text'].split()) for section in translated['sections'])
            by_language['en'].append(item | {'data': translated, 'title': translated['title'],
                'url': '/en' + item['url'], 'reading': max(2, round(words / 220))})
    paths = []
    try:
        shutil.copytree(ROOT / 'static', release / 'assets')
        for lang, localized in by_language.items():
            prefix = '/en' if lang == 'en' else ''
            t = i18n.translator(lang)
            categories = i18n.EN_CATEGORIES if lang == 'en' else CATEGORIES
            common = dict(categories=categories, base_url=base_url, articles=localized, lang=lang,
                          prefix=prefix, t=t, year=datetime.now().year,
                          updated=localized[0]['date'] if localized else None)
            def page(name, path, counterpart=True, **context):
                logical = '/' if path == 'index.html' else '/' + path.removesuffix('index.html')
                page_path = prefix + logical
                alternates = {'zh-CN': logical, 'en': '/en' + logical, 'x-default': logical} if counterpart else {lang: page_path}
                switch = (logical if lang == 'en' else '/en' + logical) if counterpart else None
                write_page(release / (prefix.lstrip('/') + '/' + path).lstrip('/'),
                    env.get_template(name).render(**(common | dict(page_path=page_path, alternates=alternates, switch_url=switch) | context)))
                if path != '404.html':
                    paths.append(page_path)
            page('home.html', 'index.html', title=t('看懂全球机器人前沿'), selected=None)
            for key, label in categories.items():
                page('home.html', f'category/{key}/index.html', title=label, selected=key,
                     articles=[a for a in localized if a['category'] == key])
            for item in localized:
                page('article.html', 'articles/' + item['slug'] + '/index.html', title=item['title'], article=item,
                     counterpart=lang == 'en' or editor.english_for(item['data']) is not None)
            page('about.html', 'about/index.html', title=t('关于与编辑准则'))
            page('search.html', 'search/index.html', title=t('搜索精选'))
            page('404.html', '404.html', title=t('页面未找到'))
            search = [{'title': a['title'], 'summary': a['data']['summary'], 'url': a['url'],
                       'category': categories[a['category']], 'date': a['date']} for a in localized]
            write_page(release / (prefix.lstrip('/') + '/search.json').lstrip('/'), json.dumps(search, ensure_ascii=False))
            rss = ET.Element('rss', version='2.0')
            channel = ET.SubElement(rss, 'channel')
            for k, v in [('title', 'KiiPeak · ' + t('前沿精选')), ('link', base_url + prefix + '/'),
                         ('description', t('看懂全球机器人前沿')), ('language', lang)]:
                ET.SubElement(channel, k).text = v
            for a in localized[:50]:
                entry = ET.SubElement(channel, 'item')
                for k, v in [('title', a['title']), ('link', base_url + a['url']), ('guid', base_url + a['url']), ('description', a['data']['summary'])]:
                    ET.SubElement(entry, k).text = v
            write_page(release / (prefix.lstrip('/') + '/feed.xml').lstrip('/'), '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(rss, encoding='unicode'))
        sitemap = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
        for path in paths:
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
