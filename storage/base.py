"""存储后端的统一接口。换存储只需实现 save()。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Article:
    """一篇推文的标准结构，所有存储后端都吃这个。"""
    account: str          # 公众号名（来自 config 的 feed.name）
    title: str            # 标题
    link: str             # 原文链接
    published: str        # 发布时间，ISO 字符串，可能为空
    summary: str          # 摘要
    content: str          # 正文（HTML 或纯文本），可能为空
    guid: str             # 全局唯一 id，用于去重
    extra: dict = field(default_factory=dict)


class BaseStorage:
    """存储后端基类。"""

    def save(self, article: Article) -> None:
        """保存一篇新文章。同一篇不会被重复调用（去重在上层做）。"""
        raise NotImplementedError

    def close(self) -> None:
        """收尾（如批量提交、关闭连接）。默认无操作。"""
        pass
