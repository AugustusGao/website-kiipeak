# KiiPeak 运维与使用

## 访问

- 主站：https://kiipeak.com
- www 自动跳转主站。HTTP 跳转 HTTPS，证书验证路径除外。
- 服务器应用 `/opt/kiipeak`，内容数据库 `/var/lib/kiipeak/data/news.db`，静态发布 `/var/www/kiipeak/current`。
- Codex 独立用户 `kiipeak-ai`，凭据仅在其私有家目录；内容管理用户 `kiipeak`。
- Cloudflare SSL/TLS 已从 Flexible 改成 Full (strict)。勿改回 Flexible，否则源站 HTTPS 跳转会形成循环。

## 管理界面

在本地项目目录运行：

```powershell
python tools/admin_tunnel.py
```

保持终端运行，浏览器打开 http://127.0.0.1:8765/ 。该脚本使用未跟踪的本地 AGENTS.md 中 SSH 连接信息，不上传该文件。关闭终端即关闭隧道。

也可以使用系统 SSH：

```text
ssh -N -L 8765:127.0.0.1:8765 root@138.2.90.126
```

管理服务只监听服务器 127.0.0.1，未暴露公网端口。通过界面可以暂停/恢复自动编辑、采集、选编、重试、撤回、更正文章、修改来源和两个编辑时间。时间使用北京时间，修改时间后由请求队列应用到 systemd 定时器。

立即选编和重试不会绕过每天最多两篇、最多四次 AI 调用的限制。重试按钮可清除一次冷却以便用户在修复登录后重试；预算仍生效。

## Codex 首次登录或重新授权

使用 SSH 在 VPS 中执行：

```sh
runuser -u kiipeak-ai -- env HOME=/var/lib/kiipeak-ai codex login --device-auth
```

在本人浏览器打开终端给出的设备登录地址，输入当前一次性代码并完成授权。不要把中文标点或后面的说明复制进地址，不要在项目目录保存凭据。

确认登录：

```sh
runuser -u kiipeak-ai -- env HOME=/var/lib/kiipeak-ai codex login status
```

状态正常后，在管理端选择“重试待处理批次”。命令行也可只清除冷却后重试：

```sh
cd /opt/kiipeak
.venv/bin/python -c "from kiipeak import db; c=db.connect('/var/lib/kiipeak/data/news.db'); db.set_setting(c,'cooldown_until',None)"
systemctl start kiipeak-edition.service
```

首次试运行必须验证“真实来源 → 中文草稿 → 独立核验 → 发布”。只有 CLI 安装或账号登录成功，不能代表完整链路成功。本站不使用 API key，不自动切换付费 API。

## 定时任务

- `kiipeak-edition.timer`：北京时间每天 **05:00、20:00 开始**，完成核验后发布。
- `kiipeak-collect.timer`：每两小时的第 15 分钟采集一次。
- `kiipeak-backup.timer`：北京时间每日 03:30 备份数据库，保留七天。
- `kiipeak-dispatch.path` / `.timer`：消费管理端请求；已有任务运行时避免重叠。
- `certbot.timer`：自动续期，续期后验证并重载 Nginx。

查看计划与日志：

```sh
systemctl list-timers 'kiipeak-*'
journalctl -u kiipeak-edition.service -n 50 --no-pager
systemctl status kiipeak-admin.service
```

UTC 21:00 对应次日北京时间 05:00；UTC 12:00 对应北京时间 20:00。systemd 定时表达式已明确设置 Asia/Shanghai，不依赖服务器系统时区。

## 故障与恢复

额度受限冷却五小时；网络失败冷却一小时；登录失败冷却一天并等待本人授权。自动任务不会高频轮询或绕过限额。实际仍有合适的候选且预算允许时，后续编辑批次会处理。

任务记录存于 SQLite，管理端可见；错误只保留安全摘要，不保存完整 Codex 网络响应或凭据。来源抓取尊重 robots.txt、限制大小，并逐次验证重定向和公网目标地址。

数据库备份包含文章、证据、来源配置、历史与任务记录，不包含 Codex 登录凭据。备份目录：`/var/lib/kiipeak/backups/YYYYMMDD-HHMMSS/news.db`。本机备份不能防 VPS 整机损坏；尚无异地备份。

恢复时先暂停自动任务和管理端，另行保存现有数据库，以 SQLite backup API 把选择的快照恢复到数据库文件，然后运行 `python -m kiipeak.cli render` 并恢复服务。不要直接覆盖正在使用的数据库或遗留其旧 WAL/SHM 文件。首次部署已在临时路径完成快照恢复与 integrity_check 验证。

静态站点使用 release 目录和原子符号链接切换，构建失败保留旧站，最多保留四个版本。旧 release 只用于临时回退故障，不应在撤回文章后恢复包含该文章的版本。正常恢复应从当前数据库重新构建。

## 更新代码

在本地已验证的项目目录运行 `python deploy/install.py`。上传只包含 kiipeak、templates、static、config、deploy 和 requirements.txt，不包含 AGENTS.md、Git、日志、数据或认证文件。

首次部署关闭了 trojan-go 自启，保留其文件及原有 MariaDB 容器。重新启用 Trojan 前应先安排其端口，避免与网站 443 冲突。

## 当前验收状态

公网 HTTPS、主域跳转、移动版布局、搜索、来源采集、备份恢复与定时表达式已实测。首批十二个来源均有成功采集记录，已采集 42 条真实候选。Codex CLI 已使用 ChatGPT 账号登录，并在 VPS 完成首次撰写与独立核验，公开发布了真实文章。设备授权与首次验收调用另行记录，不占应用自定的每日四次调度预算；实际 ChatGPT 订阅额度仍会按服务计量。

首篇：[Ctrl-F给人形机器人加入力指令：实机推踢最重20公斤箱子](https://kiipeak.com/articles/2026-11-06-c2f8d2af79/)。管理端暂停与恢复已实测，当前自动编辑开启。
