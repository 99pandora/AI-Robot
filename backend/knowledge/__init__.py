"""文档知识库：解析、元数据管理与 Chroma 索引。"""

from backend.knowledge.models import DocumentStatus, KnowledgeSettings
from backend.knowledge.service import DocumentService

__all__ = ["DocumentService", "DocumentStatus", "KnowledgeSettings"]
