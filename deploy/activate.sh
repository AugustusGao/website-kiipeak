set -eu
cd /opt/kiipeak
python3 -m venv .venv
.venv/bin/pip install --disable-pip-version-check -q -r requirements.txt
chown -R root:root /opt/kiipeak
chmod -R o-w /opt/kiipeak
chown -R kiipeak:kiipeak /var/lib/kiipeak/data /var/lib/kiipeak/backups /var/www/kiipeak
chmod 750 /var/lib/kiipeak/data /var/lib/kiipeak/backups
runuser -u kiipeak -- .venv/bin/python -m kiipeak.cli init
install -m 644 deploy/nginx.conf /etc/nginx/conf.d/kiipeak.conf
for file in deploy/kiipeak-*.service deploy/kiipeak-*.timer deploy/kiipeak-*.path; do
    [ -f "$file" ] && install -m 644 "$file" /etc/systemd/system/
done
install -d /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\n/usr/sbin/nginx -t && /bin/systemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/kiipeak-nginx
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/kiipeak-nginx
nginx -t
systemctl daemon-reload
systemctl reload nginx
systemctl enable --now kiipeak-collect.timer kiipeak-edition.timer kiipeak-backup.timer kiipeak-dispatch.path kiipeak-dispatch.timer kiipeak-admin.service
systemctl restart kiipeak-admin.service
systemctl start kiipeak-backup.service
systemctl start --no-block kiipeak-collect.service
printf '\n== STATUS ==\n'
systemctl list-timers 'kiipeak-*' --no-pager
curl --noproxy '*' -fsS --resolve kiipeak.com:443:127.0.0.1 https://kiipeak.com/ >/dev/null
printf '\nORIGIN HTTPS OK\n'
