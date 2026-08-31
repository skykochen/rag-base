"""
==========================================
  DocumentChunkRepository —— 文档切片的数据访问
==========================================

document_chunks 表存储文档被切分后的文本片段及其向量。
这是 RAG 系统的核心数据表——检索就是在这个表里搜索。

【关键功能】
1. 全文检索（keyword_search）：基于 PostgreSQL zhparser 中文分词
2. 向量检索（vector_search）：基于 pgvector 的余弦距离
3. 权限过滤：通过文档的 permission_tags 控制可见性
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Document, DocumentChunk

# 通配权限标签：admin 角色持有，含义是"无视权限过滤"
WILDCARD_PERMISSION_TAG = "*"


def _permission_where(permission_tags: list[str] | None) -> ColumnElement[bool] | None:
    """
    构造文档可见性 WHERE 条件。

    这是 RAG 权限过滤的核心逻辑。

    参数：
    - permission_tags: 用户的权限标签列表

    返回 None 时表示不附加任何 WHERE 条件（管理员或未指定权限）。

    权限判断逻辑：
    1. permission_tags 为 None → 调用方不限制（如评测路径），不加条件
    2. 含 "*" → 管理员通配，不加条件
    3. 其他情况 → 两个条件任一满足即可：
       a. 文档的 permission_tags 为空数组 → 视为公开文档
       b. 用户的标签与文档的标签有交集 → PostgreSQL 的 && 操作符

    【PostgreSQL 的 && 操作符】
    用于数组重叠判断：
    ARRAY['public', 'finance'] && ARRAY['public'] → True
    ARRAY['finance'] && ARRAY['hr'] → False
    """
    if permission_tags is None:
        return None
    if WILDCARD_PERMISSION_TAG in permission_tags:
        return None
    return or_(
        func.cardinality(Document.permission_tags) == 0,
        Document.permission_tags.op("&&")(permission_tags),
    )


@dataclass(frozen=True)
class ChunkStats:
    """单个文档下切片的统计信息。"""
    total: int          # 切片总数
    avg_length: int     # 平均字符数
    min_length: int     # 最短切片
    max_length: int     # 最长切片


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_add(self, chunks: Sequence[DocumentChunk]) -> None:
        """批量新增切片。"""
        if not chunks:
            return
        self.session.add_all(chunks)
        await self.session.flush()

    async def delete_by_document(self, document_id: UUID) -> None:
        """删除指定文档的所有切片（重新入库前清理旧数据）。"""
        stmt = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        await self.session.execute(stmt)

    async def delete_by_ids(self, chunk_ids: Sequence[UUID]) -> None:
        """按 ID 批量删除（增量索引时删除已失效的切片）。"""
        if not chunk_ids:
            return
        stmt = delete(DocumentChunk).where(DocumentChunk.id.in_(list(chunk_ids)))
        await self.session.execute(stmt)

    async def list_all_by_document(self, document_id: UUID) -> list[DocumentChunk]:
        """获取指定文档的所有切片（按索引顺序）。"""
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_paginated_by_document(
        self, document_id: UUID, page: int, page_size: int
    ) -> tuple[list[DocumentChunk], int]:
        """分页查询文档切片。"""
        offset = (page - 1) * page_size
        items_stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .offset(offset)
            .limit(page_size)
        )
        count_stmt = (
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        items = (await self.session.execute(items_stmt)).scalars().all()
        total = (await self.session.execute(count_stmt)).scalar_one()
        return list(items), int(total)

    async def get_for_document(self, document_id: UUID, chunk_id: UUID) -> DocumentChunk | None:
        """同时按文档 ID 和切片 ID 查询（强校验归属）。"""
        stmt = select(DocumentChunk).where(
            DocumentChunk.id == chunk_id,
            DocumentChunk.document_id == document_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def keyword_search(
        self,
        query: str,
        top_k: int,
        *,
        permission_tags: list[str] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """
        中文全文检索。

        【什么是全文检索？】
        不同于 SQL 的 LIKE '%关键词%'（逐字匹配，不能处理同义词、词形变化），
        全文检索使用分词器把文本拆成词语，然后进行语义级别的搜索。

        【zhparser 的作用】
        PostgreSQL 自带的分词器不支持中文，zhparser 扩展实现了中文分词：
        "我是一名程序员" → "我 / 是 / 一名 / 程序员"

        【plainto_tsquery】
        把用户输入的文本自动分词并转为 AND 连接的查询条件，
        对用户输入最友好（不需要自己写布尔运算符）。

        参数：
        - query: 用户搜索的关键词
        - top_k: 返回前 N 条结果
        - permission_tags: 权限过滤
        """
        tsquery = func.plainto_tsquery("chinese_zh", query)
        rank_expr = func.ts_rank(DocumentChunk.content_tsv, tsquery)
        conditions: list[ColumnElement[bool]] = [
            Document.status == "ready",          # 只搜已就绪的文档
            DocumentChunk.content_tsv.op("@@")(tsquery),  # 匹配全文索引
        ]
        perm_where = _permission_where(permission_tags)
        if perm_where is not None:
            conditions.append(perm_where)

        stmt = (
            select(DocumentChunk, rank_expr.label("rank"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(and_(*conditions))
            .order_by(rank_expr.desc())
            .limit(top_k)
            .options(selectinload(DocumentChunk.document))
        )
        rows = (await self.session.execute(stmt)).all()
        return [(chunk, float(rank)) for chunk, rank in rows]

    async def vector_search(
        self,
        query_embedding: list[float],
        top_k: int,
        *,
        permission_tags: list[str] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """
        向量检索（余弦距离）。

        【什么是向量检索？】
        文本 → Embedding 模型 → 向量（一串浮点数）
        然后找与"查询向量"最相似的"文档向量"。

        【余弦距离 (cosine_distance)】
        取值范围 [0, 2]：
        - 0：完全相似（向量方向相同）
        - 1：不相关（向量垂直）
        - 2：完全相反

        注意：内部存储的是距离，不是相似度。
        相似度 = 1 - 距离（上层转换）。
        """
        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        conditions: list[ColumnElement[bool]] = [Document.status == "ready"]
        perm_where = _permission_where(permission_tags)
        if perm_where is not None:
            conditions.append(perm_where)

        stmt = (
            select(DocumentChunk, distance.label("distance"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(and_(*conditions))
            .order_by(distance.asc())  # 距离越小越相似
            .limit(top_k)
            .options(selectinload(DocumentChunk.document))
        )
        rows = (await self.session.execute(stmt)).all()
        return [(chunk, float(dist)) for chunk, dist in rows]

    async def count_visible(self, *, permission_tags: list[str] | None = None) -> int:
        """统计可见切片总数（MCP 统计用）。"""
        stmt = (
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.status == "ready")
        )
        perm_where = _permission_where(permission_tags)
        if perm_where is not None:
            stmt = stmt.where(perm_where)
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_stats(self, document_id: UUID) -> ChunkStats | None:
        """
        获取文档的切片统计信息。

        使用聚合函数（count/avg/min/max）一次查询，
        避免把大量切片数据拉到 Python 侧计算。
        """
        length = func.char_length(DocumentChunk.content)
        stmt = select(
            func.count().label("total"),
            func.avg(length).label("avg_len"),
            func.min(length).label("min_len"),
            func.max(length).label("max_len"),
        ).where(DocumentChunk.document_id == document_id)
        row = (await self.session.execute(stmt)).one()
        if not row.total:
            return None
        return ChunkStats(
            total=int(row.total),
            avg_length=int(row.avg_len or 0),
            min_length=int(row.min_len or 0),
            max_length=int(row.max_len or 0),
        )
