"""
==========================================
  generate —— 调用 LLM 基于检索上下文流式生成答案
==========================================

【为什么是流式（yield）而非一次返回？】
· 用户体验：用户能看到逐字出现的效果，而不是等几秒突然一整段
· SSE（Server-Sent Events）推送需要 AsyncIterator

【调用约束】
· refused=True 时调用方应直接跳过本函数，因为 answer 已由 refuse 节点填充
· 图本身的 rerank 和 generate 之间隔着 judge_context 闸门，不会在 refused 下走到这里

【数据来源】
· question：用户原始问题（经过 normalize_query / route_query 改写后仍是同一个 question，
  改写结果在 state["query"] 中，但 prompt 里用的是 state["question"]）
· chunks：retrieve → rerank 处理后的检索结果
· chat_history：load_context 加载的多轮历史
"""

from collections.abc import AsyncIterator

from app.llm.models import get_chat_model
from app.llm.prompts import build_answer_messages
from app.workflows.rag_state import RAGState


async def stream_generate(state: RAGState) -> AsyncIterator[str]:
    messages = build_answer_messages(
        question=state["question"],
        chunks=state["retrieved_chunks"],
        history=state.get("chat_history", []),
    )
    async for chunk in get_chat_model().astream(messages):
        text = chunk.content
        if not text:
            continue
        if isinstance(text, str):
            yield text
        else:
            yield "".join(part.get("text", "") for part in text if isinstance(part, dict))
