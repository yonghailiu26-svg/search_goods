"""显式准备本地模型与片段向量；首次下载公开模型，不请求DeepSeek或MySQL。"""
import sys

from app.config import AppError
from app.knowledge_index import load_index
from app.vector_index import build_vectors, write_vectors

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        index = build_vectors(load_index())
        write_vectors(index)
        print(f"已生成{len(index.vectors)}个{index.dimension}维片段向量，保存至outputs/knowledge-vectors.json。")
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
