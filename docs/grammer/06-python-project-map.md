# Python 补课三：对象、异常与项目知识地图

前两篇：[函数参数](04-python-parameters.md)、[数据与校验](05-python-data-validation.md)。这篇把剩余知识放到实际文件中定位，不必一次学完。

## 1. 类、self 与 dataclass

`class` 定义一种对象；`SessionStore()` 创建实例；`self` 是实例方法接收到的当前对象。

```python
class SessionStore:
    def __init__(self):
        self._sessions = {}
```

`__init__` 在初始化实例时执行。`self._sessions` 属于这个实例，方法内的普通局部变量只属于本次调用。名称前的单下划线表示内部使用约定，不是强制私有。

项目 `Session` 使用 `@dataclass` 自动生成初始化等常用方法：

```python
@dataclass
class Session:
    requirements: dict = field(default_factory=dict)
```

`default_factory=dict` 表示每创建一个 Session，就调用 dict 创建独立字典；`list` 和 `Lock` 同理。不要写普通函数 `def f(history=[])`：这个默认列表会在多次调用间共享。通常写 `history=None`，再在函数内创建列表。

## 2. 装饰器、导入与模块

- `from app.sessions import store`：从模块取出名字；首次导入通常会执行模块顶层代码，因此 `store = SessionStore()` 会创建对象。同一进程内通常复用已加载模块。
- `app/__init__.py`：这里用于标记普通 Python 包。
- `@app.post("/chat")`：装饰器，让 FastAPI 注册下面的函数为 POST 路由。定义/注册路由时不会自动执行一次商品查询。
- `@dataclass` 也是装饰器，但用途是加工类；`@` 是语法，具体行为由后面的函数决定。
- `if __name__ == "__main__":`：直接运行文件时执行的入口，导入它时跳过该分支。

## 3. 异常：失败后不沿成功路径继续

```python
try:
    value = int("abc")
except ValueError:
    raise AppError("配置必须是整数") from None
```

`try` 放可能失败的操作；`except` 捕获指定异常；`raise` 抛出异常交给外层处理。裸 `raise` 重新抛出当前异常；`from None` 抑制默认 traceback 展示中的原异常链，不表示系统里不存在原异常或敏感数据。

项目常见异常：`KeyError` 键不存在，`IndexError` 索引越界，`TypeError` 类型或调用方式不对，`ValueError` 值不合要求，Pydantic 的 `ValidationError` 表示校验失败。

`AppError` 是项目自定义异常；main 把它转成 HTTP 503，未知会话转成 404，请求校验失败返回 422。排错先看状态码、错误消息、报错文件和行号，再看对应输入的类型与值。

## 4. with：结束时自动收尾

| 项目写法 | 作用 |
| --- | --- |
| `with httpx.Client(...) as client` | 创建 HTTP 客户端，退出时关闭 |
| `with session.lock` | 进入时加锁，退出时释放锁 |
| `with connect() as connection` | PyMySQL 连接作用域结束时关闭连接 |
| `with connection.cursor() as cursor` | 退出时关闭游标 |

这些对象实现了上下文管理协议，即使块内发生异常也会执行退出处理。`with` 是否提交数据库事务取决于对象实现，不能一概认为会自动 commit；当前查询主要是 SELECT。

## 5. HTTP、同步与并发

`httpx.Client.post(..., json=payload)` 把 Python 数据编码为 JSON 请求；`response.json()` 解析响应正文，`raise_for_status()` 检查失败状态。`json=` 是关键字实参，不是调用 `json` 模块。

项目 `/chat` 是同步 `def`，FastAPI 会在线程池执行它，适配当前阻塞式 httpx / PyMySQL。`async def` 定义协程函数，`await` 等待可等待对象；不能只把 def 改成 async def 就认为网络请求不会阻塞。

`SessionStore` 的锁保护会话字典操作；每个 Session 的锁保护同一会话的整轮更新。线程可共享进程内字典，多个进程各有自己的内存；服务重启或代码重载会丢失当前会话。

## 6. 配置、路径与数据库参数

- `os.getenv(name, default)`：读取环境变量，结果通常是字符串；整数配置需要 `int(...)` 转换和范围检查。
- `Path(__file__).resolve().parents[1] / ".env.dev"`：从当前文件位置找到项目根目录，再拼出配置文件路径；`/` 在 Path 对象上表示拼路径。
- `.venv`：项目独立 Python 环境；`python -m pip` 使用这个解释器对应的 pip，减少装错环境的问题。
- `cursor.execute(sql, values)`：SQL 语句与参数值分开传入；不要把用户值用 f-string 拼进 SQL。
- 当前 SQL 中的列名来自代码固定的白名单，值用 `%s` 占位。占位符不能直接替代任意表名、列名。

## 7. 整个项目需要的知识地图

| 优先级 | 知识 | 对照文件 |
| --- | --- | --- |
| 先学 | 形参/实参、默认值、关键字参数、类型标注 | agent.py、config.py；见 04 |
| 先学 | dict/list、None、解包、切片、复制与合并 | sessions.py、main.py；见 04/05 |
| 先学 | JSON、Pydantic、缺失字段与 null | schemas.py、agent.py；见 05 |
| 随代码学 | 类、self、dataclass、装饰器、导入 | sessions.py、main.py |
| 随代码学 | 异常、with、HTTP 请求与响应 | config.py、llm.py、storage.py |
| 随代码学 | FastAPI 路由/请求体、同步与线程锁 | main.py、sessions.py |
| 随代码学 | 虚拟环境、环境变量、Path、参数化 SQL | config.py、storage.py、seed_products.py |
| 后续再学 | unittest、mock 替换外部依赖、断言 | tests/test_step2.py、tests/test_step3.py |
| 后续再学 | 持久化、事务、连接池、进程与部署 | 后续会话落库阶段，当前尚未实现会话持久化 |
| 业务知识 | messages、tool_calls、Token、有限循环 | agent.py、products.py、prompts.py；见 01～03 |

工具参数是模型提出的数据，Python 负责校验并调用函数；模型没有直接执行 Python。Pydantic 能检查类型和范围，不能保证模型理解用户意图一定正确。

## 8. 最短学习路线

1. 看 04，能读懂 run_agent 的函数签名。
2. 看 05，能解释没传 brand 和传 brand=None 的区别。
3. 从 sessions.py 的 merge_requirements 开始，沿 main.py → agent.py 看一次请求。
4. 卡在具体写法时回查上表；暂时不用补元类、复杂继承等当前用不到的内容。

可以在项目根目录启动交互环境，自行试前两篇的数据示例：

```powershell
.\.venv\Scripts\python.exe
```

这些数据示例只导入 schemas，不调用模型或数据库。涉及 run_agent 的调用仅用于解释语法；真正执行它会使用模型配置并可能产生 API 费用。

参考：[Python 官方教程](https://docs.python.org/3/tutorial/)、[Pydantic 官方文档](https://docs.pydantic.dev/)、[FastAPI 同步与异步](https://fastapi.tiangolo.com/async/)。
