# 第九课：让规则与商品事实一起支持回答

当前检索策略已进入[第十二课重排](12-cross-encoder-reranking.md)；本课证据ID、claims/unknowns和校验流程继续沿用，所需模型/索引见[总验收入口](00-course-map-and-acceptance.md)。

这节只学一件事：**回答里每条有依据的结论，都明确关联到本轮取得的资料；无法确认的内容单独列出。**

用这个问题贯穿全课：

> 请查本地包装规则和SKU DEMO-PEN-0000的包装说明，判断能否确认一盒12支。

## 1. 两类资料各能证明什么

| 查什么 | 工具 | 返回内容能证明什么 |
| --- | --- | --- |
| 本项目应如何判断盒支数量 | search_knowledge | 规则原则，例如不能凭品牌猜数量 |
| 这个SKU实际提供了什么说明 | get_product_detail | 具体商品事实，例如包装说明写了什么 |

规则说“按具体SKU的包装数量换算”，不代表这个SKU已经提供了数量。商品写“按支销售”，也不代表一盒12支。

前八课已经能调用这两个工具，本课不是再造工具，而是补上**两类结果到最终结论之间的对应关系**。

## 2. 改动发生在什么时候

```text
用户问题
  ↓ 第一次模型请求：选择工具
search_knowledge → 规则结果 ─┐
                           ├→ tool_trace，也分别写入tool消息
get_product_detail → 商品结果┘
  ↓ 新增：collect_evidence(tool_trace)
可用证据ID清单 + 已发现的资料缺口
  ↓ 把清单与最终回答格式说明加入messages
下一次模型请求：根据原始tool正文，生成claims和unknowns的JSON
  ↓ 新增：校验每条结论的证据ID
  ↓ 新增：整理成纯文本
返回answer，同时保留answer_details供观察
```

两个工具没有前后依赖时，模型可以在同一次响应里提出两次调用，Python逐个执行。只有结果都回来后才能总结。如果先查规则、下一轮再查详情，也可以；仍受原有模型/工具次数上限约束。

**开启条件：本轮已经实际尝试规则检索和商品详情两类工具。** 参数校验失败不算实际尝试。只有一个工具类型时，继续使用前课的回答方式。

## 3. 第一站：已有的工具结果

下面是结构节选，省略了其他字段；省略说明不是实际程序返回值。

```python
# tool_trace中的规则结果之一
{
    "tool": "search_knowledge",
    "status": "ok",
    "passages": [{
        "chunk_id": "KB-PACK-001-C002",
        "source_id": "KB-PACK-001",
        "content": "如果具体SKU没有提供盒装数量，应明确回答未提供、无法确定……",
    }],
}

# tool_trace中的商品结果之一
{
    "tool": "get_product_detail",
    "status": "ok",
    "product": {
        "sku": "DEMO-PEN-0000",
        "package_notes": "练习包装：按支销售；没有提供盒装数量，不能换算一盒有几支。",
    },
}
```

它们仍由tool_runner返回，Agent仍把完整result序列化到`role="tool"`的消息里。本课没有更换这一条数据通路。

## 4. 第二站：从工具结果提取证据清单

新增[app/evidence.py](../app/evidence.py)，其中：

```python
evidence_context = collect_evidence(trace)
```

参数`trace`是本轮工具记录列表，返回值是一个普通字典；未同时查询两类工具则返回`None`。假设规则只命中C002，商品存在且包装说明非空，会得到：

```python
{
    "items": [
        {"id": "KB-PACK-001-C002", "kind": "rule"},
        {"id": "SKU:DEMO-PEN-0000", "kind": "product", "sku": "DEMO-PEN-0000"},
    ],
    "gaps": [],
}
```

| 字段 | 含义 |
| --- | --- |
| items | 允许引用的证据ID，依据本轮实际返回的数据生成 |
| kind=rule | 这是规则片段依据 |
| kind=product | 这是商品详情依据 |
| gaps | 程序已发现的资料缺口 |

这份清单**没有重复放完整正文**。正文已经在前面的tool消息里；清单只帮模型确认哪些ID可用。

`gaps=[]`不代表资料完备：这里包装说明是非空字符串，所以程序不会仅凭字段为空发现缺口。字符串里“没有提供盒装数量”的意思，仍需模型根据正文理解。

Python目前能直接识别的缺口是：规则检索无命中、SKU未查到、商品的package_notes为空。它不会凭空为不存在的商品或未命中的规则生成可引用ID。

## 5. 第三站：模型先给结构，不直接给最终排版

Agent将清单和`EVIDENCE_INSTRUCTION`追加到messages。下一次模型请求时，它同时拥有：

```text
原始tool消息：具体规则和商品说明，供理解
新加的system消息：允许引用哪些ID，以及如何组织回答
```

这时要求模型返回这种JSON字符串，下面为教学示例：

```json
{
  "claims": [
    {
      "text": "该SKU的包装说明写明按支销售，没有提供盒装数量。",
      "evidence_ids": ["SKU:DEMO-PEN-0000"]
    },
    {
      "text": "缺少具体SKU的盒装数量时，应回答无法确定，不能按常识猜测。",
      "evidence_ids": ["KB-PACK-001-C002"]
    }
  ],
  "unknowns": ["这个SKU具体一盒多少支，当前无法确认。"]
}
```

| 字段 | 放什么 | 不能放什么 |
| --- | --- | --- |
| claims | 有依据的结论，每条包含text和至少一个evidence_id | 无引用的结论、猜出的来源ID |
| unknowns | 未知或资料不足的内容 | 假装已确认的商品参数或商家政策 |

