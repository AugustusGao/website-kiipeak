import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def normalize_date(value):
    if not value:
        return ''
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except (ValueError, TypeError):
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (ValueError, TypeError, OverflowError):
            return ''


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS candidates (
      id INTEGER PRIMARY KEY, source TEXT NOT NULL, url TEXT UNIQUE NOT NULL,
      title TEXT NOT NULL, text TEXT NOT NULL, published_at TEXT,
      collected_at TEXT NOT NULL, fingerprint TEXT UNIQUE NOT NULL,
      status TEXT NOT NULL DEFAULT 'candidate', error TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS articles (
      id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
      category TEXT NOT NULL, payload TEXT NOT NULL, evidence TEXT NOT NULL,
      status TEXT NOT NULL, published_at TEXT NOT NULL, local_day TEXT NOT NULL,
      batch TEXT UNIQUE NOT NULL, event_key TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS revisions (
      id INTEGER PRIMARY KEY, article_id INTEGER NOT NULL, payload TEXT NOT NULL,
      reason TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs (
      id INTEGER PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
      message TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS batches (
      name TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS calls (
      id INTEGER PRIMARY KEY, local_day TEXT NOT NULL, stage TEXT NOT NULL,
      status TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')
    if 'batch' not in {row['name'] for row in c.execute('PRAGMA table_info(calls)')}:
        c.execute("ALTER TABLE calls ADD COLUMN batch TEXT NOT NULL DEFAULT ''")
    # Upgrade initial ingestion rows without changing their provenance or contents.
    for row in c.execute("SELECT id,published_at FROM candidates WHERE length(published_at)>10").fetchall():
        c.execute('UPDATE candidates SET published_at=? WHERE id=?', (normalize_date(row['published_at']), row['id']))
    c.commit()
    return c


def setting(c, key, default=None):
    row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(c, key, value):
    c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))
    c.commit()


def log(c, kind, status, message):
    c.execute('INSERT INTO runs(kind,status,message,created_at) VALUES (?,?,?,?)',
              (kind, status, str(message)[:2000], stamp()))
    c.commit()


def content_changed(c):
    """Call inside the same transaction as a public-content mutation."""
    c.execute("""INSERT INTO settings VALUES ('content_revision','1')
        ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT)""")
    c.execute("INSERT OR REPLACE INTO settings VALUES ('render_pending','true')")


def add_candidate(c, source, url, title, text, published_at):
    fp = hashlib.sha256((title.strip().casefold() + '\n' + text[:6000]).encode()).hexdigest()
    cur = c.execute('''INSERT OR IGNORE INTO candidates
      (source,url,title,text,published_at,collected_at,fingerprint) VALUES (?,?,?,?,?,?,?)''',
      (source, url, title[:500], text[:18000], normalize_date(published_at), stamp(), fp))
    c.commit()
    return cur.rowcount > 0


def withdraw(c, article_id):
    row = c.execute('SELECT * FROM articles WHERE id=?', (article_id,)).fetchone()
    if not row:
        raise ValueError('文章不存在')
    c.execute('INSERT INTO revisions(article_id,payload,reason,created_at) VALUES (?,?,?,?)',
              (article_id, row['payload'], '撤回', stamp()))
    c.execute("UPDATE articles SET status='withdrawn' WHERE id=?", (article_id,))
    content_changed(c)
    c.commit()
