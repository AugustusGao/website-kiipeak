import hashlib
import copy
import json
import re
from datetime import date
from zoneinfo import ZoneInfo

from . import db

CATEGORIES = {'humanoid': '人形机器人', 'everyday': '走进生活', 'industry': '产业现场', 'learning': '机器人学习'}


def source_digest(article):
    original = {k: v for k, v in article.items() if k not in ('translations', 'translation_sources')}
    return hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_english(article, english):
    if not isinstance(english, dict) or set(english) - {'title', 'summary', 'sections', 'limitations', 'correction'}:
        raise ValueError('英文版本字段不合法')
    def text(value, minimum=3, maximum=12000):
        result = plain(value, minimum, maximum)
        if len(re.findall(r'[A-Za-z]', result)) < 3:
            raise ValueError('英文内容缺少英文文字')
        return result
    text(english.get('title'), 6, 180)
    text(english.get('summary'), 10, 1000)
    text(english.get('limitations'), 5, 5000)
    sections = english.get('sections')
    if not isinstance(sections, list) or len(sections) != len(article['sections']):
        raise ValueError('中英文段落不对应')
    for original, translated in zip(article['sections'], sections):
        if not isinstance(translated, dict) or set(translated) != {'heading', 'text', 'source_ids'}:
            raise ValueError('英文段落字段不合法')
        text(translated.get('heading'), 3, 160)
        text(translated.get('text'))
        if translated.get('source_ids') != original['source_ids'] or any(type(i) is not int for i in translated['source_ids']):
            raise ValueError('中英文证据关联不一致')
    if article.get('correction'):
        text(english.get('correction'), 5, 1500)
    elif english.get('correction'):
        raise ValueError('英文更正说明没有中文依据')
    return english


def with_english(article, english):
    validate_english(article, english)
    result = copy.deepcopy(article)
    result.setdefault('translations', {})['en'] = copy.deepcopy(english)
    result.setdefault('translation_sources', {})['en'] = source_digest(article)
    return result


def english_for(article):
    try:
        if article.get('translation_sources', {}).get('en') != source_digest(article):
            return None
        english = article['translations']['en']
        validate_english(article, english)
        return {k: v for k, v in article.items() if k not in ('translations', 'translation_sources')} | english
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


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
    if article.get('translations', {}).get('en') is not None:
        article = with_english(article, article['translations']['en'])
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
        db.content_changed(c)
        c.commit()
        return True
    except Exception:
        c.rollback()
        raise
