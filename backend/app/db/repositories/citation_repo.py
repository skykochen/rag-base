"""
==========================================
  AnswerCitationRepository —— 答案引用的数据访问
==========================================

answer_citations 表存储 AI 回答中引用的文档片段快照。

【为什么需要引用快照？】
文档切片可能会被更新或删除，但历史对话中的引用应该保持不变。
所以引用数据是"快照"——即使原文档被删了，引用记录仍然保留。
这是通过 ON DELETE SET NULL 外键约束实现的。
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AnswerCitation


class AnswerCitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_add(self, citations: Sequence[AnswerCitation]) -> None:
        """批量新增引用记录。"""
        if not citations:
            return
        self.session.add_all(citations)
        await self.session.flush()
