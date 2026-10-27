# 第八课白话版：跟着一条数据走完RAG

本次补充可直接看：[三份原始文件如何合成一个outputs索引](#three-files-to-one-index)，含逐站类型/数量表和当前完整JSON快照。

当前代码默认使用[第十二课重排](12-cross-encoder-reranking.md)，底层沿用第十课向量召回。本文保留第八课关键词教学案例；要复现文末输出，先设置KNOWLEDGE_RETRIEVAL=keyword，再运行示例。原文→片段→passages→tool消息的主线仍适用。

这篇先不研究切句子的正则。我们只追踪一个问题：

> 具体SKU没有提供盒装数量时，应该怎样回答？

你有前端经验，可以把下面的Python字典先类比成JS普通对象，把Python列表类比成JS数组。先分清“这个变量装的是什么”，再看算法。

## 1. 项目里其实有两条独立运行的路线

```text
A. 我们准备知识资料时

Markdown文件 → Python读取和分块 → KnowledgeIndex对象 → JSON索引文件
                                                保存到硬盘，命令结束

B. 用户聊天时

问题 → 模型请求查规则 → Python读取索引 → 筛出片段 → 再交给模型 → 回答
```

**先运行A生成资料，之后很多次聊天都能使用这份资料。** 每个用户问题不会重新运行A。A不用模型，不查MySQL；B中的规则检索也不查商品表，不过完整`/chat`接口仍会用MySQL恢复和保存会话。

本课里的“索引”，可以先理解为：**我们预先整理好并保存成JSON的一份片段清单。** 这里没有向量。

## 2. A路线第一站：原文件变成字符串

你编辑的是[KB-PACK-001.md](../knowledge/KB-PACK-001.md)，里面有标题、关键词和几个小节：

```markdown
# 包装与盒支换算规则
关键词：包装、盒装、一盒、每盒、换算、装箱、按支、包装数量

本文件是本项目的练习规则，不代表真实商家的政策。

## 盒支换算依据
……

## 缺少盒装数量时怎么回答

用户问某商品一盒多少支时，应先确定SKU，再查商品详情里的包装说明。
如果具体SKU没有提供盒装数量，应明确回答“未提供，无法确定”，不得根据品牌、常识或其他SKU猜测。
```

上面是节选，`……`表示省略；原文件里没有这个省略符。

运行`build_knowledge_index.py`后，它调用`build_index()`；`build_index()`再调用`read_sources()`。读取后得到：

```python
records = [
    (path, text, version),
    # 另外两份文档也各占一项
]
```

| 变量 | 实际类型 | 装着什么 |
| --- | --- | --- |
| path | Path对象 | 文件位置，例如指向knowledge/KB-PACK-001.md |
| text | str | 原文的整段字符串，换行统一为\n |
| version | str | 用原文件字节计算的64位内容哈希 |
| records | list | 多份文件的数据，每项是一个三元组 |

```python
for path, text, version in read_sources(directory):
```

这行就是“每次从列表拿出一份文件，同时把这一项里的三个值分别放到三个变量”。此时还没有检索，更没有向模型发送原文。

## 3. A路线第二站：整篇字符串变成几个ChunkRecord

`build_index()`把一份文件的数据交给：

```python
chunk_document(path, text, version, max_chars)
```

它返回`list[ChunkRecord]`，也就是“片段对象组成的列表”。包装文件目前得到三项：

```text
整篇text
  ├─ ChunkRecord：C001，盒支换算依据
  ├─ ChunkRecord：C002，缺少盒装数量时怎么回答
  └─ ChunkRecord：C003，按支销售与预算计算
```

只看我们关心的第二项。下面字段取自当前实现，版本值为展示缩写：

```python
chunk = ChunkRecord(
    source_id="KB-PACK-001",
    source="knowledge/KB-PACK-001.md",
    source_version="79f0ef1e...",  # 实际保存完整64位，不是这个缩写
    chunk_id="KB-PACK-001-C002",
    title="包装与盒支换算规则",
    section="缺少盒装数量时怎么回答",
    content="这一小节的完整正文",  # 展示占位；程序实际保存原文
    start_line=11,
    end_line=14,
    keywords=["一盒", "包装", "盒装"],
)
```

先只记住四类信息：

| 你关心的事 | 字段 |
| --- | --- |
| 这块叫什么 | chunk_id |
| 模型真正要读什么 | content |
| 从哪里抄来的 | source、start_line、end_line |
| 怎样找到它、怎样判断原文变没变 | keywords、source_version |

`ChunkRecord`是Pydantic对象，可以用`chunk.content`访问属性。它继承`SourceRecord`，因此自动具有父类的三个字段：source_id、source、source_version；继承并不是在运行时额外去查询另一份资料。

切块时内部还有`(start, end)`这样的数字对。它们只是原字符串的字符位置，用`text[start:end]`取正文；最终保存的`start_line/end_line`才是给人查原文的行号。字符位置和行号不是同一种东西。

## 4. A路线第三站：把所有资料装进一个KnowledgeIndex

`build_index()`里有两个列表：

```python
sources = []  # 一份文档一项：登记有哪些文件，以及它们的版本
chunks = []   # 一个片段一项：存放切出来的正文和位置等
```

每读取一份文档，就做：

```python
sources.append(SourceRecord(...))
chunks.extend(chunk_document(...))
```

`append`放入一个元素；`extend`把另一个列表中的元素逐个放进来。所以我们要得到平铺的`[片段1, 片段2, 片段3]`，而不是嵌套的`[[片段1, 片段2, 片段3]]`。

最终返回一个`KnowledgeIndex`对象，结构如下，省略了版本等附加字段：

```text
index：KnowledgeIndex对象
  ├─ sources：list[SourceRecord]，3项
  │    ├─ 条件修改文档的文件登记
  │    ├─ 包装文档的文件登记
  │    └─ 价格文档的文件登记
  │
  └─ chunks：list[ChunkRecord]，5项
       ├─ 条件修改C001
       ├─ 包装C001
       ├─ 包装C002 ← 例子关心的这一片
       ├─ 包装C003
       └─ 价格C001
```

**sources按文件计数，chunks按片段计数，数量不需要相等。**

随后`write_index(index)`做两件事：

```python
json_text = index.model_dump_json(indent=2)
# 将json_text写入outputs/knowledge-index.json
```

现在内存里的对象被转成JSON文本，并写到硬盘。命令退出后，内存对象消失，文件仍在。以后聊天靠这份文件重新恢复对象。

## 5. B路线第一站：模型先提出“帮我查规则”

用户在聊天页提交：

```json
{"message": "具体SKU没有提供盒装数量时，应该怎样回答？"}
```

`main.py → run_agent()`，Agent先向DeepSeek发送问题和工具说明。**工具说明告诉模型可以查什么，此时还没把索引里五个片段全发过去。**

为了看清后续数据，下面固定用这个教学工具调用；真实模型可能选择不同query和limit：

```python
message = {
    "content": None,
    "tool_calls": [{
        "id": "call_rules_1",
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "arguments": '{"query":"盒装","limit":1}',
        },
    }],
}
```

这是`llm.complete()`从API响应中提取后的message。外面原本还有`choices`等字段；这里省略了外层。

注意：`message`是字典，但`arguments`的值是**一个JSON字符串**。模型只是提出工具名和参数，真正执行由Python负责。

## 6. B路线第二站：字符串参数变成校验后的args

Agent按工具名字找到执行器，等效调用：

```python
result, requirements, tool_record = execute_knowledge(
    '{"query":"盒装","limit":1}',
    current={"brand": "得力"},
    search=search_knowledge,
)
```

`current`只是演示：假设之前已经有“得力”的商品条件，查规则不应改变它。

`execute_knowledge()`先执行：

```python
args = SearchKnowledgeArgs.model_validate_json(arguments)
```

数据变成：

```text
arguments：str，内容为 {"query":"盒装","limit":1}
       ↓ 解析JSON + 校验字段和范围
args：SearchKnowledgeArgs对象
       args.query == "盒装"
       args.limit == 1
```

然后才执行`passages = search(args)`。这里的`search`参数指向`search_knowledge`函数，因此实际进入`knowledge.py`。

`args`装查询条件，`index`装资料清单，二者用途不同。

## 7. B路线第三站：从全部chunks筛出passages

`search_knowledge(args)`先调用`load_index()`：

```text
硬盘JSON文本 → 校验格式、文件版本 → KnowledgeIndex对象
                                      ↓
                                  index.chunks
```

加载后拿到全部五个片段，再用query逐个匹配片段关键词。这一步是Python做的，不是模型在读取你本地的目录。

我们固定查`盒装`、`limit=1`，当前代码实际返回包装C002：C002、C003都命中“盒装”，同分时按chunk_id排序，C002在前。这个结果来自简单排序，并不表示算法理解了“缺失数量”。

对命中的`chunk`做：

```python
passage = chunk.model_dump(exclude={"keywords"})
passage.update({"score": len(matched), "matched_keywords": matched})
```

这是一次重要的类型变化：**Pydantic片段对象 → 普通字典，再补充本次查询的命中信息。**

```python
# passages的结构节选；实际还包含路径、完整版本、小标题和行号等
passages = [{
    "chunk_id": "KB-PACK-001-C002",
    "source_id": "KB-PACK-001",
    "content": "## 缺少盒装数量时怎么回答\n\n用户问某商品一盒多少支时……",
    "score": 1,
    "matched_keywords": ["盒装"],
}]
```

| 名字 | 包含什么 | 类型 |
| --- | --- | --- |
| index.chunks | 索引里全部片段 | list[ChunkRecord] |
| passages | 本次命中并截取前limit条的片段 | list[dict] |

两者没有同时保存两份不同知识；passages是这次从全部资料中选出的结果，并附上本次分数。

## 8. B路线第四站：执行器把passages装进result

`search_knowledge()`把列表返回给`execute_knowledge()`后，执行器包装为：

```python
result = {
    "status": "ok",
    "practice_data": True,
    "passages": passages,
}
```

并分别返回三个值：

```python
return result, dict(current), trace
```

| 返回值 | 谁使用 | 用途 |
| --- | --- | --- |
| result | agent.py | 给模型看的工具结果，包含正文 |
| dict(current) | agent.py | 继续保留原商品条件；本例仍是得力 |
| trace | agent.py，最终也随HTTP响应返回 | 记录调用工具、参数、结果与耗时，方便我们排查 |

`trace`也含结果，但不会因它存在就自动发送给模型。Agent给模型的内容来自下面明确追加的消息。

## 9. B路线第五站：result变成tool消息，再发给模型

Agent先保存观察记录：

```python
trace.append(tool_record)
```

再把工具结果转成字符串，追加到`messages`：

```python
messages.append({
    "role": "tool",
    "tool_call_id": "call_rules_1",
    "content": json.dumps(result, ensure_ascii=False),
})
```

`messages`列表此时大致是：

```text
0. system：系统指令
1. system：当前有效商品条件
2. user：缺少盒装数量怎么办？
3. assistant：我要调用search_knowledge，编号call_rules_1
4. tool：这是call_rules_1的结果，里面有passages正文
```

如有历史对话，会插在本轮user之前。assistant工具请求消息由Agent在执行工具前加入，tool消息在执行成功后加入；二者用同一个call id对应。

**下一次`complete(..., payload)`，才将包含规则正文的新messages发给DeepSeek。** 模型此时看到的是tool消息中的文字，没有直接打开本地索引文件。

`result`是Python字典，`json.dumps(result)`生成JSON字符串，放进tool消息的content。外层整个请求仍由`httpx`的`json=payload`序列化；不要把这两层JSON误当成同一个对象。

## 10. 最后一站：模型回答变成/chat响应

教学中的回答可能是：

```text
应明确回答“未提供，无法确定”，不能按品牌或常识猜测。
[KB-PACK-001-C002]
```

Agent检查引用ID是否属于本轮实际检索到的片段，再返回回答。最后HTTP响应的结构节选如下：

```text
/chat响应
  ├─ answer：模型的回答文本
  ├─ sources：本轮检索到的来源摘要列表
  ├─ tool_trace：工具执行记录列表，其中passages有正文
  ├─ current_requirements：本轮结束时的商品筛选条件
  └─ session_id、usage等已有字段
```

这里有一个容易混淆的同名变量：

| sources出现的位置 | 实际含义 |
| --- | --- |
| 硬盘索引、index.sources | 全部源文件登记，主要用来对照文件版本 |
| Agent内部的sources字典 | 本轮命中的来源，以citation_id为键去重 |
| /chat响应里的sources列表 | 将上面字典的values转成列表，交给调用方展示 |

Agent的来源摘要含路径、片段ID、行号和版本等，不含完整正文；正文保留在tool消息和tool_trace里。响应sources收集本轮检索到的片段，不保证模型逐一引用了每条。

## 11. 你只需要先分清这四种转换

| 写法 | 转换前 | 转换后 |
| --- | --- | --- |
| chunk.model_dump() | Pydantic对象 | Python字典 |
| index.model_dump_json() | Pydantic对象 | JSON字符串 |
| KnowledgeIndex.model_validate_json(text) | JSON字符串 | 校验后的Pydantic对象 |
| json.dumps(result) | Python字典 | JSON字符串 |

可以类比JS：`json.dumps`接近`JSON.stringify`；`model_validate_json`除了类似`JSON.parse`的解析，还按模型定义做校验并构造对象。

整条数据变化是：

```text
原文str
 → ChunkRecord对象列表
 → KnowledgeIndex对象
 → 硬盘JSON文本
 → 加载回KnowledgeIndex对象
 → 筛出passages字典列表
 → result字典
 → tool.content里的JSON字符串
 → 模型回答str
 → /chat响应中的answer
```

## 12. 五分钟离线观察，不调用模型和数据库

先保证已经有索引：

```powershell
.\.venv\Scripts\python.exe build_knowledge_index.py
```

下面代码可以在项目根目录的Python交互环境中运行。为避免终端编码干扰，也可以复制进项目中的临时`.py`再运行：

```python
from app.knowledge_index import load_index
from app.knowledge import search_knowledge
from app.schemas import SearchKnowledgeArgs
from app.tool_runner import execute_knowledge

index = load_index()
print(type(index).__name__, len(index.sources), len(index.chunks))
print(type(index.chunks[0]).__name__)

arguments = '{"query":"盒装","limit":1}'
args = SearchKnowledgeArgs.model_validate_json(arguments)
print(type(arguments).__name__, type(args).__name__, args.query, args.limit)

passages = search_knowledge(args)
print(type(passages).__name__, type(passages[0]).__name__)
print(passages[0]["chunk_id"], passages[0]["start_line"], passages[0]["end_line"])

result, current, record = execute_knowledge(
    arguments, {"brand": "得力"}, search=search_knowledge,
)
print(result["status"], len(result["passages"]), current)
print(record["tool"])
```

当前默认资料的输出应为：

```text
KnowledgeIndex 3 5
ChunkRecord
str SearchKnowledgeArgs 盒装 1
list dict
KB-PACK-001-C002 11 14
ok 1 {'brand': '得力'}
search_knowledge
```

建议先把这几个变量和实际输出对上。之后再回到[第八课实现细节](08-knowledge-chunks-and-index.md)，阅读如何按段落切块、如何检测旧索引，会更容易。

<a id="three-files-to-one-index"></a>

## 13. 补充：三个原始文件，最后怎样合成一个outputs文件

**是的，第八课最终写入的是 outputs/knowledge-index.json。三份原文的处理结果合在这一个文件里，原Markdown仍留在knowledge目录。**

先看磁盘上的对应关系：

~~~text
原始资料：knowledge/                  第八课生成物：outputs/
  KB-FILTER-001.md ──┐
  KB-PACK-001.md   ──┼── 读取、分块、汇总 ──→ knowledge-index.json
  KB-PRICE-001.md  ──┘
~~~

### 13.1 一张表看清每一步的格式和数量

下表对应当前默认260字符的分块配置；修改资料或参数后，片段数量可能变化。

| 步骤 | 处理后的数据 | Python类型或磁盘格式 | 当前数量 |
| --- | --- | --- | --- |
| 原始资料 | 三份可编辑的规则原文 | 磁盘上的.md文件 | 3个文件 |
| read_sources读取 | 每份得到路径、全文、版本；三项合成一个列表 | list[tuple[Path, str, str]] | 列表里3个三元组 |
| 登记源文件 | 只登记文件ID、相对路径和版本 | list[SourceRecord] | 3个对象 |
| chunk_document切片 | 保存各片段正文、来源、行号和关键词等 | 每份返回list[ChunkRecord] | 条件1块、包装3块、价格1块 |
| build_index汇总 | 把上面两类列表装入一个总对象 | KnowledgeIndex | 1个总对象，内含3条sources、5条chunks |
| model_dump_json序列化 | 把总对象转成JSON字符串 | str | 1个完整JSON字符串 |
| write_index写磁盘 | 将字符串以UTF-8写入文件 | .json文本文件 | 1个knowledge-index.json |
| load_index再次读取 | JSON字符串解析、校验，恢复成总对象 | KnowledgeIndex | 恢复为1个总对象 |

**中间的三元组、SourceRecord和ChunkRecord主要在内存中流转，不会各自产生一个单独输出文件。**

### 13.2 读取后三份文件是什么样

read_sources返回的是列表，里面按文件名排序：

~~~python
records = [
    (filter_path, filter_text, filter_version),
    (pack_path,   pack_text,   pack_version),
    (price_path,  price_text,  price_version),
]
~~~

这里的filter_path等名字只是为了把三项区分开，源码遍历时统一叫path、text、version。

以第二项为例：

~~~text
pack_path    → Path对象，指向项目中的knowledge/KB-PACK-001.md
pack_text    → str，整个包装文件的文本，包括标题、关键词、小标题、正文
pack_version → str，原文件字节的SHA-256内容哈希
~~~

读取时还有一个短暂变量raw，类型为bytes，是磁盘读取出来的字节；解码后才得到text字符串。raw不会作为字段放进最终索引。

### 13.3 为什么同时有sources和chunks

同一份包装文件会形成两种记录：

~~~text
包装原文
  ├─ 1个SourceRecord：说明“有这一份文件，它的路径和版本是什么”
  └─ 3个ChunkRecord：说明“这份文件切出了哪三段，各段正文是什么”
~~~

一个SourceRecord只有三个字段：

~~~python
{
    "source_id": "KB-PACK-001",
    "source": "knowledge/KB-PACK-001.md",
    "source_version": "原文件的完整64位内容哈希",
}
~~~

上面是字典外观示意，内存中实际创建的是SourceRecord对象；它**没有正文content**。

每个ChunkRecord都具有这三个来源字段，再加上：

~~~text
chunk_id    片段ID，例如KB-PACK-001-C002
title       文档标题
section     这一片所属的小标题
content     这一片的原文正文
start_line  原文起始行
end_line    原文结束行
keywords    这一片保留的作者关键词列表
~~~

所以这两个字段的分工是：

~~~text
sources：文件登记，用于检查当前文件清单和版本是否匹配
chunks：知识正文，用于后续检索并交给模型
~~~

chunks中的source_id不是另外一份规则，也不是MySQL里的商品ID；它只是指明这个片段属于哪份文档。

### 13.4 三份文件最终如何放进总对象

在build_index中，每处理一份文件就做两件事：

~~~python
sources.append(SourceRecord(...))
chunks.extend(chunk_document(path, text, version, max_chars))
~~~

完整处理后的分组关系：

| 原始文件 | sources里的登记 | chunks里的片段ID |
| --- | --- | --- |
| KB-FILTER-001.md | KB-FILTER-001，一条 | KB-FILTER-001-C001 |
| KB-PACK-001.md | KB-PACK-001，一条 | KB-PACK-001-C001、C002、C003 |
| KB-PRICE-001.md | KB-PRICE-001，一条 | KB-PRICE-001-C001 |

注意包装表格中的C002、C003省写了前缀，实际都带KB-PACK-001-。

最终不是“三个KnowledgeIndex”，而是：

~~~text
index：一个KnowledgeIndex
  schema_version  = 1                    索引数据结构的版本
  chunker_version = "paragraph-v1"        分块算法版本
  max_chars       = 260                  每片字符上限
  built_at        = 本次构建时间字符串
  sources         = [文件登记1, 文件登记2, 文件登记3]
  chunks          = [条件C001, 包装C001, 包装C002, 包装C003, 价格C001]
~~~

sources、chunks是两个并列列表；chunks按source_id关联来源，不是按列表位置一对一关联。因此不能用sources[2]去推断chunks[2]属于哪个文件。

### 13.5 最后写进outputs的JSON对象到底长什么样

write_index内部调用：

~~~python
json_text = index.model_dump_json(indent=2)
~~~

这里没有先要求你手动转成dict；Pydantic可以直接把总对象及其内部对象转成JSON文本。接着先写knowledge-index.json.tmp，再替换为最终的knowledge-index.json；.tmp是写入过程中的临时文件，不是另一份正式知识库。

JSON中只有对象、数组、字符串和数字等数据，**不会保存“KnowledgeIndex”“SourceRecord”“ChunkRecord”这些Python类名**：

~~~text
Python内存                        JSON文件里
KnowledgeIndex对象       →       最外层 { ... }
list[SourceRecord]       →       "sources": [ { ... }, { ... }, { ... } ]
list[ChunkRecord]        →       "chunks":  [ { ... }, ...共5项 ]
~~~

下面可展开查看当前文件的完整快照，所有来源和片段都保留，没有省略正文。构建时间、内容哈希、行号等会随以后重建而变化；最新内容以[实际索引文件](../outputs/knowledge-index.json)为准。

<details>
<summary>展开：三份原文合成后的完整knowledge-index.json</summary>

~~~json
{
  "schema_version": 1,
  "chunker_version": "paragraph-v1",
  "max_chars": 260,
  "built_at": "2026-10-18T16:17:49.883165+08:00",
  "sources": [
    {
      "source_id": "KB-FILTER-001",
      "source": "knowledge/KB-FILTER-001.md",
      "source_version": "3a9a3b61f35f090e45beaf7f05b55a5b0b1e79b3272b1e0bf34e0f22b53b29a5"
    },
    {
      "source_id": "KB-PACK-001",
      "source": "knowledge/KB-PACK-001.md",
      "source_version": "79f0ef1ef4f415ad06177603f495ee5c756c7f8d5271c40e8e90c52657e56a7a"
    },
    {
      "source_id": "KB-PRICE-001",
      "source": "knowledge/KB-PRICE-001.md",
      "source_version": "b348e40f74b527e41915c8865e83ad2d88c3130db4971ec98ab88aed409115b9"
    }
  ],
  "chunks": [
    {
      "source_id": "KB-FILTER-001",
      "source": "knowledge/KB-FILTER-001.md",
      "source_version": "3a9a3b61f35f090e45beaf7f05b55a5b0b1e79b3272b1e0bf34e0f22b53b29a5",
      "chunk_id": "KB-FILTER-001-C001",
      "title": "多轮筛选条件修改规则",
      "section": "",
      "content": "本文件是本项目的练习规则，不代表真实商家的政策。\n\n用户明确只修改品牌并说“其他不变”时，应保留当前有效的颜色、规格、预算等未修改条件。\n用户明确说“不限品牌”时才取消品牌限制；没有提及某字段不等于取消该条件。\n没有商品是正常查询结果，不能为了有结果而自行换品牌、放宽规格或提高预算；应说明无匹配结果并询问用户是否要修改条件。\n切换品类时，按本项目的条件合并规则清理不适用的旧商品条件，不从历史中恢复已经被取消的条件。",
      "start_line": 4,
      "end_line": 9,
      "keywords": [
        "不限品牌",
        "其他不变",
        "换品牌",
        "没有商品"
      ]
    },
    {
      "source_id": "KB-PACK-001",
      "source": "knowledge/KB-PACK-001.md",
      "source_version": "79f0ef1ef4f415ad06177603f495ee5c756c7f8d5271c40e8e90c52657e56a7a",
      "chunk_id": "KB-PACK-001-C001",
      "title": "包装与盒支换算规则",
      "section": "盒支换算依据",
      "content": "本文件是本项目的练习规则，不代表真实商家的政策。\n\n## 盒支换算依据\n\n商品按“支”销售，只能说明计价或库存单位是支，不能由此推断一盒有多少支。\n盒与支的换算必须以具体SKU明确提供的包装数量为依据，不能对所有商品统一假定每盒12支。",
      "start_line": 4,
      "end_line": 9,
      "keywords": [
        "一盒",
        "包装",
        "包装数量",
        "换算",
        "每盒"
      ]
    },
    {
      "source_id": "KB-PACK-001",
      "source": "knowledge/KB-PACK-001.md",
      "source_version": "79f0ef1ef4f415ad06177603f495ee5c756c7f8d5271c40e8e90c52657e56a7a",
      "chunk_id": "KB-PACK-001-C002",
      "title": "包装与盒支换算规则",
      "section": "缺少盒装数量时怎么回答",
      "content": "## 缺少盒装数量时怎么回答\n\n用户问某商品一盒多少支时，应先确定SKU，再查商品详情里的包装说明。\n如果具体SKU没有提供盒装数量，应明确回答“未提供，无法确定”，不得根据品牌、常识或其他SKU猜测。",
      "start_line": 11,
      "end_line": 14,
      "keywords": [
        "一盒",
        "包装",
        "盒装"
      ]
    },
    {
      "source_id": "KB-PACK-001",
      "source": "knowledge/KB-PACK-001.md",
      "source_version": "79f0ef1ef4f415ad06177603f495ee5c756c7f8d5271c40e8e90c52657e56a7a",
      "chunk_id": "KB-PACK-001-C003",
      "title": "包装与盒支换算规则",
      "section": "按支销售与预算计算",
      "content": "## 按支销售与预算计算\n\n商品按支销售时，单价和库存数量都按支理解；这不能证明存在盒装，也不能推导每盒数量。\n例如计划购买10支，应先核对该SKU的支数和单支价格，计算金额前保持计价单位一致。\n如果用户改为询问整盒购买，应先查询明确的包装换算信息，不能把按支单价直接当作整盒报价。",
      "start_line": 16,
      "end_line": 20,
      "keywords": [
        "包装",
        "按支",
        "换算",
        "每盒",
        "盒装"
      ]
    },
    {
      "source_id": "KB-PRICE-001",
      "source": "knowledge/KB-PRICE-001.md",
      "source_version": "b348e40f74b527e41915c8865e83ad2d88c3130db4971ec98ab88aed409115b9",
      "chunk_id": "KB-PRICE-001-C001",
      "title": "价格单位与预算比较规则",
      "section": "",
      "content": "本文件是本项目的练习规则，不代表真实商家的政策。\n\n本项目商品单价使用整数分存储，1元等于100分，5元应转换为500分。\n用户用元表达预算时，转换为分之后，再与商品price_fen进行同单位比较。\n单价上限是包含边界的条件，例如预算5元，对应price_fen小于或等于500。\n预算只用于筛选，不能为了找到商品而自行提高用户预算；也不能据此承诺真实商家的价格或优惠。",
      "start_line": 4,
      "end_line": 9,
      "keywords": [
        "价格",
        "单价",
        "预算"
      ]
    }
  ]
}
~~~

</details>

### 13.6 再读取时，字典和Pydantic对象怎样区分

~~~python
from app.knowledge_index import load_index

index = load_index()

# index是KnowledgeIndex对象，内部成员也按模型恢复
index.sources[1].source_id     # "KB-PACK-001"
index.chunks[2].chunk_id       # "KB-PACK-001-C002"
index.chunks[2].content        # 包装文件第11～14行对应的正文
~~~

如果只是用json.loads读取，同一份数据会先得到普通字典：

~~~python
import json
from pathlib import Path

json_text = Path("outputs/knowledge-index.json").read_text(encoding="utf-8")
data = json.loads(json_text)

data["sources"][1]["source_id"]
data["chunks"][2]["content"]
~~~

这两组写法在访问同样的数据，只是容器类型不同：Pydantic对象用属性访问，普通字典用键访问。项目实际使用load_index，会额外检查结构、资料版本等；上面的json.loads只是帮助理解，不能代替这些检查。

### 13.7 outputs里其他JSON文件是什么

| 文件 | 什么时候产生 | 程序怎样使用 |
| --- | --- | --- |
| knowledge-index.json | 第八课构建片段 | 加载正文、来源与关键词等 |
| knowledge-vectors.json | 第十课构建向量 | 按chunk_id关联向量与上述正文 |
| 06-tool-selection-evaluation.json等评测报告 | 运行verify脚本验收 | 留给我们检查实际回答和调用过程，不作为规则索引加载 |

第八课没有输出向量。第十课是在这份片段索引基础上另生成向量文件，不会把knowledge-index.json里的正文替换成数字。

先对照展开的JSON，分别找到三条sources和五条chunks，再回看build_index中的append和extend，就能把三份源文件与一个最终文件对应起来。

