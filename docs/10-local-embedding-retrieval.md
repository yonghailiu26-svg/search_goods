# 第十课：本地Embedding语义检索

当前代码默认策略已进入[第十二课重排](12-cross-encoder-reranking.md)，包含[第十一课混合检索](11-hybrid-retrieval.md)。本课向量构建和单路语义检索仍沿用；复现本课可设置KNOWLEDGE_RETRIEVAL=semantic。第十课验收脚本会显式选择semantic。

**第一次接触向量，先读下面的“0. 背景原理”，再看后面的模块和代码。** 不需要先学向量数据库，本项目目前用JSON文件和Python循环完成这件事。

## 0. 背景原理：为什么这样构建向量

### 0.1 我们到底在解决什么问题

你已经有一段知识：

```text
如果商品没有提供盒装数量，应明确回答无法确定，不得根据常识猜测。
```

用户却可能问：

```text
每包里几根都没写，能按经验估一个吗？
```

两句话用词不同，但意思相关。原来的关键词程序主要比较“有没有出现作者指定的词”；现在希望多一种方法，比较文本含义的接近程度。

所以第一步是找一个已经训练好的文本编码模型，给两段文字分别生成数字表示，再比较这两组数字。我们下载的BGE就是做这个工作的模型。

**我们没有用这五个片段训练模型；现在做的是调用已有模型进行编码。** DeepSeek依然负责读资料并回答，BGE负责产生便于检索的数字表示。

### 0.2 向量是什么，512维又是什么

先把向量理解成“有固定顺序的一组数字”：

```python
vector = [0.12, -0.08, 0.31]  # 三维示意，不是真实模型输出
```

本课模型返回512个浮点数，所以叫512维向量。它不是512条知识，也不是512个关键词。一个片段对应一个512维向量；五个片段就得到五个向量。

这些数字由模型计算，不是我们手工定义“第1项是品牌，第2项是价格”。模型经过先前的训练，能够让不少语义相关的文本在向量比较时得分较高，但并不保证每次都匹配正确。

也不要把向量当作文件哈希：哈希主要帮助判断内容是否变化，本课向量主要用于比较文本的接近程度；二者用途不同。

### 0.3 向量数据库负责什么，为什么这节还没用它

可以先分清三种工作：

| 工作 | 当前由谁负责 | 你要理解的作用 |
| --- | --- | --- |
| 把文字算成向量 | 本地BGE模型，经embeddings.py调用 | 文字变成一组数字 |
| 保存向量并找到接近的向量 | knowledge-vectors.json + vector_index.py的循环 | 保存数字，比较数字，返回片段ID |
| 根据原文组织回答 | DeepSeek | 阅读检索正文，形成回答 |

向量数据库主要服务于中间这部分：保存向量及关联信息，支持相似度查询。它不是一个“天然知道公司规则”的模型；单纯建一个库也不会自动生成向量或正确回答。

本项目目前只有五个向量，逐条比较很容易。以后数量变大，可以考虑用数据库和适当的向量索引管理、加速检索；许多大规模方案还会使用近似查找，需要权衡速度和召回。这里先不展开这些算法，也不需要安装Milvus。

熟悉MySQL的话，可以先把一条向量记录类比成：

```text
chunk_id：片段的关联ID
values：这个片段的数字表示
```

它与正文文件通过chunk_id关联。本课核心查询是“找相似的向量”，不是按向量内容做字符串LIKE，也不是用向量推断商品库存。

### 0.4 为什么提前生成片段向量，而不是每次聊天都重新生成

知识片段通常比用户问题变化少。已有五块资料时，每次聊天重新编码这五块，会重复计算相同内容。

因此分成两个时机：

```text
准备资料：五个片段 → 算五个向量 → 保存，之后反复使用
每次查询：一个问题 → 算一个向量 → 与保存的五个向量比较
```

这就是build_vector_index.py单独作为命令的原因。类似前端提前生成静态数据产物，再由运行时读取；不过这里生成的是可供检索的数字表示。

原文或分块、模型发生变化后，旧向量可能不再对应当前资料，所以要重建并校验版本。模型缓存和向量索引也不是同一个东西：work/models里是用于计算的模型文件，outputs/knowledge-vectors.json里是本项目资料的计算结果。

### 0.5 对照build_vectors，逐步看为什么这样写

先看这一行：

```python
vectors = embed_documents([
    chunk.title + "\n" + chunk.content
    for chunk in index.chunks
])
```

这里的index是第八课的KnowledgeIndex，里面有五个ChunkRecord。执行后依次发生：

```text
1. index.chunks：五个片段对象
2. 取每片的标题和正文：得到五个str组成的列表
3. embed_documents：交给已经训练好的本地模型
4. 返回五个list[float]，每个包含512个数
```

