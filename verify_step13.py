"""固定工作流及Agent比较；真实DeepSeek和MySQL，API会计费。"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app


def verify():
    cases = []
    with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "rerank"}), TestClient(app) as client:
        for sku in ("DEMO-PEN-0000", "DEMO-PEN-0001", "DEMO-NOT-EXIST-999"):
            response = client.post("/workflows/package-check", json={"sku": sku})
            if response.status_code != 200:
                raise AppError(f"工作流验收失败（HTTP {response.status_code}，{response.json().get('error_code', 'unknown')}）。")
            result = response.json()
            assert [row["tool"] for row in result["tool_trace"]] == ["search_knowledge", "get_product_detail"]
            assert result["execution_mode"] == "workflow" and result["current_requirements"] == {}
            if sku == "DEMO-NOT-EXIST-999":
                assert result["model_calls"] == 0 and result["usage"]["total_tokens"] == 0 and result["outcome"] == "not_found"
            else:
                assert result["model_calls"] == 1 and result["answer_details"]["unknowns"]
                refs = {ref for claim in result["answer_details"]["claims"] for ref in claim["evidence_ids"]}
                assert "SKU:" + sku in refs and any(ref.startswith("KB-PACK-001-") for ref in refs)
            cases.append({"name": sku, **result})
            print(json.dumps({"sku": sku, "mode": result["execution_mode"], "model_calls": result["model_calls"], "usage": result["usage"], "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False), flush=True)
        response = client.post("/chat", json={"message": "请查本地包装规则和SKU DEMO-PEN-0000详情，判断一盒多少支，缺资料就明确未知。"})
        if response.status_code != 200:
            raise AppError(f"Agent对比验收失败（HTTP {response.status_code}）。")
        agent = response.json()
        assert agent["execution_mode"] == "agent" and agent["model_calls"] >= 2
        assert {row["tool"] for row in agent["tool_trace"]} == {"search_knowledge", "get_product_detail"}
        assert agent["answer_details"] and agent["answer_details"]["unknowns"]
        agent.pop("session_id", None)
        cases.append({"name": "Agent同目标比较", **agent})
        print(json.dumps({"mode": "agent", "model_calls": agent["model_calls"], "usage": agent["usage"], "elapsed_seconds": agent["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    output = Path(__file__).resolve().parent / "outputs" / "13-workflow-evaluation.json"
    output.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("第十三课真实验收通过。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except (AppError, AssertionError) as exc:
        print(f"第十三课验收停止：{exc}")
        sys.exit(1)
