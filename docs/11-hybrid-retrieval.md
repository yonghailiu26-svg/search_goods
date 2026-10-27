# 第十一课：关键词与向量混合检索

后续代码默认已进入[第十二课重排](12-cross-encoder-reranking.md)。本课的hybrid策略保留，verify_step11.py会明确选择hybrid，文末配置可用于单独复现本课。

这课只加一个能力：**让同一个规则问题同时走关键词和向量两路检索，再把两个结果列表合成一个。** 第十课的向量模型、索引文件和第九课的证据回答继续使用。

## 1. 为什么做：两种方法各有能补上的地方

本机实际观察到：

| 问题 | 原关键词检索 | 原向量检索 | 本课要保留的能力 |
| --- | --- | --- | --- |
| 其他不变 | 命中条件规则 | 当前0.58阈值下为空 | 明确词语仍能找到资料 |
| 每包里几根都没写，能按经验估一个吗 | 未命中作者关键词 | 命中包装片段 | 换说法也可能找到资料 |
| 换品牌 | 命中条件规则 | 也命中条件规则 | 两路都找到时合并去重 |

混合检索并不是用两次DeepSeek去理解问题，而是Python把同一个query交给两个已有检索函数。本课关键词仍是作者关键词命中数，没有引入BM25、全文搜索或新模型。

## 2. 发生在什么时候，改动哪些文件

```text
用户问题 → DeepSeek提出search_knowledge(query, limit)
  ↓ 工具执行器校验参数
knowledge.py读取片段索引，并选择hybrid
  ├─ search_keyword：得到关键词候选列表
  └─ search_semantic：编码问题，得到向量候选列表
  ↓ fuse_rankings按chunk_id合并、按两路名次计分
最终passages列表
  ↓ 原来的result → tool消息 → DeepSeek回答 → 引用校验
```

图中是两路逻辑，当前代码顺序执行两个函数，没有新增线程或并发请求。

| 文件 | 本课变化 |
| --- | --- |
| [knowledge.py](../app/knowledge.py) | 默认选hybrid，组织两路候选再调用融合 |
| [hybrid_search.py](../app/hybrid_search.py) | 新增纯Python合并函数，保存两路明细 |
| [vector_index.py](../app/vector_index.py) | 允许内部传入候选数量，向量计算和过滤规则沿用 |
| [main.py](../app/main.py) | 更新课次标识 |
| [test_step11.py](../tests/test_step11.py) | 验证名次计分、去重、候选数量及失败边界 |
| [verify_step11.py](../verify_step11.py) | 真实本地三策略对比及DeepSeek/MySQL验收 |

不需要重新生成片段或向量；我们改变的是“已有候选怎样合并”，没有改变编码输入和模型。

## 3. 先看输入：两个list[dict]

两路原本都返回passages，所以可直接复用。以“其他不变 预算和规格应保留”为例，下面只展示ID和分数，实际每项都有正文、路径、版本等：

```text
keyword
  第1名：条件规则，score=1
  第2名：价格规则，score=1

semantic
  第1名：价格规则，score=0.612295
  第2名：条件规则，score=0.608402
  第3名：包装C001，score=0.592881
  第4名：包装C003，也通过当前向量阈值
```

不能直接算“1 + 0.608402”来衡量条件规则有多正确：前者是关键词命中个数，后者是余弦相似度，含义不同。

本课采用RRF（Reciprocal Rank Fusion），**用各自列表中的名次计分，不把原始分数直接相加。** 公式参考[Elastic官方RRF说明](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)；本项目自行实现，没有安装Elasticsearch。

## 4. 核心规则：每路按名次贡献一份分数

当前常数取60，每条结果的总分为：

```text
某一路第rank名的贡献 = 1 / (60 + rank)
两路都有这个片段 → 两份贡献相加
某一路没有 → 这一路不加分
```

rank从1开始；60是平滑排名差异的常数，不是相似度阈值，也不是返回条数。当前使用固定常数和两路等权，尚未做数据驱动调参。

用A、B、C三个教学片段示意：

| 片段 | 关键词名次 | 向量名次 | 融合分数 |
| --- | --- | --- | --- |
| A | 1 | 未进入候选 | 1/61 ≈ 0.01639344 |
| B | 2 | 2 | 1/62 + 1/62 ≈ 0.03225806 |
| C | 未进入候选 | 1 | 1/61 ≈ 0.01639344 |

B在两路都出现，因此最终排在两个单路第一名前。这表示两路有共同信号，并不证明B一定是正确依据。

前面的实际条件/价格例子中，两者分别是“关键词1向量2”和“关键词2向量1”，所以都得0.03252247。程序用chunk_id升序打破平局，条件规则排前；不能把这个平局说成算法已识别它语义更准确。

## 5. 对照核心代码：两路候选在哪里取得

在knowledge.py中：

```python
candidate_limit = integer("KNOWLEDGE_CANDIDATE_LIMIT", 10, 3, 50)
keyword = search_keyword(args, index, candidate_limit=candidate_limit)
semantic = search_semantic(args, index, candidate_limit=candidate_limit)
return fuse_rankings(keyword, semantic, limit=args.limit)
```

| 变量 | 类型 | 装什么 |
| --- | --- | --- |
| args | SearchKnowledgeArgs | 同一个query，以及最终返回条数limit |
| index | KnowledgeIndex | 第八课全部片段正文和来源 |
| keyword | list[dict] | 关键词按命中数排好的候选 |
| semantic | list[dict] | 向量按相似度排好、已通过阈值的候选 |
| 函数返回值 | list[dict] | 融合后最多limit个片段 |

为什么多了candidate_limit？假设最终只需要1条，如果两路都只取第1名，刚才两路都排第2的B就提前被丢掉，融合看不到它。

