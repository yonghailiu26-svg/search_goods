"""真实本地Embedding对比与DeepSeek整链验收；API部分会产生费用。"""
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.embeddings import model_name
from app.knowledge import search_keyword
from app.knowledge_index import load_index
from app.main import app
from app.schemas import SearchKnowledgeArgs
from app.vector_index import load_vectors, minimum_score, search_semantic


def verify():
    corpus = load_index()
    vectors = load_vectors(corpus)
    cases = []
    # 两个正例换了措辞，一个复用探测例；只是学习验收，不是独立大规模评测。
    questions = [
        ("我说只买五块以内的，系统拿什么数去和数据库比较", "KB-PRICE-001"),
        ("每包里几根都没写，能按经验估一个吗", "KB-PACK-001"),
        ("只把厂商改掉，先前提过的粗细和钱数还算吗", "KB-FILTER-001"),
        ("坏掉后免费维修几年", None),
        ("周末会不会下雨", None),
    ]
    for query, expected in questions:
        started = perf_counter()
        args = SearchKnowledgeArgs(query=query)
        keyword = search_keyword(args, corpus)
        semantic = search_semantic(args, corpus)
        assert not keyword, "对比问句意外命中关键词，不能用它证明语义召回差异"
        if expected:
            assert semantic and semantic[0]["source_id"] == expected, "语义首条召回不符合该样例预期"
        else:
            assert not semantic, "无关问题不应强制返回最相似资料"
        cases.append({"query": query, "keyword": keyword, "semantic": semantic, "elapsed_seconds": round(perf_counter() - started, 3)})
        print(json.dumps({"query": query, "keyword_count": len(keyword), "semantic": [(row["chunk_id"], row["score"]) for row in semantic]}, ensure_ascii=False), flush=True)
    with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "semantic"}), TestClient(app) as client:
        assert client.get("/health").json()["step"] >= 10
        response = client.post("/chat", json={"message": "请只查本地规则：每包里几根都没写，能按经验估一个吗？注明规则来源。"})
        if response.status_code != 200:
            raise AppError(f"第十课整链请求失败（HTTP {response.status_code}），未输出原始响应。")
        agent = response.json()
        traces = [row for row in agent["tool_trace"] if row["tool"] == "search_knowledge"]
        assert traces and any(passage["retrieval"] == "semantic" for row in traces for passage in row["passages"])
        assert agent["sources"] and any(source["source_id"] == "KB-PACK-001" for source in agent["sources"])
        assert any(f"[{source['citation_id']}]" in agent["answer"] for source in agent["sources"])
        assert agent["current_requirements"] == {}
        agent.pop("session_id", None)
        response = client.post("/chat", json={"message": "请查询本地包装规则和SKU DEMO-PEN-0000的实际包装说明，结合两类依据判断能不能确认一盒12支，缺资料明确未知。"})
        if response.status_code != 200:
            raise AppError(f"语义检索与第九课协同验收失败（HTTP {response.status_code}），未输出原始响应。")
        mixed = response.json()
        assert mixed["answer_details"] and mixed["answer_details"]["unknowns"]
        refs = {ref for claim in mixed["answer_details"]["claims"] for ref in claim["evidence_ids"]}
        assert "SKU:DEMO-PEN-0000" in refs and any(ref.startswith("KB-PACK-001-") for ref in refs)
        assert any(passage["retrieval"] == "semantic" for row in mixed["tool_trace"] if row["tool"] == "search_knowledge" for passage in row["passages"])
        assert mixed["current_requirements"] == {}
        mixed.pop("session_id", None)
    output = Path(__file__).resolve().parent / "outputs" / "10-semantic-evaluation.json"
    output.write_text(json.dumps({"model": model_name(), "dimension": vectors.dimension, "min_score": minimum_score(), "cases": cases, "agent": agent, "mixed_agent": mixed}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"model_calls": agent["model_calls"], "usage": agent["usage"], "elapsed_seconds": agent["elapsed_seconds"]}, ensure_ascii=False))
    print(json.dumps({"case": "mixed", "model_calls": mixed["model_calls"], "usage": mixed["usage"], "elapsed_seconds": mixed["elapsed_seconds"]}, ensure_ascii=False))
    print("第十课真实验收通过，报告已保存至outputs/10-semantic-evaluation.json。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError as exc:
        print(f"第十课验收未通过：{exc}")
        sys.exit(1)
