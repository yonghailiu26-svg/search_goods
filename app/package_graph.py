"""第十五课：只组织执行顺序，节点业务仍由workflows.py负责。"""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.workflow_state import PackageCheckState


@lru_cache(maxsize=1)
def get_package_graph():
    # 延后导入避免入口与图定义互相导入；构建时不执行工具或模型请求。
    from app.workflows import compose_package_answer, load_package_detail, load_package_rules

    builder = StateGraph(PackageCheckState)
    builder.add_node("load_rules", load_package_rules)
    builder.add_node("load_detail", load_package_detail)
    builder.add_node("compose_answer", compose_package_answer)
    builder.add_edge(START, "load_rules")
    builder.add_edge("load_rules", "load_detail")
    builder.add_edge("load_detail", "compose_answer")
    builder.add_edge("compose_answer", END)
    # 本课不配置checkpointer；State只活在这次invoke中。
    return builder.compile(name="package_check")