传“标题+正文”是本项目选择的编码输入：标题可以补充该片段的主题。只传正文也可以设计成另一种方案，但要重新生成向量并检查效果，不能认为加标题必然更准。

然后，在embed_documents内部：

```python
vectors = [normalize(vector) for vector in model.passage_embed(texts)]
```

passage_embed逐项产生资料向量，外层列表推导式逐项归一化、收集结果。normalize还会把数值转为普通Python float，方便保存成JSON。

回到build_vectors，为什么还要检查数量和维度？因为后面需要把每个片段与它的向量对应起来。如果五块资料只得到四个向量，或者有的向量512项、有的却384项，继续保存就可能漏资料或无法比较。

接下来这段把关联保存下来：

```python
VectorRecord(chunk_id=chunk.chunk_id, values=vector)
for chunk, vector in zip(index.chunks, vectors)
```

两边按编码时的相同顺序配对，形成五个VectorRecord。实际结构是：

```text
VectorIndex：一个总对象
  model_name / recipe / dimension / corpus_hash等身份信息
  vectors：五个VectorRecord
    ├─ 条件C001 → 512个浮点数
    ├─ 包装C001 → 512个浮点数
    ├─ 包装C002 → 512个浮点数
    ├─ 包装C003 → 512个浮点数
    └─ 价格C001 → 512个浮点数
```

最后write_vectors把这个总对象转成JSON，保存到outputs/knowledge-vectors.json。完整正文仍在第八课的knowledge-index.json里，通过chunk_id找回；不需要在向量文件里再抄一遍正文。

### 0.6 为什么归一化，再用点积比较

本项目选择余弦相似度，可以先理解为比较“两个向量指向的方向有多接近”。为了让后面的点积直接表示这种比较，先把每个向量的长度调整成1。

用两维示意，向量[3, 4]的长度是5：

```text
[3, 4] → 每项除以5 → [0.6, 0.8]
[30, 40] → 每项除以50 → [0.6, 0.8]
```

它们原本方向一样，只是幅度不同；归一化后就一致了。这里的长度是数字向量的几何长度，不是句子的字数。

现在比较归一化后的问题向量和片段向量：

```python
score = sum(left * right for left, right in zip(query, document_vector))
```

这行就是把相同位置的数字相乘，再把结果加起来。两边都归一化后，这个点积等于余弦相似度。**归一化不是所有检索系统必须采用的步骤，而是为了配合本项目选择的相似度计算。**

### 0.7 保存了向量，查询时为什么还要读取正文

向量只帮助我们找候选片段，不能直接替代规则正文，也不能靠它还原一段原文。

```text
问题str
  → embed_query：512维问题向量
  → 和五个片段向量比较
  → 得到候选chunk_id与分数
  → 取回该chunk_id的content和来源信息
  → 原来的passages
  → tool消息中的正文
  → DeepSeek回答
```

问题与资料使用对应的同一套模型编码，并采用相同的归一化约定。只看“都是512维”还不够，不同模型的坐标表示不一定可混用，所以索引里也保存模型名和编码方式。

相似度高只是“值得看看这段”，还需要阈值、原文内容和后面的证据回答。它不等于这段一定能解决用户问题，更不等于具体商品有了资料中没有提供的参数。

### 0.8 这几份文件为什么分开

| 文件 | 可以先把它理解成 | 主要输入 → 输出 |
| --- | --- | --- |
| build_vector_index.py | 准备资料的命令入口 | 片段索引 → 调用构建、保存 |
| embeddings.py | 文字编码器 | 字符串 → 数字向量 |
| vector_index.py | 向量结果管理与比较器 | 片段/向量 → 保存、校验、相似度结果 |
| knowledge.py | 对Agent暴露的检索入口 | SearchKnowledgeArgs → passages |

因此你不用先把库源码里的模型推理全部读懂。先读build_vectors的“取文字→调用编码→绑定ID→包装对象”，再读search_semantic的“编码问题→比较→找回正文”，就抓住了这课的主线。

---

这节只替换“怎样找相关片段”，沿用原来的工具、passages、引用和第九课证据回答。

例子：用户问“每包里几根都没写，能按经验估一个吗”。原来的作者关键词是包装、盒装、换算等，这句话没有直接命中；这次尝试用向量找到意思接近的规则。

## 1. 先分清两个模型的工作

| 模型 | 收到什么 | 返回什么 | 在哪里运行 |
| --- | --- | --- | --- |
| BGE中文向量模型 | 片段文本或问题文本 | 一串浮点数，本课为512维 | 本机CPU |
| DeepSeek回答模型 | 问题、工具说明、检索后的正文等messages | 工具调用或回答 | 原有官方接口 |

