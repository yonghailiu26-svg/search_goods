"""第十一课：真实本地三种策略对比，及DeepSeek/MySQL整链验收；API部分会计费。"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError, integer
from app.knowledge import search_keyword, search_knowledge
from app.knowledge_index import load_index
from app.main import app
from app.schemas import SearchKnowledgeArgs
from app.vector_index import minimum_score, search_semantic


def verify():
    corpus = load_index()
    candidates = integer("KNOWLEDGE_CANDIDATE_LIMIT", 10, 3, 50)
    cases, agents = [], []
    questions = [
        ("关键词补回短语", "其他不变", "KB-FILTER-001", "keyword"),
        ("向量补回改写", "每包里几根都没写，能按经验估一个吗", "KB-PACK-001", "semantic"),
        ("两路共同命中", "换品牌", "KB-FILTER-001", "both"),
        ("两路排序不同", "其他不变 预算和规格应保留", "KB-FILTER-001", "both"),
        ("库外问题", "坏掉后免费维修几年", None, "neither"),
    ]
    with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "hybrid"}):
        for name, query, expected, expected_route in questions:
            args = SearchKnowledgeArgs(query=query)
            keyword = search_keyword(args, corpus, candidate_limit=candidates)
            semantic = search_semantic(args, corpus, candidate_limit=candidates)
            hybrid = search_knowledge(args)
            if expected_route == "keyword":
                assert keyword and not semantic
            elif expected_route == "semantic":
                assert semantic and not keyword
            elif expected_route == "both":
                assert keyword and semantic
            else:
                assert not keyword and not semantic and not hybrid
            if expected:
                assert hybrid and hybrid[0]["source_id"] == expected
            ids = {p["chunk_id"] for p in keyword + semantic}
            assert len({p["chunk_id"] for p in hybrid}) == len(hybrid)
            for passage in hybrid:
                assert passage["chunk_id"] in ids and passage["score_kind"] == "rrf" and passage["retrieval"] == "hybrid"
                original = next(c for c in corpus.chunks if c.chunk_id == passage["chunk_id"])
                assert passage["content"] == original.content and passage["source_version"] == original.source_version
            cases.append({"name": name, "query": query, "keyword": keyword, "semantic": semantic, "hybrid": hybrid})
            print(json.dumps({"name": name, "keyword_ids": [p["chunk_id"] for p in keyword], "semantic_ids": [p["chunk_id"] for p in semantic],
                              "hybrid": [(p["chunk_id"], p["score"]) for p in hybrid]}, ensure_ascii=False), flush=True)
        with TestClient(app) as client:
            assert client.get("/health").json()["step"] >= 11
            questions = [
                ("规则回答", "请只查本地规则：用户说换品牌、其他不变时，为什么应保留规格和预算？解释并注明来源，不查询商品。"),
                ("规则与商品协同", "请查询本地包装规则和SKU DEMO-PEN-0000实际包装说明，按两类依据判断能不能确认一盒12支。缺资料就明确未知。"),
                ("未收录保修规则", "请只检索本地保修规则：商品坏了能免费修几年？没有相关资料就明确未知，不查询商品。"),
            ]
            for name, question in questions:
                response = client.post("/chat", json={"message": question})
                if response.status_code != 200:
                    raise AppError(f"第十一课请求失败（HTTP {response.status_code}，{response.json().get('error_code', 'unknown')}），未输出原始响应。")
                agent = response.json()
                traces = [row for row in agent["tool_trace"] if row["tool"] == "search_knowledge"]
                assert traces, "未实际调用规则检索"
                assert agent["current_requirements"] == {}
                if name == "未收录保修规则":
                    assert agent["outcome"] == "no_knowledge" and not agent["sources"]
                else:
                    assert any(p["retrieval"] == "hybrid" for row in traces for p in row["passages"])
                    assert any(f"[{s['citation_id']}]" in agent["answer"] for s in agent["sources"])
                    if name == "规则回答":
                        assert any(s["source_id"] == "KB-FILTER-001" for s in agent["sources"])
                    else:
                        assert agent["answer_details"] and agent["answer_details"]["unknowns"]
                        refs = {ref for claim in agent["answer_details"]["claims"] for ref in claim["evidence_ids"]}
                        assert "SKU:DEMO-PEN-0000" in refs and any(ref.startswith("KB-PACK-001-") for ref in refs)
                agent.pop("session_id", None)
                agents.append({"name": name, **agent})
                print(json.dumps({"name": name, "tools": [row["tool"] for row in agent["tool_trace"]], "outcome": agent["outcome"],
                                  "model_calls": agent["model_calls"], "usage": agent["usage"], "elapsed_seconds": agent["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    output = Path(__file__).resolve().parent / "outputs" / "11-hybrid-evaluation.json"
    output.write_text(json.dumps({"candidate_limit": candidates, "semantic_min_score": minimum_score(), "rrf_k": 60, "cases": cases, "agents": agents}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("第十一课真实验收通过，报告已保存至outputs/11-hybrid-evaluation.json。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError as exc:
        print(f"第十一课验收未通过：{exc}")
        sys.exit(1)
