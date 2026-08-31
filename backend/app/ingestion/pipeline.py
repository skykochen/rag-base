"""
==========================================
  文档入库流水线 —— 编排整个入库流程
==========================================

这个文件是整个入库流程的"总指挥"，协调各个步骤的顺序执行。

【两个入口】
- run_ingest_sync：首次入库（从零开始处理新文档）
- run_reindex_sync：增量重建（文档更新后只处理变化的部分）

【为什么要有两个流程？】
- 首次入库：上传的文档第一次处理，全部内容是新的，全部需要 embedding
- 增量重建：文档更新后，大部分内容没变，只处理变化的部分，节省时间和费用

【Celery 同步包装】
入库函数是异步的（async），但 Celery worker 是同步进程。
所以用 run_ingest_sync → asyncio.run(_run_ingest) 的模式，
在同步函数里启动事件循环运行异步代码。
"""

import asyncio
from uuid import UUID

from langchain_core.documents import Document as LangChainDocument

from app.core.logging import get_logger
from app.db.models import DocumentChunk, DocumentStatus
from app.db.repositories.chunk_repo import DocumentChunkRepository
from app.db.repositories.document_repo import DocumentRepository
from app.db.repositories.ingestion_task_repo import IngestionTaskRepository
from app.db.session import AsyncSessionLocal
from app.ingestion import embedder, parser, splitter
from app.storage.file_service import get_file_service

logger = get_logger(__name__)


# ──────────── 辅助函数（独立事务更新状态） ────────────
#
# 为什么每个状态更新都用独立的 session 和 commit？
# 如果全程用同一个事务，前端轮询时永远看不到中间状态。
# 每次状态变更都立即提交，前端才能实时看到进度。


async def _set_status(document_id: UUID, status: DocumentStatus, *, error_message: str | None = None) -> None:
    """更新文档状态（独立事务）。"""
    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        await repo.update_status(document_id, status, error_message=error_message)
        await session.commit()


async def _mark_task(task_id: UUID, *, running: bool = False) -> None:
    """标记任务状态（独立事务）。"""
    async with AsyncSessionLocal() as session:
        repo = IngestionTaskRepository(session)
        if running:
            await repo.mark_running(task_id)
        await session.commit()


async def _mark_task_failed(task_id: UUID, error_message: str) -> None:
    """标记任务失败（独立事务）。"""
    async with AsyncSessionLocal() as session:
        repo = IngestionTaskRepository(session)
        await repo.mark_failed(task_id, error_message)
        await session.commit()


async def _mark_task_success(task_id: UUID) -> None:
    """标记任务成功（独立事务）。"""
    async with AsyncSessionLocal() as session:
        repo = IngestionTaskRepository(session)
        await repo.mark_success(task_id)
        await session.commit()


async def _set_task_total(task_id: UUID, total: int) -> None:
    """设置任务总进度（独立事务）。"""
    async with AsyncSessionLocal() as session:
        repo = IngestionTaskRepository(session)
        await repo.set_progress_total(task_id, total)
        await session.commit()


async def _increment_task_progress(task_id: UUID, delta: int) -> None:
    """增加已完成进度（独立事务）。"""
    async with AsyncSessionLocal() as session:
        repo = IngestionTaskRepository(session)
        await repo.increment_progress(task_id, delta)
        await session.commit()


async def _embed_with_progress(texts: list[str], task_id: UUID) -> list[list[float]]:
    """
    分批 embedding，每完成一批更新一次进度。

    【为什么手动分批？】
    LangChain 的 aembed_documents 内部也会分批，
    但它的分批不回调进度。手动分批可以精确控制进度更新。
    """
    from app.core.config import settings

    if not texts:
        return []
    embeddings_client = embedder.get_embeddings()
    batch_size = max(1, settings.embedding_batch_size)  # 默认 10 条一批
    results: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors = await embeddings_client.aembed_documents(batch)
        results.extend(vectors)
        await _increment_task_progress(task_id, len(batch))
    return results


# ──────────── 首次入库流程 ────────────


