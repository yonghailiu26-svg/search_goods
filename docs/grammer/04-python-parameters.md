# Python 补课一：函数参数与常见语法

这组补充文档围绕当前项目，只讲读代码会碰到的知识。建议按 04 → 05 → 06 阅读，再回看 [第三步](03-multi-turn-state.md)。

## 1. 先读懂函数定义

项目 `app/agent.py` 中：

```python
def run_agent(question: str, *, current_requirements: dict | None = None,
              history: list[dict] | None = None) -> dict:
    ...
```

| 写法 | 意思 |
| --- | --- |
| `def run_agent(...)` | 定义一个函数，调用时才执行函数体 |
| `question` | 形参，即函数接收数据时使用的名字 |
| `: str` | 类型标注：期望字符串 |
| `= None` | 默认值：调用时不传，就使用 None |
| 单独的 `*` | 它后面的参数必须写名字传入 |
| `dict \| None` | 可以是字典，也可以是 None |
| `list[dict]` | 列表中放字典 |
| `-> dict` | 返回值期望是字典；真正返回靠 `return` |

正确调用：

```python
run_agent("找签字笔")
run_agent("换得力", current_requirements={"color": "黑色"}, history=[])
run_agent(question="找签字笔")  # question 也允许用名字传
```

`run_agent("换得力", {"color": "黑色"}, [])` 会报 TypeError，因为后两个参数必须写名字。

**形参是定义时的名字，实参是调用时实际传进去的值。类型标注本身不会自动检查或转换输入；Pydantic 等库才会执行校验。**

## 2. 位置参数、关键字参数、默认参数

```python
def search(keyword, limit=5):
    return keyword, limit

search("笔", 3)                 # 按位置对应
search(keyword="笔", limit=3)   # 按名字对应
search("笔")                    # limit 使用默认值 5
```

普通调用中，位置参数放在关键字参数之前。同一个参数不能同时按位置和名字重复传值。

项目 `integer("AGENT_MAX_MODEL_CALLS", 3, 2, 5)` 对应 `integer(name, default, minimum, maximum)`：配置名、默认 3、最小 2、最大 5。数字含义不好记时，可以写成 `integer("AGENT_MAX_MODEL_CALLS", default=3, minimum=2, maximum=5)`。

## 3. `*` 和 `**` 要看出现在什么位置

| 位置 | 写法 | 含义 |
| --- | --- | --- |
| 函数定义 | `def f(*args)` | 把多余的位置实参收集成元组 |
| 函数定义 | `def f(**kwargs)` | 把多余的关键字实参收集成字典 |
| 函数定义 | `def f(x, *, y)` | y 必须写名字传入 |
| 函数调用 | `f(*items)` | 把列表/元组展开成位置实参 |
| 函数调用 | `f(**options)` | 把字典展开成关键字实参，键必须是字符串 |
| 列表构造 | `[*old, new]` | 展开旧列表的元素，再加入新元素 |
| 字典构造 | `{**old, **changes}` | 合并字典；重复的键由后面覆盖 |

```python
options = {"keyword": "笔", "limit": 3}
search(**options)  # 等价于 search(keyword="笔", limit=3)
```

`args`、`kwargs` 只是惯用变量名，不是关键字。项目中的 `args: SearchProductsArgs` 是普通参数对象，和 `*args` 没有特殊联系。

## 4. None、真假值和短路

`None` 表示没有值。JSON 的 `null` 被解析成 Python 后就是 `None`；`False`、`0`、`""`、`[]`、`{}` 和 None 在条件判断中都为假，但含义不同。

```python
requirements = dict(current_requirements or {})
```

`a or b`：a 为真时返回 a，否则返回 b。因此这里把 None 或空字典换成 `{}`，再复制成字典。它返回的是操作数，不一定是布尔值。

```python
if args.max_price_fen is not None:
    ...
```

这里不能随便换成 `if args.max_price_fen`，因为 0 也是有效预算。判断 None 通常用 `is None` / `is not None`；比较普通值用 `==` / `!=`。

`a and b` 在 a 为假时不再计算 b；项目先确认 category 非 None，再比较是否换了品类。

## 5. 其他高频写法速查

| 写法 | 解释与项目位置 |
| --- | --- |
| `value if condition else other` | 条件表达式；agent 最后一轮把 tool_choice 设为 none |
| `f"HTTP {status}"` | f-string，把变量放入字符串 |
| `for i in range(3)` | i 依次为 0、1、2；不包含 3 |
| `for name in usage` | 遍历字典的键 |
| `{name: counts[name] for name in names}` | 字典推导式：循环生成一个字典 |
| `all(condition for value in values)` | 逐个检查，全部满足才为 True |
| `isinstance(value, dict)` | 判断是不是字典，包括子类实例 |
| `getattr(args, column)` | 用变量里的属性名取值，例如 column 为 brand 时取 args.brand |
| `" AND ".join(clauses)` | 用 AND 把字符串列表连接起来 |
| `text.strip()` | 去掉字符串首尾空白 |

Python 使用缩进表示代码块，通常缩进 4 个空格；`#` 是注释，三引号可写跨行字符串或文档说明。`prompts.py` 的 SYSTEM 就是普通字符串，程序把它发送给模型后才发挥提示词作用。

先试着解释：`run_agent("找笔", history=[])` 中哪个是实参？`*` 限制了什么？为什么预算判断要用 `is not None`？能回答就可以继续。

参考：[Python 官方：函数参数与控制流](https://docs.python.org/3/tutorial/controlflow.html)。
