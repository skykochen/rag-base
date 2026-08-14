import re
from typing import get_args
from app.core.logging import get_logger
from app.llm.models import get_chat_model
from app.llm.prompts import build_route_messages, build_rewrite_messages, build_hyde_messages, \
    build_multi_query_messages, build_contextualize_messages
from app.workflows.rag_state import QueryRoute
from dataclasses import dataclass
from app.db.models import Message, MessageRole

logger = get_logger(__name__)

_VALID_ROUTE: tuple[str, ...] = get_args(QueryRoute)


@dataclass(frozen=True)
class QueryRouteResult:
    route: QueryRoute
    query: str
    rewritten_query: str | None = None
    hyde_answer: str | None = None
    multi_queries: list[str] | None = None


class QueryRewriter:

    async def decide_route(self, question: str) -> QueryRoute:
        messages = build_route_messages(question)
        response = await get_chat_model().ainvoke(messages)
        raw = _extract_text(response.content).strip().lower()
        # token = raw.strip("\"'`.。 ")
        token = re.split(r"""["'.。 ]""", raw)[0]
        if token in _VALID_ROUTE:
            return token
        logger.warning("query route 模型返回非法值，降级 original：raw=%r", raw)
        return "original"

    async def rewrite(self, question: str) -> str:
        messages = build_rewrite_messages(question)
        response = await get_chat_model().ainvoke(messages)
        return _extract_text(response.content).strip()

    async def hyde(self, question: str) -> str:
        messages = build_hyde_messages(question)
        response = await get_chat_model().ainvoke(messages)
        return _extract_text(response.content).strip()

    async def multi_query(self, question: str, n: int) -> list[str]:
        messages = build_multi_query_messages(question, n)
        response = await get_chat_model().ainvoke(messages)
        text = _extract_text(response.content)
        queries = [line.strip(" --•*0123456789.、") for line in text.splitlines()]
        return [q for q in queries if q][:n]

    #“路由 → 按策略调用 → 装配结果 → 各路径降级”
    # async def optimize(self, question: str, multi_query_count: int) -> QueryRouteResult:
    async def apply_route(
            self,
            question: str,
            route: QueryRoute,
            multi_query_count: int
            ) -> QueryRouteResult:
        try:
            if route == "rewrite":
                rewritten = await self.rewrite(question)
                if not rewritten:
                    return QueryRouteResult(route="original", query=question)
                return QueryRouteResult(
                    route="rewrite", query=rewritten, rewritten_query=rewritten)
            if route == "hyde":
                hyde_answer = await self.hyde(question)
                if not hyde_answer:
                    return QueryRouteResult(route="original", query=question)
                return QueryRouteResult(route="hyde", query=hyde_answer, hyde_answer=hyde_answer)
            if route == "multi_query":
                queries = await self.multi_query(question, multi_query_count)
                #至少有2条子查询
                if len(queries) < 2:
                    return QueryRouteResult(route="original", query=question)
                return QueryRouteResult(route="multi_query", query=question, multi_queries=queries)
            return QueryRouteResult(route="original", query=question)
        except Exception:
            logger.exception("apply_route 失败，降级到 original：route=%s, question=%r", route, question,)
            return QueryRouteResult(route="original", query=question)

    async def optimize(self, question: str, multi_query_count: int) -> QueryRouteResult:
        """完整4选1，先判断路由，再分发到apply_route.失败降级original"""
        try:
            route = await self.decide_route(question)
        except Exception:
            logger.exception("query route 判定失败，降级到 original：question=%r", question)
            return QueryRouteResult(route="original", query=question)
        return await self.apply_route(question, route, multi_query_count)

    async def contextualize(self, question: str, history: list[Message]) -> str:
        """基于多轮历史把当前问题改写成独立完整问句。

        消解"它/这个/上面提到的"等指代、补省略，让后续 route_query / retrieve
        看到的 query 已经独立可检索。空历史直接回原问题；任何异常 / 改写为空 → 降级回原问题。
        """
        history_text = _format_history_text(history)
        if not history_text:
            return question
        try:
            messages = build_contextualize_messages(
                question=question,
                history=history_text
            )
            response = await get_chat_model().ainvoke(messages)
            rewritten = _extract_text(response.content).strip()
            return rewritten or question
        except Exception:
            logger.exception(
                "contextualize 模型调用失败，降级回原问题：question=%r, history=%r", question, history
            )
            return question

_ROLE_LABEL: dict[MessageRole, str] = {
    MessageRole.USER: "用户",
    MessageRole.ASSISTANT: "助手",
    MessageRole.SYSTEM: "系统",
}

def _format_history_text(history: list[Message]) -> str:
    """把历史 Message 压成给 contextualize prompt 看的纯文本。

    只取 user / assistant，过滤 system；空内容跳过，避免把空消息塞进 prompt 浪费 token。
    """
    lines: list[str] = []
    for msg in history:
        role_label = _ROLE_LABEL.get(msg.role)
        if not role_label or not msg.content.strip():
            continue
        lines.append(f"{role_label}：{msg.content}")
    return "\n".join(lines)

    # 单例
_rewriter:QueryRewriter | None = None
def get_query_rewriter() -> QueryRewriter:
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter

def _extract_text(content: str | list[str | dict]) -> str:
    """兼容 langchain ChatModel 的 content 联合类型"""
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))