async def _run_ingest(document_id: UUID, task_id: UUID) -> None:
    """
    首次入库全流程：

    1. 标记任务为 running
    2. 从 COS 下载文件内容
    3. Docling 解析文档 → Markdown
    4. 递归切分 → chunks
    5. 批量向量化（embedding）
    6. chunks + 向量写入数据库
    7. 标记文档为 ready，标记任务为 success

    状态流转：uploading → parsing → indexing → ready
    """
    logger.info("ingest start: document_id=%s task_id=%s", document_id, task_id)
    await _mark_task(task_id, running=True)

    try:
        # 获取文档信息和文件内容
        async with AsyncSessionLocal() as session:
            document = await DocumentRepository(session).get_by_id(document_id)
            if document is None:
                logger.warning("document not found, skip ingest: %s", document_id)
                await _mark_task_failed(task_id, "文档不存在")
                return
            object_key = document.cos_object_key
            filename = document.name

        # 步骤1: 文档解析（PDF/DOCX → Markdown）
        await _set_status(document_id, DocumentStatus.PARSING)
        content = await get_file_service().download(object_key)
        parsed = await parser.parse(filename, content)

        # 步骤2: 文本切分（长文本 → 短段落）
        await _set_status(document_id, DocumentStatus.INDEXING)
        chunks = splitter.split(parsed)
        if not chunks:
            raise ValueError("切分后没有任何 chunk，请检查文档内容")

        # 步骤3: 向量化（文本 → 向量）
        await _set_task_total(task_id, len(chunks))
        embeddings = await _embed_with_progress([c.page_content for c in chunks], task_id)

        # 步骤4: 写入数据库
        async with AsyncSessionLocal() as session:
            chunk_repo = DocumentChunkRepository(session)
            await chunk_repo.bulk_add(
                [_make_chunk(document_id, c, vec) for c, vec in zip(chunks, embeddings, strict=True)]
            )
            await session.commit()

        # 标记完成
        await _set_status(document_id, DocumentStatus.READY, error_message=None)
        await _mark_task_success(task_id)
        logger.info("ingest done: document_id=%s chunks=%d", document_id, len(chunks))

    except Exception as exc:
        logger.exception("ingest failed: document_id=%s", document_id)
        message = str(exc).strip() or exc.__class__.__name__
        await _set_status(document_id, DocumentStatus.FAILED, error_message=message[:500])
        await _mark_task_failed(task_id, message)


# ──────────── 增量重建流程 ────────────


async def _run_reindex(document_id: UUID, task_id: UUID) -> None:
    """
    增量重建索引。

    【和首次入库有什么不同？】
    首次入库：解析 → 全部 embedding → 全量写入
    增量重建：解析 → 按 chunk_hash 比对 → 只处理新增的 → 更新版本号

    关键优化：
    - chunk_hash（内容的 MD5）没变的 chunk 不重新 embedding（省时省钱）
    - chunk_hash 变了的 → 删除旧记录，插入新记录
    - 位置/元数据变了但内容没变 → 只更新 metadata，不动 embedding
    """
    logger.info("reindex start: document_id=%s task_id=%s", document_id, task_id)
    await _mark_task(task_id, running=True)

    try:
        async with AsyncSessionLocal() as session:
            document = await DocumentRepository(session).get_by_id(document_id)
            if document is None:
                logger.warning("document not found, skip reindex: %s", document_id)
                await _mark_task_failed(task_id, "文档不存在")
                return
            object_key = document.cos_object_key
            filename = document.name

        # 解析新文档
        await _set_status(document_id, DocumentStatus.PARSING)
        content = await get_file_service().download(object_key)
        parsed = await parser.parse(filename, content)

        # 切分
        await _set_status(document_id, DocumentStatus.INDEXING)
        new_chunks = splitter.split(parsed)
        if not new_chunks:
            raise ValueError("切分后没有任何 chunk，请检查文档内容")

        # 拉取旧的 chunks
        async with AsyncSessionLocal() as session:
            old_chunks = await DocumentChunkRepository(session).list_all_by_document(document_id)

        if _has_duplicate_hash(new_chunks):
            # hash 重复 → 不能做增量（无法确定哪个旧 chunk 对应哪个新 chunk）
            # 降级为全量重建
            logger.warning("reindex fallback to full rebuild due to duplicate chunk_hash: %s", document_id)
            await _run_full_rebuild(document_id, task_id, new_chunks)
        else:
            await _run_incremental(document_id, task_id, old_chunks, new_chunks)

        # 版本号 +1
        async with AsyncSessionLocal() as session:
            doc_repo = DocumentRepository(session)
            doc = await doc_repo.get_by_id(document_id)
            if doc is not None:
                doc.version += 1
            await session.commit()

        await _set_status(document_id, DocumentStatus.READY, error_message=None)
        await _mark_task_success(task_id)
        logger.info("reindex done: document_id=%s new_chunks=%d", document_id, len(new_chunks))

    except Exception as exc:
        logger.exception("reindex failed: document_id=%s", document_id)
        message = str(exc).strip() or exc.__class__.__name__
        await _set_status(document_id, DocumentStatus.FAILED, error_message=message[:500])
        await _mark_task_failed(task_id, message)


