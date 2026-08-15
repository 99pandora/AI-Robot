"""文档知识库 HTTP 接口。"""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from backend.knowledge.models import DocumentResponse
from backend.knowledge.service import DocumentService


def build_document_router(service: DocumentService) -> APIRouter:
    router = APIRouter(prefix="/documents", tags=["documents"])

    @router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
    async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
        """接收 multipart 文件并完成解析、切分和向量索引。"""
        content = await file.read()
        try:
            record, skipped = service.add_document(
                filename=file.filename or "document",
                content_type=file.content_type or "application/octet-stream",
                content=content,
            )
        except ValueError as error:
            raise HTTPException(status_code=415, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"文档索引失败：{error}") from error
        return DocumentResponse.model_validate({**record.__dict__, "skipped": skipped})

    @router.get("", response_model=list[DocumentResponse])
    async def list_documents() -> list[DocumentResponse]:
        """只返回 active 文档；历史版本和已删除种子不展示。"""
        return [DocumentResponse.model_validate(record) for record in service.list_documents()]

    @router.get("/{document_id}/download")
    async def download_document(document_id: str) -> FileResponse:
        """下载原始文件，种子文件仍从 knowledges/ 原路径读取。"""
        try:
            record = service.get_document(document_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="文档不存在") from error
        path = Path(record.source_path)
        if not path.is_absolute():
            path = service.settings.project_root / path
        if not path.is_file():
            raise HTTPException(status_code=404, detail="文档文件不存在")
        return FileResponse(path, media_type=record.content_type, filename=record.filename)

    @router.post("/{document_id}/reindex", response_model=DocumentResponse)
    async def reindex_document(document_id: str) -> DocumentResponse:
        """使用当前 loader、splitter 和 Embedding 模型重建单个文档。"""
        try:
            return DocumentResponse.model_validate(service.reindex(document_id))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="文档不存在") from error
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"文档索引失败：{error}") from error

    @router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_document(document_id: str) -> None:
        """停用文档并移除向量；不会删除 knowledges/ 下的种子原文件。"""
        try:
            service.delete(document_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="文档不存在") from error

    return router
