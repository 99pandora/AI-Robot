"""供 Agent 通过 HTTP 调用的独立内部业务 mock 服务。"""

from datetime import date
from pathlib import Path

from fastapi import FastAPI, Query

from backend.mock_api.models import AttendanceRecord, OrderRecord
from backend.mock_api.repository import find_attendance, find_orders
from backend.logging_config import configure_logging

configure_logging(Path(__file__).resolve().parents[2] / "logs")
app = FastAPI(title="小苏 Mock API", version="0.1.0")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "xiaosu-mock-api"}


@app.get("/api/attendance", response_model=list[AttendanceRecord])
async def query_attendance(
    user_id: str | None = Query(default=None, alias="user_id"),
    record_date: date | None = Query(default=None, alias="date"),
) -> list[AttendanceRecord]:
    """按员工编号和日期筛选考勤；员工编号兼容 001 与 U001。"""
    return find_attendance(user_id, record_date)


@app.get("/api/orders", response_model=list[OrderRecord])
async def query_orders(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> list[OrderRecord]:
    """按创建日期范围筛选订单。"""
    return find_orders(start_date, end_date)
