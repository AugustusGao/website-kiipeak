"""Bounded public-web ingestion. Redirects are validated at every hop."""
import ipaddress
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
import urllib3
from bs4 import BeautifulSoup

from . import db

HEADERS = {'User-Agent': 'KiiPeakBot/1.0 (+https://kiipeak.com/about/)'}
MAX_BYTES = 2_000_000
KEYWORDS = ('robot', 'embodied', 'humanoid', 'manipulat', 'dexter', 'locomotion', '机器人', '具身')


def canonical_url(url):
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', urlencode(sorted(query)), ''))


def resolve_url(url):
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
    return p, [str(a) for a in addresses]


def check_url(url):
    resolve_url(url)
    return url


def fetch(url, limit=MAX_BYTES):
    for _ in range(5):
        parsed, addresses = resolve_url(url)
        # Connect to the very IP we validated; prevent a second DNS resolution/rebinding.
        headers = HEADERS | {'Host': parsed.netloc}
        if parsed.scheme == 'https':
            pool = urllib3.HTTPSConnectionPool(addresses[0], port=parsed.port or 443,
                server_hostname=parsed.hostname, assert_hostname=parsed.hostname,
                cert_reqs='CERT_REQUIRED', ca_certs=requests.certs.where())
        else:
            pool = urllib3.HTTPConnectionPool(addresses[0], port=parsed.port or 80)
        response = None
        try:
            path = urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
            response = pool.request('GET', path, headers=headers, timeout=urllib3.Timeout(connect=8, read=20),
                                    retries=False, redirect=False, preload_content=False)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    raise ValueError('重定向缺少目标地址')
                url = urljoin(url, location)
                continue
            if response.status >= 400:
                raise ValueError(f'来源 HTTP {response.status}')
            chunks, size = [], 0
            while True:
                chunk = response.read(32768)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ValueError('来源内容超过大小上限')
                chunks.append(chunk)
            import re
            charset = re.search(r'charset=([\w-]+)', response.headers.get('Content-Type', ''), re.I)
            encoding = charset.group(1) if charset else 'utf-8'
            return b''.join(chunks).decode(encoding, errors='replace'), url
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ValueError('重定向次数超过上限')


def robots_allowed(url, cache):
    p = urlsplit(url)
    origin = p.scheme + '://' + p.netloc
    if origin not in cache:
        parser = RobotFileParser()
        try:
            text, _ = fetch(origin + '/robots.txt', limit=200000)
            parser.parse(text.splitlines())
            cache[origin] = parser
        except ValueError as exc:
            if 'HTTP 404' in str(exc):
                cache[origin] = None
            else:
                raise ValueError('无法确认来源的采集许可；本次跳过')
    return cache[origin] is None or cache[origin].can_fetch('KiiPeakBot', url)


def page_date(html, fallback=''):
    import re
    from email.utils import parsedate_to_datetime
    soup = BeautifulSoup(html, 'html.parser')
    candidates = [fallback]
    for selector in ('meta[property="article:published_time"]', 'meta[name="date"]', 'meta[itemprop="datePublished"]', 'time[datetime]'):
        tag = soup.select_one(selector)
        if tag:
            candidates.append(tag.get('content') or tag.get('datetime', ''))
    for value in candidates:
        if not value:
            continue
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (ValueError, TypeError, OverflowError):
            match = re.match(r'(20\d\d-\d\d-\d\d)', value)
            if match:
                return match.group(1)
    return ''


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
    count, robots = 0, {}
    override = db.setting(c, 'sources', None)
    for source in override if override is not None else load_sources(config_path):
        if not source.get('enabled', True):
            continue
        try:
            if not robots_allowed(source['url'], robots):
                raise ValueError('来源 robots.txt 禁止此路径的自动采集')
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
                    if not robots_allowed(url, robots):
                        continue
                    page, actual = fetch(url)
                    text = extract(page)
                    if len(text) < 300:
                        continue
                    count += db.add_candidate(c, source['name'], canonical_url(actual), entry['title'], text, page_date(page, entry['date']))
                except Exception as exc:
                    db.log(c, 'source', 'warning', f"{source['name']}: {type(exc).__name__}")
            db.log(c, 'source', 'ok', source['name'])
        except Exception as exc:
            db.log(c, 'source', 'error', f"{source['name']}: {type(exc).__name__}: {str(exc)[:200]}")
    db.log(c, 'collect', 'ok', f'新增 {count} 条候选')
    return count
