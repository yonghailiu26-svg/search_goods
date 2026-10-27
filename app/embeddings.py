"""第十课：本地CPU文本编码；在线只读已下载模型，不使用DeepSeek Key。"""
from functools import lru_cache
import math
import os

from app.config import AppError
from app.knowledge_index import PROJECT_ROOT

MODEL_CACHE = PROJECT_ROOT / "work" / "models"
RECIPE = "fastembed-query-passage-v1"


def model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip()


def normalize(values) -> list[float]:
    vector = [float(value) for value in values]
    if not vector or not all(math.isfinite(value) for value in vector):
        raise AppError("向量为空或包含无效数值。", code="embedding_failed")
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0 or not math.isfinite(length):
        raise AppError("向量长度无效。", code="embedding_failed")
    return [value / length for value in vector]


@lru_cache(maxsize=1)
def get_model(name: str, allow_download: bool):
    try:
        from fastembed import TextEmbedding
        return TextEmbedding(model_name=name, cache_dir=str(MODEL_CACHE), threads=2,
                             providers=["CPUExecutionProvider"], local_files_only=not allow_download)
    except Exception:
        raise AppError("本地向量模型不可用；请安装requirements.txt并运行build_vector_index.py准备模型和索引。", code="embedding_failed") from None


def embed_documents(texts: list[str]) -> list[list[float]]:
    try:
        model = get_model(model_name(), True)  # 仅显式构建命令允许下载模型。
        vectors = [normalize(vector) for vector in model.passage_embed(texts)]
        if len(vectors) != len(texts):
            raise ValueError
        return vectors
    except Exception:
        raise AppError("片段向量生成失败，旧向量索引未被替换。", code="embedding_failed") from None


def embed_query(query: str) -> list[float]:
    try:
        model = get_model(model_name(), False)
        return normalize(next(iter(model.query_embed(query))))
    except Exception:
        raise AppError("问题向量生成失败；请检查本地模型是否已通过build_vector_index.py准备完成。", code="embedding_failed") from None
