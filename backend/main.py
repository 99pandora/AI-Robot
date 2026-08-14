"""小苏主服务入口。"""

from fastapi import FastAPI

app = FastAPI(title="小苏内部 AI 助手", version="0.1.0")


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    """主服务健康检查。"""
    return {"status": "ok", "service": "xiaosu-api"}
