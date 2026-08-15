"""知识库种子文件索引入口。"""

from pathlib import Path

from backend.knowledge.models import KnowledgeSettings
from backend.knowledge.service import DocumentService


def index_seed_documents(project_root: Path) -> list[str]:
    settings = KnowledgeSettings.from_project_root(project_root)
    service = DocumentService(settings)
    indexed: list[str] = []
    for path in sorted((project_root / "knowledges").iterdir()):
        if not path.is_file():
            continue
        record, skipped = service.add_document(
            filename=path.name,
            content_type=_content_type(path),
            content=path.read_bytes(),
            is_seed=True,
            source_path=path,
        )
        if not skipped:
            indexed.append(f"{record.filename} ({record.chunk_count} chunks)")
    return indexed


def _content_type(path: Path) -> str:
    return {
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(path.suffix.lower(), "application/octet-stream")
