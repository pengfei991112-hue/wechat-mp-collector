"""
微信公众号后台「超链接」接口客户端。

原理：登录自己的公众号后台后，借后台的"搜索其他公众号 / 列其文章"接口
（searchbiz + appmsgpublish）来检索任意公众号的文章列表。
接口与参数对齐自开源项目 wechat-article-exporter 的当前实现。

只需要两样登录态（登录公众号后台后从浏览器拿）：
  - token ：登录后地址栏 ...&token=XXXX 里的数字
  - cookie：该页面请求头里的整串 Cookie
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)

# python.org 版 Python 默认没装根证书，用 certifi 的，避免 SSL 校验失败
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


class MPSessionError(Exception):
    """登录态失效（需要重新扫码登录拿新 token/cookie）。"""


class MPFreqError(Exception):
    """被微信限频（今天搜太多了，过会儿或明天再来）。"""


class MPClient:
    def __init__(self, token: str, cookie: str, timeout: int = 20):
        self.token = str(token).strip()
        self.cookie = cookie.strip()
        self.timeout = timeout

    def _get(self, endpoint: str, params: dict) -> dict:
        params = {
            **params,
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={
                "Referer": "https://mp.weixin.qq.com/",
                "Origin": "https://mp.weixin.qq.com",
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "identity",
                "Cookie": self.cookie,
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL_CTX) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))

        ret = (data.get("base_resp") or {}).get("ret", 0)
        msg = (data.get("base_resp") or {}).get("err_msg", "")
        if ret in (200003, -1) and ("session" in str(msg).lower() or "登录" in str(msg)):
            raise MPSessionError(f"登录态失效：{ret} {msg}")
        if ret in (200013, 200002) or "freq" in str(msg).lower():
            raise MPFreqError(f"被限频：{ret} {msg}")
        if ret != 0:
            raise RuntimeError(f"接口返回错误 {ret}: {msg}")
        return data

    def search_account(self, keyword: str) -> list[dict]:
        """按名字搜公众号，返回候选列表（含 fakeid / nickname / alias）。"""
        data = self._get(
            "https://mp.weixin.qq.com/cgi-bin/searchbiz",
            {"action": "search_biz", "begin": 0, "count": 5, "query": keyword},
        )
        return data.get("list", []) or []

    def resolve_fakeid(self, keyword: str) -> dict | None:
        """搜号并挑最匹配的一个：优先昵称完全相等，否则取第一个。"""
        cands = self.search_account(keyword)
        if not cands:
            return None
        for c in cands:
            if c.get("nickname", "").strip() == keyword.strip():
                return c
        return cands[0]

    def list_articles(self, fakeid: str, begin: int = 0, count: int = 20) -> list[dict]:
        """拉某号的文章列表（一页约 20 篇）。返回原始 appmsgex 数组。"""
        data = self._get(
            "https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
            {
                "sub": "list",
                "search_field": "null",
                "begin": begin,
                "count": count,
                "query": "",
                "fakeid": fakeid,
                "type": "101_1",
                "free_publish_type": 1,
                "sub_action": "list_ex",
            },
        )
        publish_page = json.loads(data.get("publish_page", "{}"))
        articles: list[dict] = []
        for item in publish_page.get("publish_list", []):
            info_raw = item.get("publish_info")
            if not info_raw:
                continue
            info = json.loads(info_raw)
            articles.extend(info.get("appmsgex", []) or [])
        return articles


# --------------------------------------------------------------------------
# 可选：抓文章正文全文（公众号文章页是公开的，无需登录）
# --------------------------------------------------------------------------
class _JsContentExtractor(HTMLParser):
    """提取 id=js_content 这个 div 的纯文本，块级元素之间补换行。"""

    _BLOCK = {"p", "div", "br", "section", "li", "h1", "h2", "h3", "h4", "blockquote"}
    # 自闭合/无闭合标签：不计入深度，否则会让嵌套计数错乱
    _VOID = {"br", "img", "hr", "input", "meta", "link", "source",
             "area", "base", "col", "embed", "param", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.depth = 0          # js_content 内嵌套深度，>0 表示在正文里
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if self.depth == 0:
            if ad.get("id") == "js_content":
                self.depth = 1
            return
        # 已在正文里
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag not in self._VOID:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.depth > 0:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth > 0:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        out, blank = [], False
        for ln in lines:
            if ln:
                out.append(ln)
                blank = False
            elif not blank:
                out.append("")
                blank = True
        return "\n".join(out).strip()


def fetch_article_text(url: str, timeout: int = 20) -> str:
    """下载一篇公众号文章页，返回正文纯文本。失败返回空串。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return ""
    p = _JsContentExtractor()
    try:
        p.feed(html)
    except Exception:
        return ""
    return p.text()
