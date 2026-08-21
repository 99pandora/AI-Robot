"""本地文件日志配置测试。"""

import logging
from pathlib import Path

from backend.logging_config import close_logging, configure_logging


def test_logging_writes_utf8_file_and_reuses_handler(tmp_path: Path) -> None:
    log_path = configure_logging(tmp_path / "logs")
    logger = logging.getLogger("backend.tests.local_file_logging")

    try:
        logger.warning("本地文件日志测试")
        for handler in logging.getLogger().handlers:
            handler.flush()

        assert log_path.exists()
        assert "本地文件日志测试" in log_path.read_text(encoding="utf-8")
        assert configure_logging(tmp_path / "logs") == log_path
        logger.warning("重复配置后仍可写入")
        for handler in logging.getLogger().handlers:
            handler.flush()
        assert "重复配置后仍可写入" in log_path.read_text(encoding="utf-8")
        managed = [
            handler
            for handler in logging.getLogger().handlers
            if getattr(handler, "_xiaosu_file_handler", False)
        ]
        assert len(managed) == 1
    finally:
        # Windows 下临时目录删除前必须先关闭 RotatingFileHandler。
        close_logging()
