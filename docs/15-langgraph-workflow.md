# 第十五课：把已有包装核对流程改成LangGraph

日期：2026-10-27。功能分支：`feat/15-langgraph-workflow`。先完成等价迁移，读懂State、节点、边、compile和invoke，再学习下一课的条件边。

后续[第16课](16-conditional-routing.md)已将缺SKU的判断移到条件边，当前代码的缺SKU路径以第16课为准。本页保留第15课的直线图及当时数据，原代码在`lesson-15`标签。

## 1. 背景：先让框架接管已有流程的执行顺序

第13课已经能完成“查规则→查SKU详情→整理回答”，业务边界清楚。现在将三步分别放进Python函数，用LangGraph登记节点及连接顺序。商品查询、RAG、模型接口和引用校验继续调用原模块。

```mermaid
flowchart LR
    A[START] --> B[load_rules 查包装规则]
    B --> C[load_detail 查SKU详情]
    C --> D[compose_answer 整理回答]
    D --> E[END]
```

三个节点都是Python函数。SKU存在时仍至多一次DeepSeek汇总；不存在时仍由Python返回提示。图不自动决定业务规则，也没有增加模型请求。

## 2. 在一次请求的什么位置执行

```text
POST /workflows/package-check，输入sku
  → main.py：Pydantic校验请求体
  → workflows.run_package_check(args)
      → new_package_state(args.sku)：创建本次数据
      → get_package_graph()：取得已编译图
      → graph.invoke(initial)：依次执行三个节点
      → 把最终State整理为原接口结果
  → HTTP响应
```

`/chat`仍沿用原Agent循环和MySQL会话存储。本课只迁移固定包装核对入口，它不读写聊天会话。

## 3. 文件职责与阅读顺序

| 文件 | 职责 | 先看什么 |
| --- | --- | --- |
| [package_graph.py](../app/package_graph.py) | 登记节点、连接边、编译图 | 三个函数如何连接 |
| [workflow_state.py](../app/workflow_state.py) | 描述一次执行的数据结构，创建初始值 | 字段从哪里来 |
| [workflows.py](../app/workflows.py) | 业务节点、失败诊断、响应适配 | 谁读字段、谁写字段 |
| [main.py](../app/main.py) | 原HTTP入口和422/503处理 | 请求何时进入图 |
| products.py / storage.py | 原商品工具及参数化SQL | 数据库连接仍由工具管理 |
| knowledge.py及检索模块 | 原混合召回与重排 | 返回原文passages |
| llm.py / evidence.py | 原DeepSeek请求、证据校验及回答整理 | 原业务边界继续生效 |

依赖为`langgraph==1.2.18`，在Python 3.14.2实际安装通过。它会安装`langchain-core`等依赖；本课使用LangGraph图API，聊天模型仍由现有httpx代码调用，无需新的模型Key。

## 4. State：沿节点传递的一份Python字典

请求体仍然只有：

```json
{"sku": "DEMO-PEN-0000"}
```

`PackageCheckState(TypedDict)`可以类比TypeScript的对象类型：描述字典字段，不等于运行时校验器。入口SKU继续由Pydantic校验。

`new_package_state(sku)`创建实际字典。下面只省略计时字段：

```python
{
    "sku": "DEMO-PEN-0000",
    "rules": None,
    "detail": None,
    "tool_trace": [],
    "model_trace": [],
    "node_trace": [],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    "usage_complete": True,
    "answer": "",
    "answer_details": None,
    "outcome": "pending",
}
```

| 字段 | 用途 | 更新位置 |
| --- | --- | --- |
| sku | 本次核对的商品 | 入口创建，之后只读取 |
| rules | 规则工具结果，包含status、passages | load_rules |
| detail | 详情工具结果，包含status、product | load_detail |
| tool_trace | 工具及观察结果 | 前两个节点 |
| node_trace | 已进入的节点名称 | 每个节点 |
| model_trace / usage | 模型状态及用量 | compose_answer |
| answer / answer_details / outcome | 文本、结构化依据、结果类型 | compose_answer |

