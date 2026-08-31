"""retrieve：执行向量 + 关键词混合检索（RRF 融合），把召回结果交给后续 rerank。

第 4 章：单路向量检索。
第 6 章：升级为 HybridRetriever（向量 + 全文 + RRF 融合）。
第 8 章：召回数量从 `retrieval_top_k` 放大到 `retrieval_recall_top_k`，
        把全部候选交给 rerank 精排，最终 Top-K 由 rerank 节点裁剪。
第 11 章：把 state["permissions"] 透传到 retriever，让 SQL 层完成权限过滤。

multi_query 路径下每个子查询独立做一次 hybrid 检索，再按第 5 章约定的
朴素合并去重；不在子查询之间再做嵌套 RRF。

拒答闸门已移交 judge_context 节点统一处理（第 8 章），retrieve 只负责召回。
"""

from app.core.config import settings
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.vector_retriever import RetrievedChunk
from app.workflows.rag_state import RAGState


async def retrieve(state: RAGState) -> RAGState:
    retriever = HybridRetriever()
    recall_top_k = settings.retrieval_recall_top_k
    permissions = state.get("permissions")

    if state.get("route") == "multi_query" and state.get("multi_queries"):
        # 各子查询独立走 hybrid 检索，再合并；不做嵌套 RRF
        bundles: list[list[RetrievedChunk]] = []
        for sub_query in state["multi_queries"] or []:
            bundles.append(
                await retriever.search(
                    sub_query,
                    recall_top_k=recall_top_k,
                    final_top_k=recall_top_k,
                    permission_tags=permissions,
                )
            )
        chunks = _merge_chunks(bundles, top_k=recall_top_k)
    else:
        chunks = await retriever.search(
            state["query"],
            recall_top_k=recall_top_k,
            final_top_k=recall_top_k,
            permission_tags=permissions,
        )

    return {"retrieved_chunks": chunks}


def _merge_chunks(
    bundles: list[list[RetrievedChunk]], top_k: int
) -> list[RetrievedChunk]:
    """multi_query 子查询结果合并：去重 + 取 Top-K。

    同一个 chunk 可能在多条子查询中都命中；保留 RRF 分最高的那条，
    再整体按 RRF 分降序取前 top_k。
    """
    best: dict[str, RetrievedChunk] = {}
    for bundle in bundles:
        for chunk in bundle:
            key = str(chunk.chunk_id)
            prev = best.get(key)
            if prev is None or (chunk.rrf_score or 0.0) > (prev.rrf_score or 0.0):
                best[key] = chunk
    ranked = sorted(best.values(), key=lambda c: c.rrf_score or 0.0, reverse=True)
    return ranked[:top_k]
