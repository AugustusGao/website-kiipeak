set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv certbot nginx curl ca-certificates >/dev/null
id kiipeak >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/kiipeak --shell /usr/sbin/nologin kiipeak
id kiipeak-ai >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/kiipeak-ai --shell /usr/sbin/nologin kiipeak-ai
install -d -o kiipeak -g kiipeak -m 750 /var/lib/kiipeak/data /var/lib/kiipeak/backups
install -d -o kiipeak -g kiipeak -m 755 /var/www/kiipeak /opt/kiipeak
install -d -o kiipeak-ai -g kiipeak-ai -m 700 /var/lib/kiipeak-ai/.codex /var/lib/kiipeak-ai/work
install -d /usr/local/lib/kiipeak-codex
curl -fLsS --max-time 120 https://github.com/openai/codex/releases/download/rust-v0.166.0/codex-aarch64-unknown-linux-musl.tar.gz -o /tmp/kiipeak-codex.tar.gz
tar -xzf /tmp/kiipeak-codex.tar.gz -C /usr/local/lib/kiipeak-codex
find /usr/local/lib/kiipeak-codex -maxdepth 2 -type f -printf '%f\n'
