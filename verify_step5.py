"""第五步小评测：两组真实接口样例，以及首步注入错误后的真实模型修正。"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.llm import complete as real_complete
from app.main import app


def run_case(client, question, name):
    response = client.post("/chat", json={"message": question})
    if response.status_code != 200:
        raise AppError(f"评测{name}失败（HTTP {response.status_code}），未输出原始响应。")
    result = response.json()
    assert result["tool_trace"], "没有实际执行商品工具"
    products = result["tool_trace"][-1].get("products", [])
    for product in products:
        filters = result["current_requirements"]
        for field in ("category", "brand", "color", "spec"):
            assert field not in filters or product[field] == filters[field], "商品未匹配条件"
        assert "max_price_fen" not in filters or product["price_fen"] <= filters["max_price_fen"], "商品超出预算"
    return {"name": name, "question": question, **{field: result[field] for field in (
        "outcome", "recovered", "answer", "current_requirements", "usage", "usage_complete",
        "model_calls", "model_trace", "tool_trace", "elapsed_seconds",
    )}}


def verify():
    report = {"created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "cases": []}
    with patch.dict("os.environ", {"AGENT_MAX_MODEL_CALLS": "3", "AGENT_MAX_TOOL_CALLS": "3"}), TestClient(app) as client:
        normal = run_case(client, "找得力黑色0.5mm签字笔，单价不超过5元。", "真实查询")
        normal["mode"] = "real_api_and_mysql"
        assert normal["outcome"] == "answered" and normal["tool_trace"][-1]["products"]
        assert normal["current_requirements"]["brand"] == "得力"
        assert normal["current_requirements"]["max_price_fen"] == 500
        report["cases"].append(normal)

        empty = run_case(client, "查询得力黑色0.5mm签字笔，单价不超过0.01元。", "真实无商品")
        empty["mode"] = "real_api_and_mysql"
        assert empty["outcome"] == "no_results" and not empty["tool_trace"][-1]["products"]
        assert empty["current_requirements"]["max_price_fen"] == 1
        report["cases"].append(empty)

        actual_requests = 0
        injected = False

        def inject_first(client, key, payload):
            nonlocal injected, actual_requests
            if not injected:
                injected = True
                return {
                    "content": None, "tool_calls": [{
                        "id": "call_evaluation_invalid_limit", "type": "function",
                        "function": {"name": "search_products", "arguments": json.dumps({
                            "category": "签字笔", "brand": "得力", "color": "黑色",
                            "spec": "0.5mm", "max_price_fen": 500, "limit": 99,
                        }, ensure_ascii=False)},
                    }],
                }, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            actual_requests += 1
            return real_complete(client, key, payload)

        with patch("app.agent.complete", side_effect=inject_first):
            repaired = run_case(client, "找得力黑色0.5mm签字笔，单价不超过5元。", "注入非法limit后修正")
        repaired["mode"] = "injected_first_message_then_real_api_and_mysql"
        repaired["real_model_requests"] = actual_requests
        repaired["model_trace"][0]["mode"] = "injected_zero_usage"
        assert repaired["recovered"] and repaired["outcome"] == "answered"
        assert repaired["tool_trace"][0]["status"] == "invalid_arguments"
        assert repaired["tool_trace"][-1]["products"]
        assert repaired["current_requirements"]["brand"] == "得力" and repaired["current_requirements"]["max_price_fen"] == 500
        report["cases"].append(repaired)
    report["notes"] = [
        "超时、未知工具、持续调用及输出截断通过离线故障注入测试，不伪装成线上事故。",
        "修正案例首条模型消息人为注入，usage为0；其后的修正与总结是真实API请求。",
        "记录是本次样例验收，不是统计意义的通用准确率。",
    ]
    output = Path(__file__).resolve().parent / "outputs" / "05-agent-evaluation.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in report["cases"]:
        print(json.dumps({"name": case["name"], "mode": case["mode"], "outcome": case["outcome"],
                          "recovered": case["recovered"], "model_calls": case["model_calls"],
                          "usage": case["usage"], "elapsed_seconds": case["elapsed_seconds"]}, ensure_ascii=False))
    print("第五步评测通过，报告已保存至 outputs/05-agent-evaluation.json。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError:
        print("第五步评测断言未通过，请核对本轮条件、结果状态和工具轨迹。")
        sys.exit(1)
