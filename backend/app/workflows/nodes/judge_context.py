"""judge_context：rerank 后看 Top1 分数判断上下文是否足够回答。

纯规则节点，不调 LLM——避免在已经做过 rerank 精排的基础上再叠一次模型调用。
判定逻辑：
- rerank 开启：看 Top1.rerank_score 是否过 `rerank_min_score` 阈值
- rerank 关闭 / 异常降级（rerank_score=None）：回落到 Top1.vector_score 阈值

与 retrieve._should_refuse / observe_context._is_sufficient 的关系：
- retrieve._should_refuse 在召回阶段先做一次"语义相似度过低就拒答"的粗筛
- observe_context._is_sufficient 在 agent 循环里判断"是否还要再检索一轮"
- judge_context 在精排之后做最终闸门：哪怕召回阶段勉强过阈，rerank 后 Top1 不够相关也要拒答
"""

from app.core.config import settings
from app.workflows.rag_state import RAGState


async def judge_context(state: RAGState) -> RAGState:
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return {"context_is_enough": False}

    top = chunks[0]
    if top.rerank_score is not None:
        is_enough = top.rerank_score >= settings.rerank_min_score
    elif top.vector_score is not None:
        is_enough = top.vector_score >= settings.retrieval_min_score
    else:
        is_enough = False
    return {"context_is_enough": is_enough}
