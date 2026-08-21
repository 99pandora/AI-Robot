"""Agent 使用的 LangChain 工具。"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from langchain_core.tools import StructuredTool, tool

from backend.knowledge.service import DocumentService

logger = logging.getLogger(__name__)


def build_tools(knowledge: DocumentService) -> list[StructuredTool]:
    """创建绑定当前知识库服务和 mock API 地址的工具集合。"""

    @tool
    async def search_knowledge(query: str) -> str:
        """使用 MMR 检索公司文档，并返回答案所需的原文证据。"""
        try:
            rows = knowledge.mmr_search(query)
        except Exception:
            logger.exception("knowledge search failed")
            return json.dumps(
                {"references": [], "context": "", "error": "knowledge_search_unavailable"},
                ensure_ascii=False,
            )
        references = [
            {
                "filename": row["metadata"].get("filename", ""),
                "location": row["metadata"].get("location", ""),
                "title": row["metadata"].get("title", ""),
                "text": row["text"],
            }
            for row in rows
        ]
        return json.dumps(
            {
                "references": references,
                "context": "\n\n".join(item["text"] for item in references),
            },
            ensure_ascii=False,
        )

    @tool
    async def query_attendance(user_id: str | None = None, date: str | None = None) -> str:
        """通过独立 mock HTTP API 查询考勤记录。"""
        return await _mock_get("/api/attendance", {"user_id": user_id, "date": date})

    @tool
    async def query_orders(start_date: str | None = None, end_date: str | None = None) -> str:
        """通过独立 mock HTTP API 查询订单记录。"""
        return await _mock_get(
            "/api/orders", {"start_date": start_date, "end_date": end_date}
        )

    @tool
    async def current_time() -> str:
        """返回 Asia/Shanghai 时区的当前时间。"""
        shanghai = timezone(timedelta(hours=8), name="Asia/Shanghai")
        return datetime.now(shanghai).isoformat()

    return [search_knowledge, query_attendance, query_orders, current_time]


async def _mock_get(path: str, params: dict[str, Any]) -> str:
    """调用 mock API，失败时有限重试并返回可供模型理解的兜底 JSON。"""
    base_url = os.getenv("MOCK_API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    query = {key: value for key, value in params.items() if value not in (None, "")}
    last_error: Exception | None = None
    for _ in range(2):  # 首次失败后只重试一次，避免工具调用长时间阻塞对话。
        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=8.0) as client:
                response = await client.get(path, params=query)
                response.raise_for_status()
                return response.text
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
    logger.warning("mock API request failed path=%s error=%s", path, last_error)
    return json.dumps(
        {"error": "mock_api_unavailable", "detail": str(last_error or "unknown")},
        ensure_ascii=False,
    )
