import hashlib
import json
import re
from datetime import date
from zoneinfo import ZoneInfo

from . import db

CATEGORIES = {'humanoid': '人形机器人', 'everyday': '走进生活', 'industry': '产业现场', 'learning': '机器人学习'}


def plain(value, minimum=1, maximum=18000):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum or re.search(r'<[^>]+>', value):
        raise ValueError('文字字段不合法或含 HTML')
    return value.strip()


def validate(article, evidence, today):
    if not isinstance(article, dict):
        raise ValueError('文章格式错误')
    ids = {x['id']: x for x in evidence}
    plain(article.get('title'), 6, 100)
    plain(article.get('summary'), 10, 400)
    plain(article.get('limitations'), 5, 2500)
    if article.get('category') not in CATEGORIES:
        raise ValueError('未知分类')
    event_date = date.fromisoformat(article.get('event_date', ''))
    if event_date > date.fromisoformat(today) or event_date.year < 2000:
        raise ValueError('事件日期不合法')
    cited = article.get('source_ids')
    if not isinstance(cited, list) or not cited or any(type(i) is not int or i not in ids for i in cited):
        raise ValueError('来源不存在')
    sections = article.get('sections')
    if not isinstance(sections, list) or not 1 <= len(sections) <= 8:
        raise ValueError('缺少解读正文')
    for section in sections:
        plain(section.get('heading'), 1, 80)
        plain(section.get('text'), 1, 6000)
        if not section.get('source_ids') or any(i not in cited for i in section['source_ids']):
            raise ValueError('正文缺少证据关联')
    if not isinstance(article.get('facts'), list) or not article['facts']:
        raise ValueError('缺少事实核验记录')
    for fact in article['facts']:
        plain(fact.get('claim'), 1, 1000)
        quote = plain(fact.get('quote'), 12, 2000)
        if fact.get('source_id') not in cited:
            raise ValueError('事实引用了未知来源')
        normalize = lambda s: ' '.join(s.split()).casefold()
        if normalize(quote) not in normalize(ids[fact['source_id']]['text']):
            raise ValueError('证据摘录无法在来源材料中找到')
    return article


def event_key(evidence):
    return hashlib.sha256('\n'.join(sorted(x['url'] for x in evidence)).encode()).hexdigest()


def publish(c, article, evidence, now, batch):
    day = now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    validate(article, evidence, day)
    selected = [e for e in evidence if e['id'] in article['source_ids']]
    key = event_key(selected)
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM articles WHERE batch=? OR event_key=?', (batch, key)).fetchone():
            c.rollback()
            return False
        if c.execute('SELECT count(*) FROM articles WHERE local_day=?', (day,)).fetchone()[0] >= 2:
            c.rollback()
            return False
        slug = day + '-' + hashlib.sha256((key + article['title']).encode()).hexdigest()[:10]
        c.execute('''INSERT INTO articles(slug,title,category,payload,evidence,status,published_at,local_day,batch,event_key)
            VALUES (?,?,?,?,?,'published',?,?,?,?)''',
            (slug, article['title'], article['category'], json.dumps(article, ensure_ascii=False),
             json.dumps(selected, ensure_ascii=False), now.isoformat(), day, batch, key))
        for item in selected:
            c.execute("UPDATE candidates SET status='published' WHERE id=?", (item['id'],))
        c.commit()
        return True
    except Exception:
        c.rollback()
        raise
