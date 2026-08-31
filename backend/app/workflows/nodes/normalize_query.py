"""normalize_query：基于多轮历史把问题改写成独立完整的检索 query。

为什么把多轮上下文化放在 normalize_query 而不是 route_query：
- normalize_query 是图的入口，让 query 在进入路由 / 决策 / 检索之前就独立完整
- route_query 拿到的就是 contextualize 后的文本，不会因指代不清把"它的发布时间"
  路由成 hyde 这种错配
- 空历史时直接透传 question，与第 4 章行为一致；不强制走 LLM 调用
"""

from app.llm.query_rewriter import get_query_rewriter
from app.workflows.rag_state import RAGState


async def normalize_query(state: RAGState) -> RAGState:
    history = state.get("chat_history") or []
    if not history:
        return {"query": state["question"]}

    rewritten = await get_query_rewriter().contextualize(
        question=state["question"], history=history
    )
    return {"query": rewritten}
