from dataclasses import dataclass

from app.llm.models import get_chat_model
from app.llm.prompts import build_verify_answer_messages, format_context
from app.retrieval.vector_retriever import RetrievedChunk
from app.core.logging import get_logger
import json

logger = get_logger(__name__)
@dataclass(frozen=True)
class VerifyResult:
    """
    LLM 验证结果
    """
    verified: bool
    reason: str





class AnswerVerifier:
    """
    LLM 答案校验器
    """
    async def verify(
            self,
            question: str,
            answer: str,
            chunks: list[RetrievedChunk],
    ) -> VerifyResult:
        # 没有引用候选时不做校验：要么是拒答场景（service 已经标 refused），
        # 要么是异常路径，校验也没有参考片段可对照
        if not chunks or not answer.strip():
            return VerifyResult(verified=True, reason="")

        messages = build_verify_answer_messages(
            question=question,
            answer=answer,
            chunks_text=format_context(chunks),
        )
        try:
            response = await get_chat_model().ainvoke(messages)
            raw = _extract_text(response.content).strip()
            return _parse_result(raw)
        except Exception:
            logger.execption(
                "answer verifier 调用失败，降级 verified=True: question=%r", question
            )
            return VerifyResult(verified=True, reason="verifier_exception")

_verifier: AnswerVerifier | None = None

def get_answer_verifier() -> AnswerVerifier:
    """单例缓存"""
    global _verifier
    if _verifier is None:
        _verifier = AnswerVerifier()
    return _verifier

def _parse_result(raw: str) -> VerifyResult:
    """
    LLM 验证结果解析
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except Exception:
        logger.warning("answer verifier JSON 解析失败，降级 verified=True：raw=%r", raw)
        return VerifyResult(verified=True, reason="verifier_parse_failed")
    if not isinstance(data, dict):
        return VerifyResult(verified=True, reason="verifier_parse_failed")

    verified_raw = data.get("verified")
    # 严格只认布尔值；字符串 "true" / 1 等都视为非法，避免歧义
    if not isinstance(verified_raw, bool):
        logger.warning(
            "answer verifier verified 字段非法，降级 verified=True：raw=%r", raw
        )
        return VerifyResult(verified=True, reason="verifier_invalid_verified")
    reason = str(data.get("reason") or "") .strip()
    return VerifyResult(verified=verified_raw, reason=reason)


def _extract_text(content: str | list[str | dict]) -> str:
    """兼容 langchain ChatModel 的 content 联合类型"""
    if isinstance(content, str):
        return content
    # 提取content中所有为dict的部分，且将key为text的部分拼成结果，没有返回空
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))