"""小苏服务的统一本地文件日志配置。"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock

LOG_FILE_NAME = "xiaosu.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
_HANDLER_MARKER = "_xiaosu_file_handler"
_CONFIG_LOCK = RLock()


def configure_logging(log_directory: Path) -> Path:
    """配置控制台之外的本地文件日志，并返回日志文件路径。

    所有业务模块继续使用标准库 ``logging``，因此 Agent、Mock API 和飞书适配器
    的 warning/error 会统一写入同一个 UTF-8 文件。重复调用时复用同一路径的处理器。
    """

    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = (log_directory / LOG_FILE_NAME).resolve()
    level = _log_level()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",
    )

    with _CONFIG_LOCK:
        managed_loggers = _managed_loggers()
        file_handler = _prepare_existing_handlers(managed_loggers, log_path)
        if file_handler is None:
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            setattr(file_handler, _HANDLER_MARKER, True)
            file_handler.setFormatter(formatter)
        else:
            file_handler.setFormatter(formatter)

        file_handler.setLevel(level)
        root_logger = logging.getLogger()
        if file_handler not in root_logger.handlers:
            root_logger.addHandler(file_handler)
        root_logger.setLevel(level)
        # Uvicorn 的 access/error logger 默认可能不向 root 传播，单独挂载文件处理器。
        for logger in managed_loggers[1:]:
            if file_handler not in logger.handlers:
                logger.addHandler(file_handler)
            logger.setLevel(level)
            logger.propagate = False

    return log_path


def close_logging() -> None:
    """关闭本模块创建的处理器；测试结束或应用优雅退出时可调用。"""

    with _CONFIG_LOCK:
        for logger in _managed_loggers():
            for handler in list(logger.handlers):
                if getattr(handler, _HANDLER_MARKER, False):
                    logger.removeHandler(handler)
                    handler.close()


def _managed_loggers() -> list[logging.Logger]:
    """返回 root 与 Uvicorn 日志器，避免业务日志重复写入。"""

    return [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("uvicorn.access"),
    ]


def _prepare_existing_handlers(
    loggers: list[logging.Logger], log_path: Path
) -> RotatingFileHandler | None:
    """复用目标路径处理器，清理本模块遗留的其他路径处理器。"""

    existing: RotatingFileHandler | None = None
    for logger in loggers:
        for handler in list(logger.handlers):
            if not getattr(handler, _HANDLER_MARKER, False):
                continue
            handler_path = Path(getattr(handler, "baseFilename", "")).resolve()
            if handler_path == log_path and existing is None:
                existing = handler
            elif handler_path == log_path and handler is not existing:
                logger.removeHandler(handler)
                handler.close()
            else:
                logger.removeHandler(handler)
                # 同一个共享处理器可能还挂在其他 logger 上，后续调用会重新挂载。
                handler.close()
    return existing


def _log_level() -> int:
    """读取可选日志级别，非法值时回退到 INFO。"""

    value = os.getenv("XIAOSU_LOG_LEVEL", "INFO").upper().strip()
    level = logging.getLevelNamesMapping().get(value)
    return level if isinstance(level, int) else logging.INFO
