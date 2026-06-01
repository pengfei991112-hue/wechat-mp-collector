"""本地 Markdown 存储：素材库/公众号名/日期-标题.md"""
from __future__ import annotations

import re
from pathlib import Path

from .base import Article, BaseStorage

_INVALID = re.compile(r'[\\/:*?"<>|\n\r\t]+')


def _safe(name: str, maxlen: int = 80) -> str:
    name = _INVALID.sub("_", (name or "").strip())
    name = name.strip(". ")
    return (name or "untitled")[:maxlen]


class LocalMarkdownStorage(BaseStorage):
    def __init__(self, cfg: dict):
        # output_dir 相对项目根目录解析
        root = Path(__file__).resolve().parent.parent
        self.out = (root / cfg.get("output_dir", "素材库")).resolve()
        self.out.mkdir(parents=True, exist_ok=True)

    def save(self, a: Article) -> None:
        date = (a.published or "")[:10] or "未知日期"
        folder = self.out / _safe(a.account)
        folder.mkdir(parents=True, exist_ok=True)
        fname = f"{date}-{_safe(a.title)}.md"
        path = folder / fname
        # 同名极少数情况下用 guid 尾段兜底防覆盖
        if path.exists():
            path = folder / f"{date}-{_safe(a.title)}-{a.guid[-8:]}.md"

        body = a.content or a.summary or ""
        md = (
            "---\n"
            f"公众号: {a.account}\n"
            f"标题: {a.title}\n"
            f"链接: {a.link}\n"
            f"发布时间: {a.published}\n"
            f"guid: {a.guid}\n"
            "---\n\n"
            f"# {a.title}\n\n"
            f"> 来源：{a.account}　|　[原文链接]({a.link})　|　{a.published}\n\n"
            f"{body}\n"
        )
        path.write_text(md, encoding="utf-8")
