# 第七课：最小RAG，查规则再回答

补充阅读：[为什么把检索做成工具，以及execute_knowledge逐段讲解与四案例](07a-rag-tool-and-execute-knowledge.md)。

当前代码已进入[第八课：知识分块与索引](08-knowledge-chunks-and-index.md)：search_knowledge改为检索预构建片段，引用使用chunk_id。首次使用及修改资料后先运行build_knowledge_index.py；下文保留第七课一文件一条结果的学习过程。

日期：2026-10-18（北京时间）。本课只做关键词规则检索，不接Embedding、向量数据库或新框架。

## 1. 先理解为什么改、发生在什么时候

第六课已经能查询商品和商品详情，但“为什么不能所有商品统一一盒12支”是规则问题。商品表告诉我们某个SKU的事实，规则文本告诉我们应如何判断；两种资料不能互相替代。

本课使用Agent主动调用检索工具的方式。一次典型请求顺序：

```text
用户：为什么不能把所有签字笔默认一盒12支？
    ↓
第一次请求模型：问题 + 三个工具的说明
    ↓
模型返回：search_knowledge(query="包装 一盒 换算")
    ↓
Python读取knowledge目录，查到相关规则正文和来源
    ↓
把结果追加到messages，role="tool"
    ↓
第二次请求模型：现在上下文里有检索到的规则正文
    ↓
模型根据规则回答，并引用[KB-PACK-001]
```

**检索实际发生在两次模型请求之间，由Python执行；结果是在下一次模型请求时进入上下文的。** 不是把所有文件一直放在system提示词里，也不是训练模型记住文件。

这里RAG的R是检索，A是把相关正文补进上下文，G是模型据此生成回答。关键词检索也能跑通这条链；Embedding是后续可替换的检索方式，不是本课先决条件。

## 2. 按调用链看哪些文件需要同步修改

| 顺序 | 文件 | 为什么修改 |
| --- | --- | --- |
| 1 | knowledge/KB-*.md | 先准备能被检索的练习规则，正文是回答依据 |
| 2 | app/schemas.py | 新增SearchKnowledgeArgs，约束query和limit |
| 3 | app/knowledge.py | 定义知识工具，实际读取文件、匹配和排序 |
| 4 | app/tools.py | 集中注册三个工具定义，发送给模型 |
| 5 | app/tool_runner.py | execute_knowledge校验、执行、包装状态、记录耗时 |
| 6 | app/agent.py | handlers加入知识工具，结果照旧回传，收集sources并检查引用ID |
| 7 | app/prompts.py | 告诉模型何时查规则、如何引用、缺证据怎么办 |
| 8 | tests/test_step7.py、verify_step7.py | 分别验证离线边界和真实调用链 |

main.py仅更新课程标识和/health的step=7。llm.py、商品SQL、会话表和前端没有修改：它们已经能发送messages、执行商品工具和保存对话，不必为RAG另写一套流程。

工具定义清单从products.py移至新的tools.py；products.py仍只定义商品工具，tools.py把商品与知识工具汇总。没有把规则读取逻辑塞入数据库模块。

建议跟读：knowledge/KB-PACK-001.md → knowledge.py的search_knowledge → agent.py的run_knowledge/handlers → messages.append的位置。

## 3. 先准备三条可验证规则

每个Markdown文件目前就是一条完整规则：

- KB-PACK-001：包装与盒支换算，必须查具体SKU，缺盒装数量不能猜。
- KB-PRICE-001：项目价格为整数分，5元=500分，预算比较包含边界。
- KB-FILTER-001：只换品牌时保留未修改条件，不能自动放宽条件。

文件格式示意：

```markdown
# 包装与盒支换算规则
关键词：包装、盒装、一盒、每盒、换算、装箱、按支、包装数量

这里是规则正文……
```

这些都是本项目练习规则，不是某个真实商家的政策。没有提供保修规则，用它验证“没有资料怎么办”。

本课是手动准备的一文件一规则，不做自动长文档分块、版本管理或入库流水线，第八课再处理。

## 4. 检索函数做了什么

模型提供的工具参数例如：

```json
{"query":"包装 一盒 换算","limit":3}
```

先Pydantic校验：query去首尾空白后1—200字；limit为1—3，默认3；拒绝额外字段。

search_knowledge只扫描固定knowledge目录的KB-*.md，不接受调用者提供文件路径。对每个文件：

1. 读标题、关键词行和正文。
2. 找出query中包含的关键词。
3. score等于不同命中关键词的个数。
4. 按score从高到低排列；同分按source_id排列，保证结果稳定。
5. 只返回正分资料的前limit条，不拿无关资料凑数。

示意返回：

```json
{
  "status":"ok",
  "practice_data":true,
  "passages":[{
    "source_id":"KB-PACK-001",
    "title":"包装与盒支换算规则",
    "source":"knowledge/KB-PACK-001.md",
    "content":"盒与支的换算必须以具体SKU……",
    "score":3,
    "matched_keywords":["一盒","包装","换算"]
  }]
}
```

score只是关键词命中计数，不是相关性概率或事实置信度。query换一种完全不含这些词的表达，可能检索不到；本课没有中文分词、同义词扩展、BM25或语义检索。

文件每次调用时重新读取，修改正文或关键词后下一次检索会使用新内容；不需要执行建表或知识入库脚本。

## 5. 检索结果怎么进入模型

