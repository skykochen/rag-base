"""
==========================================
  workflows 包 —— LangGraph 工作流编排
==========================================

【这个包在项目中的位置】
第 4 章用 ChatService 直接顺序调用函数（一问一答），
第 7 章起引入 LangGraph 的 StateGraph 把检索过程编排成有状态的图，
第 8 章在图中加入 rerank → judge_context 精排 + 统一拒答闸门。

【为什么需要工作流？】
免去自己维护循环和状态：
  · plan_retrieval 决策下一步，retrieve 执行，observe_context 观察效果
  · 不够好就跳回 plan_retrieval 再来一轮（Agentic 循环）
  · LangGraph 的 StateGraph 负责"下一步走哪个节点"，代码里只剩节点函数

【图的边界】
· normalize_query → route_query → plan_retrieval ↔ retrieve → observe_context
                                                    → rerank → judge_context → END/refuse
· load_context / stream_generate / verify_answer 在 service 层执行，不在图里
  （load_context 需要 DB session，generate 做 SSE 流式，verify 要拿到完整 answer）
"""
