"""Chroma 向量索引封装。"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from backend.knowledge.models import DocumentChunk, DocumentRecord

EMBEDDING_BATCH_SIZE = 20  # 百炼兼容接口单次最多接收 20 条文本。


@dataclass(frozen=True)
class EmbeddingConfig:
    """OpenAI-compatible Embedding 服务配置。"""

    model: str  # Embedding 模型名，例如 text-embedding-3-small。
    api_key: str | None  # 服务鉴权密钥；优先使用 EMBEDDING_API_KEY。
    base_url: str | None  # OpenAI-compatible 服务地址；为空时使用官方地址。

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "EmbeddingConfig":
        if project_root:
            # 仅加载本地配置文件；进程环境变量仍可作为部署环境的注入方式。
            load_dotenv(project_root / ".env", override=False)
        return cls(
            model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            api_key=(
                os.getenv("EMBEDDING_API_KEY")
                or os.getenv("LLM_API_KEY")
                or os.getenv("OPENAI_API_KEY")
            ),
            base_url=(
                os.getenv("EMBEDDING_BASE_URL")
                or os.getenv("LLM_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
            ),
        )


class ChromaIndexer:
    def __init__(
        self,
        chroma_path: Path,
        *,
        project_root: Path | None = None,
        embeddings: Embeddings | None = None,
    ) -> None:
        chroma_path.mkdir(parents=True, exist_ok=True)
        self.embedding_config = EmbeddingConfig.from_env(project_root)
        self.embeddings = embeddings
        self.client = chromadb.PersistentClient(path=str(chroma_path))
        # 不同模型的向量维度可能不同，按模型名隔离 collection，避免混用向量。
        collection_name = _collection_name(self.embedding_config.model)
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def upsert(self, record: DocumentRecord, chunks: list[DocumentChunk]) -> None:
        self.remove(record.id)
        if not chunks:
            return
        # 批量调用 Embedding API，减少网络往返；Chroma 只保存结果和元数据。
        vectors = self._embedding_model().embed_documents([chunk.text for chunk in chunks])
        self.collection.upsert(
            ids=[f"{record.id}:{chunk.chunk_index}" for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=vectors,
            metadatas=[
                {
                    "document_id": record.id,
                    "version": record.version,
                    "filename": record.filename,
                    "title": chunk.title,
                    "location": chunk.location,
                    "chunk_index": chunk.chunk_index,
                }
                for chunk in chunks
            ],
        )

    def remove(self, document_id: str) -> None:
        self.collection.delete(where={"document_id": document_id})

    def has_document(self, document_id: str) -> bool:
        """检查当前模型对应的 collection 是否已有该文档向量。"""
        result = self.collection.get(where={"document_id": document_id}, limit=1)
        return bool(result.get("ids"))

    def query(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        result = self.collection.query(
            query_embeddings=[self._embedding_model().embed_query(query)],
            n_results=limit,
            include=["documents", "metadatas", "distances"],
        )
        rows: list[dict[str, object]] = []
        for document, metadata, distance in zip(
            result.get("documents", [[]])[0],
            result.get("metadatas", [[]])[0],
            result.get("distances", [[]])[0],
        ):
            rows.append({"text": document, "metadata": metadata, "distance": distance})
        return rows

    def _embedding_model(self) -> Embeddings:
        if self.embeddings is None:
            try:
                self.embeddings = OpenAIEmbeddings(
                    model=self.embedding_config.model,
                    api_key=self.embedding_config.api_key,
                    base_url=self.embedding_config.base_url,
                    # 阿里百炼 OpenAI 兼容接口要求 input 是字符串数组；
                    # LangChain 默认先用 tiktoken 编码成整数数组，关闭长度检查
                    # 后会直接传递原始字符串。知识库切片已限制在 150 字符以内，
                    # 因此这里无需再由客户端拆分超长文本。
                    # 百炼单次最多接收 20 条输入，避免触发 batch size 限制。
                    check_embedding_ctx_length=False,
                    chunk_size=EMBEDDING_BATCH_SIZE,
                )
            except Exception as error:
                raise RuntimeError(
                    "未配置可用的 Embedding 模型，请在 .env 设置 "
                    "EMBEDDING_API_KEY、EMBEDDING_BASE_URL 和 EMBEDDING_MODEL"
                ) from error
        return self.embeddings


def _collection_name(model: str) -> str:
    """将模型名映射为稳定且符合 Chroma 命名约束的 collection 名称。"""
    suffix = hashlib.sha256(model.encode("utf-8")).hexdigest()[:8]
    return f"xiaosu_knowledge_{suffix}"
