"""第十四课：评测集、明确口径的检索指标和回归门槛；不调用模型。"""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.config import AppError


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=200)
    relevant_chunk_ids: list[str]


class RetrievalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int
    cases: list[RetrievalCase] = Field(min_length=1)


def load_cases(path: Path, available_ids: set[str]) -> RetrievalDataset:
    try:
        dataset = RetrievalDataset.model_validate_json(path.read_text(encoding="utf-8"))
        ids = [case.id for case in dataset.cases]
        if dataset.version != 1 or len(ids) != len(set(ids)):
            raise ValueError
        for case in dataset.cases:
            if len(case.relevant_chunk_ids) != len(set(case.relevant_chunk_ids)) or set(case.relevant_chunk_ids) - available_ids:
                raise ValueError
        if not any(c.relevant_chunk_ids for c in dataset.cases) or not any(not c.relevant_chunk_ids for c in dataset.cases):
            raise ValueError
        return dataset
    except (OSError, ValueError):
        raise AppError("评测集无效：请检查JSON、版本、重复ID、片段标签及正负样例。", code="evaluation_failed") from None


def score_case(retrieved_ids: list[str], relevant_ids: list[str], *, k: int = 3) -> dict:
    if k < 1 or len(retrieved_ids) != len(set(retrieved_ids)) or len(relevant_ids) != len(set(relevant_ids)):
        raise ValueError("指标输入包含非法k或重复ID")
    top = retrieved_ids[:k]
    if not relevant_ids:
        return {"hit_at_k": None, "precision_at_k": None, "recall_at_k": None, "mrr_at_k": None, "abstained": not top}
    relevant = set(relevant_ids)
    matches = [rank for rank, key in enumerate(top, start=1) if key in relevant]
    return {"hit_at_k": int(bool(matches)), "precision_at_k": len(matches) / len(top) if top else 0.0,
            "recall_at_k": len(matches) / len(relevant), "mrr_at_k": 1 / matches[0] if matches else 0.0, "abstained": None}


def aggregate_scores(rows: list[dict]) -> dict:
    positive = [row for row in rows if row["hit_at_k"] is not None]
    negative = [row for row in rows if row["abstained"] is not None]
    summary = {key: sum(row[key] for row in positive) / len(positive) if positive else None
               for key in ("hit_at_k", "precision_at_k", "recall_at_k", "mrr_at_k")}
    summary.update(answerable_count=len(positive), unanswerable_count=len(negative),
                   abstention_rate=sum(row["abstained"] for row in negative) / len(negative) if negative else None)
    return summary


def quality_checks(summary: dict, *, baseline: dict | None = None) -> dict[str, bool]:
    checks = {}
    for key, minimum in (("hit_at_k", 0.8), ("mrr_at_k", 0.7), ("abstention_rate", 1.0)):
        value = summary.get(key)
        checks["minimum_" + key] = value is not None and value >= minimum
    if baseline is not None:
        for key in ("hit_at_k", "precision_at_k", "recall_at_k", "mrr_at_k", "abstention_rate"):
            before, after = baseline.get(key), summary.get(key)
            checks["baseline_" + key] = before is not None and after is not None and after + 1e-9 >= before
    return checks


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
