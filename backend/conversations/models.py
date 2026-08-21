"""对话日志的强类型模型。

日志模型与 Agent 的内存上下文明确分离：这些对象只服务于审计接口和前端展示。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationStatus(StrEnum):
    """一条会话当前最后一次处理的状态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolCallRecord(BaseModel):
    """模型实际触发过的工具及其最终状态。"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=128)
    status: Literal["started", "completed", "failed"] = Field(default="completed")


class ConversationTurn(BaseModel):
    """一次用户提问及其 Agent 回答组成的审计记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    turn_index: int = Field(ge=1)
    user_message: str
    assistant_message: str = ""
    status: ConversationStatus
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    created_at: datetime


class ConversationSummary(BaseModel):
    """对话列表中展示的轻量摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: str
    user_id: str
    conversation_id: str
    turn_count: int = Field(default=0, ge=0)
    last_question: str = ""
    last_answer: str = ""
    status: ConversationStatus
    tool_count: int = Field(default=0, ge=0)
    reference_count: int = Field(default=0, ge=0)
    total_duration_ms: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    """对话摘要及其全部轮次。"""

    turns: list[ConversationTurn] = Field(default_factory=list)
