"""真实验收：实际 MySQL + 官方模型。会产生 API 费用，不在单元测试中自动执行。"""
import json
import sys

from fastapi.testclient import TestClient

from app.main import app
from app.products import SearchProductsArgs, search_products


def verify():
    args = SearchProductsArgs(brand="得力", category="签字笔", color="黑色", spec="0.5mm", max_price_fen=500)
    products = search_products(args)
    assert products, "练习数据中应有符合条件的商品"
    assert all(p["brand"] == "得力" and p["price_fen"] <= 500 for p in products)
    assert search_products(SearchProductsArgs(brand="' OR 1=1 --")) == []
    print("真实 SQL：条件查询及注入字符串检查通过。")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.post("/chat", json={"message": " "}).status_code == 422
        for question, expect_products in (
            ("找得力黑色0.5mm签字笔，单价不超过5元。请查询并解释候选。", True),
            ("查询得力黑色0.5mm签字笔，单价不超过0.01元。", False),
        ):
            response = client.post("/chat", json={"message": question})
            assert response.status_code == 200, response.json().get("detail", "接口失败")
            result = response.json()
            trace = result["tool_trace"]
            assert trace, "应真实调用查询工具"
            for call in trace:
                filters = call["arguments"]
                assert filters.get("brand") == "得力" and filters.get("color") == "黑色"
                assert filters.get("spec") == "0.5mm"
                assert filters.get("max_price_fen") == (500 if expect_products else 1)
                assert bool(call["products"]) == expect_products
                for product in call["products"]:
                    assert product["brand"] == "得力" and product["color"] == "黑色" and product["spec"] == "0.5mm"
                    assert product["price_fen"] <= filters["max_price_fen"]
            print(json.dumps({"question": question, **result}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except Exception:
        print("真实验收失败（未输出原始异常）；请分别检查本地配置、初始化结果及模型筛选参数。")
        sys.exit(1)
