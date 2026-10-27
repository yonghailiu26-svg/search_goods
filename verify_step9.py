"""第九课真实验收：规则与商品协同、缺失说明、缺失规则；会产生API费用。"""
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app


def verify():
    cases = []
    questions = [
        ("规则与商品详情共同判断", "请先查本地包装换算规则，再查SKU DEMO-PEN-0000的包装说明，按两类资料判断能否确认一盒12支。缺资料明确未知，两条简短结论即可。", "DEMO-PEN-0000"),
        ("商品没有包装说明", "请根据本地包装规则及商品详情判断SKU DEMO-PEN-0001一盒多少支；两类都查，缺少说明就明确未知，简短回答。", "DEMO-PEN-0001"),
        ("商品存在但保修规则未收录", "请查本地保修规则和SKU DEMO-PEN-0000详情，说明能不能确认它保修多久。查不到规则就明确未知，不要猜。", "DEMO-PEN-0000"),
    ]
    with TestClient(app) as client:
        assert client.get("/health").json()["step"] >= 9
        for name, question, sku in questions:
            response = client.post("/chat", json={"message": question})
            if response.status_code != 200:
                raise AppError(f"第九课请求失败（HTTP {response.status_code}，{response.json().get('error_code', 'unknown')}），未输出原始响应。")
            case = response.json()
            assert {row["tool"] for row in case["tool_trace"]} == {"search_knowledge", "get_product_detail"}, "工具组合不符合预期"
            assert case["current_requirements"] == {}, "查询规则和详情改变了筛选条件"
            details = case["answer_details"]
            assert details and details["unknowns"], "未明确列出无法确认的内容"
            refs = {ref for claim in details["claims"] for ref in claim["evidence_ids"]}
            assert f"SKU:{sku}" in refs, "遗漏商品事实依据"
            rule_ids = {source["citation_id"] for source in case["sources"]}
            assert refs <= rule_ids | {f"SKU:{sku}"}, "出现未取得的依据"
            if name == "商品存在但保修规则未收录":
                assert not rule_ids and any(row["status"] == "no_knowledge" for row in case["tool_trace"])
            else:
                assert refs & rule_ids, "遗漏规则依据"
            if name == "商品没有包装说明":
                assert any("未提供包装说明" in text for text in details["unknowns"])
            case.pop("session_id", None)
            cases.append({"name": name, **case})
            print(json.dumps({"name": name, "tools": [row["tool"] for row in case["tool_trace"]], "evidence_ids": sorted(refs),
                              "claims": len(details["claims"]), "unknowns": len(details["unknowns"]), "model_calls": case["model_calls"],
                              "usage": case["usage"], "elapsed_seconds": case["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    output = Path(__file__).resolve().parent / "outputs" / "09-evidence-evaluation.json"
    output.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("第九课真实验收通过，报告已保存至outputs/09-evidence-evaluation.json。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError as exc:
        print(f"第九课验收未通过：{exc}")
        sys.exit(1)
