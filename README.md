# Victoria 室内网球场空档提醒

每 15 分钟检查一次 MovitSport 中 Victoria Tennishal 的公开预约数据。只提醒能预订完整 60 分钟、且符合 `config.json` 时间设置的场地。同一日期、开始时间和场地只发送一次。

## 修改时间

编辑 `config.json`：

- `weekday_start_times`：周一至周五允许的开始时间，当前为 19:00 和 20:00。
- `weekend_window`：周六、周日的完整一小时必须落在 09:00–12:00，按 30 分钟步进。
- `lookahead_days`：向前检查的天数。
- `recipient_email`：接收通知的邮箱。

GitHub Actions 计划在每小时的 03、18、33、48 分运行，由 GitHub 云端执行，电脑关机也能运行；GitHub 的实际启动时间可能比计划时间晚。监控只通知，不会自动预订或付款。

这个公开仓库使用 GitHub 的标准 Linux runner，不消耗私有仓库的 Actions 免费分钟额度。

GitHub 可能在公开仓库连续 60 天没有活动时停用计划任务。工作流会约每 30 天写入一次 `.heartbeat`，保持仓库活动。

## 邮件设置

在仓库的 Settings → Secrets and variables → Actions 中添加 secret `QQ_SMTP_PASSWORD`，值为发件 QQ 邮箱的 SMTP 授权码（不是 QQ 登录密码）。发件地址通过 `SMTP_SENDER` 设置；默认流程中使用 `15939488@qq.com`。授权码不要写入仓库文件或聊天。

## 手动验证

在 Actions 中运行 `Check court availability` 的 `Run workflow`。运行日志会显示检查天数、匹配数量和发送数量，但不会显示 SMTP 授权码。`sent.json` 保存已经通知过的场地。