State是本次执行数据，不是数据库表或上一轮session。Key、数据库连接和HTTP客户端都不放进去。

## 5. 第一个节点：读取规则，填充rules

`load_package_rules`的关键代码：

```python
current = _enter_node(state, "load_rules")
rules, _, record = execute_knowledge(
    json.dumps({"query": "包装 盒装 换算", "limit": 3}, ensure_ascii=False),
    {}, search=search_knowledge,
)
current["rules"] = rules
current["tool_trace"].append(record)
return current
```

复用的是第7课执行器。`rules`是工具结果字典，片段列表在`rules["passages"]`。下面示意只列变化，正文为占位：

```python
"rules": {
    "status": "ok",
    "practice_data": True,
    "passages": [{"chunk_id": "KB-PACK-001-C002", "content": "……规则正文……"}],
}
"node_trace": ["load_rules"]
```

`detail`还没有内容，`tool_trace`已增加规则记录。已有本地Embedding与重排可能在此执行，这不是一次DeepSeek聊天请求。

## 6. 第二个节点：读取同一个sku，填充detail

```python
args = GetProductDetailArgs(sku=state["sku"])
detail, _, record = execute_detail(args.model_dump_json(), {}, get_detail=get_product_detail)
current["detail"] = detail
current["tool_trace"].append(record)
return current
```

链路仍是`execute_detail → get_product_detail → storage → MySQL`，连接在工具内部打开并关闭。返回的State保留前一步rules，同时增加以下内容，包装文字为示意：

```python
"detail": {
    "status": "ok",
    "product": {"sku": "DEMO-PEN-0000", "package_notes": "……数据库中的包装说明……"},
    "practice_data": True,
    "effective_requirements": {},
}
"node_trace": ["load_rules", "load_detail"]
```

若没有SKU，工具返回`status="not_found"`、`product=None`；数据库故障则抛AppError并停止图。两者不能混淆。

## 7. 第三个节点：用已有工具结果整理回答

`compose_package_answer`沿用第13课判断：

- SKU不存在：设置提示及`outcome="not_found"`，不用模型Key，不请求DeepSeek。
- SKU存在：收集证据、组装原payload、调用一次`llm.complete`、校验引用、整理文本和未知项，再更新用量。

```text
rules + detail + tool_trace
  → collect_evidence
  → 原来的DeepSeek调用
  → validate_evidence_answer
  → render_evidence_answer
  → answer、answer_details、usage、model_trace、outcome
```

本课仍是直线图。缺SKU时也会进入compose_answer，但在节点内部直接返回。因此node_trace有三个名字不代表三次模型调用。发生异常时它包含已进入的失败节点，也不能当成“所有节点成功完成”的列表。

## 8. State怎样交给下一个节点

`package_graph.py`的核心代码：

```python
builder = StateGraph(PackageCheckState)
builder.add_node("load_rules", load_package_rules)
builder.add_node("load_detail", load_package_detail)
builder.add_node("compose_answer", compose_package_answer)
builder.add_edge(START, "load_rules")
builder.add_edge("load_rules", "load_detail")
builder.add_edge("load_detail", "compose_answer")
builder.add_edge("compose_answer", END)
return builder.compile(name="package_check")
```

`add_node`登记名字与函数，`add_edge`登记顺序；`compile`检查并生成可执行图，这时还没有查库或请求模型。`invoke(initial)`才真正执行节点。

