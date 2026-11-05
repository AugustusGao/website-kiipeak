"""Upload only the application allowlist, never the credential-bearing workspace instructions."""
import pathlib
import sys
import io
import tarfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'tools'))
from vps import connect, ROOT


def main():
    c = connect()
    sftp = c.open_sftp()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as tar:
        for folder in ('kiipeak', 'templates', 'static', 'config', 'deploy'):
            for path in (ROOT / folder).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                    tar.add(path, arcname=path.relative_to(ROOT).as_posix(), recursive=False)
        tar.add(ROOT / 'requirements.txt', arcname='requirements.txt')
    archive.seek(0)
    sftp.putfo(archive, '/opt/kiipeak-release.tar.gz')
    sftp.close()
    script = 'tar -xzf /opt/kiipeak-release.tar.gz -C /opt/kiipeak\n' + (ROOT / 'deploy/activate.sh').read_text(encoding='utf-8')
    _, out, err = c.exec_command(script, timeout=180)
    print(out.read().decode('utf-8', errors='replace'))
    print(err.read().decode('utf-8', errors='replace'), file=sys.stderr)
    code = out.channel.recv_exit_status()
    c.close()
    sys.exit(code)


if __name__ == '__main__':
    main()
