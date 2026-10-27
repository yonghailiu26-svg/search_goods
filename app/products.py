"""商品工具层：暴露给 Agent 的能力；SQL 实现在 storage.py。"""
from app.schemas import GetProductDetailArgs, SearchProductsArgs
from app.storage import find_product_detail, find_products

TOOL = {
    "type": "function",
    "function": {
        "name": "search_products",
        "description": "按当前需求查询MySQL练习商品。参数只传本轮明确修改项，未修改项由Python保留；取消条件传null。",
        "parameters": SearchProductsArgs.model_json_schema(),
    },
}

DETAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "get_product_detail",
        "description": "按明确SKU查询单个商品详情，包括说明、包装信息和使用说明。不会修改搜索条件；未知SKU返回not_found。",
        "parameters": GetProductDetailArgs.model_json_schema(),
    },
}
TOOLS = [TOOL, DETAIL_TOOL]


def search_products(args: SearchProductsArgs) -> list[dict]:
    return find_products(args)


def get_product_detail(args: GetProductDetailArgs) -> dict | None:
    return find_product_detail(args.sku)
