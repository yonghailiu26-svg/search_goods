"""第十一课：按配置选择检索策略，对Agent继续返回passages。"""
import os

from app.config import AppError, integer
from app.knowledge_index import INDEX_PATH, KNOWLEDGE_DIR, PROJECT_ROOT, load_index
from app.schemas import SearchKnowledgeArgs

KNOWLEDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": "检索本项目练习规则：包装/盒支换算、价格单位与预算、多轮筛选条件。规则问题应先检索再回答并引用来源。没有相关资料时返回no_knowledge，不查询商品或修改需求。",
        "parameters": SearchKnowledgeArgs.model_json_schema(),
    },
}


def search_knowledge(args: SearchKnowledgeArgs) -> list[dict]:
    index = load_index(KNOWLEDGE_DIR, INDEX_PATH)
    strategy = os.getenv("KNOWLEDGE_RETRIEVAL", "rerank")
    if strategy in {"hybrid", "rerank"}:
        from app.hybrid_search import fuse_rankings
        from app.vector_index import search_semantic
        candidate_limit = integer("KNOWLEDGE_CANDIDATE_LIMIT", 10, 3, 50)
        keyword = search_keyword(args, index, candidate_limit=candidate_limit)
        semantic = search_semantic(args, index, candidate_limit=candidate_limit)
        fused = fuse_rankings(keyword, semantic, limit=args.limit if strategy == "hybrid" else candidate_limit)
        if strategy == "rerank":
            from app.reranking import rerank_passages
            return rerank_passages(args.query, fused, limit=args.limit)
        return fused
    if strategy == "semantic":
        from app.vector_index import search_semantic
        return search_semantic(args, index)
    if strategy != "keyword":
        raise AppError("KNOWLEDGE_RETRIEVAL只能为rerank、hybrid、semantic或keyword。", code="knowledge_unavailable")
    return search_keyword(args, index)


def search_keyword(args: SearchKnowledgeArgs, index, *, candidate_limit: int | None = None) -> list[dict]:
    query = args.query.casefold()
    passages = []
    for chunk in index.chunks:
        matched = sorted({word for word in chunk.keywords if word.casefold() in query})
        if matched:
            passage = chunk.model_dump(exclude={"keywords"})
            passage.update({"score": len(matched), "matched_keywords": matched})
            passages.append(passage)
    passages.sort(key=lambda passage: (-passage["score"], passage["chunk_id"]))
    size = args.limit if candidate_limit is None else candidate_limit
    return passages[:size]  # 不返回零命中资料；score不是事实置信度。
