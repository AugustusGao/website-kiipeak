import json
from datetime import datetime, timezone

import pytest

from kiipeak import db, worker
from test_pipeline import article, evidence


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / 'news.db')
    db.add_candidate(c, 'Official source', evidence()[0]['url'], evidence()[0]['title'], evidence()[0]['text'], '2026-11-05')
    return c


def draft():
    return {'decision': 'publish', 'reason': '值得解释', 'article': article()}


def test_review_rejection_never_publishes(conn, tmp_path):
    outputs = iter([draft(), {'approved': False, 'reason': '证据不足', 'issues': ['事实不支持']}])
    worker.edition(conn, tmp_path, lambda *args: next(outputs), now=datetime(2026, 11, 6, 0, tzinfo=timezone.utc))
    assert conn.execute('SELECT count(*) FROM articles').fetchone()[0] == 0
    assert conn.execute("SELECT status FROM candidates").fetchone()[0] == 'held'


def test_success_and_same_slot_is_idempotent(conn, tmp_path):
    calls = []
    def generate(stage, prompt):
        calls.append(stage)
        return draft() if stage == 'draft' else {'approved': True, 'reason': '证据支持', 'issues': []}
    now = datetime(2026, 11, 6, 0, tzinfo=timezone.utc)
    assert worker.edition(conn, tmp_path, generate, now=now) == 'published'
    assert worker.edition(conn, tmp_path, generate, now=now) == 'already-done'
    assert calls == ['draft', 'review']


@pytest.mark.parametrize('kind', ['auth', 'quota', 'network'])
def test_failure_records_cooldown_without_publishing(conn, tmp_path, kind):
    def generate(*args):
        raise worker.GenerationError(kind, '安全错误摘要')
    now = datetime(2026, 11, 6, 0, tzinfo=timezone.utc)
    assert worker.edition(conn, tmp_path, generate, now=now) == kind
    assert conn.execute('SELECT count(*) FROM articles').fetchone()[0] == 0
    assert worker.edition(conn, tmp_path, generate, now=now) == 'cooldown'


def test_no_topic_uses_only_one_call(conn, tmp_path):
    assert worker.edition(conn, tmp_path, lambda *a: {'decision': 'skip', 'reason': '没有足够新意', 'article': None},
                          now=datetime(2026, 11, 6, 0, tzinfo=timezone.utc)) == 'skipped'
    assert conn.execute('SELECT count(*) FROM calls').fetchone()[0] == 1


def test_calls_budget_and_pausing(conn, tmp_path):
    for _ in range(4):
        conn.execute("INSERT INTO calls(local_day,stage,status,created_at) VALUES ('2026-11-06','draft','failed','x')")
    conn.commit()
    fail = lambda *a: (_ for _ in ()).throw(AssertionError('must not call'))
    assert worker.edition(conn, tmp_path, fail, now=datetime(2026, 11, 6, 0, tzinfo=timezone.utc)) == 'budget'
    db.set_setting(conn, 'paused', True)
    assert worker.edition(conn, tmp_path, fail) == 'paused'


def test_invalid_review_type_does_not_pass(conn, tmp_path):
    outputs = iter([draft(), {'approved': 'yes', 'reason': 'x', 'issues': []}])
    assert worker.edition(conn, tmp_path, lambda *a: next(outputs),
                          now=datetime(2026, 11, 6, 0, tzinfo=timezone.utc)) == 'held'
    assert conn.execute('SELECT count(*) FROM articles').fetchone()[0] == 0


def test_backup_restores_consistent_database(conn, tmp_path):
    path = worker.backup(conn, tmp_path / 'backups')
    restored = db.connect(path / 'news.db')
    assert restored.execute('SELECT count(*) FROM candidates').fetchone()[0] == 1
    assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_batch_for_reboot_uses_latest_slot_only():
    now = datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc)
    assert worker.batch_name(now, ['05:00', '20:00']) == '2026-11-06-2000'


def test_old_sources_do_not_use_ai_budget(conn, tmp_path):
    conn.execute("UPDATE candidates SET published_at='2026-07-01'")
    conn.commit()
    never = lambda *a: (_ for _ in ()).throw(AssertionError('old item sent to AI'))
    assert worker.edition(conn, tmp_path, never, now=datetime(2026, 11, 6, 0, tzinfo=timezone.utc)) == 'empty'
    assert conn.execute('SELECT count(*) FROM calls').fetchone()[0] == 0
