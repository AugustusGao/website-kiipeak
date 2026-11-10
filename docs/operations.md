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

立即选编和重试不会绕过每天最多两篇、每个早晚批次最多八次 AI 调用的限制。重试按钮可清除一次冷却以便用户在修复登录后重试；预算仍生效。

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

额度受限冷却五小时；网络失败等待十五分钟；登录失败冷却一天并等待本人授权。自动任务不会高频轮询或绕过限额。实际仍有合适的候选且预算允许时，后续编辑批次会处理。

任务记录存于 SQLite，管理端可见；错误只保留安全摘要，不保存完整 Codex 网络响应或凭据。来源抓取尊重 robots.txt、限制大小，并逐次验证重定向和公网目标地址。

数据库备份包含文章、证据、来源配置、历史与任务记录，不包含 Codex 登录凭据。备份目录：`/var/lib/kiipeak/backups/YYYYMMDD-HHMMSS/news.db`。本机备份不能防 VPS 整机损坏；尚无异地备份。

恢复时先暂停自动任务和管理端，另行保存现有数据库，以 SQLite backup API 把选择的快照恢复到数据库文件，然后运行 `python -m kiipeak.cli render` 并恢复服务。不要直接覆盖正在使用的数据库或遗留其旧 WAL/SHM 文件。首次部署已在临时路径完成快照恢复与 integrity_check 验证。

静态站点使用 release 目录和原子符号链接切换，构建失败保留旧站，最多保留四个版本。旧 release 只用于临时回退故障，不应在撤回文章后恢复包含该文章的版本。正常恢复应从当前数据库重新构建。

## 更新代码

在本地已验证的项目目录运行 `python deploy/install.py`。上传只包含 kiipeak、templates、static、config、deploy 和 requirements.txt，不包含 AGENTS.md、Git、日志、数据或认证文件。

首次部署关闭了 trojan-go 自启，保留其文件及原有 MariaDB 容器。重新启用 Trojan 前应先安排其端口，避免与网站 443 冲突。

## 当前验收状态

公网 HTTPS、主域跳转、移动版布局、搜索、来源采集、备份恢复与定时表达式已实测。首批十二个来源均有成功采集记录，已采集 42 条真实候选。Codex CLI 已使用 ChatGPT 账号登录，并在 VPS 完成首次撰写与独立核验，公开发布了真实文章。设备授权与首次验收调用另行记录，不占应用自定的正常定时批次预算；实际 ChatGPT 订阅额度仍会按服务计量。

首篇：[Ctrl-F给人形机器人加入力指令：实机推踢最重20公斤箱子](https://kiipeak.com/articles/2026-11-06-c2f8d2af79/)。管理端暂停与恢复已实测，当前自动编辑开启。


## 中英文版本

中文默认地址保持不变；英文首页为 https://kiipeak.com/en/ 。导航中的 EN / 中文可切换至对应页面。英文搜索与 RSS 各自独立，文章沿用相同 slug、事件日期、发布时间和来源；翻译不增加新闻发布篇数。

2026-11-10 起，浏览器通过本站 Cloudflare `/cdn-cgi/trace` 的 `loc` 字段识别访问 IP 地区：中国大陆、香港、澳门、台湾选择中文，其他地区及识别失败默认英语。请求不使用缓存，1.5 秒超时；不保存 IP 地址。手动切换优先，以 localStorage 的 `kiipeak-language` 记住选择，清除此项可恢复按地区选择。禁用存储时，切换链接的 `lang` 参数保证本次选择生效。

自动切换只跳转到实际存在的对应语言页，保留查询参数与锚点；缺少翻译及 404 页面不跳转。此功能需 JavaScript，页面加载后可能短暂显示原语言；未启用 JavaScript 时按访问地址显示，仍可手动切换。中文路径保持不变，`x-default` 指向英语。地区测试运行 `node --test tests/language.test.cjs`。

后续两个定时批次先生成中英文，再用独立核验检查两者及其证据。首次通过通常只需两次调用；未通过时自动带反馈修订并重新核验，必要时换选题，每批最多八次调用。英文输出与修订增加实际订阅用量；无额外付费 API。历史补翻记录使用 backfill: 前缀，与正常定时批次分开。

中文原文被更正后，过期英文自动从英文页面、搜索、RSS 与对应语言链接中移除。撤回文章同时移除两种语言。补齐或重新生成英文可在服务器执行：

```sh
cd /opt/kiipeak
.venv/bin/python -m kiipeak.cli backfill-english
```

每次最多处理六篇，执行翻译和独立核验各一次；不自动无限重试。未通过核验则不写入任何一篇翻译。全部在架文章均有有效英文版后会启用后续完整双语发布。管理界面暂保留中文。


## 核验未通过后的自动修订

05:00 和 20:00 各启动一个批次，目标各发布一篇。每个选题生成后独立核验；未通过则把具体 reason/issues 连同原稿、原始证据交给修订任务，中英文同步修改，再进行新的独立核验。同一选题修订一次仍未通过时换其他候选；每批最多两个选题、八次调用，早晚分开预留，正常每日最多十六次。不存在“次数用完就放宽核验”的逻辑。

`kiipeak-retry.timer` 每十五分钟检查未完成的当前批次，恢复已保存的草稿、阶段和核验意见。额度/网络故障遵循冷却，完成的批次不会重复发布。午夜后不补前一天晚间稿，下一批次不会覆盖上一批次的状态。自动暂停后不会继续调用 AI 或发布新稿。

稿件、反馈和阶段保存于 settings 的 editorial:<batch>，calls.batch 记录所属批次；旧调用按实际时间补记归属。管理端日志可查看 revision-required、switch-topic、budget、published 等结果。真实订阅不足、登录失效或缺乏可证实的内容时仍会延迟，不强制发布未经核验的文章。
