# 第十二课：候选片段重排

本课解决“已经找回几段资料，哪段更值得放前面”。第十一课RRF只看名次；这次用一个本地模型，把问题与每段正文一起读取，再给相关性分数。

## 1. 背景：Embedding与Reranker的区别

| 能力 | 输入 | 输出 | 在本项目的时机 |
| --- | --- | --- | --- |
| Embedding | 分别输入问题、资料 | 各自的向量 | 第十课召回候选 |
| RRF | 两路候选名次 | 融合名次分数 | 第十一课合并候选 |
| Cross-encoder重排 | 问题与一个片段组成一对 | 这个配对的相关性分数 | 本课，召回之后、交给DeepSeek之前 |

重排更仔细地读取问题与正文，但要对每个候选计算，因此只处理已召回的小集合。它找不到召回阶段漏掉的资料，也不生成回答。

采用FastEmbed当前支持的`BAAI/bge-reranker-v2-m3-int8`，ONNX权重约571MB，放在项目D盘work/models；需要更多内存和计算时间，不是原来的512维模型。参考[FastEmbed重排说明](https://qdrant.tech/documentation/fastembed/fastembed-rerankers/)与[BGE模型说明](https://huggingface.co/BAAI/bge-reranker-v2-m3)。本项目使用量化ONNX版本，不能直接拿其他实现的数值当作本机结果。

## 2. 代码修改发生在哪里

```text
search_knowledge(query, limit=3)
  → 关键词 + 向量，各取最多candidate_limit个候选
  → RRF合并后保留最多candidate_limit个
  → rerank_passages(query, candidates, limit=3)
  → 原来的passages → tool消息 → DeepSeek → 引用校验
```

核心新增[reranking.py](../app/reranking.py)；knowledge.py加rerank策略；[prepare_reranker.py](../prepare_reranker.py)只负责显式下载并检查模型。Agent、商品SQL、资料向量构建都沿用。

## 3. 跟着核心代码看输入输出

```python
scores = score_pairs(query, [p["title"] + "\n" + p["content"] for p in candidates])
```

query是问题字符串；candidates是RRF结果字典列表。列表推导式取出每个候选的标题加正文，形成list[str]。只有这小批文字交给重排模型，不是把整个知识库交给它。

score_pairs内部：

```python
model = get_reranker(reranker_name(), False)
scores = [float(score) for score in model.rerank(query, documents, batch_size=4)]
```

False表示线上只读本地模型；batch_size=4控制分批计算，每个候选都有一个对应分数。返回list[float]，顺序与documents相同，代码检查数量和有限数值。

```text
documents[0] → scores[0]
documents[1] → scores[1]
```

这里不是再得到512维数组，而是每个配对得到一个标量分数。本机可以得到正数或负数；原始分数不是概率，也不与余弦分数/RRF分数直接相加。

接着：

```python
for rank, (passage, score) in enumerate(zip(candidates, scores), start=1):
    result = dict(passage)
    result["rerank_details"] = {...}
    result.update(score=round(score, 6), score_kind="cross_encoder", retrieval="rerank")
```

zip按位置配对；rank记录重排前位置；dict(passage)复制外层字典，保留正文、来源、RRF明细。原RRF分数移到rerank_details，顶层score换为重排分数。最后按未舍入分数排序，再取limit条。

为什么RRF不能提前只取最终1条？如果正确资料原本第2名，重排看到的只有第1名，就没有机会把第2名提上来。所以先保留较大的候选窗口，重排之后再截断。

## 4. 输出对象长什么样

```text
passage
  chunk_id/content/source/source_version等：原样保留
  retrieval: rerank
  score_kind: cross_encoder
  score: 新的相关性分数
  retrieval_details: 原两路检索贡献
  rerank_details:
    model: 使用的重排模型
    input_rank: 重排前的名次
    input_score: 原RRF分数
    input_score_kind: rrf
```

没有候选直接返回[]，不加载重排模型。模型故障、分数数量不符或包含NaN/无穷大则停止，不把原RRF结果伪装成重排成功。

本课只重新排序，没有额外重排阈值：即使后几条分数很低，仍可能在limit内返回。不要认为引入重排就已消除无关资料；还需要结合评测决定过滤与候选数量。

## 5. 本地操作与验收

```powershell
# 第一次需要下载约570MB模型；此次实际下载用了约18分钟
.\.venv\Scripts\python.exe prepare_reranker.py
# 真实本地对比 + DeepSeek/MySQL，API部分计费
.\.venv\Scripts\python.exe verify_step12.py
```

默认策略为rerank；已有.env.dev显式写了hybrid时，需要改成`KNOWLEDGE_RETRIEVAL=rerank`并重启。旧hybrid/semantic/keyword仍可用于对比。换模型通过RERANK_MODEL配置，需先准备模型和重新评测；不需要重新计算资料Embedding。

82项行为测试通过，包括8项新增重排测试：配对与排序、正文不改、空候选跳过、坏分数拒绝、同分稳定、保留候选窗口、失败不降级、本地加载及适配器边界。真实报告位于[12-rerank-evaluation.json](../outputs/12-rerank-evaluation.json)。

2026-10-22两组真实接口均通过、每组2次模型请求：规则重排回答总5284 Token/4.85秒，重排与商品证据协同总6145/5.15秒。本地四例正确找回条件/包装/价格主题，无资料例为空；第十四课同组标签中重排与Hybrid指标相同，未据此宣称质量一定提升。

学习顺序：先看knowledge.py的rerank分支，再看rerank_passages的输入输出，最后看score_pairs如何调用库。先理解文本对和一个分数，不必先读ONNX推理实现。
