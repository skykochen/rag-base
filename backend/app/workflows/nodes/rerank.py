"""rerank：对召回的候选 chunk 做 query-chunk 成对打分精排。

为什么单独成节点而不是塞到 retrieve 内部：
- retrieve 负责"召回"（向量 + 关键词 + RRF 融合），rerank 负责"精排"，两步关注点不同
- rerank 调外部 API，失败可以独立降级（直接透传），不影响召回结果
- 通过 `RERANK_ENABLED` 开关，方便对比有/无精排时检索质量差异

数据流：retrieve 给出的 `recall_top_k` 条候选 → reranker 重新打分排序 → 截到
`retrieval_top_k` 条交给后续 generate。这样召回阶段宁滥勿缺，精排阶段宁缺勿滥。
"""

from app.core.config import settings
from app.llm.reranker import get_reranker
from app.workflows.rag_state import RAGState


async def rerank(state: RAGState) -> RAGState:
    chunks = state.get("retrieved_chunks", [])
    if not settings.rerank_enabled or len(chunks) <= 1:
        return {}

    reranked = await get_reranker().rerank(state["query"], chunks)
    return {"retrieved_chunks": reranked[: settings.retrieval_top_k]}
