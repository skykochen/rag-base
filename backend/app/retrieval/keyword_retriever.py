"""
==========================================
  关键词检索器 —— 中文全文检索（精确匹配）
==========================================

【和向量检索的区别】
向量检索："差旅费标准" → 找到"出差报销规定"（语义相似但用词不同）
关键词检索："差旅费标准" → 找到包含"差旅费"和"标准"的片段（精确匹配）

【适用场景】
- 制度名、编号：如"QG-2024-001"
- 专有名词：如"腾讯云 COS"
- 产品型号：如"qwen3-rerank"
- 人名、地名：如"张三"、"北京市"

向量检索在这些场景经常被同义近邻干扰，而全文检索能精确匹配。

【zhparser 中文分词】
PostgreSQL 不支持中文分词，所以项目用了 zhparser 扩展。
"我是程序员"会被分成 "我 / 是 / 程序员"。

【ts_rank 分数】
ts_rank 是 PostgreSQL 全文检索的相关度评分，
没有固定上界，但在同一个查询内的相对大小有意义，可用于排序。
"""

from langsmith import traceable
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.chunk_repo import DocumentChunkRepository
from app.retrieval.vector_retriever import RetrievedChunk


class KeywordRetriever:
    """关键词检索器：用 PostgreSQL 中文全文检索搜索。"""

    def __init__(self, session: AsyncSession) -> None:
        self.chunk_repo = DocumentChunkRepository(session)

    @traceable(name="KeywordRetriever.search", run_type="retriever")
    async def search(
        self,
        query: str,
        top_k: int,
        *,
        permission_tags: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """
        执行关键词检索。

        接口与 VectorRetriever.search 完全对齐：
        同样的参数、同样的返回类型，
        这样 HybridRetriever 可以把两路当成对称输入进行融合。
        """
        rows = await self.chunk_repo.keyword_search(
            query, top_k, permission_tags=permission_tags
        )
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_name=chunk.document.name,
                content=chunk.content,
                page_no=chunk.page_no,
                section_path=chunk.section_path,
                score=ts_rank,
                sources=("keyword",),
                keyword_rank=rank,
                keyword_score=ts_rank,
            )
            for rank, (chunk, ts_rank) in enumerate(rows, start=1)
        ]
