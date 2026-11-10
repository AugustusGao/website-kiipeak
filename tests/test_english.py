import copy
import json
from datetime import datetime, timezone

import pytest

from kiipeak import db, editor, render, worker
from test_pipeline import article, evidence


def english():
    return {'title': 'A new method helps robots learn skills',
            'summary': 'Researchers present a robot learning method, with real-world limitations still to be tested.',
            'sections': [{'heading': 'What happened', 'text': 'The team presents a learning method. Its performance still requires validation.', 'source_ids': [1]}],
            'limitations': 'Long-term testing in real homes is not available.', 'correction': ''}


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / 'news.db')


def test_valid_translation_and_stale_source_detection():
    original = article()
    bilingual = editor.with_english(original, english())
    assert editor.english_for(bilingual)['title'] == english()['title']
    assert original == article()
    bilingual['sections'][0]['text'] += '发生了重要更正。'
    assert editor.english_for(bilingual) is None


@pytest.mark.parametrize('change', [
    {'title': '<script>bad</script>'}, {'title': '全部仍然是中文'},
    {'sections': [{'heading': 'What happened', 'text': 'A new method.', 'source_ids': [999]}]},
    {'sections': []},
])
def test_invalid_english_rejected(change):
    with pytest.raises(ValueError):
        editor.with_english(article(), english() | change)


def test_localized_routes_switch_search_and_feed(conn, tmp_path):
    a = editor.with_english(article(), english())
    editor.publish(conn, a, evidence(), datetime(2026, 11, 8, 0, tzinfo=timezone.utc), 'one')
    render.build(conn, tmp_path)
    site = tmp_path / 'current'
    en = (site / 'en/index.html').read_text(encoding='utf-8')
    assert '<html lang="en">' in en
    assert english()['title'] in en
    assert 'href="/en/search/"' in en
    assert 'hreflang="zh-CN"' in en
    assert 'https://kiipeak.com/en/' in en
    assert 'hreflang="x-default" href="https://kiipeak.com/en/"' in en
    assert '<meta name="kiipeak-page" content="/en/">' in en
    assert '/assets/language.js?v=' in en
    assert (site / 'assets/language.js').is_file()
    rows = json.loads((site / 'en/search.json').read_text(encoding='utf-8'))
    assert rows[0]['url'].startswith('/en/articles/')
    assert rows[0]['title'] == english()['title']
    assert '<language>en</language>' in (site / 'en/feed.xml').read_text(encoding='utf-8')
    en_article = next((site / 'en/articles').glob('*/index.html')).read_text(encoding='utf-8')
    assert english()['limitations'] in en_article
    assert 'href="/articles/' in en_article
    assert 'https://example.org/research' in en_article
    assert '<strong>Correction</strong>' not in en_article
    assert 'https://kiipeak.com/en/articles/' in (site / 'sitemap.xml').read_text(encoding='utf-8')
    assert (site / 'en/about/index.html').is_file()
    assert (site / 'en/category/learning/index.html').is_file()
    assert 'Search articles' in (site / 'en/search/index.html').read_text(encoding='utf-8')
    db.withdraw(conn, 1)
    render.build(conn, tmp_path)
    assert json.loads((site / 'en/search.json').read_text(encoding='utf-8')) == []
    assert not list((site / 'en/articles').glob('*/index.html'))


def test_chinese_only_articles_never_masquerade_as_english(conn, tmp_path):
    editor.publish(conn, article(), evidence(), datetime(2026, 11, 8, 0, tzinfo=timezone.utc), 'one')
    render.build(conn, tmp_path)
    assert json.loads((tmp_path / 'current/en/search.json').read_text(encoding='utf-8')) == []
    chinese = next((tmp_path / 'current/articles').glob('*/index.html')).read_text(encoding='utf-8')
    assert 'hreflang="en"' not in chinese


def test_enabled_pipeline_requires_bilingual_and_keeps_two_calls(conn, tmp_path):
    db.set_setting(conn, 'english_enabled', True)
    db.add_candidate(conn, 'Official', evidence()[0]['url'], 'A robot research result', evidence()[0]['text'], '2026-11-05')
    calls = []
    def generate(stage, prompt):
        calls.append((stage, prompt))
        return {'decision': 'publish', 'reason': 'new', 'article': article() | {'translations': {'en': english()}}} if stage == 'draft' else {'approved': True, 'reason': 'supported', 'issues': []}
    assert worker.edition(conn, tmp_path, generate, now=datetime(2026, 11, 8, 0, tzinfo=timezone.utc)) == 'published'
    assert [s for s, _ in calls] == ['draft', 'review']
    assert 'English' in calls[0][1]
    assert 'English' in calls[1][1]
    assert english()['title'] in (tmp_path / 'current/en/index.html').read_text(encoding='utf-8')


