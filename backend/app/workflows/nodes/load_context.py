"""
==========================================
  load_context —— 加载多轮对话历史
==========================================

【为什么单独一个节点？】
load_context 需要一个 DB session（查 ConversationRepository），
而图的其余节点（normalize_query ~ judge_context）全是纯 LLM/检索调用。

设计决定：图里不传递 session，load_context 由 service 层在调用图之前
先执行，把 chat_history 注入 state，然后 normalize_query 消费。

【具体行为】
· 从 conversation_id 查出最近 N 条消息（含 user 和 assistant）
· limit = chat_history_window × 2（每条 message 记一次对话轮次的一半）
· 返回的 history 给 normalize_query 做多轮上下文化改写
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repositories.conversation_repo import ConversationRepository
from app.workflows.rag_state import RAGState


async def load_context(state: RAGState, session: AsyncSession) -> RAGState:
    repo = ConversationRepository(session)
    history = await repo.recent_messages(
        state["conversation_id"], limit=settings.chat_history_window * 2
    )
    return {"chat_history": history}
