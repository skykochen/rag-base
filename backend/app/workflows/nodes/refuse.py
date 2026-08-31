"""refuse：统一拒答节点。

把"塞拒答文案 + 标 refused"集中到一个节点，避免散落在 plan_retrieval / retrieve /
judge_context 等多处重复——之前 plan_retrieval / retrieve 都写过一遍 REFUSAL_ANSWER 直填，
第 8 章统一收敛到这里，所有触发拒答的边都连到 refuse。
"""

from app.llm.prompts import REFUSAL_ANSWER
from app.workflows.rag_state import RAGState


async def refuse(state: RAGState) -> RAGState:
    return {"refused": True, "answer": REFUSAL_ANSWER}
