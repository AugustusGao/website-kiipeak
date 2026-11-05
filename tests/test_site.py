import json
from datetime import datetime, timezone

import pytest

from kiipeak import admin, db, editor, render
from test_pipeline import article, evidence


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / 'news.db')


def test_static_outputs_empty_and_published(conn, tmp_path):
    root = tmp_path / 'site'
    render.build(conn, root)
    assert '精选正在准备中' in (root / 'current/index.html').read_text(encoding='utf-8')
    assert not json.loads((root / 'current/search.json').read_text())
    editor.publish(conn, article(), evidence(), datetime.now(timezone.utc), 'one')
    render.build(conn, root)
    index = (root / 'current/index.html').read_text(encoding='utf-8')
    assert article()['title'] in index
    assert 'https://kiipeak.com/articles/' in (root / 'current/sitemap.xml').read_text()
    assert article()['title'] in (root / 'current/feed.xml').read_text(encoding='utf-8')
    rows = json.loads((root / 'current/search.json').read_text(encoding='utf-8'))
    assert len(rows) == 1
    db.withdraw(conn, 1)
    render.build(conn, root)
    assert json.loads((root / 'current/search.json').read_text()) == []
    assert not list((root / 'current/articles').glob('*/index.html'))


def test_untrusted_evidence_title_is_escaped(conn, tmp_path):
    ev = [evidence()[0] | {'title': '<script>alert(1)</script>', 'url': 'javascript:alert(1)'}]
    # Legacy data must also render safely even if it predates strict input validation.
    editor.publish(conn, article(), ev, datetime.now(timezone.utc), 'one')
    render.build(conn, tmp_path)
    body = next((tmp_path / 'current/articles').glob('*/index.html')).read_text(encoding='utf-8')
    assert '<script>alert(1)</script>' not in body
    assert 'href="javascript:' not in body


def test_failed_render_keeps_previous_release(conn, tmp_path, monkeypatch):
    render.build(conn, tmp_path)
    before = (tmp_path / 'current/index.html').read_bytes()
    monkeypatch.setattr(render, 'write_page', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('disk error')))
    with pytest.raises(RuntimeError):
        render.build(conn, tmp_path)
    assert (tmp_path / 'current/index.html').read_bytes() == before


def test_admin_rejects_cross_site_and_wrong_token():
    assert admin.valid_post('http://127.0.0.1:8765', '127.0.0.1:8765', 'abc', 'abc')
    assert not admin.valid_post('https://evil.example', '127.0.0.1:8765', 'abc', 'abc')
    assert not admin.valid_post('http://127.0.0.1:8765', '127.0.0.1:8765', 'bad', 'abc')
    assert not admin.valid_host('evil.example')


def test_calendar_exact_start_times():
    from pathlib import Path
    timer = Path('deploy/kiipeak-edition.timer').read_text()
    assert '05:00:00 Asia/Shanghai' in timer
    assert '20:00:00 Asia/Shanghai' in timer
    assert 'RandomizedDelaySec=0' in timer
