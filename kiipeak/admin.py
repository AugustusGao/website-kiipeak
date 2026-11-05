"""Loopback-only management UI, intended for an SSH tunnel."""
import html
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db, editor, render


def valid_host(host):
    return host in ('127.0.0.1:8765', 'localhost:8765')


def valid_post(origin, host, token, expected):
    return valid_host(host) and origin in ('http://' + host, None) and isinstance(token, str) and secrets.compare_digest(token, expected)


def serve(db_path, site_root, source_path, data_dir):
    token = secrets.token_urlsafe(32)
    env = Environment(loader=FileSystemLoader(render.ROOT / 'templates'), autoescape=select_autoescape(['html']))
    queue = Path(data_dir) / 'requests'
    queue.mkdir(exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, code, body, location=None):
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            if location:
                self.send_header('Location', location)
            self.end_headers()
            self.wfile.write(body.encode('utf-8'))

        def do_GET(self):
            if not valid_host(self.headers.get('Host', '')):
                return self.respond(403, 'Host forbidden')
            c = db.connect(db_path)
            try:
                path = urlsplit(self.path)
                if path.path == '/assets/style.css':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/css')
                    self.end_headers()
                    self.wfile.write((render.ROOT / 'static/style.css').read_bytes())
                    return
                if path.path != '/':
                    return self.respond(404, 'Not found')
                articles = [dict(x) for x in c.execute('SELECT * FROM articles ORDER BY id DESC LIMIT 50')]
                for a in articles:
                    a['editable'] = json.dumps(json.loads(a['payload']), ensure_ascii=False, indent=2)
                rows = [dict(x) for x in c.execute('SELECT id,source,title,status,error FROM candidates ORDER BY id DESC LIMIT 60')]
                logs = [dict(x) for x in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 40')]
                sources = db.setting(c, 'sources', json.loads(Path(source_path).read_text(encoding='utf-8')))
                body = env.get_template('admin.html').render(token=token, articles=articles, candidates=rows,
                    logs=logs, paused=db.setting(c, 'paused', False),
                    times=db.setting(c, 'edition_times', ['05:00', '20:00']),
                    sources=json.dumps(sources, ensure_ascii=False, indent=2), message=parse_qs(path.query).get('message', [''])[0])
                self.respond(200, body)
            finally:
                c.close()

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size > 180000:
                    return self.respond(413, '内容过长')
                form = parse_qs(self.rfile.read(size).decode('utf-8'), keep_blank_values=True)
                value = lambda key: form.get(key, [''])[0]
                if not valid_post(self.headers.get('Origin'), self.headers.get('Host', ''), value('csrf'), token):
                    return self.respond(403, '请求来源或校验码不正确，请刷新管理页')
                c = db.connect(db_path)
                try:
                    action = value('action')
                    if action == 'pause':
                        db.set_setting(c, 'paused', not db.setting(c, 'paused', False))
                    elif action in ('edition', 'collect', 'retry'):
                        (queue / (action + '.request')).write_text(action, encoding='utf-8')
                    elif action == 'withdraw':
                        db.withdraw(c, int(value('id')))
                        render.build(c, site_root)
                    elif action == 'correct':
                        row = c.execute('SELECT * FROM articles WHERE id=?', (int(value('id')),)).fetchone()
                        if not row:
                            raise ValueError('文章不存在')
                        reason = editor.plain(value('reason'), 5, 500)
                        revised = json.loads(value('payload'))
                        revised['correction'] = reason
                        editor.validate(revised, json.loads(row['evidence']), db.stamp()[:10])
                        c.execute('INSERT INTO revisions(article_id,payload,reason,created_at) VALUES (?,?,?,?)',
                                  (row['id'], row['payload'], reason, db.stamp()))
                        c.execute('UPDATE articles SET title=?,category=?,payload=? WHERE id=?',
                                  (revised['title'], revised['category'], json.dumps(revised, ensure_ascii=False), row['id']))
                        c.commit()
                        render.build(c, site_root)
                    elif action == 'sources':
                        from .sources import check_url
                        items = json.loads(value('sources'))
                        if not isinstance(items, list) or len(items) > 40:
                            raise ValueError('来源应为最多 40 项的列表')
                        for item in items:
                            editor.plain(item['name'], 1, 100)
                            check_url(item['url'])
                            if item.get('kind') not in ('feed', 'page'):
                                raise ValueError('来源类型应为 feed 或 page')
                        db.set_setting(c, 'sources', items)
                    elif action == 'schedule':
                        import re
                        times = [value('morning'), value('evening')]
                        if any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in times) or times[0] == times[1]:
                            raise ValueError('请输入两个不同的有效时间')
                        db.set_setting(c, 'edition_times', times)
                        (queue / 'schedule.request').write_text('schedule', encoding='utf-8')
                    else:
                        raise ValueError('未知操作')
                    db.log(c, 'admin', 'ok', action)
                finally:
                    c.close()
                self.respond(303, '', '/')
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self.respond(400, '<meta charset="utf-8"><p>' + html.escape(str(exc)) + '</p><a href="/">返回管理页</a>')
            except Exception:
                self.respond(500, '操作未完成，请返回管理页检查任务记录')

    HTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
