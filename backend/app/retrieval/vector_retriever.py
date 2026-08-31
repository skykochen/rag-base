"""
==========================================
  向量检索器 —— 语义相似度搜索
==========================================

【工作原理】
1. 把用户问题用 Embedding 模型转成向量
2. 在数据库中找与问题向量最相似的文档切片向量
3. 返回 Top-K 结果

【RetrievedChunk 是什么？】
这是一个通用数据类，向量检索、关键词检索、混合检索都返回这个类型。
它包含了切片的内容、所属文档、排名和分数。

【分数说明】
- pgvector 返回的是 cosine_distance（余弦距离），范围[0, 2]
- 0 = 完全相同，1 = 不相关，2 = 完全相反
- 我们把它转成 similarity（相似度）= 1 - distance
- 最终 score 是"越大越相似"，符合直觉
"""

from dataclasses import dataclass, field
from uuid import UUID

from langsmith import traceable
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.chunk_repo import DocumentChunkRepository
from app.ingestion.embedder import get_embeddings


@dataclass(frozen=True)
class RetrievedChunk:
    """
    检索结果中的单个文档切片。

    这个类在整个 RAG 流程中广泛使用，是检索和 LLM 之间的数据桥梁。

    score 是统一后的分数（越大越相关）：
    - 向量检索：cosine similarity ∈ [0, 1]
    - 关键词检索：ts_rank（在同一查询内有相对可比性）
    - 混合检索：RRF 融合分

    sources 标记这个切片是从哪路召回的：
    - ("vector",) — 仅向量路
    - ("keyword",) — 仅关键词路
    - ("vector", "keyword") — 两路都命中
    """
    chunk_id: UUID
    document_id: UUID
    document_name: str
    content: str
    page_no: int | None
    section_path: str | None
    score: float
    sources: tuple[str, ...] = field(default_factory=tuple)
    vector_rank: int | None = None
    vector_score: float | None = None
    keyword_rank: int | None = None
    keyword_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


class VectorRetriever:
    """向量检索器：把问题转成向量，在 pgvector 中搜索最相似的切片。"""

    def __init__(self, session: AsyncSession) -> None:
        self.chunk_repo = DocumentChunkRepository(session)

    @traceable(name="VectorRetriever.search", run_type="retriever")
    async def search(
        self,
        query: str,
        top_k: int,
        *,
        permission_tags: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """
        执行向量检索。

        参数：
        - query: 用户问题（或改写后的问题）
        - top_k: 返回前 N 条最相似的结果
        - permission_tags: 权限过滤标签

        流程：
        1. 用 embedding 模型把问题转成向量
        2. 在 database 找余弦距离最近的 top_k 条切片
        3. 把距离转成相似度（越大越相似）
        4. 封装成 RetrievedChunk 列表返回
        """
        # 第1步：问题向量化
        embedding = await get_embeddings().aembed_query(query)

        # 第2步：向量检索
        rows = await self.chunk_repo.vector_search(
            embedding, top_k, permission_tags=permission_tags
        )

        # 第3步：结果封装
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_name=chunk.document.name,
                content=chunk.content,
                page_no=chunk.page_no,
                section_path=chunk.section_path,
                score=1.0 - distance,  # 距离 → 相似度
                sources=("vector",),
                vector_rank=rank,
                vector_score=1.0 - distance,
            )
            for rank, (chunk, distance) in enumerate(rows, start=1)
        ]
