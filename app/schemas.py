"""数据契约：只定义字段和校验规则，不发请求、不查数据库。"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

TextFilter = Annotated[str, Field(min_length=1, max_length=80)]


class SearchProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    keyword: TextFilter | None = Field(default=None, description="商品名关键词；品牌、颜色、规格应放专用字段")
    category: TextFilter | None = Field(default=None, description="品类精确匹配，例如签字笔、橡皮")
    brand: TextFilter | None = Field(default=None, description="品牌精确匹配，例如得力、晨光、齐心")
    color: TextFilter | None = Field(default=None, description="颜色精确匹配，例如黑色、蓝色")
    spec: TextFilter | None = Field(default=None, description="规格精确匹配，例如0.5mm、0.7mm")
    max_price_fen: int | None = Field(default=None, ge=0, le=10000000, description="单价上限，单位分；5元=500分")
    limit: int = Field(default=5, ge=1, le=10, description="最多返回几条商品")


class GetProductDetailArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    sku: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", description="用户明确给出或搜索结果中的商品SKU，不可猜测")


class SearchKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=200, description="要查的规则问题或关键词，例如包装、盒支换算、价格单位；保留原问题的核心含义")
    limit: int = Field(default=3, ge=1, le=3, description="最多返回几条规则，最多3条")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$", description="首轮不传；后续原样传回响应中的ID")
