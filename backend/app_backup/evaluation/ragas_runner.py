import asyncio
import warnings
from dataclasses import dataclass
from langchain_openai import ChatOpenAI  # noqa: E402
# ragas 0.4 把 metrics import 路径迁到 collections，但小写实例 API 在 v1.0 前都可用；
# 这里集中静默 DeprecationWarning，避免污染日志，等 ragas 1.0 发布后再升级
warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")
from app.core.config import settings
from ragas import evaluate  # noqa: E402
from ragas.dataset_schema import EvaluationDataset, SingleTurnSample  # noqa: E402
from ragas.metrics import (  # noqa: E402
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from ragas.run_config import RunConfig  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.ingestion.embedder import get_embeddings  # noqa: E402
from app.llm.models import get_chat_model  # noqa: E402

logger = get_logger(__name__)

@dataclass(frozen=True)
class RagasMetrics:
    """单条 case 的 RAGAS 4 指标结果，全部 [0, 1] ∪ {None}。

    None 表示 RAGAS 本次未能算出该指标（异常 / 缺关键输入），下游按缺失处理。
    """

    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None


@dataclass(frozen=True)
class RagasSample:
    """喂给 evaluate 的单条样本。"""

    question: str
    answer: str
    retrieved_contexts: list[str]
    reference_answer: str


_METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]

_RUN_CONFIG = RunConfig(
    timeout=300,      # 单次 LLM/embedding 调用放宽到 5 分钟（DashScope 响应慢）
    max_workers=4,    # 并发降到 4，避免 16 个 Job 同时打爆 DashScope 限流
    max_retries=3,    # 失败最多重试 3 次（默认 10 次反而会拖长整批时间）
)

# 评测专用 LLM：不复用 get_chat_model()（那是聊天流式用，默认 httpx 超时仅 60s，
# 评测请求上下文长、响应慢，60s 会被 httpx 层直接掐断导致批量 TimeoutError）
_eval_chat_model = ChatOpenAI(
    model=settings.chat_model,
    api_key=settings.chat_api_key,
    base_url=settings.chat_base_url,
    temperature=0,
    timeout=300,      # httpx 客户端超时放宽到 5 分钟，必须比 ragas 层更大
)

async def evaluate_batch(samples: list[RagasSample]) -> list[RagasMetrics]:
    """对一批样本算 RAGAS 指标，返回长度与 samples 一致的指标列表。

    任一条样本因为字段缺失（空 retrieved_contexts / 空 reference）会被 RAGAS
    某些指标判 NaN，这里统一转 None；整批异常时全部样本返回 None 占位。
    """
    if not samples:
        return []

    dataset = EvaluationDataset(
        samples=[
            SingleTurnSample(
                user_input=s.question,
                response=s.answer or " ",
                retrieved_contexts=s.retrieved_contexts or [" "],
                reference=s.reference_answer or " ",
            )
            for s in samples
        ]
    )

    try:
        result = await asyncio.to_thread(
            evaluate,
            dataset=dataset,
            metrics=_METRICS,
            llm=_eval_chat_model,
            embeddings=get_embeddings(),
            run_config=_RUN_CONFIG,
            raise_exceptions=False,
            show_progress=False,
        )
    except Exception:
        logger.exception("RAGAS evaluate 整批失败，返回 None 占位")
        return [_empty_metrics() for _ in samples]

    return _extract_metrics(result, expected=len(samples))

def _extract_metrics(result, expected: int) -> list[RagasMetrics]:
    rows = getattr(result, "scores", None) or []
    if len(rows) != expected:
        logger.warning(
            "RAGAS 返回行数 %d 与样本数 %d 不一致，按可用值对齐", len(rows), expected
        )

    metrics: list[RagasMetrics] = []
    for i in range(expected):
        row = rows[i] if i < len(rows) else {}
        metrics.append(
            RagasMetrics(
                faithfulness=_pick(row, "faithfulness"),
                answer_relevancy=_pick(row, "answer_relevancy"),
                context_precision=_pick(row, "context_precision"),
                context_recall=_pick(row, "context_recall"),
            )
        )
    return metrics


def _pick(row: dict, key: str) -> float | None:
    """从 RAGAS 结果行里取分数；NaN / 缺失 / 非数值都视为 None。"""
    value = row.get(key)
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    #aN 有一个奇特性质：它不等于任何值，包括它自己。
    if as_float != as_float:  # NaN
        return None
    return as_float


def _empty_metrics() -> RagasMetrics:
    return RagasMetrics(
        faithfulness=None, answer_relevancy=None,
        context_precision=None, context_recall=None,
    )
