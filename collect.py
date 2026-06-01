#!/usr/bin/env python3
"""
公众号每天收集推文 —— 主程序

每天定时跑一次：把目标公众号"新出现"的文章存进素材库，自动去重。
支持两种采集源（config.yaml 里 source 切换）：
  - rss : 拉取 RSS 地址（配合 Wechat2RSS 等）
  - mp  : 用你登录的公众号后台接口，按名字搜号并拉文章（全覆盖，需登录态）

用法：
    python3 collect.py                # 用 config.yaml
    python3 collect.py -c other.yaml  # 指定配置
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import yaml

from storage import Article, get_storage

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "seen.json"
MP_ACCOUNTS_FILE = ROOT / "state" / "mp_accounts.json"   # 缓存号名→fakeid
MP_SESSION_FILE = ROOT / "mp_session.json"               # token + cookie
_CST = dt.timezone(dt.timedelta(hours=8))                # 北京时间


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ----------------------------- 通用：状态读写 -----------------------------
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def epoch_to_cst(ts) -> str:
    try:
        return dt.datetime.fromtimestamp(int(ts), _CST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def guid_of(account: str, key: str) -> str:
    return hashlib.sha1(f"{account}::{key}".encode("utf-8")).hexdigest()


# ----------------------------- 采集源 1：RSS -----------------------------
def collect_rss(cfg, storage, seen) -> tuple[int, int]:
    import feedparser

    def resolve_url(url: str) -> str:
        return str((ROOT / url).resolve()) if "://" not in url else url

    save_full = bool(cfg.get("save_full_content", True))
    feeds = cfg.get("feeds") or []
    new_total = err_total = 0

    for feed in feeds:
        name, url = feed.get("name", "未命名"), feed.get("url", "")
        if not url:
            log(f"⚠️  [{name}] 没有 url，跳过")
            continue
        log(f"拉取 [{name}] …")
        try:
            parsed = feedparser.parse(resolve_url(url))
        except Exception as e:
            log(f"❌ [{name}] 拉取异常：{e}")
            err_total += 1
            continue
        if getattr(parsed, "bozo", 0) and not parsed.entries:
            log(f"❌ [{name}] 解析失败/空源")
            err_total += 1
            continue

        new_here = 0
        for entry in parsed.entries:
            key = getattr(entry, "id", "") or getattr(entry, "link", "") \
                or getattr(entry, "title", "")
            guid = guid_of(name, key)
            if guid in seen:
                continue
            tm = getattr(entry, "published_parsed", None) \
                or getattr(entry, "updated_parsed", None)
            published = (
                dt.datetime(*tm[:6], tzinfo=dt.timezone.utc).astimezone(_CST)
                .strftime("%Y-%m-%d %H:%M:%S")
                if tm else getattr(entry, "published", "")
            )
            content = ""
            if save_full:
                c = getattr(entry, "content", None)
                content = (c[0].get("value", "") if c else "") \
                    or getattr(entry, "summary", "")
            art = Article(
                account=name, title=getattr(entry, "title", "无标题").strip(),
                link=getattr(entry, "link", ""), published=published,
                summary=getattr(entry, "summary", ""), content=content, guid=guid,
            )
            try:
                storage.save(art)
                seen.add(guid)
                new_here += 1
                new_total += 1
            except Exception as e:
                log(f"   ❌ 存储失败《{art.title}》：{e}")
                err_total += 1
        log(f"   [{name}] 本次新增 {new_here} 篇")
        time.sleep(1)
    return new_total, err_total


# ------------------------- 采集源 2：公众号后台 mp -------------------------
def collect_mp(cfg, storage, seen) -> tuple[int, int]:
    from mp_client import (MPClient, MPFreqError, MPSessionError,
                           fetch_article_text)

    session = load_json(MP_SESSION_FILE, {})
    token, cookie = session.get("token", ""), session.get("cookie", "")
    if not token or not cookie:
        log(f"❌ 缺少登录态。请把 token 和 cookie 填进 {MP_SESSION_FILE.name}"
            f"（参考 mp_session.example.json）")
        return 0, 1

    mp_cfg = cfg.get("mp") or {}
    accounts = mp_cfg.get("accounts") or []
    pages = int(mp_cfg.get("pages", 1))
    save_full = bool(cfg.get("save_full_content", True))
    page_size = 20

    client = MPClient(token, cookie)
    fakeid_cache = load_json(MP_ACCOUNTS_FILE, {})   # {号名: {fakeid, nickname}}
    new_total = err_total = 0

    for name in accounts:
        log(f"采集 [{name}] …")
        # 1) 解析 fakeid（缓存优先，避免频繁搜号被限频）
        rec = fakeid_cache.get(name)
        if not rec or not rec.get("fakeid"):
            try:
                hit = client.resolve_fakeid(name)
            except MPSessionError as e:
                log(f"❌ {e}　→ 需要重新扫码登录、更新 mp_session.json，本次中止。")
                notify_session_expired(cfg, str(e))
                break
            except MPFreqError as e:
                log(f"⏳ {e}　→ 搜号被限频，今天先到这，明天再跑。")
                break
            except Exception as e:
                log(f"   ❌ [{name}] 搜号失败：{e}")
                err_total += 1
                continue
            if not hit:
                log(f"   ⚠️ [{name}] 没搜到这个号，检查名字是否准确")
                err_total += 1
                continue
            rec = {"fakeid": hit["fakeid"], "nickname": hit.get("nickname", name)}
            fakeid_cache[name] = rec
            save_json(MP_ACCOUNTS_FILE, fakeid_cache)
            log(f"   ✓ 命中「{rec['nickname']}」(fakeid={rec['fakeid']})")
            time.sleep(2)

        # 2) 拉文章列表
        new_here = 0
        try:
            for pg in range(pages):
                arts = client.list_articles(rec["fakeid"], begin=pg * page_size,
                                            count=page_size)
                if not arts:
                    break
                for a in arts:
                    link = a.get("link", "")
                    guid = guid_of(name, link or a.get("title", ""))
                    if guid in seen:
                        continue
                    published = epoch_to_cst(a.get("update_time")
                                             or a.get("create_time"))
                    content = ""
                    if save_full and link:
                        content = fetch_article_text(link)
                        time.sleep(1)
                    art = Article(
                        account=name, title=(a.get("title") or "无标题").strip(),
                        link=link, published=published,
                        summary=a.get("digest", ""), content=content, guid=guid,
                        extra={"author": a.get("author_name", "")},
                    )
                    try:
                        storage.save(art)
                        seen.add(guid)
                        new_here += 1
                        new_total += 1
                    except Exception as e:
                        log(f"   ❌ 存储失败《{art.title}》：{e}")
                        err_total += 1
                time.sleep(2)
        except MPSessionError as e:
            log(f"❌ {e}　→ 需要重新扫码登录、更新 mp_session.json，本次中止。")
            notify_session_expired(cfg, str(e))
            break
        except MPFreqError as e:
            log(f"⏳ {e}　→ 被限频，今天先到这，明天再跑。")
            break
        except Exception as e:
            log(f"   ❌ [{name}] 拉文章失败：{e}")
            err_total += 1

        log(f"   [{name}] 本次新增 {new_here} 篇")
        time.sleep(3)   # 号与号之间慢一点，降低限频风险
    return new_total, err_total


# ----------------------------- 登录态探针 + 推送 -----------------------------
def notify_session_expired(cfg, reason: str = "") -> None:
    """登录态失效时推一条到手机（Bark）。静默失败，绝不影响采集。"""
    try:
        from notify import push_bark
    except Exception:
        return
    body = "mp_session.json 的 token/cookie 失效了，去公众号后台重新扫码、更新一次。"
    if reason:
        body += f"（{reason}）"
    sent = push_bark(
        cfg, "🔑 公众号采集·登录态过期", body,
        click_url="https://mp.weixin.qq.com",
        event="session_expired", min_interval_sec=12 * 3600,   # 12h 内只提醒一次
    )
    log("📲 已推送失效提醒到手机" if sent else "（未推送：通知未启用/未填 key/被节流）")


def notify_new_articles(cfg, new_total: int, pending: int) -> None:
    """采集到新推文时推一条到手机（Bark），提醒去 ima 批量导入。静默失败。"""
    if new_total <= 0:
        return
    try:
        from notify import push_bark
    except Exception:
        return
    body = (f"今天新增 {new_total} 篇推文，待导入 ima 共 {pending} 条。"
            f"去电脑打开「链接清单-待导入.txt」按批粘进 ima。")
    sent = push_bark(
        cfg, "📰 公众号采集·有新推文", body,
        event="new_articles", min_interval_sec=0,   # 有新就提醒，不节流
    )
    log("📲 已推送新推文提醒到手机" if sent else "（未推送：通知未启用/未填 key）")


def probe_mp(cfg) -> int:
    """
    只检查 mp 登录态是否有效，不采集、不写库。失效则推送提醒。
    退出码：0 有效（或仅被限频）/ 1 没填登录态 / 2 请求异常 / 3 登录态失效。
    """
    from mp_client import MPClient, MPFreqError, MPSessionError

    session = load_json(MP_SESSION_FILE, {})
    token, cookie = session.get("token", ""), session.get("cookie", "")
    if not token or not cookie:
        log(f"❌ {MP_SESSION_FILE.name} 里没有 token/cookie")
        notify_session_expired(cfg, "mp_session.json 为空")
        return 1

    accounts = (cfg.get("mp") or {}).get("accounts") or []
    probe_kw = accounts[0] if accounts else "微信"   # 用已配置的号名做最小搜号探测
    try:
        MPClient(token, cookie).search_account(probe_kw)
        log("✅ 登录态有效")
        try:
            from notify import clear_event
            clear_event("session_expired")   # 恢复正常，下次失效能立即提醒
        except Exception:
            pass
        return 0
    except MPFreqError as e:
        log(f"⏳ 被限频，但登录态本身有效：{e}")
        return 0
    except MPSessionError as e:
        log(f"❌ 登录态已失效：{e}")
        notify_session_expired(cfg, str(e))
        return 3
    except Exception as e:
        log(f"⚠️ 探针请求异常（不一定是登录态问题）：{e}")
        return 2


# --------------------------------- 主流程 ---------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="公众号推文每日收集")
    ap.add_argument("-c", "--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--probe", action="store_true",
                    help="只检查 mp 登录态是否有效，失效则推送提醒后退出（不采集）")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    source = (cfg.get("source") or "rss").lower()

    if args.probe:
        return probe_mp(cfg)

    try:
        storage = get_storage(cfg.get("storage", "local"), cfg)
    except Exception as e:
        log(f"❌ 初始化存储失败：{e}")
        return 2

    seen = set(load_json(STATE_FILE, []))
    log(f"采集源：{source}　存储：{cfg.get('storage', 'local')}")

    if source == "rss":
        new_total, err_total = collect_rss(cfg, storage, seen)
    elif source == "mp":
        new_total, err_total = collect_mp(cfg, storage, seen)
    else:
        log(f"❌ 未知 source：{source}（可选 rss / mp）")
        return 1

    storage.close()
    save_json(STATE_FILE, sorted(seen))
    log(f"完成 ✅ 共新增 {new_total} 篇，失败 {err_total} 处。已记录去重状态。")

    # 重建链接清单（仅本地 Markdown 存储时有意义）。失败不影响采集本身。
    pending = 0
    if (cfg.get("storage", "local") or "local").lower() == "local":
        try:
            from export_links import export
            out_dir = (cfg.get("local") or {}).get("output_dir", "素材库")
            res = export(ROOT / out_dir)
            pending = res["pending"]
            log(f"链接清单已更新 ✅ 共 {res['total']} 条（滤掉非营销 {res['filtered']} 条），"
                f"待导入 ima {pending} 条 → 链接清单.md / .csv / -待导入.txt")
        except Exception as e:
            log(f"⚠️ 链接清单生成失败（不影响采集）：{e}")

    # 有新推文就推手机提醒去 ima 导入（待导入数取自上面的链接清单）
    notify_new_articles(cfg, new_total, pending)
    return 0


if __name__ == "__main__":
    sys.exit(main())
