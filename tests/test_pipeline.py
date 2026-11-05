import sqlite3
from datetime import datetime, timezone

import pytest

from kiipeak import db, editor, sources


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / 'news.db')


def article():
    return {'title': '机器人学习有了新进展', 'summary': '研究团队展示了新的机器人学习方法。',
            'category': 'learning', 'event_date': '2026-11-05',
            'sections': [{'heading': '发生了什么', 'text': '团队展示了一种学习方法，实际效果仍需验证。', 'source_ids': [1]}],
            'facts': [{'claim': '团队展示了方法', 'source_id': 1, 'quote': 'a robot learns new skills'}],
            'limitations': '尚无家庭环境长期测试数据。', 'source_ids': [1]}


def evidence():
    return [{'id': 1, 'url': 'https://example.org/research', 'title': 'Research',
             'text': 'Our research shows a robot learns new skills from demonstrations.'}]


def test_tracking_urls_and_fragments_are_deduplicated(conn):
    a = sources.canonical_url('https://example.org/a?utm_source=x&v=1#top')
    assert a == 'https://example.org/a?v=1'
    assert db.add_candidate(conn, 'source', a, 'robot', 'body', '2026-11-05')
    assert not db.add_candidate(conn, 'source', a, 'robot', 'body', '2026-11-05')


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://127.0.0.1/a',
    'https://169.254.169.254/', 'https://10.0.0.1', 'https://user:pass@example.org', 'http://[::1]/'])
def test_private_or_credential_urls_rejected(url):
    with pytest.raises(ValueError):
        sources.check_url(url)


def test_valid_evidence_and_plain_text():
    assert editor.validate(article(), evidence(), '2026-11-06')['title'] == article()['title']


@pytest.mark.parametrize('change', [
    {'source_ids': [999]}, {'event_date': '2099-01-01'}, {'category': 'invented'},
    {'title': '<script>alert(1)</script>'}, {'facts': []},
    {'facts': [{'claim': 'x', 'source_id': 1, 'quote': 'not in original'}]},
    {'sections': [{'heading': 'x', 'text': 'x', 'source_ids': []}]},
])
def test_invalid_articles_cannot_pass(change):
    a = article() | change
    with pytest.raises(ValueError):
        editor.validate(a, evidence(), '2026-11-06')


def test_publish_idempotent_and_limits(conn):
    now = datetime(2026, 11, 6, 5, tzinfo=timezone.utc)
    a = editor.validate(article(), evidence(), '2026-11-06')
    assert editor.publish(conn, a, evidence(), now, '2026-11-06-am')
    assert not editor.publish(conn, a, evidence(), now, '2026-11-06-am')
    b = a | {'title': '另一项机器人进展', 'event_date': '2026-11-06'}
    ev = [evidence()[0] | {'id': 2, 'url': 'https://example.org/other'}]
    b['source_ids'] = [2]
    b['sections'] = [b['sections'][0] | {'source_ids': [2]}]
    b['facts'] = [b['facts'][0] | {'source_id': 2}]
    assert editor.publish(conn, b, ev, now, '2026-11-06-pm')
    ev3 = [ev[0] | {'url': 'https://example.org/third'}]
    assert not editor.publish(conn, b | {'title': '第三项机器人进展'}, ev3, now, 'extra')
    assert conn.execute("SELECT count(*) FROM articles WHERE status='published'").fetchone()[0] == 2


def test_withdraw_preserves_history(conn):
    editor.publish(conn, article(), evidence(), datetime.now(timezone.utc), 'test')
    row = conn.execute('SELECT id FROM articles').fetchone()
    db.withdraw(conn, row['id'])
    assert conn.execute('SELECT status FROM articles').fetchone()[0] == 'withdrawn'
    assert conn.execute('SELECT count(*) FROM revisions').fetchone()[0] >= 1
