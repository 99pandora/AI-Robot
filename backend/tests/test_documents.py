from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.knowledge.models import KnowledgeSettings
from backend.knowledge.parser import CHUNK_OVERLAP, MAX_CHUNK_LENGTH, parse_document
from backend.knowledge.routes import build_document_router
from backend.knowledge.service import DocumentService


class FakeEmbeddings:
    """测试替身：返回固定 8 维向量，避免测试调用真实 Embedding API。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量生成文档向量，模拟 LangChain Embeddings 接口。"""
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        """生成查询向量，保持与文档向量相同的维度。"""
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        return [float((sum(map(ord, text)) + index) % 97) for index in range(8)]


def _client(tmp_path: Path) -> TestClient:
    """为每条测试创建隔离的临时 SQLite、上传目录和 Chroma 索引。"""
    app = FastAPI()
    settings = KnowledgeSettings.from_project_root(tmp_path)
    app.include_router(
        build_document_router(DocumentService(settings, embeddings=FakeEmbeddings())),
        prefix="/api",
    )
    return TestClient(app)


def test_upload_list_and_duplicate_skip(tmp_path: Path) -> None:
    """验证上传、列表、下载，以及同内容重复上传时跳过索引。"""
    client = _client(tmp_path)
    file_data = {"file": ("policy.md", b"# Leave\nAnnual leave is 10 days.", "text/markdown")}

    first = client.post("/api/documents", files=file_data)
    duplicate = client.post("/api/documents", files=file_data)
    listing = client.get("/api/documents")

    assert first.status_code == 201
    assert first.json()["status"] == "indexed"
    assert first.json()["chunk_count"] == 1
    download = client.get(f"/api/documents/{first.json()['id']}/download")
    assert download.status_code == 200
    assert download.content == b"# Leave\nAnnual leave is 10 days."
    assert duplicate.status_code == 201
    assert duplicate.json()["skipped"] is True
    assert len(listing.json()) == 1


def test_same_filename_replaces_previous_version(tmp_path: Path) -> None:
    """验证同名但内容变化时生成新版本，并只保留一个 active 文档。"""
    client = _client(tmp_path)
    first = client.post(
        "/api/documents",
        files={"file": ("faq.txt", b"old answer", "text/plain")},
    )
    second = client.post(
        "/api/documents",
        files={"file": ("faq.txt", b"new answer", "text/plain")},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["version"] == 2
    assert len(client.get("/api/documents").json()) == 1


def test_delete_removes_document_from_list_and_download(tmp_path: Path) -> None:
    """验证删除会停用文档、移除列表结果，并禁止继续下载。"""
    client = _client(tmp_path)
    uploaded = client.post(
        "/api/documents",
        files={"file": ("guide.txt", b"hello", "text/plain")},
    )
    document_id = uploaded.json()["id"]

    deleted = client.delete(f"/api/documents/{document_id}")

    assert deleted.status_code == 204
    assert client.get("/api/documents").json() == []
    assert client.get(f"/api/documents/{document_id}/download").status_code == 404


def test_unsupported_document_format_is_rejected(tmp_path: Path) -> None:
    """验证不支持的扩展名返回 415，而不是写入可检索索引。"""
    client = _client(tmp_path)

    response = client.post(
        "/api/documents",
        files={"file": ("payload.csv", b"a,b", "text/csv")},
    )

    assert response.status_code == 415


def test_langchain_splitter_uses_configured_size_and_overlap(tmp_path: Path) -> None:
    """验证 LangChain 切分器遵守 150 字符上限和 30 字符重叠规则。"""
    source = tmp_path / "long.txt"
    source.write_text("a" * 420, encoding="utf-8")

    chunks = parse_document(source, source.name)

    assert len(chunks) > 2
    assert max(len(chunk.text) for chunk in chunks) <= MAX_CHUNK_LENGTH
    assert chunks[1].text[:CHUNK_OVERLAP] == chunks[0].text[-CHUNK_OVERLAP:]


def test_openai_embeddings_keep_alibaba_string_input(monkeypatch, tmp_path: Path) -> None:
    """验证 OpenAI 兼容 Embedding 不会把文本转换成整数 token 数组。"""
    from backend.knowledge import indexer

    captured: dict[str, object] = {}

    class FakeOpenAIEmbeddings(FakeEmbeddings):
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("EMBEDDING_MODEL", "qwen3.7-text-embedding")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.test/compatible-mode/v1")
    monkeypatch.setattr(indexer, "OpenAIEmbeddings", FakeOpenAIEmbeddings)

    knowledge_indexer = indexer.ChromaIndexer(tmp_path / "chroma", project_root=tmp_path)
    knowledge_indexer._embedding_model()

    assert captured["model"] == "qwen3.7-text-embedding"
    assert captured["base_url"] == "https://example.test/compatible-mode/v1"
    assert captured["check_embedding_ctx_length"] is False
    assert captured["chunk_size"] == 20


def test_main_mounts_document_routes_under_api_prefix() -> None:
    """验证模块路由与主服务前缀组合后暴露为 /api/documents。"""
    from backend.main import app

    paths = app.openapi()["paths"]

    assert "/api/documents" in paths
    assert "/api/documents/{document_id}/download" in paths
    assert "/api/documents/{document_id}/reindex" in paths