async def _run_incremental(
    document_id: UUID, task_id: UUID, old_chunks: list[DocumentChunk], new_chunks: list[LangChainDocument]
) -> None:
    """
    增量对齐：按 chunk_hash 比对新旧 chunks。

    三种情况：
    1. 旧 chunk 的 hash 不在新列表中 → 删除（内容被删了）
    2. 新 chunk 的 hash 已在旧列表中 → 只更新 metadata（内容没变）
    3. 新 chunk 的 hash 不在旧列表中 → 插入（新增内容）
    """
    old_by_hash = {c.chunk_hash: c for c in old_chunks}
    new_hashes = {c.metadata["chunk_hash"] for c in new_chunks}

    to_delete_ids: list[UUID] = [c.id for c in old_chunks if c.chunk_hash not in new_hashes]
    to_insert: list[LangChainDocument] = []
    to_update: list[tuple[DocumentChunk, LangChainDocument]] = []
    for nc in new_chunks:
        h = nc.metadata["chunk_hash"]
        existing = old_by_hash.get(h)
        if existing is None:
            to_insert.append(nc)
        else:
            to_update.append((existing, nc))

    await _set_task_total(task_id, len(to_insert))
    new_embeddings = await _embed_with_progress([c.page_content for c in to_insert], task_id)

    async with AsyncSessionLocal() as session:
        chunk_repo = DocumentChunkRepository(session)
        await chunk_repo.delete_by_ids(to_delete_ids)

        for old, nc in to_update:
            old.chunk_index = nc.metadata["chunk_index"]
            old.page_no = nc.metadata.get("page_no")
            old.section_path = nc.metadata.get("section_path")
            old.extra_metadata = nc.metadata

        await chunk_repo.bulk_add(
            [_make_chunk(document_id, c, vec) for c, vec in zip(to_insert, new_embeddings, strict=True)]
        )
        await session.commit()

    logger.info("incremental reindex: doc=%s delete=%d update=%d insert=%d", document_id, len(to_delete_ids), len(to_update), len(to_insert))


async def _run_full_rebuild(document_id: UUID, task_id: UUID, new_chunks: list[LangChainDocument]) -> None:
    """全量重建兜底：清空旧数据，全部重新 embedding 后写入。"""
    await _set_task_total(task_id, len(new_chunks))
    embeddings = await _embed_with_progress([c.page_content for c in new_chunks], task_id)

    async with AsyncSessionLocal() as session:
        chunk_repo = DocumentChunkRepository(session)
        await chunk_repo.delete_by_document(document_id)
        await chunk_repo.bulk_add(
            [_make_chunk(document_id, c, vec) for c, vec in zip(new_chunks, embeddings, strict=True)]
        )
        await session.commit()


def _has_duplicate_hash(chunks: list[LangChainDocument]) -> bool:
    """检查新 chunks 中是否有重复的 hash（增量对齐的前提假设是 hash 唯一）。"""
    seen: set[str] = set()
    for c in chunks:
        h = c.metadata["chunk_hash"]
        if h in seen:
            return True
        seen.add(h)
    return False


def _make_chunk(document_id: UUID, chunk: LangChainDocument, embedding: list[float]) -> DocumentChunk:
    """把 LangChain Document + 向量 → ORM DocumentChunk 对象。"""
    return DocumentChunk(
        document_id=document_id,
        content=chunk.page_content,
        embedding=embedding,
        page_no=chunk.metadata.get("page_no"),
        section_path=chunk.metadata.get("section_path"),
        chunk_index=chunk.metadata["chunk_index"],
        chunk_hash=chunk.metadata["chunk_hash"],
        extra_metadata=chunk.metadata,
    )


# ──────────── 同步入口（供 Celery worker 调用） ────────────

def run_ingest_sync(document_id: UUID, task_id: UUID) -> None:
    """首次入库同步入口（Celery worker 调用）。"""
    asyncio.run(_run_ingest(document_id, task_id))


def run_reindex_sync(document_id: UUID, task_id: UUID) -> None:
    """增量重建同步入口（Celery worker 调用）。"""
    asyncio.run(_run_reindex(document_id, task_id))
