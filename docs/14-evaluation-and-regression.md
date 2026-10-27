# 第十四课：评测与回归，把“感觉能用”变成可重复检查

本课不增加检索算法。我们把固定问题、预期知识片段、计分规则和真实接口检查保存下来，后续改代码能比较是否退步。

## 1. 为什么要分三层检查

| 检查 | 验证什么 | 不能证明什么 |
| --- | --- | --- |
| 行为测试 | 坏参数、引用、边界、失败路径和数据交接 | 真实模型一定理解正确 |
| 本地检索评测 | 哪些预期片段被找回、排在第几 | 最终回答每句话都正确 |
| 真实接口冒烟 | DeepSeek/MySQL、会话与工作流能协同运行 | 任意表达都可靠、生产性能达标 |

最终仍需人工对照正文看答案。本课没有用另一个LLM给答案打分，也没有把模型自称“正确”当验收依据。

## 2. 数据准备：问题旁边写清预期ID

[evals/retrieval_cases.json](../evals/retrieval_cases.json)保存8条学习样例，6条有资料、2条应无匹配。结构示例：

```json
{
  "id": "missing-package",
  "query": "具体SKU未提供盒装数量，应该怎样回答",
  "relevant_chunk_ids": ["KB-PACK-001-C002"]
}
```

relevant_chunk_ids是人工指定的期望相关片段集合，不是让模型自己生成的答案。空列表在这份评测集里表示“预期本地资料无法回答”。这不表示现实中没有相应规则。

样例沿用了课程中的问题，不是独立大型测试集；标签也有人工判断边界。因此下面的数字只描述这8条，不能外推准确率。

load_cases检查版本、重复样例ID、重复标签、标签是否对应现有片段，以及是否同时有正负样例。资料切块改变ID后，应先审查标签，不能继续拿旧标签计算。

## 3. 核心代码：输入ID列表，输出指标字典

在[evaluation.py](../app/evaluation.py)中：

```python
metrics = score_case(retrieved_ids, relevant_ids, k=3)
```

retrieved_ids来自真实检索结果的chunk_id，relevant_ids来自评测集。它不读取回答的文字，也不凭分数大小猜正确答案。

假设预期B，实际返回[A, B]：

| 指标 | 本项目含义 | 这个例子 |
| --- | --- | --- |
| Hit@3 | 前3条有没有至少一条相关片段 | 1 |
| Precision@3 | 截取前3条后，实际返回条目中相关的比例 | 1/2 |
| Recall@3 | 预期相关片段有多少比例被找回 | 1/1 |
| MRR@3 | 第一条相关片段名次的倒数 | 1/2 |

本项目Precision分母是实际返回数量，最多3；不是始终除以3。空结果的正例指标为0；完全无正例时汇总指标为null，不伪装为满分。

负例不混进正例的Hit/MRR：它单独记录abstained，结果为空才算预期拒答成功。两条负例一条正确为空、一条误召回，abstention_rate就是0.5。

重复结果ID直接判为评测输入异常，不允许通过重复一条正确结果抬高精确率。

## 4. 同一组问题跑四种策略

在[verify_step14.py](../verify_step14.py)中：

```python
for strategy in ("keyword", "semantic", "hybrid", "rerank"):
    # 临时指定策略，不改.env.dev
    passages = search_knowledge(SearchKnowledgeArgs(query=case.query, limit=3))
    ids = [p["chunk_id"] for p in passages]
    metrics = score_case(ids, case.relevant_chunk_ids)
```

实际循环还包含临时环境配置、错误记录、计时和指标汇总。每种策略使用相同问题、同一资料和相同最终limit。keyword不跑模型；semantic/hybrid使用本地向量；rerank还使用本地重排模型。

```text
评测JSON → RetrievalDataset对象 → 每条RetrievalCase
  → 四种策略各自返回passages
  → 提取chunk_id列表
  → score_case产生指标字典
  → aggregate_scores汇总
  → 质量门槛/基线比较
  → 保存报告
```

