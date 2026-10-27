# 纯文本找商品 Agent · Python 学习项目

[Git版本管理与后续分支流程](docs/00-git-workflow.md)：第1～14课作为基线，后续每阶段在功能分支完成、验收后合入。

当前扩展：[第15课：把固定包装核对迁移为LangGraph](docs/15-langgraph-workflow.md)，位于`feat/15-langgraph-workflow`分支。原HTTP路径保留，新增State、三个节点和执行轨迹；本课暂不加入断点恢复。

[课程总目录与本地验收入口](docs/00-course-map-and-acceptance.md)：主线第1～14课已实现，最终整体验收命令为verify_step14.py --with-agent。

## 分步实现文档

- [第一步：环境与真实模型调用](docs/01-first-call.md)
- [第二步：FastAPI 与 MySQL 查询工具](docs/02-fastapi-product-tool.md)
- [第三步：模块分工与多轮条件状态](docs/03-multi-turn-state.md)
- [第四步A：会话表读写与简单聊天页](docs/04a-session-storage-and-chat-ui.md)
- [第四步B：Agent跨重启恢复上下文](docs/04b-agent-persistent-context.md)
- [第五步：Agent错误恢复、执行边界与小评测](docs/05-agent-recovery-and-evaluation.md)
- [第六步：Agent选择并串联两个工具](docs/06-agent-tool-selection.md)
- [第七课：最小RAG，查规则再回答](docs/07-minimal-rag.md)
- [第07课补充：检索为什么是工具、execute_knowledge逐段与案例](docs/07a-rag-tool-and-execute-knowledge.md)
- [第八课：知识整理、分块与来源追溯](docs/08-knowledge-chunks-and-index.md)
- [第八课先读：一条数据如何从Markdown走到模型回答](docs/08a-rag-data-flow.md)
- [第九课：规则证据与商品事实协同回答](docs/09-evidence-and-product-answers.md)
- [第十课：本地Embedding语义检索](docs/10-local-embedding-retrieval.md)
- [第十一课：关键词与向量混合检索](docs/11-hybrid-retrieval.md)
- [第十二课：候选交叉编码重排](docs/12-cross-encoder-reranking.md)
- [第十三课：Agent与固定工作流](docs/13-agent-and-workflow.md)
- [第十四课：评测、指标与基线回归](docs/14-evaluation-and-regression.md)
- [第十五课：State、节点、边与固定流程等价迁移](docs/15-langgraph-workflow.md)

Python 补充知识（按顺序简读）：

- [函数参数与常见语法：类型标注、默认值、星号与解包](docs/grammer/04-python-parameters.md)
- [数据与参数校验：字典、JSON、Pydantic、没传与 null](docs/grammer/05-python-data-validation.md)
- [项目知识地图：对象、异常、HTTP、数据库与学习顺序](docs/grammer/06-python-project-map.md)

当前进度：第1～14课基础主线已完成，第15课在扩展分支学习LangGraph。第四步起/chat从MySQL恢复会话，成功后保存条件和消息；后端重启后可以按原ID继续。聊天页在当前标签页刷新后恢复最近6轮对话。

第五步已完成：非法工具参数可在执行预算内修正；无商品、接口错误和执行上限分别处理，响应提供逐步用量/耗时。V1五步已具备，完整本次报告见outputs/05-agent-evaluation.json。

第六步已完成：search_products筛选候选，get_product_detail按SKU看说明/包装信息；模型可先搜索再查详情，也可明确SKU直查。详情查看不改变搜索条件。初次使用详情前运行seed_product_details.py。

第七课已完成：新增search_knowledge按关键词检索本地练习规则，把正文和来源交回模型，回答带[KB-PACK-001]等引用。无资料明确说明未知，规则检索不改变商品条件；未接Embedding或向量库。

第八课已完成：规则预先按小标题、段落分块，运行时检索片段并引用[KB-PACK-001-C001]等chunk_id，来源包含原文行号与内容版本。首次使用或修改knowledge资料后运行build_knowledge_index.py；旧索引不自动重建。

