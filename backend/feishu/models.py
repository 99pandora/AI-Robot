"""飞书适配器配置和状态模型。"""

from dataclasses import dataclass
from enum import StrEnum
import os


class FeishuConnectionStatus(StrEnum):
    """飞书连接对外展示的状态。"""

    DISABLED = "disabled"
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    MISCONFIGURED = "misconfigured"


@dataclass(frozen=True)
class FeishuSettings:
    """飞书机器人运行配置；密钥只存在于进程内存，不写入运行日志。"""

    app_id: str = ""
    app_secret: str = ""
    connect_timeout_seconds: float = 10.0
    send_max_attempts: int = 3
    send_backoff_seconds: float = 0.5
    dedup_ttl_seconds: int = 12 * 60 * 60
    dedup_max_entries: int = 5000

    @classmethod
    def from_env(cls) -> "FeishuSettings":
        """从环境变量读取配置；未配置凭据时保持可本地启动。"""

        return cls(
            app_id=os.getenv("FEISHU_APP_ID", "").strip(),
            app_secret=os.getenv("FEISHU_APP_SECRET", "").strip(),
            connect_timeout_seconds=_env_float(
                "FEISHU_CONNECT_TIMEOUT_SECONDS", 10.0, minimum=1.0
            ),
            send_max_attempts=_env_int("FEISHU_SEND_MAX_ATTEMPTS", 3, minimum=1),
            send_backoff_seconds=_env_float(
                "FEISHU_SEND_BACKOFF_SECONDS", 0.5, minimum=0.0
            ),
            dedup_ttl_seconds=_env_int(
                "FEISHU_DEDUP_TTL_SECONDS", 12 * 60 * 60, minimum=1
            ),
            dedup_max_entries=_env_int("FEISHU_DEDUP_MAX_ENTRIES", 5000, minimum=1),
        )

    @property
    def configured(self) -> bool:
        """只有 App ID 和 Secret 都存在时才尝试建立长连接。"""

        return bool(self.app_id and self.app_secret)

    @property
    def configuration_error(self) -> str | None:
        """返回部分配置的可读错误；完全为空表示功能被主动停用。"""

        if bool(self.app_id) == bool(self.app_secret):
            return None
        return "FEISHU_APP_ID 和 FEISHU_APP_SECRET 必须同时配置"

    def __post_init__(self) -> None:
        if self.connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds 必须大于 0")
        if self.send_max_attempts < 1:
            raise ValueError("send_max_attempts 必须至少为 1")
        if self.send_backoff_seconds < 0:
            raise ValueError("send_backoff_seconds 不能为负数")
        if self.dedup_ttl_seconds < 1 or self.dedup_max_entries < 1:
            raise ValueError("去重缓存配置必须为正数")


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _env_float(name: str, default: float, *, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default
