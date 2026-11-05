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


def test_retention_failure_never_deletes_active_release(conn, tmp_path, monkeypatch):
    for i in range(5):
        (tmp_path / 'releases' / f'old-{i}').mkdir(parents=True)
    original = render.shutil.rmtree
    def fail_on_old(path, *args, **kwargs):
        if path.name.startswith('old-'):
            raise PermissionError('old release is busy')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(render.shutil, 'rmtree', fail_on_old)
    render.build(conn, tmp_path)
    assert (tmp_path / 'current/index.html').is_file()


def test_concurrent_withdrawal_cannot_be_restored_by_stale_render(conn, tmp_path, monkeypatch):
    import threading
    editor.publish(conn, article(), evidence(), datetime.now(timezone.utc), 'one')
    database = conn.execute('PRAGMA database_list').fetchone()[2]
    snapshot_ready, release, second_started, second_done = (threading.Event() for _ in range(4))
    failures = []
    original = render.write_page
    def paused_write(path, text):
        if threading.current_thread().name == 'stale' and path.name == 'index.html' and not snapshot_ready.is_set():
            snapshot_ready.set()
            assert release.wait(5)
        original(path, text)
    monkeypatch.setattr(render, 'write_page', paused_write)
    def first():
        c = db.connect(database)
        try:
            render.build(c, tmp_path)
        except Exception as exc:
            failures.append(exc)
        finally:
            c.close()
    def second():
        c = db.connect(database)
        try:
            db.withdraw(c, 1)
            second_started.set()
            render.build(c, tmp_path)
        except Exception as exc:
            failures.append(exc)
        finally:
            c.close()
            second_done.set()
    a = threading.Thread(target=first, name='stale')
    b = threading.Thread(target=second, name='withdrawal')
    a.start()
    assert snapshot_ready.wait(5)
    b.start()
    assert second_started.wait(5)
    try:
        assert not second_done.wait(0.15), 'withdrawal render must wait for the older snapshot to finish'
    finally:
        release.set()
        a.join(5)
        b.join(5)
    assert not failures
    assert article()['title'] not in (tmp_path / 'current/index.html').read_text(encoding='utf-8')
    assert json.loads((tmp_path / 'current/search.json').read_text()) == []


def test_event_date_distinct_from_publication_date(conn, tmp_path):
    editor.publish(conn, article(), evidence(), datetime(2026, 11, 6, 0, tzinfo=timezone.utc), 'one')
    render.build(conn, tmp_path)
    body = next((tmp_path / 'current/articles').glob('*/index.html')).read_text(encoding='utf-8')
    assert '事件日期：2026-11-05' in body


def test_stale_render_keeps_later_withdrawal_pending(conn, tmp_path, monkeypatch):
    editor.publish(conn, article(), evidence(), datetime.now(timezone.utc), 'one')
    original = render.write_page
    changed = []
    def withdraw_after_snapshot(path, body):
        if not changed:
            changed.append(True)
            db.withdraw(conn, 1)
        original(path, body)
    monkeypatch.setattr(render, 'write_page', withdraw_after_snapshot)
    render.build(conn, tmp_path)
    assert db.setting(conn, 'render_pending') is True
