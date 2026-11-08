import json
from datetime import datetime, timezone

import pytest

from kiipeak import db, worker
from test_pipeline import article, evidence

MORNING = datetime(2026, 11, 8, 0, 0, tzinfo=timezone.utc)
EVENING = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
PASS = {'approved': True, 'issues': [], 'reason': '证据支持'}
FAIL = {'approved': False, 'issues': ['标题把联合改进误写成额外规则的必要性'], 'reason': '标题和摘要过度推断'}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / 'news.db')
    db.add_candidate(c, 'Official', evidence()[0]['url'], 'A robot research result', evidence()[0]['text'], '2026-11-05')
    return c


def proposal(title=None, sid=1):
    a = article()
    if title:
        a['title'] = title
    a['source_ids'] = [sid]
    a['sections'][0]['source_ids'] = [sid]
    a['facts'][0]['source_id'] = sid
    return {'decision': 'publish', 'reason': '值得解释', 'article': a}


def test_rejected_draft_is_revised_using_feedback_and_reviewed_before_publish(conn, tmp_path):
    stages = []
    checks = 0
    def generate(stage, prompt):
        nonlocal checks
        stages.append(stage)
        if stage == 'review':
            checks += 1
            return FAIL if checks == 1 else PASS
        if stage == 'revise':
            assert FAIL['issues'][0] in prompt
            assert FAIL['reason'] in prompt
            return proposal('机器人研究展示联合改进的效果')
        return proposal()
    assert worker.edition(conn, tmp_path, generate, now=MORNING) == 'published'
    assert stages == ['draft', 'review', 'revise', 'review']
    assert conn.execute('SELECT title FROM articles').fetchone()[0] == '机器人研究展示联合改进的效果'


def test_repeated_rejection_switches_topic_with_no_unverified_publication(conn, tmp_path):
    db.add_candidate(conn, 'Other', 'https://example.org/other', 'Other robot', evidence()[0]['text'] + ' More.', '2026-11-05')
    stages = []
    def generate(stage, prompt):
        stages.append(stage)
        if stage == 'review':
            return PASS if stages.count('draft') == 2 else FAIL
        if stage == 'draft' and stages.count('draft') == 2:
            assert 'https://example.org/research' not in prompt.split('不可信公开资料=')[-1]
            return proposal('另一个机器人研究的新进展', 2)
        return proposal()
    assert worker.edition(conn, tmp_path, generate, now=MORNING) == 'published'
    assert stages == ['draft', 'review', 'revise', 'review', 'draft', 'review']
    assert conn.execute('SELECT count(*) FROM articles').fetchone()[0] == 1


def test_quota_during_revision_resumes_saved_draft_and_feedback(conn, tmp_path):
    def first(stage, prompt):
        if stage == 'draft': return proposal()
        if stage == 'review': return FAIL
        raise worker.GenerationError('quota', '额度不足')
    assert worker.edition(conn, tmp_path, first, now=MORNING) == 'quota'
    db.set_setting(conn, 'cooldown_until', None)
    stages = []
    def resumed(stage, prompt):
        stages.append(stage)
        if stage == 'revise':
            assert FAIL['issues'][0] in prompt
            return proposal('根据证据收紧后的机器人新进展')
        assert stage == 'review'
        return PASS
    assert worker.edition(conn, tmp_path, resumed, now=MORNING) == 'published'
    assert stages == ['revise', 'review']


def test_morning_call_budget_does_not_consume_evening_allocation(conn, tmp_path):
    for _ in range(8):
        conn.execute("INSERT INTO calls(local_day,stage,status,created_at,batch) VALUES ('2026-11-08','revise','failed','x','2026-11-08-0500')")
    conn.commit()
    assert worker.edition(conn, tmp_path, lambda *a: pytest.fail('morning exhausted'), now=MORNING) == 'budget'
    assert worker.edition(conn, tmp_path, lambda stage,p: proposal() if stage == 'draft' else PASS, now=EVENING) == 'published'


def test_strict_review_never_passes_after_all_repairs_fail(conn, tmp_path):
    stages = []
    def generate(stage, prompt):
        stages.append(stage)
        return FAIL if stage == 'review' else proposal()
    assert worker.edition(conn, tmp_path, generate, now=MORNING) == 'held'
    assert stages == ['draft', 'review', 'revise', 'review']
    assert conn.execute('SELECT count(*) FROM articles').fetchone()[0] == 0


def test_retry_eligibility_respects_pause_midnight_completed_and_cooldown(conn):
    assert worker.retry_due(conn, now=MORNING)
    assert not worker.retry_due(conn, now=datetime(2026,11,7,18,tzinfo=timezone.utc))  # Beijing 02:00
    db.set_setting(conn, 'paused', True)
    assert not worker.retry_due(conn, now=MORNING)
    db.set_setting(conn, 'paused', False)
    db.set_setting(conn, 'cooldown_until', '2026-11-08T01:00:00+00:00')
    assert not worker.retry_due(conn, now=MORNING)
    db.set_setting(conn, 'cooldown_until', None)
    conn.execute("INSERT INTO batches VALUES ('2026-11-08-0500','published','x')")
    conn.commit()
    assert not worker.retry_due(conn, now=MORNING)


def test_existing_held_morning_draft_is_repaired_without_reselecting(conn, tmp_path):
    db.set_setting(conn, 'latest_draft', article())
    conn.execute("UPDATE candidates SET status='held',error='标题和摘要过度推断'")
    conn.execute("INSERT INTO batches VALUES ('2026-11-08-0500','held','2026-11-08T00:01:00+00:00')")
    conn.commit()
    stages = []
    def generate(stage, prompt):
        stages.append(stage)
        return proposal('修订后更符合证据的机器人进展') if stage == 'revise' else PASS
    assert worker.edition(conn, tmp_path, generate, now=MORNING) == 'published'
    assert stages == ['revise', 'review']
