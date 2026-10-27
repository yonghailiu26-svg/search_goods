"""第十一课：仅按两路名次融合，不重新编码、不调用模型或数据库。"""
RRF_K = 60


def fuse_rankings(keyword: list[dict], semantic: list[dict], *, limit: int) -> list[dict]:
    merged = {}
    for retriever, passages in (("keyword", keyword), ("semantic", semantic)):
        seen = set()
        rank = 0
        for passage in passages:
            chunk_id = passage["chunk_id"]
            if chunk_id in seen:
                continue  # 同一路重复片段不能重复加分。
            seen.add(chunk_id)
            rank += 1
            if chunk_id not in merged:
                # 保留正文和来源；各路原始分数移到明细，避免混淆量纲。
                merged[chunk_id] = {key: value for key, value in passage.items()
                                    if key not in {"score", "score_kind", "retrieval", "matched_keywords"}}
                merged[chunk_id].update(score=0.0, score_kind="rrf", retrieval="hybrid", retrieval_details=[])
            record = merged[chunk_id]
            record["score"] += 1.0 / (RRF_K + rank)
            detail = {"retriever": retriever, "rank": rank, "raw_score": passage["score"],
                      "raw_score_kind": "keyword_hits" if retriever == "keyword" else "cosine"}
            if retriever == "keyword":
                detail["matched_keywords"] = passage.get("matched_keywords", [])
            record["retrieval_details"].append(detail)
    ranked = sorted(merged.values(), key=lambda record: (-record["score"], record["chunk_id"]))
    for record in ranked:
        record["score"] = round(record["score"], 8)
    return ranked[:limit]
