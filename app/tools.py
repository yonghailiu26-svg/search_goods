"""模型可见的工具清单；工具执行白名单在agent.py的handlers。"""
from app.knowledge import KNOWLEDGE_TOOL
from app.products import TOOLS as PRODUCT_TOOLS

TOOLS = [*PRODUCT_TOOLS, KNOWLEDGE_TOOL]