一条综合结论也可以同时引用规则ID和商品ID。不要把“未检索到规则”塞进一个`evidence_ids=[]`的claim；它应该放unknowns。

这里只在模型最终content中约定JSON，没有使用额外API结构化输出功能；模型仍可能不遵守，所以Python必须再校验。

## 6. 第四站：Python校验，再拼成纯文本

Agent执行：

```python
structured = validate_evidence_answer(answer, evidence_context)
answer, answer_details = render_evidence_answer(structured, evidence_context)
```

数据类型变化：

```text
模型content：JSON字符串
     ↓ Pydantic解析字段与类型
EvidenceAnswer对象
  ├─ claims：list[EvidenceClaim]
  │     每项有text、evidence_ids
  └─ unknowns：list[str]
     ↓ 校验证据ID，整理展示
answer：纯文本字符串
answer_details：普通字典，保留claims与unknowns
```

校验做四件事：

1. JSON、字段、类型、长度不合法就拒绝，不直接展示原始输出。
2. 每条claim至少引用一个本轮实际取得的ID。
3. 两类资料都有时，两类都应在结论里使用，不能查完商品却只总结规则。
4. 程序发现的gaps一定加入最终unknowns，模型不能通过省略字段隐藏缺口。

例如`SKU:FAKE`、未检索的`KB-PACK-001-C999`都会被拒绝。返回`invalid_evidence`，沿用现有失败诊断；不会自动重试或放宽校验，失败轮次也不会当成功会话保存。

最后展示成：

```text
该SKU的包装说明写明按支销售，没有提供盒装数量。 [SKU:DEMO-PEN-0000]

缺少具体SKU的盒装数量时，应回答无法确定，不能按常识猜测。 [KB-PACK-001-C002]

暂无法确认：
- 这个SKU具体一盒多少支，当前无法确认。
```

最终响应继续有answer、sources、tool_trace等字段，新增`answer_details`。非混合回答中该字段为null。聊天页仍只展示answer，想看结构可用`/docs`或Network。

注意：`sources`继续表示知识来源，商品ID在`answer_details.claims[].evidence_ids`中；商品原始事实在tool_trace里。没有把商品表改造成知识文档。

## 7. 三种情况，结论为什么不一样

| 实际取得的资料 | 应如何处理 |
| --- | --- |
| 规则有，商品包装说明写“未提供盒装数量” | 解释原则，引用实际商品说明，明确数量未知 |
| 规则有，商品package_notes为null | 商品存在；程序自动补充包装说明缺失，不能说商品不存在 |
| 商品有，保修规则未命中 | 可陈述已有商品事实，保修规则/期限不能确认；不能挂一个假的规则ID |

没有命中规则不等于规则不存在。商品字段没有提供某项资料，也不能靠通用规则补出这个SKU的具体参数。

## 8. 对应修改哪些文件

| 文件 | 本课职责 |
| --- | --- |
| [evidence.py](../app/evidence.py) | 收集证据ID/缺口，解析并校验混合结论，整理文本 |
| [agent.py](../app/agent.py) | 工具执行后收集清单，下一次请求前加格式指令，结束前校验并返回 |
| [prompts.py](../app/prompts.py) | 说明两类工具如何协同、claims与unknowns的格式 |
| [main.py](../app/main.py) | 更新课程标识，HTTP请求格式沿用 |
| [test_step9.py](../tests/test_step9.py) | 验证假引用、无依据、资料缺失、消息和结果流转 |

本课没有新工具、新表或新依赖；不改第八课的分块与关键词检索。明确SKU的案例通常只需两类工具；没有SKU还需要先找商品时，可能触及原有执行上限，不在这课增加预算。

建议阅读顺序：本课第3～6节 → evidence.py三个主要函数 → agent.py中搜索`evidence_context`。

## 9. 本地体验与验证

重载现有服务，在聊天页开启新会话发送开头的例子即可。首次还没有初始化详情或索引时，分别运行seed_product_details.py和build_knowledge_index.py；已初始化则不用重复。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# 下面会真实调用DeepSeek和MySQL，产生API费用
.\.venv\Scripts\python.exe verify_step9.py
```

报告位置：[09-evidence-evaluation.json](../outputs/09-evidence-evaluation.json)。查看answer_details里每条结论引用了什么，再对照tool_trace中的实际正文。

2026-10-18验收：58项行为测试、依赖检查通过；以下三组均使用真实DeepSeek和本地MySQL，每组2次模型请求，同时取得规则工具和商品详情工具的实际观察：

| 场景 | 结果 | 总Token | 耗时 |
| --- | --- | --- | --- |
| 规则与商品共同判断 | 规则及SKU引用齐备，盒装数量未知 | 5583 | 3.17秒 |
| 商品缺少包装说明 | 规则及SKU引用齐备，自动补入包装缺口 | 5582 | 3.14秒 |
| 未收录保修规则 | 仅商品ID可引用，保修无法确认 | 4844 | 3.25秒 |

这些用量是最终通过的三组报告，不包含前一次失败验收和定位问题时额外发生的模型请求；它们也实际产生了API用量。无引用claim的拒绝同时用离线测试固定覆盖。

本课的限制：**引用ID合法，不等于结论语义一定正确。** 模型把错误结论挂到一个合法ID上，仍可能通过；unknowns的自由文本也需要检查。我们实现的是可检查的依据关联与确定缺口提示，不是自动事实核验器。

真实验收中发现过“未命中规则”被模型放进无引用claim，Python以invalid_evidence拒绝。修复方式是明确要求这类信息进入unknowns，并增加相应回归测试，没有放松“每条claim必须有依据”的要求。
