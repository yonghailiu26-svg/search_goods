# 第十三课：什么时候让Agent决定，什么时候写固定工作流

这节不是再加一个模型，而是增加一种执行方式：目标已明确、输入已结构化时，由Python固定安排步骤，模型只负责最后表达。

## 1. 用同一个包装问题比较

| 方式 | 输入 | 谁决定查什么 | 谁汇总 |
| --- | --- | --- | --- |
| 原/chat Agent | 自然语言问题、可带session_id | 模型在工具循环里选择 | 模型 |
| 新/package-check工作流 | 明确sku | Python固定先查规则、再查详情 | 最多一次模型请求 |

本课并不自动判断每句话该走哪条路，而是给两个明确入口。自然语言需求、多轮修改、工具选择练习继续用/chat；目标确定的包装核对可用固定接口。

两者输入形式和任务范围不同，比较用于认识执行控制，不是严格性能竞赛。固定工作流也可能因数据库、模型或资料不足而失败。

## 2. 发生时机与改动位置

新增[workflows.py](../app/workflows.py)，main.py新增`POST /workflows/package-check`。复用第九课证据校验、现有知识工具和商品工具；evidence.py抽出collect_sources供两种执行方式共用，原Agent增加execution_mode字段。

```text
HTTP body {"sku":"DEMO-PEN-0000"}
 → GetProductDetailArgs校验
 → run_package_check(args)
 → execute_knowledge：固定查包装、盒装、换算规则
 → execute_detail：只查指定SKU
 → 商品不存在：直接返回not_found，不调用模型
 → 商品存在：收集证据，进行一次模型汇总
 → 校验claims/unknowns，整理文本
```

不是先请求模型制定计划；Python执行工具后才调用模型。流程最多两个工具步骤、一次DeepSeek请求。

## 3. 跟着输入输出读核心代码

```python
rules, _, record = execute_knowledge(..., {}, search=search_knowledge)
trace.append(record)
detail, _, record = execute_detail(args.model_dump_json(), {}, get_detail=get_product_detail)
trace.append(record)
```

rules、detail都是工具结果字典，record是观察记录。中间的`_`接收原工具函数返回的条件副本，但固定任务没有筛选条件修改，因此不使用它。传空字典表示这条独立流程不读写聊天会话。

两个结果的结构节选：

```text
rules  = {status, passages: [...规则正文与来源...]}
detail = {status, product: {...商品详情...}}
trace  = [规则工具记录, 商品详情工具记录]
```

如果detail.status是not_found，程序直接回答SKU未查到。已经查到规则不代表该商品存在，因此不能用通用规则生成这个SKU的事实。

商品存在时：

```python
context = collect_evidence(trace)
```

context是第九课的可用证据ID和资料缺口。Python把任务、原始observations及context序列化为user消息，配上证据格式system指令，再调用一次complete。

与Agent的区别：这里没有先前由模型提出的tool_calls，因此也不伪造assistant工具请求；已执行观察作为明确的数据交给汇总模型。请求中没有tools清单，返回中如果出现额外tool_calls，程序仍拒绝。

## 4. 一次模型汇总后怎样处理

```python
structured = validate_evidence_answer(message.get("content"), context)
answer, details = render_evidence_answer(structured, context)
```

模型content是JSON字符串，先恢复EvidenceAnswer对象，核对每条引用属于真实观察，然后得到纯文本answer及answer_details字典。缺包装说明等确定缺口由Python补充；未知包装数量仍必须依据正文承认未知。

引用校验不能证明所有语义正确。商品说明明确写了未提供数量，与字段为null也不是同一种情况；前者需要模型理解文字，后者程序能直接检查。

## 5. 返回结果与会话的边界

```text
execution_mode: workflow
workflow: package_check
answer / answer_details / sources / tool_trace
model_calls: 0或1
usage / usage_complete / model_trace / elapsed_seconds
current_requirements: {}
```

这个独立端点不接受session_id、不保存聊天、不修改已有搜索条件；商品与规则都为只读。聊天页仍使用/chat，要验收固定工作流请打开/docs。原Agent返回execution_mode=agent。

工具故障直接停止，诊断保留已执行步骤。模型超时不重试，用量未知时usage_complete=false，不把未知用量当成确定0。引用无效或模型要求额外工具也停止。这里沿用AppError安全错误边界，不返回底层错误原文。

## 6. 本地验收怎么操作

打开`http://127.0.0.1:8000/docs`，选择`POST /workflows/package-check`，输入：

```json
{"sku":"DEMO-PEN-0000"}
```

再试DEMO-PEN-0001（存在但未提供详情说明）以及DEMO-NOT-EXIST-999（不存在）。查看固定工具顺序、model_calls、unknowns；再用/chat问同样目标，查看模型如何选择工具。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
# 真实MySQL及DeepSeek；API部分计费
.\.venv\Scripts\python.exe verify_step13.py
```

测试覆盖固定顺序与一次汇总、商品不存在零模型请求、缺包装自动提示、规则失败不继续查商品、商品失败保留前步、超时用量未知、不合法引用/额外工具拒绝、入口SKU与额外字段校验。实际报告：[13-workflow-evaluation.json](../outputs/13-workflow-evaluation.json)。

2026-10-22累计91项测试通过，四组真实验收通过：存在SKU工作流1次模型/总1964 Token/7.49秒；缺说明SKU工作流1次/1948/5.25秒；未知SKU工作流0次/0/1.68秒；相同目标Agent2次/6069/7.44秒。用量含已报告Token，耗时含本机检索和模型冷加载等，不能推广为固定性能差异。

适用判断：步骤稳定且输入明确，用工作流容易说明和检查执行边界；步骤需要根据问题与观察变化，Agent更灵活。实际项目可以组合两者，但这里保持两个明确入口方便学习，没有加入自动路由大框架。
