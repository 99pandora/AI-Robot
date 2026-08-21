"""对话日志管理接口。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.conversations.models import ConversationDetail, ConversationStatus, ConversationSummary
from backend.conversations.store import ConversationAuditStore


def build_conversation_router(store: ConversationAuditStore) -> APIRouter:
    """创建日志列表与详情路由。"""
    router = APIRouter(prefix="/conversations", tags=["conversations"])

    @router.get("", response_model=list[ConversationSummary])
    async def list_conversations(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        status: ConversationStatus | None = None,
        keyword: Annotated[str | None, Query(max_length=128)] = None,
    ) -> list[ConversationSummary]:
        return store.list_conversations(limit=limit, status=status, keyword=keyword)

    @router.get("/{conversation_pk}", response_model=ConversationDetail)
    async def get_conversation(conversation_pk: str) -> ConversationDetail:
        record = store.get_conversation(conversation_pk)
        if record is None:
            raise HTTPException(status_code=404, detail="对话日志不存在")
        return record

    return router
