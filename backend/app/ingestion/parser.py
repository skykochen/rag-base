"""
==========================================
  文档解析器 —— 把原始文件"读懂"成文本
==========================================

【这个模块做什么？】
用户上传的是 PDF/DOCX/Markdown/HTML 文件，
但计算机只能理解纯文本。这个模块用 Docling 库把各种格式转成 Markdown 文本。

【为什么用 Docling？】
Docling 是一个 IBM 开源的文档解析库，支持：
- PDF（包括扫描件，OCR 识别）
- DOCX（Word 文档）
- HTML
- Markdown（这个本来就能直接读）

【同步还是异步？】
Docling 是同步调用（内部可能加载模型），
用 asyncio.to_thread 包装异步接口，避免阻塞事件循环。
"""

import asyncio
import io

from docling.datamodel.base_models import DocumentStream
from docling.document_converter import DocumentConverter
from langchain_core.documents import Document

from app.core.exceptions import AppException
from app.core.logging import get_logger

logger = get_logger(__name__)


class DocumentParseError(AppException):
    """解析失败时抛出的异常。"""
    code = "document_parse_error"
    message = "文档解析失败"
    http_status = 400


# 模块级缓存 DocumentConverter 实例
# 因为 DocumentConverter 内部加载的模型比较大，重复创建浪费时间和内存
_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    """
    获取单例 DocumentConverter。

    第一次调用时创建，后续复用。
    这种模式叫"延迟初始化"（Lazy Initialization）：
    不启动时就加载模型，而是等到真正需要时才加载。
    """
    global _converter
    if _converter is None:
        _converter = DocumentConverter()
    return _converter


def _convert_sync(filename: str, content: bytes) -> str:
    """
    同步执行文档解析（由 asyncio.to_thread 在后台线程执行）。

    参数：
    - filename: 文件名（Docling 用扩展名判断格式）
    - content: 文件的原始字节流

    返回：
    - Markdown 格式的文本内容
    """
    source = DocumentStream(name=filename, stream=io.BytesIO(content))
    result = _get_converter().convert(source)
    return result.document.export_to_markdown()


async def parse(filename: str, content: bytes) -> list[Document]:
    """
    解析文档并返回 LangChain Document 列表。

    参数：
    - filename: 文件名（含扩展名）
    - content: 文件字节流

    返回：
    - LangChain Document 列表。目前一份文档只返回一篇。
      后续可扩展为按页拆分，每页一个 Document。

    【为什么返回 list[Document] 而不是 str？】
    LangChain 的 Document 对象不仅包含文本（page_content），
    还包含元数据（metadata），方便下游（如切分器）使用。
    """
    try:
        markdown = await asyncio.to_thread(_convert_sync, filename, content)
    except Exception as exc:
        logger.exception("docling parse failed: %s", filename)
        raise DocumentParseError(f"Docling 解析失败：{exc}") from exc

    if not markdown.strip():
        raise DocumentParseError("解析结果为空，文档可能损坏或不受支持")

    return [
        Document(
            page_content=markdown,
            metadata={"source": filename},
        )
    ]
