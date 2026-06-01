#!/usr/bin/env python3
"""
回捞 —— 把某个公众号「指定日期范围」的历史文章一次性补进素材库

日常 collect.py 只增量拉最新 1 页；想回捞某个号某段时间的活动，用这个。
按号名搜号 → 一页页往回翻（公众号列表是新→旧）→ 只存落在 [起, 止] 区间的文章 →
比 START 还旧就停。复用 collect 的去重(seen)/存储/链接清单，所以和日常采集无缝衔接。

用法：
    python3 backfill.py 示例公众号 --since 2026-05-01 --until 2026-06-30
    python3 backfill.py 示例公众号 --since 2026-05-01            # 止默认今天
省略正文：沿用 config.yaml 的 save_full_content（当前 false，只存链接+元信息，快）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import yaml

import collect
from mp_client import MPClient, MPFreqError, MPSessionError, fetch_article_text
from storage import Article, get_storage

ROOT = Path(__file__).resolve().parent
PAGE = 20


def backfill(name: str, since: str, until: str, cfg_path: str) -> int:
    cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}
    session = collect.load_json(collect.MP_SESSION_FILE, {})
    token, cookie = session.get("token", ""), session.get("cookie", "")
    if not token or not cookie:
        collect.log("❌ 缺少登录态，先更新 mp_session.json")
        return 0

    save_full = bool(cfg.get("save_full_content", False))
    client = MPClient(token, cookie)

    # 解析 fakeid（用缓存，没有就搜并写回缓存，和 collect 共用）
    cache = collect.load_json(collect.MP_ACCOUNTS_FILE, {})
    rec = cache.get(name)
    if not rec or not rec.get("fakeid"):
        hit = client.resolve_fakeid(name)
        if not hit:
            collect.log(f"❌ 没搜到「{name}」")
            return 0
        rec = {"fakeid": hit["fakeid"], "nickname": hit.get("nickname", name)}
        cache[name] = rec
        collect.save_json(collect.MP_ACCOUNTS_FILE, cache)
    collect.log(f"回捞「{rec['nickname']}」 {since} ~ {until} …")

    storage = get_storage(cfg.get("storage", "local"), cfg)
    seen = set(collect.load_json(collect.STATE_FILE, []))
    new = scanned = 0
    begin = 0
    stop = False

    try:
        while not stop:
            arts = client.list_articles(rec["fakeid"], begin=begin, count=PAGE)
            if not arts:
                break
            for a in arts:
                scanned += 1
                pub = collect.epoch_to_cst(a.get("update_time")
                                           or a.get("create_time"))
                d = pub[:10]
                if not d:
                    continue
                if d < since:           # 列表新→旧，已翻到区间更早，本页扫完即停
                    stop = True
                    continue
                if d > until:           # 比止还新，跳过（不停，继续往旧翻）
                    continue
                link = a.get("link", "")
                guid = collect.guid_of(name, link or a.get("title", ""))
                if guid in seen:
                    continue
                content = ""
                if save_full and link:
                    content = fetch_article_text(link)
                    time.sleep(1)
                art = Article(
                    account=name, title=(a.get("title") or "无标题").strip(),
                    link=link, published=pub, summary=a.get("digest", ""),
                    content=content, guid=guid,
                    extra={"author": a.get("author_name", "")},
                )
                storage.save(art)
                seen.add(guid)
                new += 1
            begin += PAGE
            time.sleep(2)
    except MPSessionError as e:
        collect.log(f"❌ 登录态失效：{e}　已存的不丢，重扫码后再跑。")
    except MPFreqError as e:
        collect.log(f"⏳ 被限频：{e}　已存的不丢，过会儿再跑。")
    except Exception as e:
        collect.log(f"⚠️ 出错：{e}")

    storage.close()
    collect.save_json(collect.STATE_FILE, sorted(seen))
    collect.log(f"回捞完成：扫 {scanned} 篇，新增 {new} 篇入库。")

    # 重建链接清单（含待导入批次）
    try:
        from export_links import export
        out_dir = (cfg.get("local") or {}).get("output_dir", "素材库")
        res = export(ROOT / out_dir)
        collect.log(f"链接清单已更新 ✅ 共 {res['total']} 条，待导入 ima {res['pending']} 条")
    except Exception as e:
        collect.log(f"⚠️ 链接清单生成失败：{e}")
    return new


def main() -> int:
    ap = argparse.ArgumentParser(description="回捞某号指定日期范围的历史文章")
    ap.add_argument("name", help="公众号名（如 示例公众号）")
    ap.add_argument("--since", required=True, help="起始日期 YYYY-MM-DD（含）")
    ap.add_argument("--until", default=dt.date.today().isoformat(),
                    help="截止日期 YYYY-MM-DD（含，默认今天）")
    ap.add_argument("-c", "--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()
    backfill(args.name, args.since, args.until, args.config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
