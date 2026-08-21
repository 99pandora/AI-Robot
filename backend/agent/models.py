"""最小聊天 Agent 接口的请求模型。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000, description="用户本轮问题")
    platform: str = Field(default="web", min_length=1, max_length=32, description="来源平台")
    user_id: str = Field(default="anonymous", min_length=1, max_length=128, description="用户 ID")
    conversation_id: str = Field(
        default="default", min_length=1, max_length=128, description="会话 ID"
    )