第九课：本轮同时查询规则与商品详情时，模型按claims/unknowns组织结论，Python校验每条结论的证据ID再整理成文本。answer_details保留结构便于对照，不把规则原则当成某SKU的事实。

第十课：默认用本地BGE中文模型把片段和问题编码成向量，按余弦相似度检索；仍返回原文passages，DeepSeek继续负责回答。首次使用或更新资料后构建向量索引，无需新增Key。可用KNOWLEDGE_RETRIEVAL=keyword对比旧关键词方法。

第十一课：引入hybrid，同时取关键词和向量候选，用RRF按名次合并去重。retrieval_details可查看两路名次/原始分数，原文及引用继续沿用。

第十二课：当前默认rerank，在RRF候选之后用本地交叉编码模型读取“问题+片段正文”重新排序；先运行prepare_reranker.py准备模型。显式配置旧策略时仍按本地配置执行。

第十三课：新增POST /workflows/package-check，固定查规则→查SKU→至多一次模型汇总。/chat继续作为Agent；工作流不读写聊天会话。

第十四课：固定8条检索样例、四策略指标与基线比较，加全部行为测试及可选真实接口检查。已通过100项测试与真实整体验收。

启动服务（商品库已初始化时不必再次运行seed_products.py）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --no-cache-dir
.\.venv\Scripts\python.exe seed_products.py
.\.venv\Scripts\python.exe build_knowledge_index.py
.\.venv\Scripts\python.exe build_vector_index.py
.\.venv\Scripts\python.exe prepare_reranker.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/ 使用聊天页（自动带回session_id）；也可以在 http://127.0.0.1:8000/docs 测试 `POST /chat`。

首轮：

```json
{"message":"找黑色0.5mm签字笔，单价不超过5元"}
```

后续带回首轮响应中的真实session_id：

```json
{"message":"换得力，其他不变","session_id":"替换为首轮返回的32位ID"}
```

查看current_requirements（完整条件）、tool_trace[].changes（本轮修改）和tool_trace[].arguments（实际查询条件）。不传session_id开始新会话。

## 当前模块职责

| 模块 | 职责 |
| --- | --- |
| app/main.py | HTTP入口、成功后保存会话 |
| app/schemas.py | 请求体与工具参数校验 |
| app/sessions.py | 会话锁、恢复与保存调度、条件合并 |
| app/agent.py | 调度模型与工具循环 |
| app/evidence.py | 混合回答的证据清单、逐条引用校验与文本展示 |
| app/llm.py | DeepSeek请求、响应与用量解析 |
| app/prompts.py | 模型指令 |
| app/products.py | 商品工具说明与入口 |
| app/knowledge.py | 规则工具定义、检索策略选择与两路候选调度 |
| app/hybrid_search.py | 关键词/向量结果按名次融合、去重及明细解释 |
| app/reranking.py | 本地问题/片段配对计分与候选重排 |
| app/workflows.py | 固定SKU包装核对流程，至多一次模型汇总 |
| app/package_graph.py | 第十五课：三个节点及顺序、编译可执行图 |
| app/workflow_state.py | 第十五课：本次包装核对的State及初始值 |
| app/evaluation.py | 冻结评测集、检索指标、质量与回归门槛 |
| app/evaluation_live.py | 可选真实接口冒烟检查 |
| app/knowledge_index.py | 资料分块、来源元信息、索引构建/读取与版本校验 |
| app/embeddings.py | 本地CPU模型加载、片段与问题编码、向量归一化 |
| app/vector_index.py | 向量索引、资料/模型身份核对及余弦检索 |
| build_knowledge_index.py | 问答流程之外显式构建本地JSON片段索引 |
| app/tools.py | 汇总模型可见的工具清单 |
| knowledge/ | 本项目练习规则文本 |
| app/tool_runner.py | 工具校验反馈、执行与耗时记录 |
| app/storage.py | MySQL连接与SQL |
| app/session_repository.py | 会话持久化、条件与消息一致提交 |
| web/ | 简单HTML/CSS/JS聊天页 |
| app/config.py | 本地配置 |

