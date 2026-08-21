from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend.agent.routes import build_chat_router
from backend.agent.service import AgentService
from backend.conversations.routes import build_conversation_router
from backend.conversations.store import ConversationAuditStore
from backend.knowledge.models import KnowledgeSettings
from backend.knowledge.service import DocumentService
from backend.tests.test_documents import FakeEmbeddings


class FakeChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools: list[object], **kwargs: object) -> "FakeChatModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="审计测试回答"))])


def test_audit_store_records_turn_and_detail(tmp_path: Path) -> None:
    store = ConversationAuditStore(tmp_path / "conversations.sqlite3")
    handle = store.start_turn(
        platform="web",
        user_id="U001",
        conversation_id="demo",
        user_message="现在几点？",
    )
    store.finish_turn(
        handle,
        answer="现在是 10:00。",
        tool_calls=[{"name": "current_time", "status": "completed"}],
        references=[],
        duration_ms=12,
    )

    summaries = store.list_conversations(keyword="现在几点")
    detail = store.get_conversation(handle.conversation_pk)

    assert len(summaries) == 1
    assert summaries[0].turn_count == 1
    assert detail is not None
    assert detail.turns[0].tool_calls[0].name == "current_time"


def test_failed_tool_keeps_fallback_answer_and_status(tmp_path: Path) -> None:
    store = ConversationAuditStore(tmp_path / "conversations.sqlite3")
    handle = store.start_turn(
        platform="web",
        user_id="U001",
        conversation_id="attendance-failed",
        user_message="查询最近考勤",
    )
    store.fail_turn(
        handle,
        answer="考勤服务暂时不可用，请稍后重试。",
        error="考勤数据服务暂时不可用",
        tool_calls=[{"name": "query_attendance", "status": "failed"}],
        references=[],
        duration_ms=8,
    )

    detail = store.get_conversation(handle.conversation_pk)

    assert detail is not None
    assert detail.status.value == "failed"
    assert detail.last_answer == "考勤服务暂时不可用，请稍后重试。"
    assert detail.turns[0].assistant_message == "考勤服务暂时不可用，请稍后重试。"
    assert detail.turns[0].tool_calls[0].status == "failed"


def test_chat_request_is_visible_in_conversation_api(tmp_path: Path) -> None:
    knowledge = DocumentService(
        KnowledgeSettings.from_project_root(tmp_path), embeddings=FakeEmbeddings()
    )
    store = ConversationAuditStore(tmp_path / "conversations.sqlite3")
    agent = AgentService(knowledge, model=FakeChatModel(), audit_store=store)
    app = FastAPI()
    app.include_router(build_chat_router(agent), prefix="/api")
    app.include_router(build_conversation_router(store), prefix="/api")

    client = TestClient(app)
    response = client.post(
        "/api/chat/stream",
        json={
            "message": "你好",
            "platform": "web",
            "user_id": "U001",
            "conversation_id": "audit-demo",
        },
    )

    assert response.status_code == 200
    summaries = client.get("/api/conversations").json()
    assert len(summaries) == 1
    detail = client.get(f"/api/conversations/{summaries[0]['id']}").json()
    assert detail["turns"][0]["assistant_message"] == "审计测试回答"


def test_agent_failure_is_also_audited(tmp_path: Path) -> None:
    knowledge = DocumentService(
        KnowledgeSettings.from_project_root(tmp_path), embeddings=FakeEmbeddings()
    )
    store = ConversationAuditStore(tmp_path / "conversations.sqlite3")
    # 不注入模型，模拟本地未配置 LLM 的启动状态。
    agent = AgentService(knowledge, audit_store=store)

    async def collect() -> list[dict[str, object]]:
        return [
            item
            async for item in agent.stream(
                key="web:U001:failed-demo",
                message="测试失败日志",
                platform="web",
                user_id="U001",
                conversation_id="failed-demo",
            )
        ]

    import asyncio

    events = asyncio.run(collect())
    summaries = store.list_conversations()
    detail = store.get_conversation(summaries[0].id)

    assert events[-1]["event"] == "error"
    assert summaries[0].status.value == "failed"
    assert detail is not None
    assert detail.turns[0].error
