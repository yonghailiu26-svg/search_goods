# 找商品 Agent · 第一步

本课只完成真实 DeepSeek 文本调用，不连接数据库和知识库。

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

## 实际验收记录

2026-10-16：Python 3.14.2，虚拟环境与依赖检查通过。真实 DeepSeek 返回中文回答，退出码 0，耗时 1.78 秒；输入 28 Token，输出 64 Token，共 92 Token。Key 首次未保存导致本地校验失败，保存后通过；未输出密钥。
