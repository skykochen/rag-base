"""
==========================================
  问答工作流状态定义（RAGState）
==========================================

【为什么用 TypedDict 而非 Pydantic？】
· 节点函数 return 部分字段（partial update），由调用方 merge 到全局 state
· TypedDict total=False 天然支持"只返回某几个字段"，Pydantic 需要逐字段 copy_update
· 不需要运行时校验——state 只在图内部流转，字段类型由节点自己保证

【数据流向】
  service 层注入 → normalize_query → route_query → plan_retrieval ↔ retrieve
                                                    → observe_context
                                                    → rerank → judge_context → END

  每个节点读自己需要的字段，写自己负责的字段，不互相覆盖。
"""

from typing import Literal, TypedDict
from uuid import UUID

from app.db.models import Message
from app.retrieval.vector_retriever import RetrievedChunk

# 4 选 1 路由策略
# · original：不改写，直接检索
# · rewrite：消歧义/补完整后检索
# · hyde：先生成假设回答，用假设回答做检索（解决"关键词稀疏"问题）
# · multi_query：拆成多个子查询分别检索再合并（解决"多角度"问题）
QueryRoute = Literal["original", "rewrite", "hyde", "multi_query"]


class RAGState(TypedDict, total=False):
    # ════════════════════════════════════════════════
    # 输入字段 —— 由 chat_service.stream_answer 注入
    # ════════════════════════════════════════════════

    # 会话 ID，用于加载多轮聊天历史（load_context）
    conversation_id: UUID
    # 用户原始问题，图中的每个节点都可能读
    question: str
    # 用户拥有的权限标签列表
    # · 含 "*" 时检索不附加权限过滤（admin / 评测）
    # · 非 admin 时 SQL 层加 WHERE permission_tags && ARRAY[...]
    permissions: list[str]

    # ════════════════════════════════════════════════
    # load_context 产出 —— normalize_query 消费
    # ════════════════════════════════════════════════
    chat_history: list[Message]

    # ════════════════════════════════════════════════
    # normalize_query 产出 —— route_query 消费
    # ════════════════════════════════════════════════
    # 基于多轮历史改写后的独立完整 query；无历史时 = question
    query: str

    # ════════════════════════════════════════════════
    # route_query 产出 —— plan_retrieval / retrieve 消费
    # ════════════════════════════════════════════════
    route: QueryRoute                         # 实际采用的策略
    rewritten_query: str | None               # rewrite 路径下的改写文本
    hyde_answer: str | None                   # HyDE 路径下的假设回答
    multi_queries: list[str] | None           # multi_query 路径下的子查询列表

    # ════════════════════════════════════════════════
    # retrieve 产出 —— observe_context / rerank 消费
    # ════════════════════════════════════════════════
    retrieved_chunks: list[RetrievedChunk]    # 混合检索召回的结果列表
    refused: bool                             # 是否触发拒答（generate 跳过）

    # ════════════════════════════════════════════════
    # Agentic RAG 循环状态 —— plan_retrieval ↔ observe_context
    # ════════════════════════════════════════════════
    # agent_steps 每项：{round, action, reason, route, query, retrieved_count, top_score, sufficient}
    # · plan_retrieval 追加决策字段（前 5 个）
    # · observe_context 回填观察字段（后 3 个）
    # 一轮决策+观察用同一个 dict，前端展示和审计都方便
    agent_steps: list[dict]
    retrieval_round: int                      # 当前第几轮检索（从 1 开始）
    context_sufficient: bool                  # observe_context 判定的结果

    # ════════════════════════════════════════════════
    # rerank + judge_context 产出
    # ════════════════════════════════════════════════
    # judge_context 基于 rerank_score（或回退到 vector_score）做最终闸门
    context_is_enough: bool                   # True → END，False → refuse

    # ════════════════════════════════════════════════
    # generate 产出 —— service 层写回
    # ════════════════════════════════════════════════
    answer: str                               # 最终答案全文

    # ════════════════════════════════════════════════
    # 落库回写 —— chat_service 在 generate 完成后注入
    # ════════════════════════════════════════════════
    user_message_id: UUID                     # 刚写入的用户消息 ID
    assistant_message_id: UUID                # 刚写入的助手消息 ID

    # ════════════════════════════════════════════════
    # 观测 —— 仅由 service 层写入，节点不感知
    # ════════════════════════════════════════════════
    trace_id: str | None                      # LangSmith trace_id
