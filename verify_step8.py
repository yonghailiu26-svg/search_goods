"""第八课真实验收：片段检索、引用、无证据与原商品流程；会产生API费用。"""
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

from app.config import AppError
from app.knowledge_index import load_index
from app.main import app


def verify():
    index = load_index()
    chunks = {chunk.chunk_id: chunk for chunk in index.chunks}
    cases = []
    questions = [
        ("引用盒支换算依据片段", "为什么不能把所有签字笔默认每盒12支？请查本地规则，引用具体片段。", "盒支换算依据"),
        ("引用缺少盒装数量的处理片段", "具体SKU没有提供盒装数量时，应如何答复？请查本地规则，引用相关片段。这次只解释规则，不查询商品。", "缺少盒装数量时怎么回答"),
        ("未收录保修政策", "请查本地规则：商品保修政策是多久？找不到就说无法确认。", None),
        ("商品查询回归", "找得力黑色0.5mm签字笔，单价不超过5元。", None),
    ]
    with TestClient(app) as client:
        assert client.get("/health").json()["step"] >= 8
        for name, question, expected_section in questions:
            response = client.post("/chat", json={"message": question})
            if response.status_code != 200:
                code = response.json().get("error_code", "unknown")
                raise AppError(f"第八课请求失败（HTTP {response.status_code}，{code}），未输出原始响应。")
            case = response.json()
            if expected_section:
                assert any(row["tool"] == "search_knowledge" for row in case["tool_trace"]), "未实际检索"
                assert any(source["section"] == expected_section and f"[{source['citation_id']}]" in case["answer"] for source in case["sources"]), "缺少预期片段引用"
                assert case["current_requirements"] == {}, "知识检索修改了商品条件"
                for source in case["sources"]:
                    actual = chunks[source["citation_id"]]
                    for key in ("source_id", "source", "section", "start_line", "end_line", "source_version"):
                        assert source[key] == getattr(actual, key), "来源元信息不一致"
            elif name == "未收录保修政策":
                assert case["outcome"] == "no_knowledge" and not case["sources"]
            else:
                assert [row["tool"] for row in case["tool_trace"]] == ["search_products"]
                assert case["tool_trace"][0]["products"] and not case["sources"]
                assert case["current_requirements"]["max_price_fen"] == 500
            case.pop("session_id", None)
            cases.append({"name": name, **case})
            print(json.dumps({"name": name, "tools": [row["tool"] for row in case["tool_trace"]],
                              "citations": [source["citation_id"] for source in case["sources"]],
                              "outcome": case["outcome"], "model_calls": case["model_calls"],
                              "usage": case["usage"], "elapsed_seconds": case["elapsed_seconds"]}, ensure_ascii=False))
    output = Path(__file__).resolve().parent / "outputs" / "08-chunks-evaluation.json"
    output.write_text(json.dumps({"source_count": len(index.sources), "chunk_count": len(index.chunks), "cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("第八课真实验收通过，报告已保存至outputs/08-chunks-evaluation.json。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError as exc:
        print(f"第八课验收未通过：{exc}")
        sys.exit(1)
