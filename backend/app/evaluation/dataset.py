"""评测集加载：从 backend/app/evaluation/datasets/*.jsonl 读取 case 列表。"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import NotFoundError, ValidationError

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


@dataclass(frozen=True)
class EvaluationCase:
    """单条评测样本。

    expected_keywords 与 expected_document_names 配合做"引用命中率"判定：
    - 命中文档名 → 视为引用命中
    - 命中任一关键词（在 actual citations 的 quote 拼接里）→ 视为引用命中
    """

    case_id: str
    question: str
    expected_answer: str
    expected_document_names: list[str]
    expected_keywords: list[str]
    should_refuse: bool
    tags: list[str]


def list_datasets() -> list[tuple[str, int]]:
    """枚举 datasets/ 下所有 jsonl，返回 (name, size) 二元组列表。

    name 为去掉后缀的文件名（如 `seed`），size 是 case 条数。
    """
    if not DATASETS_DIR.exists():
        return []
    results: list[tuple[str, int]] = []
    for path in sorted(DATASETS_DIR.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip())
        results.append((path.stem, count))
    return results


def load_dataset(name: str) -> list[EvaluationCase]:
    """按名称加载 jsonl 评测集。

    name 为不带后缀的文件名（如 `seed`）。文件不存在时抛 NotFoundError，
    便于 API 层直接返回 404。
    """
    path = DATASETS_DIR / f"{name}.jsonl"
    if not path.exists():
        raise NotFoundError(f"评测集不存在：{name}")

    cases: list[EvaluationCase] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"评测集 {name} 第 {line_no} 行 JSON 非法：{exc.msg}"
                ) from exc
            cases.append(_parse_case(data, line_no=line_no, dataset=name))
    return cases


def _parse_case(data: dict, *, line_no: int, dataset: str) -> EvaluationCase:
    """把单行 jsonl 解析成 EvaluationCase，缺关键字段就抛 ValidationError。"""
    try:
        return EvaluationCase(
            case_id=str(data["id"]),
            question=str(data["question"]),
            expected_answer=str(data.get("expected_answer", "")),
            expected_document_names=list(data.get("expected_document_names") or []),
            expected_keywords=list(data.get("expected_keywords") or []),
            should_refuse=bool(data.get("should_refuse", False)),
            tags=list(data.get("tags") or []),
        )
    except KeyError as exc:
        raise ValidationError(
            f"评测集 {dataset} 第 {line_no} 行缺失字段：{exc.args[0]}"
        ) from exc
