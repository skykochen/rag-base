"""LangGraph 编排：Agentic RAG 检索子图。

第 4 章用 ChatService 顺序调用节点函数；第 7 章起切换到 `StateGraph`，
让 plan_retrieval → retrieve → observe_context 形成可循环的检索子图。
第 8 章在 observe_context 之后接入 rerank → judge_context 精排，
plan_retrieval 拒答 / judge_context 拒答统一收敛到 refuse 节点。

边界：
- `load_context` 需要 DB session，留在 service 层执行后把 `chat_history` 注入 state，
  这里不在图里拿 session，避免把基础设施穿过图配置。
- `generate` 走 SSE 流式 token，与 LangGraph 同步执行模型不匹配，同样留在 service 层。
- `verify_answer` 在 generate 之后跑（要看流式生成出来的最终 answer），也留在 service 层。

子图覆盖：normalize_query → route_query → plan_retrieval ↔ retrieve → observe_context
                                                       → rerank → judge_context → END/refuse。
"""

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.logging import get_logger
from app.workflows.nodes import (
    judge_context,
    normalize_query,
    observe_context,
    plan_retrieval,
    refuse,
    rerank,
    retrieve,
    route_query,
)
from app.workflows.rag_state import RAGState

logger = get_logger(__name__)


def _after_plan(state: RAGState) -> str:
    """planner 决策为 refuse 时直接走 refuse 节点统一塞拒答文案，跳过后续检索 / 精排。"""
    if state.get("agent_steps"):
        last_action = state["agent_steps"][-1].get("action")
        if last_action == "refuse":
            return "refuse"
    return "retrieve"


def _after_observe(state: RAGState) -> str:
    """observe 后决定继续循环还是结束循环交给 rerank 精排。

    退出循环条件（任一即停）：
    - 关闭了 agent loop（退化为单轮）
    - 本轮已足够（context_sufficient=True）
    - 达到 agent_max_rounds 上限

    退出循环后统一进 rerank（不再直接 END）：哪怕本轮 sufficient=False，
    也走完 rerank → judge_context，让 judge_context 一处统一拒答闸门。
    """
    if not settings.agent_loop_enabled:
        return "rerank"
    if state.get("context_sufficient"):
        return "rerank"
    if state.get("retrieval_round", 0) >= settings.agent_max_rounds:
        return "rerank"
    return "plan"


def _after_judge(state: RAGState) -> str:
    """judge_context 后的最终闸门：上下文足够 → END；不足 → refuse 节点。"""
    if state.get("context_is_enough"):
        return "end"
    return "refuse"


def _build_graph():
    builder = StateGraph(RAGState)

    builder.add_node("normalize_query", normalize_query)
    builder.add_node("route_query", route_query)
    builder.add_node("plan_retrieval", plan_retrieval)
    builder.add_node("retrieve", retrieve)
    builder.add_node("observe_context", observe_context)
    builder.add_node("rerank", rerank)
    builder.add_node("judge_context", judge_context)
    builder.add_node("refuse", refuse)

    builder.add_edge(START, "normalize_query")
    builder.add_edge("normalize_query", "route_query")
    builder.add_edge("route_query", "plan_retrieval")
    builder.add_conditional_edges(
        "plan_retrieval",
        _after_plan,
        {"retrieve": "retrieve", "refuse": "refuse"},
    )
    builder.add_edge("retrieve", "observe_context")
    builder.add_conditional_edges(
        "observe_context",
        _after_observe,
        {"plan": "plan_retrieval", "rerank": "rerank"},
    )
    builder.add_edge("rerank", "judge_context")
    builder.add_conditional_edges(
        "judge_context",
        _after_judge,
        {"end": END, "refuse": "refuse"},
    )
    builder.add_edge("refuse", END)

    return builder.compile()


_rag_graph = _build_graph()


def get_rag_graph():
    """对外暴露已编译好的子图；模块加载时一次编译，请求里直接复用。"""
    return _rag_graph
