# 本项目的Git版本管理

本说明于2026-10-27加入。项目继续位于`D:\myStudy\面试\search_goods`；代码和课程文档在同一个仓库中维护。

## 1. 当前基线与后续改造

第1～14课作为第一份代码基线，稳定分支为`main`，对应标签为`lesson-14-baseline`。标签在首次提交与验证完成后创建；是否已存在可用下面的命令确认：

```powershell
git status
git log --oneline --decorate -5
git tag --list
```

这次接入不安装LangGraph、不修改Agent运行逻辑。第15课从基线开始，复用商品、知识检索和证据校验模块。

首次纳入Git前于2026-10-27执行：100项现有行为测试通过，`pip check`通过；扫描待提交文件及暂存内容，未发现与本地凭据匹配的内容或所检查的常见密钥模式。检查没有调用真实DeepSeek或MySQL，也没有把历史真实接口报告当成本次新验收。

## 2. 日常查看与提交

```powershell
# 先检查本次改了哪些文件。
git status
git diff

# 只加入本次相关文件；这里以文档修改为例。
git add docs/00-git-workflow.md
git diff --cached
git commit -m "docs: update Git workflow"
```

提交前确认不包含Key、密码、实际用户数据或敏感运行报告。提交是本地操作；只有另行配置远程并执行push，才上传到远程仓库。

## 3. 每个阶段一个分支

开始第15课时，在工作区修改已妥善保存的前提下执行：

```powershell
git switch main
git switch -c feat/15-langgraph-workflow
```

在该分支完成一个可运行闭环：代码、对应测试、课程文档、运行方法及失败场景说明。验证通过并完成阶段提交后，再合并：

```powershell
git switch main
git merge --ff-only feat/15-langgraph-workflow
git tag -a lesson-15 -m "Lesson 15: verified LangGraph workflow"
```

如果`--ff-only`报告分支已分叉，先检查双方提交；不要为了合并成功而覆盖工作区。上述命令是后续操作说明，本次接入不会自动执行第15课改造或创建其完成标签。

## 4. 哪些内容进入仓库

| 内容 | 处理 |
| --- | --- |
| `app/`、`web/`、根目录脚本、`sql/` | 保存源代码和初始化方法 |
| `docs/`、`knowledge/`、`evals/`、`tests/` | 保存课程、练习资料、人工标签和行为验证 |
| `.env.example`、`requirements.txt` | 保存不含凭据的配置模板和依赖版本 |
| 两份`knowledge-*.json`索引、`14-retrieval-baseline.json` | 保存当前小型练习语料的索引及参考评测基线 |
| `.env.dev`、`.venv/`、`work/` | 忽略本地凭据、虚拟环境、模型下载及临时文件 |
| `app_1_to_9/` | 保留现有本地副本，后续通过Git记录版本 |
| `outputs/`其余生成报告 | 本地保留；不随首次代码提交上传 |

部分课程链接指向本地生成报告，首次克隆后这些报告不会自动存在；需要相应验收脚本重新生成。真实API验收会计费并可能创建练习会话，按课程说明主动选择执行，不属于普通启动必需步骤。

## 5. 配置与数据库不会随Git回退

新环境需要自行填写`.env.dev`、创建虚拟环境、初始化练习数据库，并按课程说明准备本地模型。Git历史不包含MySQL实际数据、Key或模型缓存；切换代码版本也不会自动改变这些内容。

后续修改资料或编码模型时，仍须重建匹配索引；修改数据库结构时，另外记录迁移、备份与回退方式。

## 6. 远程仓库

建议使用私有远程仓库。提供HTTPS或SSH地址即可，地址中不放Token或密码；登录授权在本机完成，不把凭据发到聊天。

远程建立后，可先用`git remote -v`确认目标，再按远程已有内容决定首次同步方式；不使用强制推送覆盖远程内容。新建远程仓库时，可以不预置README，以便直接接收现有项目的首次提交。
