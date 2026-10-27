"""第六步：真实模型自主选工具，实际查MySQL；会产生API费用。"""
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app


def ask(client, question, session_id=None):
    body = {"message": question}
    if session_id is not None:
        body["session_id"] = session_id
    response = client.post("/chat", json=body)
    if response.status_code != 200:
        raise AppError(f"第六步请求失败（HTTP {response.status_code}），未输出原始响应。")
    return response.json()


def verify():
    cases = []
    with TestClient(app) as client:
        chain = ask(client, "先找最便宜的得力黑色0.5mm签字笔，单价不超过5元，再查询它的详细说明、包装信息和使用说明。")
        names = [row["tool"] for row in chain["tool_trace"]]
        assert names == ["search_products", "get_product_detail"], "未按需求先搜索再查详情"
        sku = chain["tool_trace"][0]["products"][0]["sku"]
        assert chain["tool_trace"][1]["arguments"]["sku"] == sku
        product = chain["tool_trace"][1]["product"]
        assert product["sku"] == "DEMO-PEN-0000" and product["package_notes"] and product["description"]
        assert chain["current_requirements"]["max_price_fen"] == 500
        cases.append({"name": "先搜索后详情", **chain})

        current = chain["current_requirements"]
        direct = ask(client, "只查看SKU DEMO-PEN-1000的说明和包装信息，不修改刚才的筛选条件。", chain["session_id"])
        assert [row["tool"] for row in direct["tool_trace"]] == ["get_product_detail"]
        assert direct["tool_trace"][0]["product"]["sku"] == "DEMO-PEN-1000"
        assert direct["current_requirements"] == current, "查看另一商品详情修改了原搜索需求"
        cases.append({"name": "明确SKU直查且保留需求", **direct})

        missing = ask(client, "查询SKU DEMO-NOT-EXIST-999的详细说明；不存在就明确告诉我，不要搜索其他商品。")
        assert [row["tool"] for row in missing["tool_trace"]] == ["get_product_detail"]
        assert missing["outcome"] == "not_found" and missing["tool_trace"][0]["product"] is None
        cases.append({"name": "不存在的SKU", **missing})

        sparse = ask(client, "只查询SKU DEMO-PEN-0001的详细说明和包装信息，没有提供就说明未知。")
        assert [row["tool"] for row in sparse["tool_trace"]] == ["get_product_detail"]
        assert sparse["outcome"] == "answered"
        assert sparse["tool_trace"][0]["product"]["description"] is None
        cases.append({"name": "商品存在但缺少说明", **sparse})
    output = Path(__file__).resolve().parent / "outputs" / "06-tool-selection-evaluation.json"
    output.parent.mkdir(exist_ok=True)
    # ID仅用于本次真实会话，不需要出现在交付报告里。
    for case in cases:
        case.pop("session_id", None)
    output.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in cases:
        print(json.dumps({"name": case["name"], "tools": [row["tool"] for row in case["tool_trace"]],
                          "outcome": case["outcome"], "model_calls": case["model_calls"],
                          "usage": case["usage"], "elapsed_seconds": case["elapsed_seconds"]}, ensure_ascii=False))
    print("第六步真实验收通过，报告已保存至outputs/06-tool-selection-evaluation.json。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError as exc:
        print(f"第六步验收未通过：{exc}")
        sys.exit(1)
