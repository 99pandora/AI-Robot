"""小苏主服务入口。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.knowledge.models import KnowledgeSettings
from backend.knowledge.routes import build_document_router
from backend.knowledge.service import DocumentService

app = FastAPI(title="小苏内部 AI 助手", version="0.1.0")
# 以源码位置确定项目根目录，保证从任意工作目录启动都能找到 storage/ 和 knowledges/。
project_root = Path(__file__).resolve().parents[1]
document_service = DocumentService(KnowledgeSettings.from_project_root(project_root))

app.include_router(build_document_router(document_service), prefix="/api")


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    """主服务健康检查。"""
    return {"status": "ok", "service": "xiaosu-api"}


# 构建前端后由 FastAPI 同源托管管理后台；开发时则使用 Vite 的 /api 代理。
frontend_dist = project_root / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
