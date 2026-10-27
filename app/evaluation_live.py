"""第十四课可选真实API冒烟检查；不把结构检查当作自动语义事实核验。"""
from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app


def run_live_checks() -> list[dict]:
    results = []
    with TestClient(app) as client:
        def ask(path, body):
            response = client.post(path, json=body)
            if response.status_code != 200:
                raise AppError(f"真实冒烟请求失败（HTTP {response.status_code}，{response.json().get('error_code', 'unknown')}）。", code="evaluation_failed")
            return response.json()
        first = ask("/chat", {"message": "找得力黑色0.5mm签字笔，单价不超过5元。"})
        assert [r["tool"] for r in first["tool_trace"]] == ["search_products"]
        assert first["tool_trace"][0]["products"]
        assert first["current_requirements"]["brand"] == "得力" and first["current_requirements"]["max_price_fen"] == 500
        second = ask("/chat", {"message": "换晨光，其他不变。", "session_id": first["session_id"]})
        assert second["current_requirements"]["brand"] == "晨光"
        for field in ("color", "spec", "max_price_fen"):
            assert second["current_requirements"][field] == first["current_requirements"][field]
        workflow = ask("/workflows/package-check", {"sku": "DEMO-PEN-0000"})
        assert workflow["model_calls"] == 1 and workflow["answer_details"]["unknowns"]
        assert [r["tool"] for r in workflow["tool_trace"]] == ["search_knowledge", "get_product_detail"]
        missing = ask("/workflows/package-check", {"sku": "DEMO-NOT-EXIST-999"})
        assert missing["model_calls"] == 0 and missing["outcome"] == "not_found"
        for name, result in (("商品查询", first), ("同会话保留条件", second), ("固定工作流", workflow), ("无商品提前结束", missing)):
            result.pop("session_id", None)
            results.append({"name": name, "passed": True, **result})
        response = client.post("/workflows/package-check", json={"sku": "../../invalid"})
        assert response.status_code == 422
        results.append({"name": "非法SKU入口拒绝", "passed": True, "status_code": 422})
    return results
