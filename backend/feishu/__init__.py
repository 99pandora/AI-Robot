"""飞书长连接适配器。"""

from backend.feishu.models import FeishuConnectionStatus, FeishuSettings
from backend.feishu.service import FeishuAdapter, build_feishu_channel

__all__ = [
    "FeishuAdapter",
    "FeishuConnectionStatus",
    "FeishuSettings",
    "build_feishu_channel",
]
