# Python 补课二：数据容器、JSON 与参数校验

前一篇：[函数参数](04-python-parameters.md)。这篇重点解释多轮条件为什么能保留、修改和取消。

## 1. 字典、列表、元组与对象

```python
requirements = {"brand": "得力", "limit": 5}  # dict：按键取值
history = [{"role": "user", "content": "找笔"}]  # list：按顺序保存
pair = ("会话ID", "会话对象")  # tuple：固定的一组值
```

| 操作 | 结果 |
| --- | --- |
| `requirements["brand"]` | 得到得力；键不存在则 KeyError |
| `requirements.get("color")` | 键不存在时返回 None |
| `requirements.get("limit", 5)` | 键不存在时返回 5；已有键值为 None 时仍返回 None |
| `requirements.update({"brand": "晨光"})` | 原地修改字典；方法返回 None |
| `requirements.pop("brand", None)` | 删除 brand 并返回原值；键不存在时返回 None |
| `history.append(message)` | 向原列表追加一项；方法返回 None |
| `history[-12:]` | 取最后最多 12 项，得到新列表 |
| `session_id, session = pair` | 拆出两个值，叫解包 |

`args.brand` 是对象属性访问；`requirements["brand"]` 是字典按键访问。Pydantic 对象和字典不是同一种数据，不能直接混用访问方式。

## 2. 赋值不是复制

```python
current = {"brand": "得力"}
merged = current
merged["brand"] = "晨光"
print(current)  # {'brand': '晨光'}：两个名字指向同一个字典
```

项目用 `merged = dict(current)` 创建新字典，再 update。这样合并中途失败时，旧字典不会被改坏。

这是**浅复制**：最外层字典独立，内部嵌套的列表/字典仍可能共享。当前筛选字段都是字符串、整数或 None，浅复制足够；不要把这个结论套到任意嵌套结构上。

## 3. JSON 字符串与 Python 字典

```python
import json

text = '{"brand": "得力", "max_price_fen": null}'  # str
data = json.loads(text)  # dict，其中 null 变为 None
text_again = json.dumps(data, ensure_ascii=False)  # str，中文不转成 \u 转义
```

JSON 使用 `null/true/false`；Python 使用 `None/True/False`。合法 JSON 字符串解析后也可能是列表或数字，不保证一定是字典。

项目的 `function["arguments"]` 是 JSON 字符串。`SearchProductsArgs.model_validate_json(...)` 把解析和模型校验一起做了；不要用 `eval` 执行这些文本。

## 4. Pydantic 是第三方校验库

`app/schemas.py` 中的核心结构可简化为：

```python
from pydantic import BaseModel, ConfigDict, Field

class SearchProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    brand: str | None = None
    limit: int = Field(default=5, ge=1, le=10)
```

- `BaseModel`：继承它，让类具备数据校验和导出能力。
- `Field`：补充默认值、范围、描述等；`ge` 为大于等于，`le` 为小于等于。
- `extra="forbid"`：传入未定义字段时报错。
- `strict=True`：采用严格类型校验，例如这里的整数字段不接受字符串 `"5"`。
- 项目另有 `str_strip_whitespace=True`：去掉字符串首尾空白。
- `Annotated[str, Field(min_length=1, max_length=80)]`：把字符串类型和约束组合成可复用的 TextFilter；约束由 Pydantic 读取执行。

`ChatRequest` 与 `SearchProductsArgs` 配置不同：前者没有设置 strict=True，不要认为所有模型自动采用同一套严格规则。

| 方法 | 输入/输出与用途 |
| --- | --- |
| `SearchProductsArgs.model_validate(data)` | 从 Python 数据校验并创建模型对象 |
| `SearchProductsArgs.model_validate_json(text)` | 从 JSON 文本解析、校验并创建模型对象 |
| `args.model_dump()` | 把模型对象导出为 Python 字典 |
| `args.model_dump_json()` | 导出为 JSON 字符串 |
| `SearchProductsArgs.model_json_schema()` | 生成字段结构说明，项目用它向模型描述工具参数 |

## 5. 最关键：没传与传 None 不一样

```python
missing = SearchProductsArgs.model_validate({})
cancel = SearchProductsArgs.model_validate({"brand": None})

print(missing.brand)  # None
print(cancel.brand)   # None
print(missing.model_dump(exclude_unset=True))  # {}
print(cancel.model_dump(exclude_unset=True))   # {'brand': None}
```

虽然属性值一样，Pydantic 仍记录哪些字段被明确提供。模型创建后显式给字段赋值也会影响已设置字段记录；当前项目在解析 patch 后立即导出。

| 导出方式 | 筛选标准 | 本项目用途 |
| --- | --- | --- |
| `exclude_unset=True` | 省略没有明确设置的字段 | 提取本轮修改，保留明确传入的 None |
| `exclude_none=True` | 省略值为 None 的字段 | 保存有效条件，取消后不再保留该筛选项 |
| `exclude_defaults=True` | 省略与默认值相同的字段 | 不适合提取 patch：明确传入默认值也可能需要覆盖旧值 |

例如旧 limit 为 8，本轮明确传 `limit=5`。虽然 5 是默认值，它仍是一次修改，不能被丢掉。

## 6. 把项目的合并串起来

```python
current = {"brand": "得力", "color": "黑色", "limit": 8}
patch = SearchProductsArgs.model_validate({"brand": None, "limit": 5})
changes = patch.model_dump(exclude_unset=True)
merged = dict(current)
merged.update(changes)
args = SearchProductsArgs.model_validate(merged)
effective = args.model_dump(exclude_none=True)
# effective == {'color': '黑色', 'limit': 5}
```

规则：没提到颜色 → 保留；brand 为 None → 取消；明确传 limit → 覆盖。真实 `merge_requirements` 还在 update 前处理换品类时清理旧字段，详见 [第三步](03-multi-turn-state.md)。

接着读 [项目知识地图](06-python-project-map.md)。参考：[Pydantic 官方：导出与字段排除](https://docs.pydantic.dev/latest/concepts/serialization/)。
