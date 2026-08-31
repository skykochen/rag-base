"""
==========================================
  ConversationRepository —— 会话与消息的数据访问
==========================================

管理会话（conversations）和消息（messages）的 CRUD。
会话是问答的容器，一个会话包含多条消息（user 提问 + assistant 回答）。
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, Message, MessageRole

DEFAULT_CONVERSATION_TITLE = "新对话"


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        title: str = DEFAULT_CONVERSATION_TITLE,
        *,
        user_id: UUID | None = None,
    ) -> Conversation:
        """创建新会话。"""
        conversation = Conversation(title=title, user_id=user_id)
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> Conversation | None:
        """
        根据 ID 查询会话（可选的用户归属校验）。

        参数：
        - user_id: 非 None 时强制要求会话属于该用户；
                   None 时管理员可查任何会话
        """
        if user_id is None:
            return await self.session.get(Conversation, conversation_id)
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_messages(self, conversation_id: UUID) -> list[Message]:
        """
        获取指定会话的全部消息（按时间正序）。

        selectinload(Message.citations) 会预加载消息的引用列表，
        避免后续访问每条消息的 citations 时触发 N+1 查询。
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .options(selectinload(Message.citations))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def recent_messages(self, conversation_id: UUID, limit: int) -> list[Message]:
        """
        获取最近的 N 条消息。

        用来构建对话历史上下文（history_window），喂给 LLM。
        limit = history_window * 2（因为 user 和 assistant 消息交替出现）。

        实现方式：
        1. 先按时间倒序取 N 条
        2. 在 Python 侧反转为正序返回
        """
        if limit <= 0:
            return []
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        return list(reversed(rows))

    async def count_messages(self, conversation_id: UUID) -> int:
        """统计会话中的消息数量。"""
        stmt = select(func.count(Message.id)).where(
            Message.conversation_id == conversation_id
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_page(
        self,
        page: int,
        page_size: int,
        *,
        user_id: UUID | None = None,
    ) -> tuple[list[tuple[Conversation, int]], int]:
        """
        分页查询会话列表（按更新时间倒序）。

        返回 (会话, 消息数) 的列表 + 总数量。

        【LEFT JOIN 优化】
        使用 LEFT JOIN + GROUP BY，一次查询同时拿到会话和消息数量，
        避免 N+1 问题（查一次会话列表 + 查 N 次消息数量）。
        """
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)
        offset = (page - 1) * page_size

        msg_count = func.count(Message.id).label("message_count")
        stmt = (
            select(Conversation, msg_count)
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .group_by(Conversation.id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(page_size)
            .offset(offset)
        )
        count_stmt = select(func.count(Conversation.id))
        if user_id is not None:
            stmt = stmt.where(Conversation.user_id == user_id)
            count_stmt = count_stmt.where(Conversation.user_id == user_id)

        rows = (await self.session.execute(stmt)).all()
        items = [(row[0], int(row[1])) for row in rows]
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return items, total

    async def delete(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> bool:
        """
        删除会话。

        级联删除：messages 和 answer_citations 会被自动清理。
        数据库中设置了 ON DELETE CASCADE 外键约束。

        返回是否真的删除了（False 表示会话不存在）。
        """
        conversation = await self.get(conversation_id, user_id=user_id)
        if conversation is None:
            return False
        await self.session.delete(conversation)
        await self.session.flush()
        return True

    async def update_title_if_default(
        self, conversation_id: UUID, title: str
    ) -> None:
        """
        首次提问后自动改会话标题（取问题前 30 个字）。

        只有在标题还是默认值时才改，避免覆盖用户手动修改过的标题。
        """
        new_title = title.strip()
        if not new_title:
            return
        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is None or conversation.title != DEFAULT_CONVERSATION_TITLE:
            return
        conversation.title = new_title[:30]
        await self.session.flush()

    async def add_messages(self, messages: Sequence[Message]) -> None:
        """批量添加消息。"""
        if not messages:
            return
        self.session.add_all(messages)
        await self.session.flush()

    @staticmethod
    def make_user_message(conversation_id: UUID, content: str) -> Message:
        """创建用户消息对象。"""
        return Message(conversation_id=conversation_id, role=MessageRole.USER, content=content)

    @staticmethod
    def make_assistant_message(
        conversation_id: UUID,
        content: str,
        *,
        extra_metadata: dict | None = None,
    ) -> Message:
        """创建 AI 回复消息对象。"""
        return Message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=content,
            extra_metadata=extra_metadata or {},
        )
