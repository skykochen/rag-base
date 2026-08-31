"""
==========================================
  问答路由 —— 会话管理与 SSE 流式问答
==========================================

这是项目的核心功能接口！负责：
1. 会话的 CRUD（创建、查看、删除）
2. SSE 流式问答（打字机效果）

【什么是 SSE？】
SSE = Server-Sent Events（服务器推送事件）。
普通的 HTTP 请求：客户端发请求 → 服务器算完 → 一次性返回结果。
SSE：客户端发请求 → 服务器持续推送 token → 客户端逐字显示。

效果就是"打字机"——AI 生成一个字，前端就显示一个字，
用户不用等到全部生成完才看到内容。

【事件协议】
服务端按顺序推送以下事件：
message_start → query_route → agent_steps → citations → token... → [verify_result] → message_end

前端用 @microsoft/fetch-event-source 库接收。
"""

from collections.abc import AsyncIterable
from uuid import UUID

from fastapi import APIRouter, Query, Response
from fastapi.responses import EventSourceResponse
from fastapi.sse import ServerSentEvent

from app.api.deps import CurrentUser, DbSession, RateLimited
from app.api.schemas.chat import (
    ChatRequest,
    ConversationCreate,
    ConversationDetail,
    ConversationListItem,
    ConversationPage,
    ConversationRead,
    MessageRead,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations", tags=["chat"])


@router.post("", response_model=ConversationRead, status_code=201, operation_id="createConversation")
async def create_conversation(
    user: CurrentUser,
    payload: ConversationCreate,
    session: DbSession,
) -> ConversationRead:
    """创建新会话。会话是问答的容器，一个会话内可以连续多轮提问。"""
    service = ChatService(session)
    conversation = await service.create_conversation(user_id=user.id, title=payload.title)
    return ConversationRead.model_validate(conversation)


@router.get("", response_model=ConversationPage, operation_id="listConversations")
async def list_conversations(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ConversationPage:
    """按更新时间倒序分页列出当前用户的会话列表。"""
    service = ChatService(session)
    items, total = await service.list_conversations(page=page, page_size=page_size, user_id=user.id)
    return ConversationPage(
        items=[
            ConversationListItem(id=conv.id, title=conv.title, updated_at=conv.updated_at, message_count=count)
            for conv, count in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail, operation_id="getConversation")
async def get_conversation(
    user: CurrentUser,
    conversation_id: UUID,
    session: DbSession,
) -> ConversationDetail:
    """获取会话详情，包含全部历史消息和引用。"""
    service = ChatService(session)
    conversation, messages = await service.list_messages(conversation_id, user_id=user.id)
    return ConversationDetail(
        conversation=ConversationRead.model_validate(conversation),
        messages=[MessageRead.from_orm(m) for m in messages],
    )


@router.delete("/{conversation_id}", status_code=204, operation_id="deleteConversation")
async def delete_conversation(
    user: CurrentUser,
    conversation_id: UUID,
    session: DbSession,
) -> Response:
    """删除会话及其全部消息。"""
    service = ChatService(session)
    await service.delete_conversation(conversation_id, user_id=user.id)
    return Response(status_code=204)


@router.post("/{conversation_id}/chat", operation_id="streamChat", response_class=EventSourceResponse)
async def stream_chat(
    user: CurrentUser,
    _rate_limit: RateLimited,
    conversation_id: UUID,
    payload: ChatRequest,
    session: DbSession,
) -> AsyncIterable[ServerSentEvent]:
    """
    ⭐ SSE 流式问答——项目核心功能！

    流程（聊天服务层，约8步）：
    1. 校验会话是否存在
    2. 加载对话历史上下文
    3. 查询语义缓存（命中则直接返回缓存答案）
    4. 运行 LangGraph RAG 子图（检索+推理）
    5. 用户消息落库 + 自动改标题
    6. 推送事件：query_route → agent_steps → citations → token...
    7. 答案校验（verify_answer）
    8. AI 回复落库 + 写入语义缓存
    """
    service = ChatService(session)
    async for sse_event in service.stream_answer(
        conversation_id, payload.question, current_user=user
    ):
        yield ServerSentEvent(
            data=sse_event["data"],
            event=sse_event["event"],
        )
