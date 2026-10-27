"""工具执行：校验可恢复错误，合法参数合并后才能查库。"""
from time import perf_counter

from pydantic import ValidationError

from app.config import AppError
from app.knowledge import search_knowledge
from app.products import get_product_detail, search_products
from app.schemas import GetProductDetailArgs, SearchKnowledgeArgs, SearchProductsArgs
from app.sessions import merge_requirements


def execute_search(arguments: str, current: dict, *, search=search_products) -> tuple[dict, dict, dict]:
    started = perf_counter()
    try:
        patch = SearchProductsArgs.model_validate_json(arguments)
        args = merge_requirements(current, patch)
    except ValidationError as exc:
        # 不把原始参数、异常正文或ctx回传；只提供字段名与错误类型。
        issues = []
        for issue in exc.errors(include_input=False, include_context=False, include_url=False):
            field = issue["loc"][0] if issue["loc"] else "arguments"
            if field not in SearchProductsArgs.model_fields:
                field = "arguments"
            issues.append({"field": field, "type": issue["type"]})
        result = {
            "status": "invalid_arguments", "issues": issues,
            "message": "参数未通过校验，尚未查询数据库。请按工具契约修正，不擅自修改用户的业务条件；无法修正时追问。",
        }
        trace = {"tool": "search_products", **result, "elapsed_seconds": round(perf_counter() - started, 3)}
        return result, dict(current), trace
    try:
        products = search(args)
    except AppError:
        raise AppError("商品工具暂时不可用，本次未完成查询；这不表示没有商品。", code="tool_failed") from None
    requirements = args.model_dump(exclude_none=True)
    result = {
        "status": "ok" if products else "no_results",
        "practice_data": True, "products": products, "returned_count": len(products),
        "effective_requirements": requirements,
    }
    trace = {
        "tool": "search_products", "changes": patch.model_dump(exclude_unset=True),
        "arguments": requirements, **result, "elapsed_seconds": round(perf_counter() - started, 3),
    }
    return result, requirements, trace


def execute_detail(arguments: str, current: dict, *, get_detail=get_product_detail) -> tuple[dict, dict, dict]:
    started = perf_counter()
    try:
        args = GetProductDetailArgs.model_validate_json(arguments)
    except ValidationError as exc:
        issues = []
        for issue in exc.errors(include_input=False, include_context=False, include_url=False):
            field = issue["loc"][0] if issue["loc"] else "arguments"
            issues.append({"field": field if field in GetProductDetailArgs.model_fields else "arguments", "type": issue["type"]})
        result = {"status": "invalid_arguments", "issues": issues,
                  "message": "详情参数无效，尚未查询数据库；需要明确SKU，不得猜测。"}
        trace = {"tool": "get_product_detail", **result, "elapsed_seconds": round(perf_counter() - started, 3)}
        return result, dict(current), trace
    try:
        product = get_detail(args)
    except AppError:
        raise AppError("商品详情工具暂时不可用，本次未完成查询；这不表示商品不存在。", code="tool_failed") from None
    result = {
        "status": "ok" if product is not None else "not_found", "practice_data": True,
        "product": product, "effective_requirements": dict(current),
    }
    trace = {"tool": "get_product_detail", "arguments": args.model_dump(), **result,
             "elapsed_seconds": round(perf_counter() - started, 3)}
    # 详情查看不能改变品牌、规格、预算等已保存的筛选条件。
    return result, dict(current), trace


def execute_knowledge(arguments: str, current: dict, *, search=search_knowledge) -> tuple[dict, dict, dict]:
    started = perf_counter()
    try:
        args = SearchKnowledgeArgs.model_validate_json(arguments)
    except ValidationError as exc:
        issues = []
        for issue in exc.errors(include_input=False, include_context=False, include_url=False):
            field = issue["loc"][0] if issue["loc"] else "arguments"
            issues.append({"field": field if field in SearchKnowledgeArgs.model_fields else "arguments", "type": issue["type"]})
        result = {"status": "invalid_arguments", "issues": issues,
                  "message": "规则检索参数无效，尚未检索；请提供非空query及1到3的limit。"}
        trace = {"tool": "search_knowledge", **result, "elapsed_seconds": round(perf_counter() - started, 3)}
        return result, dict(current), trace
    try:
        passages = search(args)
    except AppError:
        raise AppError("规则检索暂时不可用，本次未完成检索；这不表示没有相关规则。请检查规则，运行build_knowledge_index.py；语义或混合检索还需运行build_vector_index.py。", code="tool_failed") from None
    result = {"status": "ok" if passages else "no_knowledge", "practice_data": True, "passages": passages}
    trace = {"tool": "search_knowledge", "arguments": args.model_dump(), **result,
             "elapsed_seconds": round(perf_counter() - started, 3)}
    return result, dict(current), trace
