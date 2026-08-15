"""文档知识库业务服务。"""

from hashlib import sha256
from pathlib import Path
from threading import RLock
from uuid import uuid4

from langchain_core.embeddings import Embeddings

from backend.knowledge.indexer import ChromaIndexer
from backend.knowledge.models import (
    DocumentChunk,
    DocumentRecord,
    KnowledgeSettings,
)
from backend.knowledge.parser import parse_document
from backend.knowledge.store import DocumentStore


class DocumentService:
    def __init__(
        self, settings: KnowledgeSettings, *, embeddings: Embeddings | None = None
    ) -> None:
        self.settings = settings
        self.settings.storage_root.mkdir(parents=True, exist_ok=True)
        self.settings.uploads_path.mkdir(parents=True, exist_ok=True)
        self.store = DocumentStore(settings.database_path)
        self.indexer = ChromaIndexer(
            settings.chroma_path,
            project_root=settings.project_root,
            embeddings=embeddings,
        )
        self._lock = RLock()

    def list_documents(self) -> list[DocumentRecord]:
        """列出当前 active 文档。"""
        return self.store.list_active()

    def get_document(self, document_id: str) -> DocumentRecord:
        """获取 active 文档，不存在时抛出 KeyError。"""
        record = self.store.get_active(document_id)
        if record is None:
            raise KeyError(document_id)
        return record

    def add_document(
        self,
        *,
        filename: str,
        content_type: str,
        content: bytes,
        is_seed: bool = False,
        source_path: Path | None = None,
    ) -> tuple[DocumentRecord, bool]:
        """保存文件并完成解析、切分、Embedding 和 Chroma 写入。"""
        filename = _safe_filename(filename)
        digest = sha256(content).hexdigest()
        with self._lock:
            current = self.store.find_active_filename(filename)
            if current and current.sha256 == digest and current.status.value == "indexed":
                # 元数据可能来自旧模型索引；缺少当前 collection 向量时必须重建。
                if self.indexer.has_document(current.id):
                    return current, True
                return self.reindex(current.id), False
            version = current.version + 1 if current else 1
            document_id = uuid4().hex
            target_path = source_path or self.settings.uploads_path / f"{document_id}_{filename}"
            if source_path is None:
                target_path.write_bytes(content)
            if current:
                # 同名新版本上线前先移除旧版本向量，避免检索到过期内容。
                self.indexer.remove(current.id)
            record = self.store.create_pending(
                document_id=document_id,
                filename=filename,
                content_type=content_type or "application/octet-stream",
                size=len(content),
                sha256=digest,
                version=version,
                is_seed=is_seed,
                source_path=str(target_path),
            )
            try:
                chunks = parse_document(target_path, filename)
                self.indexer.upsert(record, chunks)
                return self.store.mark_indexed(document_id, len(chunks)), False
            except Exception as error:
                self.store.mark_failed(document_id, str(error))
                raise

    def reindex(self, document_id: str) -> DocumentRecord:
        """按当前配置重新处理一个文档。"""
        with self._lock:
            record = self.get_document(document_id)
            try:
                chunks = parse_document(Path(record.source_path), record.filename)
                self.indexer.upsert(record, chunks)
                return self.store.mark_indexed(document_id, len(chunks))
            except Exception as error:
                self.store.mark_failed(document_id, str(error))
                raise

    def delete(self, document_id: str) -> None:
        """删除检索资格并移除向量；种子原文件保留。"""
        with self._lock:
            record = self.get_document(document_id)
            self.indexer.remove(record.id)
            self.store.deactivate(record.id)

    def query(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        """检索当前 active 文档，并过滤残留的历史向量。"""
        active_ids = {record.id for record in self.list_documents()}
        return [
            result
            for result in self.indexer.query(query, limit)
            if result["metadata"]["document_id"] in active_ids
        ]


def _safe_filename(filename: str) -> str:
    """判断文件名是否正确"""
    name = Path(filename or "document").name
    if not name or name in {".", ".."}:
        raise ValueError("文件名不能为空")
    return name
