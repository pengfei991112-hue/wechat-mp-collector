"""存储后端注册表。新增一种存储（如飞书/企微），在这里登记即可。"""
from .base import Article, BaseStorage


def get_storage(name: str, config: dict) -> BaseStorage:
    name = (name or "local").lower()
    if name == "local":
        from .local_md import LocalMarkdownStorage
        return LocalMarkdownStorage(config.get("local", {}))
    if name == "feishu":
        from .feishu import FeishuStorage
        return FeishuStorage(config.get("feishu", {}))
    raise ValueError(f"未知的存储后端: {name}（可选 local / feishu）")
