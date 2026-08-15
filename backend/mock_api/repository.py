"""只读加载项目中的 mock JSON 数据。"""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from backend.mock_api.models import AttendanceRecord, OrderRecord

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=1)
def load_attendance() -> tuple[AttendanceRecord, ...]:
    """读取并缓存只读考勤 mock 数据。"""
    records = json.loads((DATA_DIR / "attendance.json").read_text(encoding="utf-8"))
    return tuple(AttendanceRecord.model_validate(record) for record in records)


@lru_cache(maxsize=1)
def load_orders() -> tuple[OrderRecord, ...]:
    """读取并缓存只读订单 mock 数据。"""
    records = json.loads((DATA_DIR / "order.json").read_text(encoding="utf-8"))
    return tuple(OrderRecord.model_validate(record) for record in records)


def find_attendance(user_id: str | None, record_date: date | None) -> list[AttendanceRecord]:
    """按兼容格式的员工编号和日期筛选考勤。"""
    normalized_user_id = _normalize_user_id(user_id) if user_id else None
    return [
        record
        for record in load_attendance()
        if (normalized_user_id is None or record.user_id == normalized_user_id)
        and (record_date is None or record.check_in_date == record_date)
    ]


def find_orders(start_date: date | None, end_date: date | None) -> list[OrderRecord]:
    """按闭区间创建日期筛选订单。"""
    return [
        record
        for record in load_orders()
        if (start_date is None or record.create_time.date() >= start_date)
        and (end_date is None or record.create_time.date() <= end_date)
    ]


def _normalize_user_id(user_id: str) -> str:
    normalized = user_id.strip().upper()
    return normalized if normalized.startswith("U") else f"U{normalized.zfill(3)}"
