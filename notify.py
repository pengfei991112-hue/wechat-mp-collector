"""
轻量推送：把"登录态失效"等事件提醒到手机。

当前实现 Bark(iOS)：Bark App 里能看到一串形如
    https://api.day.app/AbCdEf123...
末尾那段就是 key，填到 config.yaml 的 notify.bark.key。

设计要点：
  - 纯 GET 请求 Bark 公共/自建服务器，免费、不依赖第三方库。
  - 带节流：同一类事件在 min_interval_sec 内只推一次，避免每天/每次跑都炸你手机。
  - 通知可点：带 url 参数，点开直接跳公众号后台登录页。
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

# python.org 版 Python 默认没装根证书，用 certifi 的，避免 SSL 校验失败
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

ROOT = Path(__file__).resolve().parent
_THROTTLE_FILE = ROOT / "state" / "notify.json"   # 记录各事件上次推送时间，做节流


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _throttled(event: str, min_interval_sec: int) -> bool:
    if not event or not min_interval_sec:
        return False
    last = _load(_THROTTLE_FILE, {}).get(event, 0)
    return (time.time() - last) < min_interval_sec


def _mark(event: str) -> None:
    if not event:
        return
    data = _load(_THROTTLE_FILE, {})
    data[event] = int(time.time())
    _THROTTLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _THROTTLE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def clear_event(event: str) -> None:
    """事件恢复正常时调用（如登录态又有效了），让下次失效能立即提醒。"""
    data = _load(_THROTTLE_FILE, {})
    if event in data:
        data.pop(event, None)
        _THROTTLE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def push_bark(cfg: dict, title: str, body: str, *, click_url: str = "",
              event: str = "", min_interval_sec: int = 0) -> bool:
    """
    按 config 的 notify.bark 配置推送一条。返回是否实际发出。
    未启用 / 没填 key / 被节流 / 网络失败，都返回 False（静默，不影响主流程）。
    """
    nc = cfg.get("notify") or {}
    if not nc.get("enabled"):
        return False
    bark = nc.get("bark") or {}
    key = (bark.get("key") or "").strip()
    if not key or key.startswith("在这里"):
        return False
    if _throttled(event, min_interval_sec):
        return False

    base = (bark.get("server") or "https://api.day.app").rstrip("/")
    url = (f"{base}/{urllib.parse.quote(key)}"
           f"/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}")
    params = {}
    if click_url:
        params["url"] = click_url
    for k in ("sound", "level", "group"):
        if bark.get(k):
            params[k] = bark[k]
    if params:
        url += "?" + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wxcollect/1.0"})
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as r:
            body_resp = json.loads(r.read().decode("utf-8", "replace"))
        ok = (body_resp.get("code") == 200)
    except Exception:
        return False
    if ok:
        _mark(event)
    return ok