官方允许节点只返回更新字段，默认规则是覆盖对应字段。本课每个节点返回完整状态副本，未修改字段继续保留，不使用自动累加的reducer。[官方Graph API说明](https://docs.langchain.com/oss/python/langgraph/graph-api)。

真正改变字段的是节点中的Python赋值；框架负责按图传递更新，不会自己补出正文或商品详情。`_enter_node`复制外层字典、待更新的列表和usage，避免原地修改上一份状态。

`get_package_graph`缓存图结构，每次请求仍新建State；复用图不等于复用上一位用户的数据。当前没有checkpointer，State只活在这次invoke中。

## 9. 最后变回原HTTP结果

```python
final = get_package_graph().invoke(
    new_package_state(args.sku),
    config={"recursion_limit": 8},
)
```

8是图执行步数上限，不是8次模型调用。入口从final取出原answer、sources、usage等字段，新增两个观察字段：

```json
{
  "execution_mode": "workflow",
  "workflow_engine": "langgraph",
  "node_trace": ["load_rules", "load_detail", "compose_answer"]
}
```

路径和输入不变。`sources`仍只列规则来源；SKU证据在`answer_details.claims[].evidence_ids`，实际详情在`tool_trace`。它们分别承担不同职责。

## 10. 本地操作与验收

确认分支为feat/15-langgraph-workflow，安装该分支依赖。已有MySQL、模型和索引不用重复初始化：

```powershell
git branch --show-current
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --no-cache-dir
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开`http://127.0.0.1:8000/docs`，调用`POST /workflows/package-check`，输入`{"sku":"DEMO-PEN-0000"}`，再试DEMO-PEN-0001和DEMO-NOT-EXIST-999。检查工具顺序、node_trace和缺SKU时零模型调用。实际模型请求会计费。

```powershell
# 全部行为测试，不调用真实模型或数据库。
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
# 固定夹具与原标签实现对照，不调用真实模型或数据库。
.\.venv\Scripts\python.exe verify_step15.py
# 再加真实RAG、MySQL和DeepSeek；API会计费。
.\.venv\Scripts\python.exe verify_step15.py --with-live
```

对照脚本从自己仓库的lesson-14-baseline读取旧workflows.py，在内存加载，用同一夹具执行新旧实现。仅排除耗时和新增图元数据，其他回答、错误、用量与工具观察必须一致。夹具中的Token是模拟值。脚本不把旧版复制成另一套业务目录，也不执行模型生成的代码。克隆时若没取到标签，需先取回该基线。

报告在本地`outputs/15-langgraph-evaluation.json`，按现有规则不随代码上传；直接运行离线模式会覆盖此报告并将真实检查标为skipped。

## 11. 2026-10-27实际结果

106项行为测试和依赖检查通过；6个离线场景与旧实现一致：正常回答、缺包装说明、无SKU、规则故障、模型超时、额外工具请求。新增测试覆盖编译无业务副作用、State不被原地修改、并发请求隔离、无SKU不需要Key、失败请求不复用旧用量，以及错误保留已知用量。

| 真实场景 | 模型请求数 | 总Token | 耗时 |
| --- | --- | --- | --- |
| DEMO-PEN-0000 | 1 | 1896 | 4.58秒 |
| DEMO-PEN-0001 | 1 | 1900 | 2.50秒 |
| DEMO-NOT-EXIST-999 | 0 | 0 | 0.63秒 |

三例都经过真实本地RAG和MySQL；前两例使用官方DeepSeek，保留规则、SKU证据及未知项。非法SKU返回422。工作流不新增聊天会话。耗时是本次小样例观察，不能据此宣称框架提高准确率或固定性能。

新增并发测试最初误把SKU证据当作sources内容，产生一次断言失败；核对第九课契约后改从answer_details检查SKU引用，106项重跑通过，没有改变原字段含义。Python 3.14下第三方依赖首次导入有弃用提示，不影响执行，也未全局屏蔽警告。

## 12. 下一课与当前边界

下一课再增加条件边：让图根据详情结果选择后续节点，将原来节点内部的判断显式放到图上。之后再分课学习检查点、人工确认。

当前重启不能恢复执行到一半的State，也不会自动写入原MySQL会话表。审批、多worker协调、外部写操作幂等、多Agent均未提前加入。

阅读顺序：package_graph.py的图 → workflow_state.py的初始字典 → workflows.py的三个节点，沿同一SKU追踪变化。官方参考：[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)、[Quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)。
