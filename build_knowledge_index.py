"""第八课：显式准备知识索引，不调用模型或数据库。"""
import argparse
import sys

from app.config import AppError
from app.knowledge_index import DEFAULT_MAX_CHARS, build_index, write_index

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="按小标题、段落与句子构建本地规则片段索引")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    arguments = parser.parse_args()
    try:
        index = build_index(max_chars=arguments.max_chars)
        write_index(index)
        print(f"已整理{len(index.sources)}份规则为{len(index.chunks)}个片段，保存至outputs/knowledge-index.json。")
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
