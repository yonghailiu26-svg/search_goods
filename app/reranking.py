"""第十二课：对已有候选做本地交叉编码重排，不生成新知识片段。"""
from functools import lru_cache
import math
import os

from app.config import AppError
from app.embeddings import MODEL_CACHE


def reranker_name() -> str:
    return os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3-int8").strip()


@lru_cache(maxsize=1)
def get_reranker(name: str, allow_download: bool):
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        return TextCrossEncoder(model_name=name, cache_dir=str(MODEL_CACHE), threads=2,
                                providers=["CPUExecutionProvider"], local_files_only=not allow_download)
    except Exception:
        raise AppError("本地重排模型不可用，请先运行prepare_reranker.py。", code="rerank_failed") from None


def score_pairs(query: str, documents: list[str]) -> list[float]:
    try:
        model = get_reranker(reranker_name(), False)
        scores = [float(score) for score in model.rerank(query, documents, batch_size=4)]
        if len(scores) != len(documents) or not all(math.isfinite(score) for score in scores):
            raise ValueError
        return scores
    except Exception:
        raise AppError("候选片段重排失败，本次未返回未经重排的结果。", code="rerank_failed") from None


def rerank_passages(query: str, candidates: list[dict], *, limit: int) -> list[dict]:
    if not candidates:
        return []  # 没召回就没有可重排的候选，也不加载模型。
    scores = score_pairs(query, [p["title"] + "\n" + p["content"] for p in candidates])
    if len(scores) != len(candidates) or not all(math.isfinite(score) for score in scores):
        raise AppError("重排分数数量或数值异常。", code="rerank_failed")
    ranked = []
    for rank, (passage, score) in enumerate(zip(candidates, scores), start=1):
        result = dict(passage)
        result["rerank_details"] = {"model": reranker_name(), "input_rank": rank,
                                    "input_score": passage["score"], "input_score_kind": passage["score_kind"]}
        result.update(score=round(score, 6), score_kind="cross_encoder", retrieval="rerank")
        ranked.append((score, passage["chunk_id"], result))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [passage for _, _, passage in ranked[:limit]]
