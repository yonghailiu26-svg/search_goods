"""第三步真实验收：会访问本地 MySQL 和 DeepSeek，产生实际 API 费用。"""
import json
import sys

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app


def ask(client, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    response = client.post("/chat", json=body)
    if response.status_code != 200:
        raise AppError(f"验收请求失败，HTTP {response.status_code}；未输出原始响应。")
    result = response.json()
    if not result["tool_trace"]:
        raise AppError("模型没有执行商品工具，未通过真实验收。")
    for call in result["tool_trace"]:
        filters = call["arguments"]
        for product in call["products"]:
            for name in ("category", "brand", "color", "spec"):
                assert name not in filters or product[name] == filters[name], "商品不符合过滤条件"
            assert "max_price_fen" not in filters or product["price_fen"] <= filters["max_price_fen"], "商品超出预算"
    print(json.dumps({
        "question": message, "current_requirements": result["current_requirements"],
        "changes": result["tool_trace"][0]["changes"],
        "returned_count": result["tool_trace"][-1]["returned_count"],
        "answer": result["answer"], "usage": result["usage"],
        "model_calls": result["model_calls"], "elapsed_seconds": result["elapsed_seconds"],
    }, ensure_ascii=False))
    return result


def verify():
    with TestClient(app) as client:
        first = ask(client, "找黑色0.5mm签字笔，单价不超过5元。请查询商品。")
        session_id = first["session_id"]
        second = ask(client, "换得力，其他不变", session_id)
        for name in ("category", "color", "spec", "max_price_fen", "limit"):
            assert second["current_requirements"][name] == first["current_requirements"][name], "未修改条件丢失"
        assert second["current_requirements"]["brand"] == "得力"
        assert second["tool_trace"][0]["changes"] == {"brand": "得力"}, "本轮应仅修改品牌"
        assert second["tool_trace"][-1]["products"], "应找到符合条件的得力商品"

        independent = ask(client, "找晨光蓝色0.7mm签字笔，单价不超过4元。")
        assert independent["session_id"] != session_id
        assert independent["current_requirements"]["brand"] == "晨光"

        third = ask(client, "不限价格了，其他不变", session_id)
        assert "max_price_fen" not in third["current_requirements"]
        assert third["current_requirements"]["brand"] == "得力"
        assert third["current_requirements"]["color"] == "黑色"
        assert third["current_requirements"]["spec"] == "0.5mm"

        fourth = ask(client, "改找橡皮，旧的品牌、颜色和笔尖规格不保留。", session_id)
        assert fourth["current_requirements"]["category"] == "橡皮"
        for name in ("brand", "color", "spec", "keyword", "max_price_fen"):
            assert name not in fourth["current_requirements"], "旧品类条件没有清除"
        assert fourth["tool_trace"][-1]["products"], "应找到橡皮练习商品"
        print("第三步真实验收通过：保留条件、只改品牌、独立会话、取消预算、切换品类。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
    except AssertionError as exc:
        print(f"第三步验收未通过：{exc}")
        sys.exit(1)