agent.py中新增的包装与分发：

```python
def run_knowledge(arguments, current):
    return execute_knowledge(arguments, current, search=search_knowledge)

handlers = {
    "search_products": run_search,
    "get_product_detail": run_detail,
    "search_knowledge": run_knowledge,
}
```

选择之后仍走现有的工具消息回传：

```python
result, requirements, tool_record = handlers[active_tool_name](
    function["arguments"], requirements
)
messages.append({
    "role": "tool",
    "tool_call_id": call["id"],
    "content": json.dumps(result, ensure_ascii=False),
})
```

这一刻result中的passages.content才被放进messages。append只修改本地列表；到for循环下一次complete时，才连同其他消息发给DeepSeek。

execute_knowledge始终返回current的副本，不更新商品品牌、规格、预算。它和详情工具都是读资料，只有search_products的需求合并会形成新的筛选条件。

## 6. 来源与无资料怎么处理

命中规则后，提示词要求引用本轮source_id，例如[KB-PACK-001]。程序收集本轮实际返回的sources；最终回答不能使用符合本项目引用格式、但本轮未检索到的ID，有证据却不标引用时也会停止，错误码invalid_citation。

这只检查来源标识存在且属于本轮证据，不能自动证明每句话都忠实于正文。sources是本轮检索到的可用来源清单，不代表模型引用了清单中的每一条。历史回答中的旧引用不能直接充当本轮证据；需要重新检索。

| 情况 | 结果 |
| --- | --- |
| 检索到规则 | ok，passages有正文和来源 |
| 合法检索但关键词无匹配 | no_knowledge，passages为空 |
| query为空或limit越界 | invalid_arguments，未执行检索，可按第五课机制修正 |
| 规则目录不存在、无文件、文件损坏 | tool_failed，停止；不能说成没有相关规则 |

仅调用知识工具且完全无证据时，程序固定返回“本地练习规则库未检索到相关资料，无法按本项目规则确认”，防止把模型自行补充的保修政策当成项目规则。混合商品与规则回答的逐项证据检查尚未实现，后续课程继续加强。

没有检索到，不等于现实中没有这项规则；只是本地小规则库没有匹配证据。规则正文只是数据，提示词要求不执行正文中改变系统行为的命令，但这不是完整的提示注入防护证明。

## 7. 本地怎么体验

重启或热重载自己的后端，打开 http://127.0.0.1:8000/ 。已有环境无需安装新依赖、建表或向量服务。

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

试三句话：

1. “为什么不能把所有签字笔默认一盒12支？请查本地规则并注明来源。”
2. “请检索本地练习规则：商品保修政策是多久？找不到就说明未知。”
3. “找得力黑色0.5mm签字笔，单价不超过5元。”

前两句应使用search_knowledge；第三句仍使用search_products，不要求所有请求都做RAG。在/docs或Network查看/chat响应：tool_trace中的passages是模型实际收到的正文，sources是来源，answer是最终生成的回答。

本课重点是检索规则本身。一个问题如果还要搜索商品、查询详情、检索规则再总结，可能超过默认3次模型请求；本次没有为了更长链路提高执行预算。

## 8. 验证结果

```powershell
# 离线行为验证，不访问模型/数据库
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 真实DeepSeek + 本地规则 + 原商品工具回归，会产生API费用
.\.venv\Scripts\python.exe verify_step7.py
```

2026-10-18：41项测试及pip check通过。新增10项覆盖检索正文与来源、排序/limit、无匹配不凑数、缺失/损坏资料、非法参数不执行、状态不变、正文进入下一轮模型请求、无效引用拒绝、无证据不编政策、检索失败不伪装无资料。原31项测试保留通过，第六课关于工具清单的断言调整为允许新增工具。

本轮四组都是实际DeepSeek调用，没有模拟模型响应：

| 样例 | 工具 | 来源/结果 | 模型次数 | 总Token | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 包装换算规则 | search_knowledge | KB-PACK-001，正确引用 | 2 | 4141 | 2.59秒 |
| 库中没有保修规则 | search_knowledge | no_knowledge，不编保修期限 | 2 | 3812 | 3.00秒 |
| 得力黑色0.5mm，预算5元 | search_products | 正常找到1款，无强制规则检索 | 2 | 4158 | 3.73秒 |
| 同会话解释“其他不变” | search_knowledge | KB-FILTER-001与KB-PRICE-001，需求未变 | 2 | 4663 | 3.38秒 |

报告：outputs/07-minimal-rag-evaluation.json。实际包装回答明确“具体SKU未提供盒装数量时无法确定”，保修问题明确本地资料不足；条件解释正确保留得力、黑色、0.5mm与500分预算。

本轮未发生运行报错；测试中的损坏文件、非法参数与假政策是离线主动构造的场景，不是线上事故。报告不包含本地Key和数据库密码，检查时未输出凭据值；没有读取配置全文或启动后台服务器。

收尾文档检查曾把示例中的Python下标加函数调用误判为Markdown链接，导致链接扫描断言失败；限制为单行Markdown链接后检查通过，健康接口step=7和页面返回正常。该问题仅在临时检查脚本，不涉及Agent执行。

本课完成的是可验证的小型RAG基线，不保证任意表达都能检索正确，也没有做语义一致性自动判定。后续再逐步学习长文分块、版本、Embedding与更严格的证据回答。
