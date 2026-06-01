#!/usr/bin/env python3
"""
一键更新登录态：弹出浏览器 → 你扫码登录公众号后台 → 自动抓 token+cookie 写回 mp_session.json。

把原来"扫码 + F12 手抄 token + 手抄整串 cookie 粘进 json"压成"扫码 + 等它自动写好"。
关键：用浏览器自带的 cookie 能力读到 HttpOnly 的 slave_sid 等（网页脚本读不到），不碰任何逆向。

用法：
    python3 update_session.py

说明：
  - 用持久化浏览器档案（state/browser_profile/）。若上次的会话还活着，这次打开可能直接已登录、
    连扫码都免了；掉线了才需要再扫一次。
  - 扫码超时默认 5 分钟；中途关掉浏览器或超时都不会动你现有的 mp_session.json。
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SESSION_FILE = ROOT / "mp_session.json"
PROFILE_DIR = ROOT / "state" / "browser_profile"
HOME = "https://mp.weixin.qq.com/"
LOGIN_TIMEOUT_SEC = 300        # 扫码登录最多等 5 分钟


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def _token_from_url(url: str) -> str:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return (q.get("token") or [""])[0]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        log("❌ 没装 Playwright。先跑：")
        log("   python3 -m pip install playwright && python3 -m playwright install chromium")
        return 1

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False,
            viewport={"width": 1100, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log("打开公众号后台…若未登录，请在弹出的浏览器里用绑定微信扫码。")
        try:
            page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            log(f"⚠️ 打开后台超时/失败：{e}（可在浏览器里手动刷新）")

        # 轮询等待登录成功：登录后地址栏会带 token=。
        # 注意 mp 登录成功常在「新标签页」打开后台，所以要扫描所有打开的标签页，不能只盯最初那个。
        token = ""
        deadline = time.time() + LOGIN_TIMEOUT_SEC
        while time.time() < deadline:
            if not ctx.pages:
                log("❌ 浏览器被关闭，已取消，未改动 mp_session.json。")
                return 2
            for pg in list(ctx.pages):
                try:
                    t = _token_from_url(pg.url)
                except Exception:
                    t = ""
                if t:
                    token = t
                    break
            if token:
                break
            time.sleep(1)

        if not token:
            log("❌ 等了 5 分钟没等到登录（地址栏没出现 token）。未改动 mp_session.json。")
            ctx.close()
            return 3

        # 抓 cookie（含 HttpOnly），拼成请求头用的整串
        cookies = ctx.cookies(HOME)
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))
        ctx.close()

    if not cookie_str:
        log("❌ 没抓到 cookie，未改动 mp_session.json。")
        return 4

    # 写回（保留文件里其它键，只更新 token/cookie，加个更新时间戳）
    data = {}
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["token"] = token
    data["cookie"] = cookie_str
    data["_updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✅ 已写回 {SESSION_FILE.name}（token={token}，cookie {len(cookie_str)} 字符）")

    # 顺手验证一下新登录态能不能用
    try:
        import yaml

        from mp_client import MPClient, MPFreqError, MPSessionError
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        kw = ((cfg.get("mp") or {}).get("accounts") or ["微信"])[0]
        try:
            MPClient(token, cookie_str).search_account(kw)
            log("✅ 新登录态验证通过，可以正常采集了。")
        except MPFreqError:
            log("✅ 新登录态有效（当前被限频，属正常，过会儿再采）。")
        except MPSessionError as e:
            log(f"⚠️ 写好了但验证仍提示失效：{e}（可能扫码没真正完成，重跑一次）")
    except Exception as e:
        log(f"（跳过自检：{e}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
