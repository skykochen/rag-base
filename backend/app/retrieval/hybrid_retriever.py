"""
==========================================
  混合检索器 —— 向量 + 关键词双路召回 + RRF 融合
==========================================

【为什么需要混合检索？】
只用向量检索：语义好，但专有名词和编号不行
只用关键词检索：精确匹配好，但搜不到同义词
两路一起用，用 RRF 融合，各取所长。

【RRF（Reciprocal Rank Fusion）融合算法】
不是直接加分数（因为两路分数量纲不同），
而是基于排名融合：

score(d) = 1/(k + rank_vector(d)) + 1/(k + rank_keyword(d))

- rank = 1 时得分最高，rank 越大得分越低
- k 是平滑常数（默认 60），越小越偏向高排名条目
- 一个片段在两路都命中，得分就会叠加，排名更靠前

【为什么不在 SQL 里做？】
因为需要并发执行向量检索和关键词检索，
然后在 Python 侧做融合。SQL 一条 FULL OUTER JOIN
也能实现，但应用层融合更易调试和跟踪。

【并发安全】
两路检索用独立的数据库 session（不共享连接），
因为 SQLAlchemy 的异步 session 不支持并发执行。
使用 asyncio.gather 同时发起两路检索。
"""

import asyncio
from uuid import UUID

from langsmith import traceable

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.retrieval.keyword_retriever import KeywordRetriever
from app.retrieval.vector_retriever import RetrievedChunk, VectorRetriever

logger = get_logger(__name__)


class HybridRetriever:
    """
    混合检索器。

    刻意不接收外部 session：
    - SQLAlchemy AsyncSession 不支持并发执行
    - 两路 gather 共用一个 session 会把连接搞坏
    - 检索是只读操作，与调用方的写事务天然解耦
    """

    @traceable(name="HybridRetriever.search", run_type="retriever")
    async def search(
        self,
        query: str,
        *,
        recall_top_k: int,
        final_top_k: int,
        permission_tags: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """
        混合检索主入口：两路并发召回 + RRF 融合 + 取 Top-K。

        参数：
        - recall_top_k: 每路各召回多少条
        - final_top_k: 融合后最终返回多少条

        安全设计：
        - 任一路异常退化为另一路的结果
        - 比如向量路挂了，就只返回关键词路的结果
        - 不会因为一路抖动阻断了整个问答
        """
        vector_hits, keyword_hits = await asyncio.gather(
            self._safe_search(VectorRetriever, query, recall_top_k, "vector", permission_tags),
            self._safe_search(KeywordRetriever, query, recall_top_k, "keyword", permission_tags),
        )
        return rrf_fuse(
            vector_hits=vector_hits,
            keyword_hits=keyword_hits,
            k=settings.rrf_k,
            top_k=final_top_k,
        )

    @staticmethod
    async def _safe_search(
        retriever_cls: type[VectorRetriever] | type[KeywordRetriever],
        query: str,
        top_k: int,
        label: str,
        permission_tags: list[str] | None,
    ) -> list[RetrievedChunk]:
        """
        安全的单路检索（异常时降级为空结果，不往上抛）。

        参数：
        - label: 日志标签，用于区分是向量路还是关键词路
        """
        try:
            async with AsyncSessionLocal() as session:
                retriever = retriever_cls(session)
                return await retriever.search(query, top_k, permission_tags=permission_tags)
        except Exception:
            logger.exception("hybrid retrieve %s 路异常，降级为空结果", label)
            return []


def rrf_fuse(
    vector_hits: list[RetrievedChunk],
    keyword_hits: list[RetrievedChunk],
    *,
    k: int,
    top_k: int,
) -> list[RetrievedChunk]:
    """
    RRF 融合核心算法。

    公式：score(d) = sum(1 / (k + rank_i(d)))

    对每个文档切片：
    - 在向量路有排名 → 加 1/(k+rank_v) 分
    - 在关键词路有排名 → 加 1/(k+rank_k) 分
    - 两路都有 → 分数叠加，排名更靠前

    保留每路的排名和分数，供前端调试面板展示。
    """
    by_id: dict[UUID, RetrievedChunk] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        by_id[hit.chunk_id] = _with_vector(hit, rank=rank, k=k)

    for rank, hit in enumerate(keyword_hits, start=1):
        existing = by_id.get(hit.chunk_id)
        if existing is None:
            by_id[hit.chunk_id] = _with_keyword(hit, rank=rank, k=k)
        else:
            by_id[hit.chunk_id] = _merge_keyword_into(existing, hit, rank=rank, k=k)

    fused = sorted(by_id.values(), key=lambda c: c.rrf_score or 0.0, reverse=True)
    return fused[:top_k]


def _with_vector(hit: RetrievedChunk, *, rank: int, k: int) -> RetrievedChunk:
    """只被向量路命中的 chunk。"""
    rrf_score = 1.0 / (k + rank)
    return RetrievedChunk(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        document_name=hit.document_name,
        content=hit.content,
        page_no=hit.page_no,
        section_path=hit.section_path,
        score=rrf_score,
        sources=("vector",),
        vector_rank=rank,
        vector_score=hit.vector_score,
        rrf_score=rrf_score,
    )


def _with_keyword(hit: RetrievedChunk, *, rank: int, k: int) -> RetrievedChunk:
    """只被关键词路命中的 chunk。"""
    rrf_score = 1.0 / (k + rank)
    return RetrievedChunk(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        document_name=hit.document_name,
        content=hit.content,
        page_no=hit.page_no,
        section_path=hit.section_path,
        score=rrf_score,
        sources=("keyword",),
        keyword_rank=rank,
        keyword_score=hit.keyword_score,
        rrf_score=rrf_score,
    )


def _merge_keyword_into(existing: RetrievedChunk, keyword_hit: RetrievedChunk, *, rank: int, k: int) -> RetrievedChunk:
    """两路都命中的 chunk：合并 sources 和分数。"""
    new_rrf = (existing.rrf_score or 0.0) + 1.0 / (k + rank)
    return RetrievedChunk(
        chunk_id=existing.chunk_id,
        document_id=existing.document_id,
        document_name=existing.document_name,
        content=existing.content,
        page_no=existing.page_no,
        section_path=existing.section_path,
        score=new_rrf,
        sources=("vector", "keyword"),
        vector_rank=existing.vector_rank,
        vector_score=existing.vector_score,
        keyword_rank=rank,
        keyword_score=keyword_hit.keyword_score,
        rrf_score=new_rrf,
    )
