"""Markdown、TXT、PDF 和 Word 文档解析器。"""

import re
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_community.document_loaders import (
        Docx2txtLoader,
        PyPDFLoader,
        TextLoader,
    )

    LANGCHAIN_LOADER_BACKEND = "langchain-community"
except ImportError:  # 兼容未安装可选 LangChain loader 包的本地环境
    Docx2txtLoader = PyPDFLoader = TextLoader = None  # type: ignore[assignment]
    LANGCHAIN_LOADER_BACKEND = "stdlib-fallback"

from docx import Document as WordDocument
from pypdf import PdfReader

from backend.knowledge.models import DocumentChunk

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".docx"}  # 允许的文件后缀。
MAX_CHUNK_LENGTH = 150  # 单个切片的最大字符数。
CHUNK_OVERLAP = 30  # 相邻切片保留的重叠字符数。


def parse_document(path: Path, filename: str) -> list[DocumentChunk]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"不支持的文档格式；支持：{supported}")
    sections = _load_sections(path, extension)
    return _chunk_sections(sections)


def _load_sections(path: Path, extension: str) -> list[tuple[str, str, str]]:
    """优先使用 LangChain 官方 loader，未安装时保留本地开发回退。"""
    if LANGCHAIN_LOADER_BACKEND == "langchain-community":
        loader: Any
        if extension == ".pdf":
            loader = PyPDFLoader(str(path))
        elif extension == ".docx":
            loader = Docx2txtLoader(str(path))
        else:
            loader = TextLoader(str(path), encoding="utf-8", autodetect_encoding=True)
        documents = loader.load()
        return _sections_from_langchain_documents(documents, path, extension)
    if extension == ".pdf":
        return _parse_pdf_fallback(path)
    if extension == ".docx":
        return _parse_docx_fallback(path)
    return _parse_text_fallback(path)


def _sections_from_langchain_documents(
    documents: list[Document], path: Path, extension: str
) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    for index, document in enumerate(documents, start=1):
        text = document.page_content.strip()
        if not text:
            continue
        metadata = document.metadata or {}
        page = metadata.get("page")
        location = f"第 {int(page) + 1} 页" if page is not None else f"第 {index} 段"

        if extension in {".md", ".markdown", ".txt"}:
            sections.extend(_text_sections(text, path.stem, location))
        elif extension == ".docx":
            sections.extend(_paragraph_sections(text, path.stem))
        else:
            sections.append((text, path.stem, location))
    return sections


def _text_sections(text: str, title: str, location: str) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    current_title = title
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        block = block.strip()
        if not block:
            continue
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", block)
        if heading:
            current_title = heading.group(1).strip()
            remainder = block[heading.end() :].strip()
            if not remainder:
                continue
            block = remainder
        sections.append((block, current_title, location))
    return sections


def _paragraph_sections(text: str, title: str) -> list[tuple[str, str, str]]:
    return [
        (paragraph.strip(), title, f"第 {index} 段")
        for index, paragraph in enumerate(re.split(r"\n+", text), start=1)
        if paragraph.strip()
    ]


def _parse_text_fallback(path: Path) -> list[tuple[str, str, str]]:
    return _text_sections(path.read_text(encoding="utf-8-sig"), path.stem, "第 1 段")


def _parse_pdf_fallback(path: Path) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    for page_number, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append((text, path.stem, f"第 {page_number} 页"))
    return sections


def _parse_docx_fallback(path: Path) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    current_title = path.stem
    paragraph_number = 0
    for paragraph in WordDocument(str(path)).paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        paragraph_number += 1
        if paragraph.style.name.lower().startswith("heading"):
            current_title = text
            continue
        sections.append((text, current_title, f"第 {paragraph_number} 段"))
    return sections


def _chunk_sections(sections: list[tuple[str, str, str]]) -> list[DocumentChunk]:
    # 中文优先按段落和标点切分，最后才退化到字符级，保持语义边界。
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHUNK_LENGTH,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        keep_separator=True,
    )
    chunks: list[DocumentChunk] = []
    for text, title, location in sections:
        for chunk_text in splitter.split_text(text):
            chunk_text = chunk_text.strip()
            if chunk_text:
                chunks.append(DocumentChunk(chunk_text, title, location, len(chunks)))
    return chunks
