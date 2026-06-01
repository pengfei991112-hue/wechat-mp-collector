# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-06-01

首个开源版本。

### 功能
- **mp 后台采集**：借自有公众号后台接口搜号、拉文章列表，全覆盖任意公众号（含不被 RSS 收录的号）。
- **扫码登录**：`update_session.py` 弹浏览器扫码、自动抓 token+cookie 写回，持久化档案免重复扫码。
- **自动去重**：`state/seen.json` 记录，只入新增。
- **链接清单**：`export_links.py` 生成 `链接清单.md`（人看）、`.csv`（机器用）、`-待导入.txt`（按公众号分块、每 10 条一批）。
- **已推送追踪**：`--done`（全部 / 按公众号 / 按批数）标记，下次只列新链接。
- **关键词过滤**：白名单 + 黑名单（营销优先豁免），只把目标内容喂进待导入。
- **历史回捞**：`backfill.py` 按日期范围补某号历史文章。
- **手机提醒**：`notify.py` Bark 推送（登录态失效 / 有新推文）。
- **定时运行**：附 macOS launchd 模板；Linux cron 同理。
- **备用 rss 源**：`source: rss` 切换，复用同一套去重/存储/清单逻辑。

### 存储
- 本地 Markdown（`storage/local_md.py`）已实现；飞书多维表格（`storage/feishu.py`）留骨架待补全。
