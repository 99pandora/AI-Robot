"""SQLite 对话审计日志存储。

该存储只记录请求结果、工具调用和引用，绝不向 Agent 提供上下文恢复能力。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.conversations.models import (
    ConversationDetail,
    ConversationStatus,
    ConversationSummary,
    ConversationTurn,
    ToolCallRecord,
)


@dataclass(frozen=True)
class ConversationTurnHandle:
    """Agent 一次流式处理对应的内部审计句柄。"""

    conversation_pk: str
    turn_id: str
    turn_index: int


class ConversationAuditStore:
    """线程安全的 SQLite 审计日志仓库。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self):
        """显式关闭连接，避免 Windows 下 SQLite 文件被临时目录锁住。"""
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    last_question TEXT NOT NULL DEFAULT '',
                    last_answer TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    tool_count INTEGER NOT NULL DEFAULT 0,
                    reference_count INTEGER NOT NULL DEFAULT 0,
                    total_duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform, user_id, conversation_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id TEXT PRIMARY KEY,
                    conversation_pk TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_message TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    tool_calls_json TEXT NOT NULL DEFAULT '[]',
                    references_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_pk) REFERENCES conversations(id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_updated_at "
                "ON conversations(updated_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_turns_parent "
                "ON conversation_turns(conversation_pk, turn_index)"
            )

    def start_turn(
        self,
        *,
        platform: str,
        user_id: str,
        conversation_id: str,
        user_message: str,
    ) -> ConversationTurnHandle:
        """创建或复用会话，并写入一条 running 轮次。"""
        now = _now()
        conversation_pk = ""
        turn_index = 1
        turn_id = str(uuid4())
        with self._lock, self._session() as connection:
            row = connection.execute(
                """
                SELECT id, turn_count
                FROM conversations
                WHERE platform = ? AND user_id = ? AND conversation_id = ?
                """,
                (platform, user_id, conversation_id),
            ).fetchone()
            if row is None:
                conversation_pk = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO conversations
                    (id, platform, user_id, conversation_id, turn_count, last_question,
                     last_answer, status, tool_count, reference_count, total_duration_ms,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, '', ?, 0, 0, 0, ?, ?)
                    """,
                    (
                        conversation_pk,
                        platform,
                        user_id,
                        conversation_id,
                        user_message,
                        ConversationStatus.RUNNING.value,
                        now,
                        now,
                    ),
                )
            else:
                conversation_pk = row["id"]
                turn_index = int(row["turn_count"]) + 1
                connection.execute(
                    """
                    UPDATE conversations
                    SET turn_count = ?, last_question = ?, status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        turn_index,
                        user_message,
                        ConversationStatus.RUNNING.value,
                        now,
                        conversation_pk,
                    ),
                )
            connection.execute(
                """
                INSERT INTO conversation_turns
                (id, conversation_pk, turn_index, user_message, assistant_message, status,
                 tool_calls_json, references_json, error, duration_ms, created_at)
                VALUES (?, ?, ?, ?, '', ?, '[]', '[]', NULL, 0, ?)
                """,
                (
                    turn_id,
                    conversation_pk,
                    turn_index,
                    user_message,
                    ConversationStatus.RUNNING.value,
                    now,
                ),
            )
        return ConversationTurnHandle(conversation_pk, turn_id, turn_index)

    def finish_turn(
        self,
        handle: ConversationTurnHandle,
        *,
        answer: str,
        tool_calls: list[dict[str, Any]],
        references: list[dict[str, Any]],
        duration_ms: int,
    ) -> None:
        """将一条轮次标记为成功，并更新会话摘要。"""
        self._complete_turn(
            handle,
            status=ConversationStatus.COMPLETED,
            answer=answer,
            tool_calls=tool_calls,
            references=references,
            error=None,
            duration_ms=duration_ms,
        )

    def fail_turn(
        self,
        handle: ConversationTurnHandle,
        *,
        error: str,
        answer: str = "",
        tool_calls: list[dict[str, Any]],
        references: list[dict[str, Any]],
        duration_ms: int,
    ) -> None:
        """记录失败原因，方便后台定位配置或外部服务问题。"""
        self._complete_turn(
            handle,
            status=ConversationStatus.FAILED,
            answer=answer,
            tool_calls=tool_calls,
            references=references,
            error=error,
            duration_ms=duration_ms,
        )

    def _complete_turn(
        self,
        handle: ConversationTurnHandle,
        *,
        status: ConversationStatus,
        answer: str,
        tool_calls: list[dict[str, Any]],
        references: list[dict[str, Any]],
        error: str | None,
        duration_ms: int,
    ) -> None:
        now = _now()
        safe_duration = max(0, int(duration_ms))
        tool_payload = _json_text(tool_calls)
        reference_payload = _json_text(references)
        with self._lock, self._session() as connection:
            connection.execute(
                """
                UPDATE conversation_turns
                SET assistant_message = ?, status = ?, tool_calls_json = ?,
                    references_json = ?, error = ?, duration_ms = ?
                WHERE id = ?
                """,
                (
                    answer,
                    status.value,
                    tool_payload,
                    reference_payload,
                    error,
                    safe_duration,
                    handle.turn_id,
                ),
            )
            connection.execute(
                """
                UPDATE conversations
                SET last_answer = ?, status = ?, tool_count = tool_count + ?,
                    reference_count = reference_count + ?,
                    total_duration_ms = total_duration_ms + ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    answer,
                    status.value,
                    len(tool_calls),
                    len(references),
                    safe_duration,
                    now,
                    handle.conversation_pk,
                ),
            )

    def list_conversations(
        self,
        *,
        limit: int = 50,
        status: ConversationStatus | str | None = None,
        keyword: str | None = None,
    ) -> list[ConversationSummary]:
        """返回最新会话摘要，支持状态和关键字筛选。"""
        safe_limit = min(max(int(limit), 1), 200)
        clauses: list[str] = []
        parameters: list[Any] = []
        if status:
            clauses.append("status = ?")
            parameters.append(str(status))
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            clauses.append(
                "(platform LIKE ? OR user_id LIKE ? OR conversation_id LIKE ? "
                "OR last_question LIKE ? OR last_answer LIKE ?)"
            )
            parameters.extend([pattern] * 5)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(safe_limit)
        with self._lock, self._session() as connection:
            rows = connection.execute(
                f"SELECT * FROM conversations {where} ORDER BY updated_at DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [_summary_from_row(row) for row in rows]

    def get_conversation(self, conversation_pk: str) -> ConversationDetail | None:
        """读取会话详情；找不到时由路由转换为 404。"""
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_pk,)
            ).fetchone()
            if row is None:
                return None
            turns = connection.execute(
                """
                SELECT * FROM conversation_turns
                WHERE conversation_pk = ?
                ORDER BY turn_index ASC
                """,
                (conversation_pk,),
            ).fetchall()
        summary = _summary_from_row(row)
        return ConversationDetail(
            **summary.model_dump(),
            turns=[_turn_from_row(turn) for turn in turns],
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_text(value: list[dict[str, Any]]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_value(raw: str, fallback: list[Any]) -> list[Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return fallback
    return value if isinstance(value, list) else fallback


def _summary_from_row(row: sqlite3.Row) -> ConversationSummary:
    return ConversationSummary(
        id=row["id"],
        platform=row["platform"],
        user_id=row["user_id"],
        conversation_id=row["conversation_id"],
        turn_count=row["turn_count"],
        last_question=row["last_question"],
        last_answer=row["last_answer"],
        status=row["status"],
        tool_count=row["tool_count"],
        reference_count=row["reference_count"],
        total_duration_ms=row["total_duration_ms"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _turn_from_row(row: sqlite3.Row) -> ConversationTurn:
    raw_tools = _json_value(row["tool_calls_json"], [])
    tools = [ToolCallRecord.model_validate(item) for item in raw_tools if isinstance(item, dict)]
    raw_references = _json_value(row["references_json"], [])
    references = [item for item in raw_references if isinstance(item, dict)]
    return ConversationTurn(
        id=row["id"],
        turn_index=row["turn_index"],
        user_message=row["user_message"],
        assistant_message=row["assistant_message"],
        status=row["status"],
        tool_calls=tools,
        references=references,
        error=row["error"],
        duration_ms=row["duration_ms"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