排序分数的尺度不同，所以比较“相关片段是否找到、排第几”，不直接比较关键词score与重排score谁大。

## 5. 为什么还要保存基线

固定绝对门槛只约束最终rerank策略：Hit@3至少0.8，MRR@3至少0.7，两条无资料例均应为空。这些是本课程选的门槛，不是行业标准，修改前应理解取舍。

首次通过会创建[14-retrieval-baseline.json](../outputs/14-retrieval-baseline.json)。以后同一批资料和配置运行，除绝对门槛外，还要求这五个指标不低于旧基线。

例如MRR从1降到0.8，虽然仍超过0.7绝对门槛，但相对旧基线已退步，检查会失败。

基线同时记录评测文件哈希、资料哈希、模型名、编码recipe、FastEmbed版本、向量阈值、候选数量、RRF常数等。身份不一致时不能直接比较，应审阅变更后显式更新。这里尚未记录模型权重文件哈希，不能当作完整模型版本管理系统。

失败报告也保存，但失败不会覆盖基线；不自动重试网络请求，也不为了让报告变绿而修改人工标签。

## 6. 一个命令怎样执行

```powershell
# 行为测试 + 真实本地检索；不请求DeepSeek/MySQL
.\.venv\Scripts\python.exe verify_step14.py

# 再加真实DeepSeek/MySQL冒烟，会产生API费用
.\.venv\Scripts\python.exe verify_step14.py --with-agent

# 资料/模型/评测集有意变更，先审阅结果，再显式建立新基线
.\.venv\Scripts\python.exe verify_step14.py --with-agent --update-baseline
```

脚本先以子进程运行全部unittest；通过后才做四策略评测。默认不会下载模型，使用前课已准备的本地缓存。真实接口检查是显式选项，报告明确passed/failed/skipped，未运行不冒充通过。

[evaluation_live.py](../app/evaluation_live.py)检查：商品查询确实调用搜索；同session_id换品牌时保留颜色/规格/预算；固定流程一次模型汇总；无SKU商品提前结束、零模型调用；非法SKU在入口拒绝。

真实接口会创建少量练习会话。固定工作流本身不写会话。报告移除session_id，保留回答、工具轨迹、用量和检查结果供复核。

## 7. 验收后看哪些文件

| 文件 | 重点看什么 |
| --- | --- |
| [14-regression-report.json](../outputs/14-regression-report.json) | passed、checks、四策略summary、逐题结果、live_checks状态 |
| [14-retrieval-baseline.json](../outputs/14-retrieval-baseline.json) | 与哪些资料/模型/配置对应，旧指标是什么 |
| [test_step14.py](../tests/test_step14.py) | 指标口径、空值/重复ID、标签、回归门槛的确定性测试 |

报告的passed为本次所请求检查的结果；不带--with-agent时live_checks明确为skipped，不能据此声称真实接口已验收。本次代跑将使用--with-agent。

2026-10-22实际执行verify_step14.py --with-agent：100项测试通过，四策略各8例全部执行，真实接口检查passed，初始基线创建，命令退出0，总37.44秒。6条有资料问题上的Hit@3为keyword 4/6、semantic 5/6、hybrid 6/6、rerank 6/6；MRR分别为0.6667、0.7222、1、1。两条负例四策略均为空；Hybrid与Rerank的结果指标相同，不能说重排已带来额外提升。

另外以独立报告路径执行一次本地基线复核：[14-baseline-recheck.json](../outputs/14-baseline-recheck.json)。再次100项测试、四策略评测及五个baseline指标比较全部通过，22.69秒；该次未请求真实接口，live_checks=skipped。原14-regression-report.json保留上一次完整真实验收，不用“未运行”覆盖“已真实通过”的证据。

本课仍未实现多用户生产压测、语义事实自动核验、长期线上质量监控、模型权重归档。至此主课程完成，可以先人工验收，再按实际问题选择优化，而不是继续无目的堆功能。
