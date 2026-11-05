import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from . import admin, db, render, sources, worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'collect', 'edition', 'render', 'backup', 'admin', 'dispatch', 'status'])
    parser.add_argument('--data', default=os.environ.get('KIIPEAK_DATA', '/var/lib/kiipeak/data'))
    parser.add_argument('--site', default=os.environ.get('KIIPEAK_SITE', '/var/www/kiipeak'))
    args = parser.parse_args()
    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True)
    source_path = Path(__file__).resolve().parents[1] / 'config/sources.json'
    c = db.connect(data / 'news.db')
    try:
        if args.command == 'admin':
            c.close()
            return admin.serve(data / 'news.db', args.site, source_path, data)
        with worker.lock(data / 'pipeline.lock'):
            if args.command == 'init':
                (data / 'requests').mkdir(exist_ok=True)
                render.build(c, args.site)
            elif args.command == 'collect':
                sources.collect(c, source_path)
            elif args.command == 'edition':
                print(worker.edition(c, args.site))
            elif args.command == 'render':
                print(render.build(c, args.site))
            elif args.command == 'backup':
                print(worker.backup(c, data.parent / 'backups'))
            elif args.command == 'status':
                print(json.dumps({'articles': c.execute("SELECT count(*) FROM articles WHERE status='published'").fetchone()[0],
                                  'candidates': c.execute('SELECT count(*) FROM candidates').fetchone()[0],
                                  'paused': db.setting(c, 'paused', False)}, ensure_ascii=False))
            elif args.command == 'dispatch':
                for name in ('schedule', 'collect', 'edition', 'retry'):
                    request = data / 'requests' / (name + '.request')
                    if not request.exists():
                        continue
                    request.unlink()
                    if name == 'schedule':
                        times = db.setting(c, 'edition_times', ['05:00', '20:00'])
                        if len(times) != 2 or any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in times):
                            db.log(c, 'schedule', 'error', '启动时间无效')
                            continue
                        timer = '[Unit]\nDescription=KiiPeak editorial editions\n[Timer]\n'
                        timer += ''.join(f'OnCalendar=*-*-* {t}:00 Asia/Shanghai\n' for t in times)
                        timer += 'RandomizedDelaySec=0\nAccuracySec=1s\nPersistent=true\nUnit=kiipeak-edition.service\n[Install]\nWantedBy=timers.target\n'
                        Path('/etc/systemd/system/kiipeak-edition.timer').write_text(timer)
                        subprocess.run(['systemctl', 'daemon-reload'], check=True)
                        subprocess.run(['systemctl', 'restart', 'kiipeak-edition.timer'], check=True)
                        db.log(c, 'schedule', 'ok', '北京时间 ' + ' / '.join(times))
                    elif name == 'collect':
                        sources.collect(c, source_path)
                    else:
                        if name == 'retry':
                            db.set_setting(c, 'cooldown_until', None)
                        worker.edition(c, args.site)
    except BlockingIOError:
        db.log(c, args.command, 'busy', '已有采集或编辑任务运行，避免重叠')
    finally:
        try:
            c.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
