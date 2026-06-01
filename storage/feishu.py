"""飞书多维表格存储（骨架）。
跑通本地后再启用：在 config.yaml 把 storage 改成 feishu，并填好 feishu 段。
当前为占位实现，调用 save 会提示尚未接好——届时我再帮你补全 API 调用。
"""
from __future__ import annotations

from .base import Article, BaseStorage


class FeishuStorage(BaseStorage):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        missing = [k for k in ("app_id", "app_secret", "app_token", "table_id")
                   if not cfg.get(k)]
        if missing:
            raise RuntimeError(
                "飞书存储未配置完整，缺少: " + ", ".join(missing) +
                "\n请先在 config.yaml 的 feishu 段填好，或暂时把 storage 改回 local。"
            )
        # TODO: 用 app_id/app_secret 换 tenant_access_token，缓存复用
        raise NotImplementedError(
            "飞书写入还没接好。等本地流程跑通、你确定要切飞书时，告诉我，"
            "我用 bitable records/batch_create 接口补全这里。"
        )

    def save(self, a: Article) -> None:  # pragma: no cover
        ...