def test_missing_english_cannot_publish_when_enabled(conn, tmp_path):
    db.set_setting(conn, 'english_enabled', True)
    db.add_candidate(conn, 'Official', evidence()[0]['url'], 'Robot result', evidence()[0]['text'], '2026-11-05')
    assert worker.edition(conn, tmp_path, lambda *a: {'decision': 'publish', 'reason': 'new', 'article': article()},
                          now=datetime(2026, 11, 8, 0, tzinfo=timezone.utc)) == 'held'
    assert conn.execute('SELECT count(*) FROM articles').fetchone()[0] == 0


def test_backfill_is_reviewed_atomic_and_preserves_article_identity(conn, tmp_path):
    editor.publish(conn, article(), evidence(), datetime(2026, 11, 6, 0, tzinfo=timezone.utc), 'one')
    before = dict(conn.execute('SELECT * FROM articles').fetchone())
    stages = []
    def generate(stage, prompt):
        stages.append(stage)
        if stage == 'review':
            rendered = json.loads(prompt.split('\nEnglish articles as rendered:\n')[1])
            assert rendered[0]['article']['event_date'] == article()['event_date']
            assert rendered[0]['article']['title'] == english()['title']
        return {'translations': [{'article_id': 1, 'english': english()}]} if stage == 'translation' else {'approved': True, 'issues': [], 'reason': 'faithful'}
    assert worker.backfill_english(conn, tmp_path, generate) == 1
    after = dict(conn.execute('SELECT * FROM articles').fetchone())
    assert before['slug'] == after['slug']
    assert before['published_at'] == after['published_at']
    assert stages == ['translation', 'review']
    assert editor.english_for(json.loads(after['payload']))
    assert worker.backfill_english(conn, tmp_path, lambda *a: pytest.fail('already translated')) == 0


def test_rejected_backfill_leaves_chinese_payload_untouched(conn, tmp_path):
    editor.publish(conn, article(), evidence(), datetime(2026, 11, 6, 0, tzinfo=timezone.utc), 'one')
    before = conn.execute('SELECT payload FROM articles').fetchone()[0]
    outputs = iter([{'translations': [{'article_id': 1, 'english': english()}]}, {'approved': False, 'issues': ['meaning changed'], 'reason': 'unfaithful'}])
    with pytest.raises(ValueError):
        worker.backfill_english(conn, tmp_path, lambda *a: next(outputs))
    assert conn.execute('SELECT payload FROM articles').fetchone()[0] == before


def test_correction_removes_stale_english_pages_and_alternate_links(conn, tmp_path):
    editor.publish(conn, editor.with_english(article(), english()), evidence(), datetime(2026, 11, 6, 0, tzinfo=timezone.utc), 'one')
    payload = json.loads(conn.execute('SELECT payload FROM articles').fetchone()[0])
    payload['summary'] += '这是更正后的摘要。'
    conn.execute('UPDATE articles SET payload=?', (json.dumps(payload, ensure_ascii=False),))
    db.content_changed(conn)
    conn.commit()
    render.build(conn, tmp_path)
    assert json.loads((tmp_path / 'current/en/search.json').read_text(encoding='utf-8')) == []
    assert not list((tmp_path / 'current/en/articles').glob('*/index.html'))
    chinese = next((tmp_path / 'current/articles').glob('*/index.html')).read_text(encoding='utf-8')
    assert 'hreflang="en"' not in chinese


def test_backfill_does_not_overwrite_concurrent_correction(conn, tmp_path):
    editor.publish(conn, article(), evidence(), datetime(2026, 11, 6, 0, tzinfo=timezone.utc), 'one')
    def generate(stage, prompt):
        if stage == 'translation':
            return {'translations': [{'article_id': 1, 'english': english()}]}
        corrected = article() | {'summary': '管理员已经更正了这篇文章的摘要。'}
        conn.execute('UPDATE articles SET payload=?', (json.dumps(corrected, ensure_ascii=False),))
        conn.commit()
        return {'approved': True, 'reason': 'faithful', 'issues': []}
    with pytest.raises(ValueError, match='原文已修改'):
        worker.backfill_english(conn, tmp_path, generate)
    current = json.loads(conn.execute('SELECT payload FROM articles').fetchone()[0])
    assert current['summary'] == '管理员已经更正了这篇文章的摘要。'
    assert 'translations' not in current
