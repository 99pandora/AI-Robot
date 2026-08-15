"""SQLite 文档元数据存储。"""

from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from threading import RLock

from backend.knowledge.models import DocumentRecord, DocumentStatus


class DocumentStore:
    """只保存文档审计元数据，不向 Agent 提供上下文记忆。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    is_seed INTEGER NOT NULL,
                    active INTEGER NOT NULL,
                    source_path TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_filename_active "
                "ON documents(filename, active)"
            )

    def list_active(self) -> list[DocumentRecord]:
        """返回仍参与业务流程的文档，按创建时间倒序。"""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE active = 1 ORDER BY created_at DESC"
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def get_active(self, document_id: str) -> DocumentRecord | None:
        """按 ID 查找 active 文档；删除或旧版本返回 None。"""
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ? AND active = 1", (document_id,)
            ).fetchone()
        return _record_from_row(row) if row else None

    def find_active_filename(self, filename: str) -> DocumentRecord | None:
        """查找某文件名当前生效的最高版本。"""
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE filename = ? AND active = 1 "
                "ORDER BY version DESC LIMIT 1",
                (filename,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def create_pending(
        self,
        *,
        document_id: str,
        filename: str,
        content_type: str,
        size: int,
        sha256: str,
        version: int,
        is_seed: bool,
        source_path: str,
    ) -> DocumentRecord:
        """先写入 pending 记录，索引成功后由服务更新为 indexed。"""
        now = _now()
        with self._lock, self._connect() as connection:
            # 同名文件只保留一个 active 版本，历史版本留在审计库中。
            connection.execute(
                "UPDATE documents SET active = 0, updated_at = ? "
                "WHERE filename = ? AND active = 1",
                (now, filename),
            )
            connection.execute(
                """
                INSERT INTO documents
                (id, filename, content_type, size, sha256, status, version, is_seed,
                 active, source_path, chunk_count, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0, NULL, ?, ?)
                """,
                (
                    document_id,
                    filename,
                    content_type,
                    size,
                    sha256,
                    DocumentStatus.PENDING.value,
                    version,
                    int(is_seed),
                    source_path,
                    now,
                    now,
                ),
            )
        record = self.get_active(document_id)
        if record is None:
            raise RuntimeError("创建文档记录失败")
        return record

    def mark_indexed(self, document_id: str, chunk_count: int) -> DocumentRecord:
        """记录索引成功及切片数量。"""
        return self._update(document_id, DocumentStatus.INDEXED, chunk_count, None)

    def mark_failed(self, document_id: str, error: str) -> DocumentRecord:
        """记录索引失败原因，便于后台诊断。"""
        return self._update(document_id, DocumentStatus.FAILED, 0, error)

    def deactivate(self, document_id: str) -> DocumentRecord | None:
        """停用文档，不删除 SQLite 历史记录。"""
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE documents SET active = 0, updated_at = ? WHERE id = ? AND active = 1",
                (now, document_id),
            )
        return self.get_active(document_id)

    def _update(
        self,
        document_id: str,
        status: DocumentStatus,
        chunk_count: int,
        error: str | None,
    ) -> DocumentRecord:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE documents SET status = ?, chunk_count = ?, error = ?, updated_at = ? "
                "WHERE id = ? AND active = 1",
                (status.value, chunk_count, error, now, document_id),
            )
        record = self.get_active(document_id)
        if record is None:
            raise RuntimeError("更新文档记录失败")
        return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_from_row(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        id=row["id"],
        filename=row["filename"],
        content_type=row["content_type"],
        size=row["size"],
        sha256=row["sha256"],
        status=DocumentStatus(row["status"]),
        version=row["version"],
        is_seed=bool(row["is_seed"]),
        active=bool(row["active"]),
        source_path=row["source_path"],
        chunk_count=row["chunk_count"],
        error=row["error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
