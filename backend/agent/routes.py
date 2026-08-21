"""最小 Agent 聊天 SSE 接口。"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.agent.models import ChatRequest
from backend.agent.service import AgentService


def build_chat_router(agent: AgentService) -> APIRouter:
    """创建聊天路由；Agent 实例由应用层注入以共享进程内记忆。"""
    router = APIRouter(prefix="/chat", tags=["chat"])

    @router.post("/stream")
    async def chat_stream(request: ChatRequest) -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            # 三段组合键保证不同平台、用户和会话之间不会串上下文。
            key = f"{request.platform}:{request.user_id}:{request.conversation_id}"
            async for item in agent.stream(
                key=key,
                message=request.message,
                platform=request.platform,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
            ):
                yield _sse(item["event"], item["data"])

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def _sse(event: str, data: object) -> str:
    """将一个 Agent 事件编码为浏览器可消费的 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