所以内部每路默认先取最多10条，合并后才取最终1～3条。当前一共只有5个片段，不会为了凑10条制造数据。

这是Python内部参数，不是放宽工具契约：模型可传的limit仍为1～3，不能给工具传limit=10。

## 6. 对照核心代码：怎样合成一个列表

进入hybrid_search.py：

```python
merged = {}
for retriever, passages in (("keyword", keyword), ("semantic", semantic)):
    ...
```

外层循环执行两次，分别处理两路列表。merged是以chunk_id为键的字典，类似JS的Record，用来将同一片段汇总到一项。

```python
chunk_id = passage["chunk_id"]
if chunk_id not in merged:
    # 复制这一片的正文、来源等，初始化分数和明细
    ...
record = merged[chunk_id]
record["score"] += 1.0 / (RRF_K + rank)
```

第一次遇到某片段时创建记录；另一路再遇到同一个chunk_id，就取出已有记录加分，不再新增一个重复片段。

每路内部另有seen集合防止自身重复ID多次加分。它在切换检索路时重新创建，所以同一片段可以从关键词、向量各得到一份贡献。

最后：

```python
ranked = sorted(merged.values(), key=lambda record: (-record["score"], record["chunk_id"]))
return ranked[:limit]
```

先按分数从大到小，相同时按片段ID；最终截取limit条。实际实现先用未舍入分数排序，再将展示分数保留8位。

## 7. 输出：正文不变，多了融合解释

下面是单个结果的结构示意，正文为占位。两个原始分数取“换品牌”这个真实查询：

```json
{
  "chunk_id": "KB-FILTER-001-C001",
  "source_id": "KB-FILTER-001",
  "content": "条件修改规则的完整正文，此处省略展示",
  "score": 0.03278689,
  "score_kind": "rrf",
  "retrieval": "hybrid",
  "retrieval_details": [
    {"retriever": "keyword", "rank": 1, "raw_score": 1, "raw_score_kind": "keyword_hits", "matched_keywords": ["换品牌"]},
    {"retriever": "semantic", "rank": 1, "raw_score": 0.597598, "raw_score_kind": "cosine"}
  ]
}
```

实际还保留路径、行号、版本等。顶层score现在是RRF分数；每路原分数移到retrieval_details。0.03278689不是低置信度，也不能拿它与第十课的0.58阈值比较。

0.58只在向量路内部使用；关键词路零命中就不返回；融合不再加一个余弦阈值。两路为空时返回[]，继续由执行器形成no_knowledge。

一条路正常执行但为空，可以使用另一路结果；一条路出错则停止本次检索，不会悄悄把“关键词单路结果”标成成功的hybrid。本课没有做自动降级策略。

## 8. 你本地怎么体验

默认策略已改为hybrid。如果.env.dev原来显式填写了semantic或keyword，需要将这项改成hybrid并重启服务；原Key不动：

```dotenv
KNOWLEDGE_RETRIEVAL=hybrid
KNOWLEDGE_CANDIDATE_LIMIT=10
KNOWLEDGE_MIN_SCORE=0.58
```

模型和两份索引已经准备好时，直接重启原服务即可，不必重新构建或安装新依赖。

在聊天页发：“请查本地规则：换品牌但其他不变时，应保留哪些条件？” 在/docs或Network看tool_trace里的passages：retrieval应为hybrid，retrieval_details列出每路贡献。

想看不经过模型改写的原问对比，可以运行：

```powershell
# 不调用真实模型的行为测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
# 含真实本地向量和DeepSeek/MySQL，API部分会计费
.\.venv\Scripts\python.exe verify_step11.py
```

## 9. 一小段可离线运行的合并演示

这些A/B/C只是教学ID，不是假装实际知识来源；直接测试合并函数，不调用模型或数据库：

```python
from app.hybrid_search import fuse_rankings

keyword = [
    {"chunk_id": "A", "content": "演示A", "score": 2},
    {"chunk_id": "B", "content": "演示B", "score": 1},
]
semantic = [
    {"chunk_id": "C", "content": "演示C", "score": 0.9},
    {"chunk_id": "B", "content": "演示B", "score": 0.8},
]
result = fuse_rankings(keyword, semantic, limit=3)
print([item["chunk_id"] for item in result])
# ['B', 'A', 'C']
print(result[0]["score"])
# 0.03225806
```

先确认两路输入→merged按ID累计→最终list这个变化，再读完整函数中的字典复制、去重和明细记录。

## 10. 验证与本课边界

74项行为测试通过，新增8项覆盖共同命中、不同分数尺度不影响名次融合、跨路及路内去重、空/单路结果、来源正文保留、不修改输入、扩大候选后再截断、故障及配置边界。

真实本地三策略对比的五例覆盖关键词补回、向量补回、共同命中、排序不同、未收录规则。它们用于验证本课机制，不代表整体准确率提高；部分问句沿用前课观察样例，不是独立评测集。

整链报告：[11-hybrid-evaluation.json](../outputs/11-hybrid-evaluation.json)。关键词规则仍比较简单；向量Top3仍可能混入无关片段；RRF只利用名次，不会阅读正文判定相关性，也不会修复两路都没召回的资料。

2026-10-22真实接口三组均通过、每组2次模型请求：规则回答总5034 Token/3.46秒；规则与商品协同总5950/3.26秒；未收录保修规则no_knowledge，总4111/2.73秒。这是本次小样例观察，非性能承诺。

最终的规则/商品事实仍需要第九课证据流程，ID合法仍不能保证结论语义正确。下一课可以研究重排，而本课不引入新模型、BM25、向量数据库或更复杂Agent框架。
