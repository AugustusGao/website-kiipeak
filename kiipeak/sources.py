"""Bounded public-web ingestion. Redirects are validated at every hop."""
import ipaddress
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from . import db

HEADERS = {'User-Agent': 'KiiPeakBot/1.0 (+https://kiipeak.com/about/)'}
MAX_BYTES = 2_000_000
KEYWORDS = ('robot', 'embodied', 'humanoid', 'manipulat', 'dexter', 'locomotion', '机器人', '具身')


def canonical_url(url):
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', urlencode(sorted(query)), ''))


def check_url(url):
    p = urlsplit(url)
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
        raise ValueError('仅允许无凭据的公开 HTTP(S) 地址')
    if p.port not in (None, 80, 443):
        raise ValueError('不允许的端口')
    try:
        addresses = [ipaddress.ip_address(p.hostname)]
    except ValueError:
        addresses = [ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM)]
    if not addresses or any(not a.is_global for a in addresses):
        raise ValueError('不允许访问非公网地址')
    return url


def fetch(url, limit=MAX_BYTES):
    session = requests.Session()
    session.trust_env = False
    for _ in range(5):
        check_url(url)
        with session.get(url, headers=HEADERS, timeout=(8, 20), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(32768):
                size += len(chunk)
                if size > limit:
                    raise ValueError('来源内容超过大小上限')
                chunks.append(chunk)
            encoding = response.encoding
            if not encoding or encoding.lower() == 'iso-8859-1':
                encoding = 'utf-8'
            return b''.join(chunks).decode(encoding, errors='replace'), url
    raise ValueError('重定向次数超过上限')


def extract(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'noscript']):
        tag.decompose()
    body = soup.find('article') or soup.find('main') or soup.body or soup
    return '\n'.join(x.strip() for x in body.get_text('\n').splitlines() if x.strip())[:18000]


def load_sources(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def collect(c, config_path):
    import feedparser
    count = 0
    override = db.setting(c, 'sources', None)
    for source in override if override is not None else load_sources(config_path):
        if not source.get('enabled', True):
            continue
        try:
            raw, final_url = fetch(source['url'])
            if source['kind'] == 'feed':
                feed = feedparser.parse(raw)
                if not feed.entries:
                    raise ValueError('没有可识别的订阅条目')
                entries = [{'url': e.get('link', ''), 'title': e.get('title', ''),
                            'summary': BeautifulSoup(e.get('summary', ''), 'html.parser').get_text(),
                            'date': e.get('published') or e.get('updated', '')} for e in feed.entries[:12]]
            else:
                soup = BeautifulSoup(raw, 'html.parser')
                entries, seen = [], set()
                for a in soup.select(source.get('selector', 'main a[href]')):
                    link = urljoin(final_url, a.get('href', ''))
                    title = a.get_text(' ', strip=True)
                    if len(title) < 12 or link in seen or urlsplit(link).hostname != urlsplit(final_url).hostname:
                        continue
                    seen.add(link)
                    if any(k in (title + link).lower() for k in KEYWORDS):
                        entries.append({'url': link, 'title': title, 'summary': '', 'date': ''})
                entries = entries[:6]
            for entry in entries:
                if not any(k in (entry['title'] + ' ' + entry['summary']).lower() for k in KEYWORDS):
                    continue
                url = canonical_url(entry['url'])
                if c.execute('SELECT 1 FROM candidates WHERE url=?', (url,)).fetchone():
                    continue
                try:
                    page, actual = fetch(url)
                    text = extract(page)
                    if len(text) < 300:
                        continue
                    count += db.add_candidate(c, source['name'], canonical_url(actual), entry['title'], text, entry['date'])
                except Exception as exc:
                    db.log(c, 'source', 'warning', f"{source['name']}: {type(exc).__name__}")
            db.log(c, 'source', 'ok', source['name'])
        except Exception as exc:
            db.log(c, 'source', 'error', f"{source['name']}: {type(exc).__name__}: {str(exc)[:200]}")
    db.log(c, 'collect', 'ok', f'新增 {count} 条候选')
    return count
