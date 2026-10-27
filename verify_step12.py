"""真实本地重排对比及DeepSeek/MySQL验收；API部分计费。"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.knowledge import search_knowledge
from app.main import app
from app.reranking import reranker_name
from app.schemas import SearchKnowledgeArgs


def verify():
    cases, agents = [], []
    questions = [
        ("只改品牌，其他不变时，预算和规格要保留吗", "KB-FILTER-001"),
        ("具体SKU未提供盒装数量，应该怎样回答", "KB-PACK-001"),
        ("用户说五元，怎样和price_fen比较", "KB-PRICE-001"),
        ("坏掉后免费维修几年", None),
    ]
    for query, expected in questions:
        args = SearchKnowledgeArgs(query=query)
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "hybrid"}):
            before = search_knowledge(args)
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "rerank"}):
            after = search_knowledge(args)
        if expected:
            assert after and after[0]["source_id"] == expected
            assert all(p["retrieval"] == "rerank" and p["score_kind"] == "cross_encoder" for p in after)
        else:
            assert not before and not after
        cases.append({"query": query, "hybrid": before, "rerank": after})
        print(json.dumps({"query": query, "after": [(p["chunk_id"], p["score"]) for p in after]}, ensure_ascii=False), flush=True)
    with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "rerank"}), TestClient(app) as client:
        for name, question in [
            ("规则重排回答", "请查本地规则：只改品牌、其他不变时，预算和规格要保留吗？请引用来源，不查询商品。"),
            ("重排与商品证据协同", "请查本地包装规则和SKU DEMO-PEN-0000实际包装说明，判断能否确认一盒12支，缺资料明确未知。"),
        ]:
            response = client.post("/chat", json={"message": question})
            if response.status_code != 200:
                raise AppError(f"第十二课请求失败（HTTP {response.status_code}，{response.json().get('error_code', 'unknown')}）。")
            result = response.json()
            assert any(p["retrieval"] == "rerank" for t in result["tool_trace"] if t["tool"] == "search_knowledge" for p in t["passages"])
            assert any(f"[{s['citation_id']}]" in result["answer"] for s in result["sources"])
            assert result["current_requirements"] == {}
            if name == "重排与商品证据协同":
                assert result["answer_details"] and result["answer_details"]["unknowns"]
            result.pop("session_id", None)
            agents.append({"name": name, **result})
            print(json.dumps({"name": name, "model_calls": result["model_calls"], "usage": result["usage"], "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    output = Path(__file__).resolve().parent / "outputs" / "12-rerank-evaluation.json"
    output.write_text(json.dumps({"model": reranker_name(), "cases": cases, "agents": agents}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("第十二课真实验收通过。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except (AppError, AssertionError) as exc:
        print(f"第十二课验收停止：{exc}")
        sys.exit(1)
