"""
==========================================
  文本切分器 —— 把长文本切成小段落
==========================================

【为什么需要切分？】
语言模型的上下文长度有限（如 8K tokens），
不能把整本书直接丢给模型，需要切成合适大小的段落。

【什么是 RecursiveCharacterTextSplitter？】
递归字符文本切分器。它的工作方式：
1. 先用段落分隔符（\n\n）尝试切
2. 如果切出来的块还是太大，用下一级分隔符（\n）
3. 如果还是太大，再用句号（。！？）
4. 依此类推，直到字符分隔符
5. 最终如果还是大，直接按 chunk_size 硬切

【chunk_size 和 chunk_overlap 是什么意思？】
- chunk_size=600：每个段落大约 600 个字符
- chunk_overlap=60：相邻段落有 60 个字符的重叠
- 为什么要重叠？防止"一刀切"把一个完整概念切成两半，
  重叠可以让关键信息不被"切丢"
"""

import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


def _build_splitter() -> RecursiveCharacterTextSplitter:
    """
    构建中文优化的递归切分器。

    分隔符优先级（从高到低）：
    1. \n\n      — 段落分隔（最高优先级）
    2. \n        — 换行
    3. 。！？     — 句子结束
    4. ；        — 分句
    5. ，        — 逗号停顿
    6. 空格       — 英文单词分界
    7. ""（空串） — 最后兜底，按字符切

    【为什么分隔符顺序很重要？】
    优先用段落符，尽量保持段落完整。
    如果段落太长才用句号切。
    这样切出来的 chunk 语义更完整。
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )


def split(documents: list[Document]) -> list[Document]:
    """
    切分文档并补充元数据。

    输入：解析后的文档（可能只有一篇）
    输出：切分后的多个 chunk

    每个 chunk 携带：
    - chunk_index：在文档中的序号
    - chunk_hash：内容的 MD5 哈希（增量索引时用于比对变化）
    """
    splitter = _build_splitter()
    chunks = splitter.split_documents(documents)

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index
        chunk.metadata["chunk_hash"] = hashlib.md5(
            chunk.page_content.encode("utf-8")
        ).hexdigest()

    return chunks
