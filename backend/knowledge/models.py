"""知识库领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DocumentStatus(StrEnum):
    """文档在元数据仓库中的生命周期状态。"""

    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


@dataclass(frozen=True)
class KnowledgeSettings:
    project_root: Path  # 项目根目录，用于定位 knowledges/ 和配置文件。
    storage_root: Path  # 运行时目录，保存 SQLite、Chroma 和上传文件。
    database_path: Path  # 文档元数据 SQLite 文件路径。
    chroma_path: Path  # Chroma 持久化向量索引目录。
    uploads_path: Path  # 用户上传文件的运行时存储目录。

    @classmethod
    def from_project_root(cls, project_root: Path) -> "KnowledgeSettings":
        storage_root = project_root / "storage"
        return cls(
            project_root=project_root,
            storage_root=storage_root,
            database_path=storage_root / "documents.sqlite3",
            chroma_path=storage_root / "chroma",
            uploads_path=storage_root / "uploads",
        )


@dataclass(frozen=True)
class DocumentChunk:
    text: str  # 送入 Embedding 模型和检索结果展示的正文片段。
    title: str  # 片段所属标题，来源于 Markdown 标题或文件名。
    location: str  # 原文位置，例如“第 2 页”或“第 3 段”。
    chunk_index: int  # 文档内从 0 开始的切片序号。


@dataclass(frozen=True)
class DocumentRecord:
    id: str  # 文档实例唯一 ID；同名替换会生成新的 ID。
    filename: str  # 用户看到的原始文件名，也是同名替换的业务键。
    content_type: str  # MIME 类型，用于下载响应头。
    size: int  # 原始文件字节数。
    sha256: str  # 文件内容摘要，用于判断是否重复上传。
    status: DocumentStatus  # pending、indexed 或 failed。
    version: int  # 同一文件名的递增版本号。
    is_seed: bool  # 是否来自只读 knowledges/ 种子目录。
    active: bool  # 是否参与列表、检索和下载；删除只会置为 False。
    source_path: str  # 原文件路径，上传文件位于 storage/uploads/。
    chunk_count: int  # 成功索引后生成的切片数量。
    error: str | None  # 最近一次索引失败原因。
    created_at: datetime  # 记录创建时间（UTC）。
    updated_at: datetime  # 记录最近更新时间（UTC）。


class DocumentResponse(BaseModel):
    """文档管理接口返回模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="文档实例唯一 ID")
    filename: str = Field(description="文件名")
    content_type: str = Field(description="文件 MIME 类型")
    size: int = Field(description="文件字节数")
    sha256: str = Field(description="文件内容 SHA-256 摘要")
    status: DocumentStatus = Field(description="pending、indexed 或 failed")
    version: int = Field(description="同名文件的递增版本号")
    is_seed: bool = Field(description="是否为 knowledges/ 中的种子文档")
    chunk_count: int = Field(description="已生成的索引切片数")
    error: str | None = Field(default=None, description="最近一次索引错误")
    created_at: datetime = Field(description="创建时间（UTC）")
    updated_at: datetime = Field(description="更新时间（UTC）")
    skipped: bool = Field(default=False, description="是否因内容重复而跳过重新索引")
