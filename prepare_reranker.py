"""显式下载并检查本地重排模型；不调用DeepSeek或MySQL。"""
import sys

from app.config import AppError
from app.reranking import get_reranker, reranker_name

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        model = get_reranker(reranker_name(), True)
        scores = list(model.rerank("如何确定盒装数量？", ["应核对具体SKU的包装说明。"], batch_size=1))
        if len(scores) != 1:
            raise AppError("重排模型检查没有返回分数。", code="rerank_failed")
        print("本地重排模型已准备完成，在线只读取本地缓存。")
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
