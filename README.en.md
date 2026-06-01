# wechat-mp-collector

[简体中文](README.md) | English

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)

> Scan a QR code once to log in to your **own** WeChat Official Account (公众号) admin console. After that, it **automatically collects** new article links from the accounts you track every day — deduplicated, archived by date, keyword-filtered, and chunked into "10 links per batch" for easy import into knowledge bases like [ima.copilot](https://ima.qq.com/).

It uses your **own** Official Account admin console's "search other accounts / view their articles" capability to fetch any account's article list. This means it **covers accounts that RSS aggregators don't index** (e.g. brands' marketing accounts), for free. Interface/params follow the open-source project [wechat-article-exporter](https://github.com/jooooock/wechat-article-exporter).

```
QR login (once) → daily scheduled fetch → dedupe → keyword filter → archive + link lists + import batches ─(manual paste)→ ima knowledge base
```

## Use cases

- Continuously track a set of Official Accounts (e.g. brands' marketing accounts) for **marketing campaigns**, building a searchable archive;
- Feed article links into ima / other knowledge bases for **Q&A, content analysis, topic research**;
- Any personal scenario that needs to **scheduled, fully, and freely** fetch certain accounts' article lists.

## ✨ Features

- **Scan once, automated forever** — login state persists locally; runs daily via launchd/cron, unattended.
- **Covers any account** — searches via your own admin console, no dependency on third-party RSS indexing.
- **Automatic dedupe** — via `state/seen.json`, only new articles are saved.
- **Keyword filtering** — whitelist + blacklist, so only the content you want flows downstream (the default example separates marketing campaigns from anti-fraud/educational noise).
- **Three outputs** — `链接清单.md` (human-readable), `链接清单.csv` (machine-readable), `链接清单-待导入.txt` (grouped per account, 10 links per batch, matching ima's "max 10 links per import" limit).
- **Pushed tracking** — mark a batch done with `--done`; next time only un-imported links are listed.
- **Historical backfill** — `backfill.py` fetches an account's past articles within a date range.
- **Phone alerts** — optional Bark (iOS) push when login expires or new articles arrive.

## 🚀 Quick start

### 1. Install (once)

```bash
git clone https://github.com/pengfei991112-hue/wechat-mp-collector.git
cd wechat-mp-collector
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium      # for QR login
```

> Requires Python 3.10+. The tool uses **your own** Official Account as the search entry point, so you need a WeChat Official Account (subscription or service account).

### 2. Log in (get login state)

```bash
python3 update_session.py
```

A browser opens the admin console — **scan the QR with WeChat**. The script grabs token+cookie and writes them to `mp_session.json`. The login state lives in a persistent browser profile; when it expires (after a few days), just run this command again.

> Prefer not to use browser automation? Copy `mp_session.example.json` to `mp_session.json` and fill in token/cookie manually (instructions inside).

### 3. Configure

```bash
cp config.example.yaml config.yaml
```

Edit `mp.accounts:` in `config.yaml` — one account name per line (match the display name as closely as possible). Everything else works out of the box.

### 4. Run once

```bash
python3 collect.py
```

Outputs:
- `素材库/<account>/<date>-<title>.md` — one file per article (title / link / publish time).
- `素材库/链接清单.md / .csv / -待导入.txt` — auto-generated link lists.

### 5. Schedule daily

**macOS (launchd):**
```bash
cp com.example.wxcollect.plist ~/Library/LaunchAgents/com.<you>.wxcollect.plist
# Edit it: replace /PATH/TO/... with your project's absolute path and python3 path
launchctl load ~/Library/LaunchAgents/com.<you>.wxcollect.plist
launchctl start com.<you>.wxcollect      # test once now
```
**Linux (cron):** `30 9 * * * cd /path/to/wechat-mp-collector && python3 collect.py`

Logs go to `run.log`.

## 📥 Feeding ima (one manual step)

ima.copilot has no public import API yet; its desktop "import web links" box accepts at most 10 links at a time. This tool pre-chunks pending links per account, 10 per batch. `链接清单-待导入.txt` looks like:

```
########## 示例公众号B (58 links / 6 batches) ##########

===== [示例公众号B] batch 1 / 6 (10 links) — copy the 10 lines below =====
https://mp.weixin.qq.com/s/XXXXXXXX
https://mp.weixin.qq.com/s/YYYYYYYY
... (10 lines)
```

Workflow:
1. Copy each batch of 10 links, paste into ima's "import web links" box, submit;
2. After importing, mark as pushed (so next time only new links are listed):
   ```bash
   python3 export_links.py --done                  # mark all
   python3 export_links.py --done 示例公众号A      # mark one account only
   python3 export_links.py --done 3                # mark first 3 batches only
   ```

## 🔁 Backfill history

```bash
python3 backfill.py 示例公众号A --since 2025-05-01 --until 2025-06-30
```

Fetches an account's past articles within a date range (list runs newest→oldest; stops once older than `--since`). Reuses the same dedupe/storage/list machinery.

## 🧹 Keyword filtering

Controlled by the `filter` section in `config.yaml`. A title hitting `blacklist` = noise, excluded from the import list; but if it also hits `whitelist`, it's kept (to avoid false drops). **Only affects `链接清单-待导入.txt`** — the archive and lists keep everything, mark filtered items with 🚫, and add a "category" column in the CSV. Set `enabled: false` to turn off.

## 🛠️ Troubleshooting

| Message | Cause / fix |
|---|---|
| `登录态失效` (login expired) | Token/cookie expired. Re-run `python3 update_session.py`. Bark will alert your phone if enabled. |
| `被限频` (rate-limited) | Too many requests. Wait a while or try tomorrow (once-a-day is fine; there's throttling between accounts). |
| `没搜到这个号` (account not found) | The name in `config.yaml` is off — use one closer to the account's display name. |
| SSL errors | python.org Python ships without root certs; this project handles it via `certifi` — make sure `pip install -r requirements.txt` ran fully. |

## ⚠️ Disclaimer

- This tool is for **personal study and archiving your own content**, operated through **your own account's** admin console — no cracking or reverse engineering involved.
- Respect WeChat's platform rules, **keep the frequency low**, and don't abuse it; you bear all consequences of use.
- Collected articles' copyright belongs to their original authors; do not use for infringement or unauthorized redistribution.

## 👋 About the author

Built by **阿飞 (Aifei)**. On my WeChat Official Account「**AI产品阿飞**」I share hands-on experience with AI products, automation, and productivity tools — this project is one real example.

If it helped you, please ⭐ **Star** the repo. You're also welcome to follow「**AI产品阿飞**」(scan the QR or search it in WeChat) 👇

<p align="center">
  <img src="assets/follow-aifei.png" alt="WeChat: search AI产品阿飞" width="460">
</p>

## License

[MIT](LICENSE) © 2026 阿飞 (AI产品阿飞)
