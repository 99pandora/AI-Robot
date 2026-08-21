from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from backend.agent.memory import ConversationMemory
from backend.agent.routes import build_chat_router
from backend.agent.service import AgentService
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
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="测试回答"))])


def _agent(tmp_path: Path) -> AgentService:
    knowledge = DocumentService(
        KnowledgeSettings.from_project_root(tmp_path), embeddings=FakeEmbeddings()
    )
    return AgentService(knowledge, model=FakeChatModel())


def test_memory_keeps_four_turns_and_is_in_process() -> None:
    memory = ConversationMemory(max_turns=4)
    for index in range(5):
        memory.append("web:U001:c1", f"q{index}", f"a{index}")

    assert [message.content for message in memory.messages("web:U001:c1")] == [
        "q1",
        "a1",
        "q2",
        "a2",
        "q3",
        "a3",
        "q4",
        "a4",
    ]
    memory.clear()
    assert memory.messages("web:U001:c1") == []


def test_chat_stream_returns_tokens_and_complete(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(build_chat_router(_agent(tmp_path)), prefix="/api")
    response = TestClient(app).post(
        "/api/chat/stream",
        json={"message": "你好", "platform": "web", "user_id": "U001", "conversation_id": "c1"},
    )

    assert response.status_code == 200
    assert "event: token" in response.text
    assert "测试回答" in response.text
    assert "event: complete" in response.text


def test_mmr_search_uses_three_results_from_five_candidates(tmp_path: Path) -> None:
    knowledge = DocumentService(
        KnowledgeSettings.from_project_root(tmp_path), embeddings=FakeEmbeddings()
    )
    knowledge.add_document(
        filename="policy.txt",
        content_type="text/plain",
        content=("annual leave policy " * 50).encode(),
    )

    results = knowledge.mmr_search("leave policy")

    assert len(results) <= 3
    assert knowledge._retriever.search_kwargs == {"fetch_k": 5, "k": 3}
