"""小语料的向量JSON索引与余弦检索，不需要向量数据库。"""
from hashlib import sha256
import math
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from app.config import AppError
from app.embeddings import RECIPE, embed_documents, embed_query, model_name
from app.knowledge_index import KnowledgeIndex, PROJECT_ROOT
from app.schemas import SearchKnowledgeArgs

VECTOR_PATH = PROJECT_ROOT / "outputs" / "knowledge-vectors.json"


class VectorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chunk_id: str
    values: list[FiniteFloat] = Field(min_length=1)


class VectorIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int
    model_name: str
    recipe: str
    dimension: int = Field(ge=1, le=4096)
    corpus_hash: str
    vectors: list[VectorRecord] = Field(min_length=1)


def corpus_hash(index: KnowledgeIndex) -> str:
    # 构建时间不同不影响资料身份；原文版本/切块参数/正文变化都使旧向量失效。
    return sha256(index.model_dump_json(exclude={"built_at"}).encode("utf-8")).hexdigest()


def build_vectors(index: KnowledgeIndex) -> VectorIndex:
    vectors = embed_documents([chunk.title + "\n" + chunk.content for chunk in index.chunks])
    if len(vectors) != len(index.chunks) or not vectors or not vectors[0]:
        raise AppError("片段与向量数量不一致。", code="embedding_failed")
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise AppError("片段向量维度不一致。", code="embedding_failed")
    return VectorIndex(schema_version=1, model_name=model_name(), recipe=RECIPE, dimension=dimension,
                       corpus_hash=corpus_hash(index), vectors=[VectorRecord(chunk_id=chunk.chunk_id, values=vector)
                       for chunk, vector in zip(index.chunks, vectors)])


def write_vectors(index: VectorIndex, path: Path = VECTOR_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(index.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        raise AppError("向量索引写入失败。", code="knowledge_unavailable") from None


def load_vectors(corpus: KnowledgeIndex, path: Path = VECTOR_PATH) -> VectorIndex:
    try:
        index = VectorIndex.model_validate_json(path.read_text(encoding="utf-8"))
        if (index.schema_version != 1 or index.model_name != model_name() or index.recipe != RECIPE or
                index.corpus_hash != corpus_hash(corpus)):
            raise ValueError
        ids = [vector.chunk_id for vector in index.vectors]
        if len(ids) != len(set(ids)) or set(ids) != {chunk.chunk_id for chunk in corpus.chunks}:
            raise ValueError
        for vector in index.vectors:
            norm = math.sqrt(sum(value * value for value in vector.values))
            if len(vector.values) != index.dimension or not math.isfinite(norm) or abs(norm - 1) > 0.001:
                raise ValueError
        return index
    except (OSError, UnicodeError, ValueError):
        raise AppError("向量索引缺失、过期或损坏；请先构建知识片段，再运行build_vector_index.py。", code="knowledge_unavailable") from None


def minimum_score() -> float:
    try:
        value = float(os.getenv("KNOWLEDGE_MIN_SCORE", "0.58"))
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError
        return value
    except ValueError:
        raise AppError("KNOWLEDGE_MIN_SCORE必须为0到1的有限数值。", code="knowledge_unavailable") from None


def search_semantic(args: SearchKnowledgeArgs, corpus: KnowledgeIndex, *, candidate_limit: int | None = None) -> list[dict]:
    threshold = minimum_score()
    index = load_vectors(corpus)
    query = embed_query(args.query)
    if len(query) != index.dimension:
        raise AppError("问题与片段向量维度不一致，请检查模型并重建索引。", code="embedding_failed")
    vectors = {record.chunk_id: record.values for record in index.vectors}
    ranked = []
    for chunk in corpus.chunks:
        # 两边都归一化后，点积就是余弦相似度；先按原始分数筛选，再做展示舍入。
        score = sum(left * right for left, right in zip(query, vectors[chunk.chunk_id]))
        if score >= threshold:
            passage = chunk.model_dump(exclude={"keywords"})
            passage.update(score=round(score, 6), score_kind="cosine", retrieval="semantic")
            ranked.append((score, chunk.chunk_id, passage))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    size = args.limit if candidate_limit is None else candidate_limit
    return [passage for _, _, passage in ranked[:size]]
