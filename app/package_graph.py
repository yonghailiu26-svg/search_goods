"""第十六课：详情读取成功后，只选择一条后续路线。"""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.workflow_state import PackageCheckState


@lru_cache(maxsize=1)
def get_package_graph():
    # 延后导入避免入口与图定义互相导入；构建时不执行工具或模型请求。
    from app.workflows import (
        compose_package_answer, load_package_detail, load_package_rules,
        reply_package_not_found, route_package_detail,
    )

    builder = StateGraph(PackageCheckState)
    builder.add_node("load_rules", load_package_rules)
    builder.add_node("load_detail", load_package_detail)
    builder.add_node("compose_answer", compose_package_answer)
    builder.add_node("reply_not_found", reply_package_not_found)
    builder.add_edge(START, "load_rules")
    builder.add_edge("load_rules", "load_detail")
    # 替换旧普通边；不能同时保留，否则汇总路径也可能执行。
    builder.add_conditional_edges(
        "load_detail", route_package_detail,
        {"summarize": "compose_answer", "not_found": "reply_not_found"},
    )
    builder.add_edge("compose_answer", END)
    builder.add_edge("reply_not_found", END)
    # 本课不配置checkpointer；State只活在这次invoke中。
    return builder.compile(name="package_check")