建议先读sessions.py的merge_requirements，再看main.py和agent.py。完整例子、阅读指南与实测结果见第三步文档。

```powershell
# 单元行为测试，不调用模型
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 第三步真实验收，会产生API费用
.\.venv\Scripts\python.exe verify_step3.py
# 第四步A会话表及真实MySQL验证，不调用模型
.\.venv\Scripts\python.exe init_session_tables.py
.\.venv\Scripts\python.exe verify_session_storage.py
# 第四步跨进程真实Agent验收，会调用模型
.\.venv\Scripts\python.exe verify_step4.py
# 第五步小评测：真实查询、无商品、注入错误后修正
.\.venv\Scripts\python.exe verify_step5.py
# 第六步：初始化少量练习详情，再运行真实工具选择验收
.\.venv\Scripts\python.exe seed_product_details.py
.\.venv\Scripts\python.exe verify_step6.py
# 第七课：规则RAG、缺失资料与商品工具回归（真实模型调用）
.\.venv\Scripts\python.exe verify_step7.py
# 第八课：整理规则索引，再验收片段引用与原商品查询
.\.venv\Scripts\python.exe build_knowledge_index.py
.\.venv\Scripts\python.exe verify_step8.py
# 第九课：规则与商品详情协同、资料缺失（真实模型调用）
.\.venv\Scripts\python.exe verify_step9.py
# 第十课：真实本地向量检索对比和DeepSeek整链
.\.venv\Scripts\python.exe verify_step10.py
# 第十一课：三策略对比、混合规则与商品证据回答
.\.venv\Scripts\python.exe verify_step11.py
# 第十二、十三课各自的真实验收
.\.venv\Scripts\python.exe verify_step12.py
.\.venv\Scripts\python.exe verify_step13.py
# 最终整体验收（含全部测试、本地检索和真实计费API）
.\.venv\Scripts\python.exe verify_step14.py --with-agent
# 第15课：与第14课标签中的旧实现离线对照
.\.venv\Scripts\python.exe verify_step15.py
# 第15课：再加真实图流程验收，会调用计费API
.\.venv\Scripts\python.exe verify_step15.py --with-live
```

## 第一步独立调用回顾

first_call.py 只完成真实 DeepSeek 文本调用，不连接数据库；当前第三步后端另外使用MySQL，尚未引入知识库。

## 在 PowerShell 中运行

```powershell
# 在项目根目录执行（虚拟环境已创建时不必重复创建）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

在本地 `.env.dev` 填写 `DEEPSEEK_API_KEY`；`DEEPSEEK_MODEL` 指定模型名。
不要把密钥发到聊天或提交到版本库。配置读取优先级：进程环境变量 > `.env.dev`。

```powershell
.\.venv\Scripts\python.exe first_call.py
```

不需要激活虚拟环境，也不需要修改 PowerShell 执行策略。
VS Code 中执行 `Python: Select Interpreter`，选择 `.venv\Scripts\python.exe`。

## 关键代码

- `load_dotenv`：把本地配置载入环境变量；模型名没有写死在请求中。
- `messages`：`system` 说明回答风格，`user` 放这一轮问题。
- `client.post`：类似前端 `fetch`，但这里在 Python 中调用官方接口；`json=payload` 自动发送 JSON。
- `stream=False`：一次收取完整回答；`thinking` 关闭思考模式，`max_tokens` 限制输出长度。
- `choices[0].message.content`：第一条候选回答的文本。
- `usage`：输入、输出及总 Token 数；Token 是模型处理文本的单位，不等于汉字数，也不是金额。

成功标准：命令退出码为 0，收到非空真实回答，并输出三个 usage 计数。
此时只有模型调用；后续加上工具及执行循环才开始构建 Agent。

官方依据：[首次调用](https://api-docs.deepseek.com/)。
# search_goods
