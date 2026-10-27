"""第七课真实验收：DeepSeek自主调用规则工具，包含原商品工具回归；调用会计费。"""
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app


def ask(client, question, session_id=None):
    body = {"message": question}
    if session_id:
        body["session_id"] = session_id
    response = client.post("/chat", json=body)
    if response.status_code != 200:
        raise AppError(f"第七课请求失败（HTTP {response.status_code}），未输出原始响应。")
    return response.json()


def verify():
    cases = []
    with TestClient(app) as client:
        package = ask(client, "为什么不能把所有签字笔默认一盒12支？请查本地规则并注明来源。")
        assert any(row["tool"] == "search_knowledge" for row in package["tool_trace"]), "包装问题未检索规则"
        assert any(source["source_id"] == "KB-PACK-001" for source in package["sources"])
        assert any(f"[{source.get('citation_id', source['source_id'])}]" in package["answer"] for source in package["sources"] if source["source_id"] == "KB-PACK-001")
        assert package["current_requirements"] == {}, "规则检索修改了搜索条件"
        cases.append({"name": "查包装规则并引用", **package})

        missing = ask(client, "请检索本地练习规则：商品保修政策是多久？找不到就说明未知，不要根据常识补充。")
        assert any(row["tool"] == "search_knowledge" for row in missing["tool_trace"]), "缺失规则问题未检索"
        assert missing["outcome"] == "no_knowledge" and missing["sources"] == []
        cases.append({"name": "库中没有保修规则", **missing})

        products = ask(client, "找得力黑色0.5mm签字笔，单价不超过5元。")
        assert [row["tool"] for row in products["tool_trace"]] == ["search_products"], "普通商品查询不应强制查规则"
        assert products["tool_trace"][0]["products"]
        assert products["current_requirements"]["brand"] == "得力"
        assert products["current_requirements"]["max_price_fen"] == 500
        cases.append({"name": "原商品工具回归", **products})

        follow = ask(client, "请查本地规则解释：我只换品牌并说其他不变时，为什么预算和规格应保留？这次只解释，不修改现有条件。", products["session_id"])
        assert any(row["tool"] == "search_knowledge" for row in follow["tool_trace"])
        assert any(source["source_id"] == "KB-FILTER-001" for source in follow["sources"])
        assert any(f"[{source.get('citation_id', source['source_id'])}]" in follow["answer"] for source in follow["sources"] if source["source_id"] == "KB-FILTER-001")
        assert follow["current_requirements"] == products["current_requirements"], "解释规则改变了商品条件"
        cases.append({"name": "同会话查规则保留需求", **follow})
    for case in cases:
        case.pop("session_id", None)
    output = Path(__file__).resolve().parent / "outputs" / "07-minimal-rag-evaluation.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in cases:
        print(json.dumps({"name": case["name"], "tools": [row["tool"] for row in case["tool_trace"]],
                          "sources": [source["source_id"] for source in case["sources"]],
                          "outcome": case["outcome"], "model_calls": case["model_calls"],
                          "usage": case["usage"], "elapsed_seconds": case["elapsed_seconds"]}, ensure_ascii=False))
    print("第七课真实验收通过，报告已保存至outputs/07-minimal-rag-evaluation.json。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError as exc:
        print(f"第七课验收未通过：{exc}")
        sys.exit(1)
