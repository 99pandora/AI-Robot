"""小苏主服务入口。"""

from pathlib import Path
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.agent.routes import build_chat_router
from backend.agent.service import AgentService
from backend.conversations.routes import build_conversation_router
from backend.conversations.store import ConversationAuditStore
from backend.knowledge.models import KnowledgeSettings
from backend.knowledge.routes import build_document_router
from backend.knowledge.service import DocumentService

app = FastAPI(title="小苏内部 AI 助手", version="0.1.0")
# 以源码位置确定项目根目录，保证从任意工作目录启动都能找到 storage/ 和 knowledges/。
project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env", override=False)
document_service = DocumentService(KnowledgeSettings.from_project_root(project_root))
conversation_store = ConversationAuditStore(
    document_service.settings.storage_root / "conversations.sqlite3"
)
agent_service = AgentService(document_service, audit_store=conversation_store)

app.include_router(build_document_router(document_service), prefix="/api")
app.include_router(build_chat_router(agent_service), prefix="/api")
app.include_router(build_conversation_router(conversation_store), prefix="/api")


@app.get("/api/health")
async def health_check() -> dict[str, object]:
    """主服务健康检查，同时探测 Agent 依赖的独立 mock API。"""
    mock_api_status = await _check_mock_api()
    return {
        "status": "ok",
        "service": "xiaosu-api",
        "dependencies": {"mock_api": mock_api_status},
    }


async def _check_mock_api() -> str:
    """以短超时探测考勤和订单共用的 mock API，不阻断主服务健康状态。"""
    base_url = os.getenv("MOCK_API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=0.8) as client:
            response = await client.get("/health")
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return "unavailable"
    return "ok"


# 构建前端后由 FastAPI 同源托管管理后台；开发时则使用 Vite 的 /api 代理。
frontend_dist = project_root / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
