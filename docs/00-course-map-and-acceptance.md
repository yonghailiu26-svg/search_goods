# 课程总目录与本地验收

当前主线第1～14课已实现。Python、DeepSeek官方接口、本地MySQL与练习规则，纯文本；第四课分为会话存储和上下文恢复两部分。

## 1. 学习顺序

| 课次 | 能力 | 文档 |
| --- | --- | --- |
| 1 | Python环境与真实模型调用 | [01](01-first-call.md) |
| 2 | FastAPI、MySQL及商品查询工具 | [02](02-fastapi-product-tool.md) |
| 3 | 多轮条件状态与合并 | [03](03-multi-turn-state.md) |
| 4A/4B | 会话持久化、上下文恢复、简单聊天页 | [04A](04a-session-storage-and-chat-ui.md)、[04B](04b-agent-persistent-context.md) |
| 5 | 参数纠错、执行上限与诊断 | [05](05-agent-recovery-and-evaluation.md) |
| 6 | 工具选择与串联 | [06](06-agent-tool-selection.md) |
| 7 | 最小规则RAG | [07](07-minimal-rag.md)、[执行器补充](07a-rag-tool-and-execute-knowledge.md) |
| 8 | 文档分块与索引 | [08](08-knowledge-chunks-and-index.md)、[数据流白话版](08a-rag-data-flow.md) |
| 9 | 规则与商品证据关联 | [09](09-evidence-and-product-answers.md) |
| 10 | 本地Embedding | [10](10-local-embedding-retrieval.md) |
| 11 | 关键词/向量候选RRF融合 | [11](11-hybrid-retrieval.md) |
| 12 | 问题与候选正文的交叉编码重排 | [12](12-cross-encoder-reranking.md) |
| 13 | Agent与固定工作流边界 | [13](13-agent-and-workflow.md) |
| 14 | 固定评测集、指标与基线回归 | [14](14-evaluation-and-regression.md) |

最近三课按“背景问题→执行时机→核心代码输入输出→对象变化→验收→限制”组织。建议一课读完、运行例子，再进入下一课。

## 2. 当前运行链路

```text
自由聊天：/chat
 → 恢复会话条件与历史
 → Agent决定商品/详情/规则工具
 → 规则默认走关键词+向量召回、RRF、候选重排
 → 工具正文交给模型
 → 引用与混合证据校验
 → 成功保存会话

固定包装核对：/workflows/package-check
 → 校验sku
 → Python固定查包装规则、查SKU详情
 → 不存在则提前返回；存在则一次模型汇总
 → 证据校验后返回，不保存聊天会话
```

当前默认检索策略为rerank。已有.env.dev如果显式指定hybrid/semantic/keyword，会保留该选择；想验收最终链路，请本地改为KNOWLEDGE_RETRIEVAL=rerank并重启。Key、MySQL密码继续在本地，不发到聊天。

## 3. 怎么启动、怎么准备资料

已经初始化商品库/详情/会话表时，不必再次初始化。新的环境可按前课逐项准备，不能跳过本地配置。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --no-cache-dir
# 原文/分块参数变动后执行前两条；现有产物匹配时不用重建
.\.venv\Scripts\python.exe build_knowledge_index.py
.\.venv\Scripts\python.exe build_vector_index.py
# 首次需要下载约570MB；本次已经准备好，模型在D盘work/models
.\.venv\Scripts\python.exe prepare_reranker.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

聊天页`http://127.0.0.1:8000/`；固定工作流在`http://127.0.0.1:8000/docs`。若本机8000不可绑定，可把端口和访问地址一起改成8001。本轮未启动常驻后台服务。

## 4. 你之后怎么验收

先运行整体验收：

```powershell
.\.venv\Scripts\python.exe verify_step14.py --with-agent
```

它运行全部测试、本地四策略检索及真实DeepSeek/MySQL检查；API部分会计费。不带--with-agent时只做测试和本地检索，报告中真实接口明确标为skipped。

再人工检查这几组场景：

1. /chat找“得力黑色0.5mm签字笔，单价不超过5元”，然后同会话“换晨光，其他不变”。对照current_requirements。
2. /chat问“只改品牌、其他不变时，预算和规格要保留吗”，对照引用、tool_trace中的retrieval和两路/重排明细。
3. /workflows/package-check提交SKU DEMO-PEN-0000，检查两工具固定顺序、一次模型调用，以及实际包装数量未知的回答。
4. 同接口提交DEMO-PEN-0001检查缺包装提示，提交DEMO-NOT-EXIST-999检查零模型请求和not_found。

结构校验通过仍需阅读原文核对语义。特别留意“未知”是否被写成确定数量，规则原则是否被误当成具体SKU事实。

## 5. 本次代跑结果（2026-10-22）

| 验收 | 结果/产物 |
| --- | --- |
| 第十一课 | 74项测试通过；5组检索对比、3组真实接口；[报告](../outputs/11-hybrid-evaluation.json) |
| 第十二课 | 累计82项测试通过；4组本地对比、2组真实接口；[报告](../outputs/12-rerank-evaluation.json) |
| 第十三课 | 累计91项测试通过；3组工作流及1组Agent比较；[报告](../outputs/13-workflow-evaluation.json) |
| 第十四课 | 最终100项测试通过，4策略×8条样例、真实接口检查通过；[报告](../outputs/14-regression-report.json) |
| 初始基线 | 首次通过后创建，后续变更需要明确比较或更新；[基线](../outputs/14-retrieval-baseline.json) |
| 基线复核 | 再次本地执行、五项指标与原基线比较均通过；[复核报告](../outputs/14-baseline-recheck.json)，这次未调用真实接口 |

固定样例上的Hit@3：keyword=4/6、semantic=5/6、hybrid=6/6、rerank=6/6；两条无资料问题四策略均返回空。Hybrid/Rerank在这些样例上的指标相同，重排没有在这组数据上显示额外排名收益。它也尚未过滤Top3中的所有无关资料，不能按6/6宣传真实业务准确率。

## 6. 到这里先停止增加能力

本主线没有加入Milvus、前端流式、图片、表格、报价单、多worker协调或生产压测。模型/索引版本和语义事实校验也仍有文档所列限制。后续先依据你的人工验收反馈改进，再决定是否学习这些选修内容。
