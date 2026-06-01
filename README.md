# wechat-mp-collector

> 扫码登录一次自己的公众号后台，之后**每天自动**把目标公众号的新推文链接收进素材库——去重、按时间归档、关键词过滤，并切好「10 条一批」方便喂进 [ima 知识库](https://ima.qq.com/) 等下游。

借**你自己的微信公众号后台**「搜索其他公众号 / 看其文章」的能力来检索任意公众号的文章列表，因此**全覆盖**那些不被 RSS 收录的号（如各类营销活动号），且免费。接口/参数对齐开源项目 [wechat-article-exporter](https://github.com/jooooock/wechat-article-exporter)。

```
扫码登录(一次) → 每天定时拉列表 → 去重 → 关键词过滤 → 素材库 + 链接清单 + 待导入批次 →(手动粘)→ ima 知识库
```

## ✨ 特性

- **一次扫码，长期自动**：登录态写进本地，之后每天 launchd 定时跑，无人值守。
- **全覆盖任意公众号**：走自己的后台接口搜号，不依赖第三方 RSS 收录。
- **自动去重**：靠 `state/seen.json`，只入新增。
- **关键词过滤**：白名单+黑名单，只把"想要的"内容喂进下游（默认配置示例为营销活动 vs 防诈/科普噪音）。
- **三种产物**：`链接清单.md`（人看）、`链接清单.csv`（机器用）、`链接清单-待导入.txt`（按公众号分块、每 10 条一批，匹配 ima「导入网页链接」框一次最多 10 条的限制）。
- **已推送追踪**：导完一批 `--done` 标记，下次只列没导过的新链接。
- **历史回捞**：`backfill.py` 按日期范围补某个号的历史文章。
- **手机提醒**：登录态失效 / 有新推文，可选 Bark 推送到 iOS。

## 🚀 快速开始

### 1. 装依赖（一次）

```bash
git clone https://github.com/<你的用户名>/wechat-mp-collector.git
cd wechat-mp-collector
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium      # 给扫码登录用
```

> 需要 Python 3.10+。本工具用你**自己的公众号**做检索入口，所以你得有一个微信公众号（订阅号/服务号都行）。

### 2. 扫码登录（拿登录态）

```bash
python3 update_session.py
```

会弹出浏览器打开公众号后台，**微信扫码登录**即可——脚本自动抓取 token+cookie 写进 `mp_session.json`。登录态会维持一个持久化浏览器档案，几天后过期了再跑一次本命令重扫即可。

> 不想用浏览器自动化？也可手动：复制 `mp_session.example.json` 为 `mp_session.json`，按里面说明从浏览器手抄 token 和 cookie。

### 3. 配置

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml` 的 `mp.accounts:`，每行写一个要盯的公众号名（尽量与显示名一致）。其余开箱即用。

### 4. 跑一次

```bash
python3 collect.py
```

输出：
- `素材库/<公众号名>/<日期>-<标题>.md` —— 每篇一文件，含标题/链接/发布时间。
- `素材库/链接清单.md / .csv / -待导入.txt` —— 自动生成的链接清单。

### 5. 每天自动跑（macOS launchd）

```bash
cp com.example.wxcollect.plist ~/Library/LaunchAgents/com.<你的名字>.wxcollect.plist
# 编辑该文件，把 /PATH/TO/... 改成你的项目绝对路径、python3 路径
launchctl load ~/Library/LaunchAgents/com.<你的名字>.wxcollect.plist
launchctl start com.<你的名字>.wxcollect      # 立即测试一次
```

日志在 `run.log`。Linux 用 cron 同理：`30 9 * * * cd /path && python3 collect.py`。

## 📥 喂给 ima 知识库（手动一步）

ima.copilot 目前没有开放导入 API，PC 客户端「导入网页链接」框一次最多 10 条。本工具把待导入链接切好批次，你照着粘即可：

1. 打开 `素材库/链接清单-待导入.txt`，已按公众号分块、每 10 条一批；
2. 逐批复制 10 行链接，粘进 ima「导入网页链接」框提交；
3. 全部导完后标记已推送（下次只列新链接）：
   ```bash
   python3 export_links.py --done              # 标记全部
   python3 export_links.py --done 示例公众号A  # 只标某个号
   python3 export_links.py --done 3            # 只标前 3 批
   ```

## 🔁 回捞历史文章

```bash
python3 backfill.py 示例公众号A --since 2025-05-01 --until 2025-06-30
```

按日期范围把某号的历史文章补进素材库（列表新→旧，翻到比 `--since` 更旧就停）。复用同一套去重/存储/清单，和日常采集无缝。

## 🧹 关键词过滤

`config.yaml` 的 `filter` 段控制。标题命中 `blacklist`=噪音、不进待导入；但同时命中 `whitelist` 则保留（避免误杀）。**只影响 `链接清单-待导入.txt`**，素材库与清单仍保留全部、并对过滤项标 🚫、CSV 加「类别」列供核对。`enabled: false` 关闭。

## 📁 目录结构

```
config.yaml              你的配置（从 config.example.yaml 复制，.gitignore）
mp_session.json          你的登录态（自动生成，.gitignore，别外传）
collect.py               主程序：采集 + 去重 + 生成清单 + 推送
mp_client.py             公众号后台接口客户端 + 正文提取
update_session.py        扫码自动抓登录态
export_links.py          链接清单 / 待导入批次 / 已推送追踪
backfill.py              按日期范围回捞历史
notify.py                Bark 手机推送
storage/                 存储后端：local 已实现，feishu 留骨架
state/                   去重记录 + fakeid 缓存 + 登录档案（自动生成，.gitignore）
素材库/                   采集输出（.gitignore）
```

## ⏰ 登录态过期怎么办

mp 方案唯一需要你定期做的事：登录态几天一过期。过期后自动任务会停在"登录态失效"（开了 Bark 会推手机），重跑 `python3 update_session.py` 重扫一次即可。

## ⚠️ 免责声明

- 本工具仅用于**个人学习与自己内容的归档整理**，通过你**本人账号**的公众号后台进行，不涉及任何破解或逆向。
- 请遵守微信平台规则，**控制频率**（默认一天一次、号间有节流），勿滥用；因使用本工具产生的任何后果由使用者自负。
- 采集到的文章版权归原作者所有；请勿用于侵权用途或未经授权的再分发。

## License

[MIT](LICENSE)
