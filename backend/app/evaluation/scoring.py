
from typing import Literal
from dataclasses import dataclass
# 坏例归因分类：评测中发现错误答案时，按 RAG 管道阶段定位根因。
# 取值存入 EvaluationItem.bad_case_category，用于坏例筛选与统计分析。
BadCaseCategory = Literal[
    "document_parse_failed",     # 文档解析失败：文档无法解析为文本，内容缺失无法入库
    "chunk_split_bad",          # 分块质量差：语义被切碎或边界不合理，相关信息分散/丢失
    "embedding_recall_miss",    # 向量召回遗漏：embedding 向量检索未召回相关 chunk
    "keyword_recall_miss",      # 关键词召回遗漏：关键词/全文检索未召回相关 chunk
    "rrf_fusion_error",         # RRF 融合错误：混合检索结果融合（Reciprocal Rank Fusion）阶段出错
    "rerank_order_error",       # 重排顺序错误：重排器把相关文档排到末尾，被截断丢弃
    "context_judge_too_loose",  # 上下文判定过松：上下文实际不足仍判定充足，生成时缺依据
    "context_judge_too_strict", # 上下文判定过严：上下文实际充足仍判定不足，本可回答却拒答
    "prompt_constraint_weak",   # 生成约束不足：提示词未严格约束模型仅依据给定上下文作答
    "generation_off_context",   # 生成偏离上下文：答案内容与检索到的上下文不符（幻觉/编造）
    "citation_parse_failed",    # 引用解析失败：模型生成的引用无法解析/映射到知识库文档
    "permission_filter_error",  # 权限过滤错误：过滤逻辑误伤（该放行的被拦截或反之）
    "other",                    # 其他：无法归入上述类别的坏例
]

# 指标低于此值视为"显著低"，触发对应归因。教学项目用单一阈值即可，
# 真实项目通常按指标类型分别调阈值
_LOW_SCORE_THRESHOLD = 0.5
@dataclass
class BadCaseRule:
    """一条规则归因结论。"""
    is_bad_case: bool
    category: BadCaseCategory | None



def compute_citation_hit(
        actual_citations: list[dict],
        expected_document_names: list[str],
        expected_keywords: list[str],
) -> bool:
    """引用命中率判定：

    1. 任一 citation 的 document_name 出现在 expected_document_names → 命中
    2. 任一 expected_keyword 出现在 citations 的 quote 拼接里 → 命中
    3. 否则未命中
    """
    if not actual_citations:
        return False
    # any( <条件> for <变量> in <列表> if <过滤条件> )
    actual_doc_names = {c.get("document_name", "") for c in actual_citations}
    if any(name in actual_doc_names for name in expected_document_names if name):
        return True
    if expected_keywords:  # 拼一次而不是 N 次 in 调用，O(L*K) → O(L+K) 量级
        quote_blob = "\n".join(str(c.get("quote", "")) for c in actual_citations)
        if any(kw in quote_blob for kw in expected_keywords if kw):
            return True
    return False

def compute_refusal_correct(actual_refused: bool, should_refuse: bool) -> bool:
    """拒答正确率：实际拒答状态 == 期望。"""
    return actual_refused == should_refuse

def classify_bad_case(
        *,
        should_refuse: bool,
        actual_refused: bool,
        refusal_correct: bool,
        citation_hit: bool | None,
        faithfulness: float|None,
        answer_relevancy: float|None,
        context_precision: float|None,
        context_recall: float|None,
        has_error: bool,
) -> BadCaseRule:
    """归因主函数，规则按优先级排序，命中即停："""
    if has_error:
        return BadCaseRule(is_bad_case=True, category="other")
    # 拒答错误的两种方向：该拒不拒 / 不该拒却拒了
    if not refusal_correct:
        if should_refuse and not actual_refused:
            return BadCaseRule(is_bad_case=True, category="context_judge_too_loose")
        return BadCaseRule(is_bad_case=True, category="context_judge_too_strict")
    # 非拒答 case 才考察引用命中：拒答 case 的 citation_hit 本就 None
    if citation_hit is False:
        return BadCaseRule(is_bad_case=True, category="embedding_recall_miss")
    # RAGAS 指标顺序：先看召回（context_recall）→ 排序（context_precision）→
    # 生成忠实度（faithfulness）→ 答案相关性（answer_relevancy）
    if _is_low(context_recall):#Context Recall：参考答案里的关键信息有多少能在召回上下文里找到。低分说明召回环节漏掉了关键信息
        return BadCaseRule(is_bad_case=True, category="embedding_recall_miss")
    if _is_low(context_precision):#Context Precision：召回的上下文里「有用片段」的占比。低分说明 rerank 没把真正相关的片段顶到前面
        return BadCaseRule(is_bad_case=True, category="rerank_order_error")
    if _is_low(faithfulness):# Faithfulness：答案里的事实声明是否都能在 retrieved_contexts 里找到对应支撑。低分说明模型在编造，也就是我们常说的幻觉
        return BadCaseRule(is_bad_case=True, category="generation_off_context")
    if _is_low(answer_relevancy):#Answer Relevancy：回答和原问题的相关程度。低分说明模型答非所问、或答案太啰嗦

        return BadCaseRule(is_bad_case=True, category="prompt_constraint_weak")
    return BadCaseRule(is_bad_case=False, category=None)


def _is_low(score: float | None) -> bool:
    """判断 score 是否显著低。"""
    return score is not None and score < _LOW_SCORE_THRESHOLD