本课安装FastEmbed运行本地模型，实际选择`BAAI/bge-small-zh-v1.5`；模型缓存存放在项目`work/models`，本次约95MB，不包含新增Python依赖大小。没有新增API Key，也没有把聊天模型换成BGE。

实现使用FastEmbed的`passage_embed`编码资料、`query_embed`编码问题，参考[FastEmbed官方示例](https://qdrant.github.io/fastembed/qdrant/Retrieval_with_FastEmbed/)。中文模型及相似度使用说明见[BGE作者模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5/raw/main/README.md)。

## 2. 改在什么时候：仍然是两条路线

```text
准备资料时：
Markdown → 第八课片段索引knowledge-index.json
         → 取出每个片段的标题+正文
         → 本地模型生成片段向量
         → 保存knowledge-vectors.json

用户聊天时：
用户问题 → DeepSeek提出search_knowledge(query)
         → 本地模型把query转成问题向量
         → 与已保存的片段向量比较
         → 用命中的chunk_id找回原正文
         → 原来的passages → tool消息 → DeepSeek回答
```

**片段向量提前算好；查询时只新算问题向量。** 真正给DeepSeek的是命中的规则正文，不是这512个数字。

本课语料只有5块，直接遍历5个向量即可，没有接向量数据库。向量文件不是“另一个商品数据库”。

## 3. 第一站：片段多了一份数字表示

第八课的片段继续保留原文：

```text
knowledge-index.json
  chunks
    └─ chunk_id: KB-PACK-001-C002
       content: 缺少盒装数量时如何回答的完整正文
       source/start_line/end_line/source_version等原有信息
```

第十课另存一份向量：

```text
knowledge-vectors.json
  model_name: BAAI/bge-small-zh-v1.5
  dimension: 512
  recipe: fastembed-query-passage-v1
  corpus_hash: 这批资料和切块参数的内容哈希
  vectors
    └─ chunk_id: KB-PACK-001-C002
       values: [0.012, -0.034, ... 共512个数字]
```

上面的数字只是结构示意，不是实际向量截取。文件中还含schema_version等校验字段。

**用chunk_id把“数字”和“正文”关联起来。** 每个数字不是人工定义的字段，不能把第1维理解为品牌、第2维理解为价格。我们主要使用整个向量之间的距离关系。

`corpus_hash`用于核对向量是否仍对应当前资料；它不是片段的语义向量。名称里都有hash或数字，不代表用途相同。

## 4. 第二站：问题也变成向量，再比较相似度

`embed_query(query)`返回`list[float]`，同样512项。问题与资料必须使用对应的同一套编码模型，维度相同也不足以说明不同模型的向量可以混用。

本课先把向量归一化，再计算点积：

```python
score = sum(left * right for left, right in zip(query, document_vector))
```

先用两维示意：

```text
问题向量 [1, 0]
片段A    [1, 0]     相似度 1
片段B    [0.6, 0.8] 相似度 0.6
片段C    [0, 1]     相似度 0
```

以上三组都已归一化，所以点积等于余弦相似度。实际代码对512维逐项相乘再求和，方法相同。

分数高只表示模型表示下更接近，**不是答案正确率、不是这条规则一定适用的概率**。它也不是第七课“命中几个关键词”的整数score，两种分数不能直接相加。

## 5. 第三站：过滤、排序、还原passages

流程对应[vector_index.py](../app/vector_index.py)的`search_semantic`：

1. 加载并校验片段向量索引。
2. 编码query，核对维度。
3. 遍历全部片段向量，计算相似度。
4. 过滤低于阈值的结果，再按分数排序，取前limit条。
5. 通过chunk_id找到片段正文，返回字典列表。

例如本次真实检索返回的一条结果，下面为字段节选：

```json
{
  "chunk_id": "KB-PACK-001-C002",
  "source_id": "KB-PACK-001",
  "content": "该小节完整正文，此处仅为占位展示",
  "score": 0.621119,
  "score_kind": "cosine",
  "retrieval": "semantic"
}
```

实际返回还含文件路径、行号、版本等元信息。`content`不会变成向量；`tool_runner → result.passages → tool消息`继续沿用前课。

全部分数太低就返回空列表，后续仍得到`no_knowledge`。不能因为向量总能排出第一名，就强行拿无关资料作为依据。模型或索引故障则报错，不会偷偷退回关键词并伪装语义检索成功。

## 6. 阈值0.58从哪来，有什么限制

默认`KNOWLEDGE_MIN_SCORE=0.58`是根据当前五个片段的少量正例/无关例观察设置的，属于本项目练习参数，不是通用标准。

本次探测中，无资料的保修表达最高分约0.51～0.55；几个相关改写约0.59～0.63，因此暂选0.58。换模型、资料、编码方式后要重新观察。

阈值越低，容易混入无关资料；越高，容易漏掉相关资料。只看这几个问题不能证明准确率，也不能保证所有保修问法都会被拒绝。

实测仍有噪声：条件修改问题的第一条是正确规则，但Top3也带了包装片段。有一个探测问法还把价格排在条件规则前面。这节没有解决这些问题；后续混合检索/重排再逐步比较。

## 7. 为什么要检查模型、版本和维度

加载时核对模型名、编码recipe、资料哈希、片段ID集合、维度、有限数值及归一化长度。向量数量不能漏块或重复。

第八课先检查原文件是否变化；第十课再检查当前片段是否与向量对应。改了文档、小节、分块参数或模型后，要重建相应产物。

构建完整向量结果后才通过临时文件替换原索引；生成失败不预先清空旧文件。旧文件若已不匹配当前资料，仍会被拒绝使用。

模型按进程懒加载并缓存，线上查询设置`local_files_only=True`，不会在用户请求中自动下载模型。首次显式构建命令允许下载公开模型；Windows无符号链接时的缓存提示不影响本课运行，不需要为此修改系统权限。

目前按模型名及编码recipe校验，没有归档权重文件哈希或历史模型版本；更换缓存中的权重也应重新构建。长文本会受模型Token上限影响，本课260字符的中文片段不代表对任意更长资料都无需检查截断。

## 8. 修改地图与阅读顺序

| 文件 | 负责什么 |
| --- | --- |
| [embeddings.py](../app/embeddings.py) | 本地模型加载，片段/问题编码，归一化 |
| [vector_index.py](../app/vector_index.py) | 向量构建、保存、身份校验、相似度排序 |
| [build_vector_index.py](../build_vector_index.py) | 显式准备模型与资料向量的命令 |
| [knowledge.py](../app/knowledge.py) | 根据配置选择语义或旧关键词检索，工具名保持不变 |
| [test_step10.py](../tests/test_step10.py) | 小维度可控夹具验证算法、坏索引、故障边界 |
| [verify_step10.py](../verify_step10.py) | 真实本地模型对比，以及真实DeepSeek/MySQL整链验收 |

先读`search_knowledge → search_semantic`，理解问题如何找回正文；再看`build_vectors`和`embed_documents`理解向量提前怎样生成。Agent循环与第九课evidence.py没有改动。

## 9. 本地配置和启动

默认已经使用semantic；以下非敏感配置可按需填写到`.env.dev`，Key保持原配置：

```dotenv
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_RETRIEVAL=semantic
KNOWLEDGE_MIN_SCORE=0.58
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --no-cache-dir
# 修改原文/切块参数后，按这个顺序执行
.\.venv\Scripts\python.exe build_knowledge_index.py
.\.venv\Scripts\python.exe build_vector_index.py
# 模型和向量已经准备好，启动原聊天服务
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

首次构建需要联网下载模型，后续使用本地缓存。模型文件位于`work/models`并已加入忽略规则。仅换模型且正文未变时，可只重建向量；更换为其他模型前仍要确认本地依赖、Token限制及检索效果。

想对比旧方法，把`KNOWLEDGE_RETRIEVAL`改成`keyword`并重启/重载服务即可；本课不是把两种排序混在一起。配置文件的修改可能不会触发Uvicorn的Python代码重载，改配置后建议重启。

聊天页可试：“请只查本地规则：每包里几根都没写，能按经验估一个吗？” 在tool_trace里确认`retrieval=semantic`；在verify脚本中还会直接比较原始问句，避免只看到模型把问题改写成关键词后的效果。

## 10. 本次验证结果

66项行为测试及依赖检查通过；旧关键词专项测试显式选keyword，新增8项用可控向量夹具测试，不在单元测试中下载或加载真实模型。真实模型结果另见[10-semantic-evaluation.json](../outputs/10-semantic-evaluation.json)。

五个直接检索样例中，三个相关问题关键词均0命中，向量首条分别为价格、包装和条件规则；两个无关问题经阈值过滤为空。两题正例更换了探测措辞，一题复用探测例，不能当作独立大规模评测。

最终两组真实DeepSeek+本地MySQL整链通过：规则回答2次模型请求，输入5463/输出326/总5789，3.26秒；规则与SKU协同回答2次请求，输入5301/输出395/总5696，3.63秒。后者确认沿用了第九课claims/unknowns与两类引用，条件未被修改。本地向量计算不计入DeepSeek Token，但消耗本机资源。

前一轮只包含规则问答的验收也实际调用过DeepSeek；最终报告不包含那次额外API用量。以上耗时是本机小样例观察，不是性能承诺。
