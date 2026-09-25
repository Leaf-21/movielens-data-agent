# GitHub 团队协作开发指导文档

## 一、文档目的

为了保证三人团队能够基于 GitHub 高效、规范地完成“Agent 驱动的 Hadoop 数据清洗与五维质量评估系统”的开发工作，制定本团队 GitHub 协作开发规范。

本项目主要由三个部分组成：

1. Hadoop 数据清洗与五维质量评估；
2. Agent 后端、任务调度及结果解释；
3. 前端页面、结果展示及系统测试。

项目要求用户通过自然语言提交一次请求后，由 Agent 自动调用 Hadoop 完成清洗前评分、数据清洗、清洗后评分和结果对比，并最终在前端展示任务状态、五维评分、数据变化及评估报告。

GitHub 主要用于完成以下工作：

- 项目源代码统一管理；
- 三人并行开发；
- 任务分配与进度跟踪；
- 代码提交与版本记录；
- Pull Request 代码审核；
- 分支合并；
- Bug 管理；
- 项目最终版本发布。

GitHub 官方也将 Branch、Commit 和 Pull Request 作为协作开发中的核心机制，用于隔离开发、提交变更并在合并前进行审查。([GitHub Docs](https://docs.github.com/en/pull-requests/concepts/writing-code-for-a-project?utm_source=chatgpt.com))

------

# 二、团队成员及职责

本项目采用三人协作模式。

| 成员  | GitHub 职责         | 项目职责                               |
| ----- | ------------------- | -------------------------------------- |
| 成员A | Hadoop 模块负责人   | 数据分析、数据清洗、五维质量评分       |
| 成员B | Agent 模块负责人    | Agent、Hadoop Tool、任务调度、结果解释 |
| 成员C | Frontend 模块负责人 | 前端页面、接口联调、系统测试           |

建议三个人全部加入同一个 GitHub 仓库，并拥有开发权限。

如果使用 GitHub Organization，可以通过 Repository Roles 和 Teams 对团队成员权限进行管理；GitHub 官方提供 Read、Triage、Write、Maintain、Admin 等不同仓库角色。对于普通学生项目，参与实际代码开发的成员需要能够推送代码，因此通常应具有相应的 Write 权限。([GitHub Docs](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles?utm_source=chatgpt.com))

项目管理员尽量只保留必要的管理权限，不建议所有人都直接使用 Admin 权限。

------

# 三、GitHub 仓库建立

## 3.1 创建仓库

由成员B或者项目负责人创建 GitHub Repository。

建议仓库名称：

```text
movielens-data-agent
```

仓库简介：

```text
Agent-driven Hadoop data cleaning and five-dimensional data quality evaluation system
```

建议设置：

```text
Repository visibility：根据课程要求选择 Public 或 Private
README：创建
.gitignore：创建
License：根据项目要求决定
```

项目最终代码、实验结果说明、使用文档和部分项目资料统一放入该仓库。

------

# 四、项目目录结构

建议使用统一的项目目录结构，避免三个人各自按照不同方式组织代码。

```text
movielens-data-agent/
│
├── README.md
├── .gitignore
│
├── docs/
│   ├── project-plan.md
│   ├── team-work.md
│   ├── github-guide.md
│   └── evaluation-method.md
│
├── hadoop/
│   ├── src/
│   ├── config/
│   ├── scripts/
│   └── README.md
│
├── agent/
│   ├── src/
│   ├── tools/
│   ├── config/
│   └── README.md
│
├── frontend/
│   ├── src/
│   ├── public/
│   └── README.md
│
├── tests/
│   ├── hadoop/
│   ├── agent/
│   └── frontend/
│
├── data/
│   └── README.md
│
└── reports/
    ├── quality-report/
    └── test-report/
```

注意：

**原始 MovieLens 1M 数据文件不建议直接上传到 GitHub 仓库。**

`data/README.md` 中可以说明数据来源、文件名称、编码方式和使用方法，数据文件通过本地环境配置。

------

# 五、Git 分支管理规范

## 5.1 主分支

项目使用：

```text
main
```

作为最终稳定版本分支。

**禁止直接向 main 分支提交代码。**

GitHub 支持对重要分支配置 Branch Protection Rules，可以限制直接推送、强制推送和删除，并可以设置 Pull Request、状态检查等合并要求。([GitHub Docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches?utm_source=chatgpt.com))

因此建议将 `main` 设置为保护分支。

------

## 5.2 功能分支

每个人开发自己的功能时，必须建立独立分支。

分支命名格式：

```text
feature/功能名称
fix/问题名称
docs/文档名称
test/测试名称
```

本项目建议：

```text
feature/hadoop-cleaning
feature/hadoop-quality-score

feature/agent-core
feature/hadoop-tool

feature/frontend
feature/frontend-test
```

例如成员A负责数据清洗：

```bash
git checkout main
git pull origin main
git checkout -b feature/hadoop-cleaning
```

成员B开发 Agent：

```bash
git checkout main
git pull origin main
git checkout -b feature/agent-core
```

成员C开发前端：

```bash
git checkout main
git pull origin main
git checkout -b feature/frontend
```

这样每个人都可以独立开发，不会直接影响主分支。

GitHub 官方建议使用 Branch 将开发工作隔离，在完成后通过 Pull Request 提交合并请求。([GitHub Docs](https://docs.github.com/en/pull-requests/concepts/writing-code-for-a-project?utm_source=chatgpt.com))

------

# 六、Issue 任务管理

开发之前，先在 GitHub Issues 中建立任务。

每一个任务对应一个 Issue。

例如：

```text
Issue #1
标题：完成 MovieLens ratings.dat 数据格式检查

Issue #2
标题：实现 ratings 数据去重

Issue #3
标题：实现五维质量评分

Issue #4
标题：封装 Hadoop Tool

Issue #5
标题：完成 Agent 任务调度

Issue #6
标题：完成前端评分对比页面
```

Issue 内容建议按照下面格式填写：

```text
## 任务描述

完成 ratings.dat 数据的格式检查。

## 工作内容

1. 检查字段数量
2. 检查 UserID
3. 检查 MovieID
4. 检查 Rating
5. 检查 Timestamp
6. 输出异常记录统计

## 完成标准

程序能够正确识别格式异常记录，
并输出统计结果。

## 负责人

成员A

## 预计完成时间

2026-XX-XX
```

GitHub 中可以由仓库成员管理 Issues 和 Pull Requests；如果使用 Organization，还可以通过 Teams 统一管理成员和通知。([GitHub Docs](https://docs.github.com/en/organizations/organizing-members-into-teams/about-teams?utm_source=chatgpt.com))

------

# 七、Commit 提交规范

为了方便老师查看团队每个人的实际工作，以及后期出现问题时进行版本追踪，所有代码必须进行规范提交。

建议使用以下 Commit 格式：

```text
类型: 简短描述
```

例如：

```text
feat: 实现 ratings 数据清洗
feat: 增加五维质量评分算法
feat: 增加 Hadoop Tool 接口
feat: 完成 Agent 任务调度
feat: 增加前端评分对比页面

fix: 修复 Timestamp 类型转换问题
fix: 修复前端评分数据显示错误

docs: 更新项目 README
docs: 增加 GitHub 协作说明

test: 增加 ratings 数据测试
test: 增加 Agent 接口测试
```

推荐使用以下类型：

| 类型       | 含义     |
| ---------- | -------- |
| `feat`     | 新功能   |
| `fix`      | Bug 修复 |
| `docs`     | 文档修改 |
| `test`     | 测试     |
| `refactor` | 代码重构 |
| `config`   | 配置修改 |

一次 Commit 尽量只完成一项相对独立的工作。

不要使用：

```text
update
test
aaa
修改
最终版
最终版2
最终代码
```

这类无法体现修改内容的 Commit 信息。

------

# 八、日常开发操作流程

每个人开始当天开发前，先同步主分支。

```bash
git checkout main
git pull origin main
```

然后回到自己的开发分支：

```bash
git checkout feature/xxx
```

将最新 main 合并到当前分支：

```bash
git merge main
```

完成开发后检查：

```bash
git status
```

查看代码变化：

```bash
git diff
```

提交：

```bash
git add .
git commit -m "feat: 完成XXX功能"
```

推送：

```bash
git push origin feature/xxx
```

第一次推送新分支可以使用：

```bash
git push -u origin feature/xxx
```

------

# 九、Pull Request 协作规范

开发完成以后，不允许直接合并到 `main`。

必须通过 Pull Request。

操作流程：

```text
个人开发分支
      ↓
完成代码
      ↓
本地测试
      ↓
git push
      ↓
GitHub
      ↓
Create Pull Request
      ↓
其他成员审核
      ↓
修改意见
      ↓
再次提交
      ↓
审核通过
      ↓
Merge
      ↓
main
```

GitHub 的 Pull Request 用于提出代码变更、进行审查，并在确认后合并到目标分支。([GitHub Docs](https://docs.github.com/en/pull-requests/concepts/writing-code-for-a-project?utm_source=chatgpt.com))

------

# 十、Pull Request 命名规范

建议：

```text
[Feature] 完成 MovieLens 数据清洗
[Feature] 增加五维质量评分
[Feature] 实现 Agent Hadoop Tool
[Feature] 完成前端评分展示

[Fix] 修复 ratings 时间戳处理问题
[Fix] 修复 Agent 任务状态异常
```

------

# 十一、Pull Request 模板

团队成员创建 PR 时，统一填写：

```text
## 1. 修改内容

本次主要完成：

- 
- 
- 

## 2. 对应 Issue

Closes #XX

## 3. 测试情况

- [ ] 本地运行成功
- [ ] 单元测试通过
- [ ] 接口测试通过
- [ ] 前端测试通过

## 4. 是否涉及其他模块

- [ ] Hadoop
- [ ] Agent
- [ ] Frontend
- [ ] Docs

## 5. 注意事项

请审核以下内容：

- 
- 
```

------

# 十二、代码审核规则

每个人提交 Pull Request 后，至少由另外一名成员进行代码审核。

审核重点：

### 1. 功能是否正确

例如 Hadoop 模块：

```text
输入数据
↓
清洗
↓
评分
↓
输出
```

是否能够实际运行。

### 2. 是否影响其他模块

例如成员A修改 Hadoop Tool 的输出格式时，需要通知成员B，因为 Agent 依赖 Hadoop 返回的数据格式。

### 3. 是否存在明显 Bug

检查：

- 空值；
- 异常数据；
- 文件路径；
- 编码；
- 数据类型；
- 接口参数；
- 错误处理。

### 4. 是否具有测试依据

不能只写：

```text
“我本地测试过了。”
```

应说明：

```text
测试数据：
MovieLens 1M

测试结果：
清洗成功
原始记录：XXXX
清洗后记录：XXXX
五维评分正常返回
```

------

# 十三、三人具体 GitHub 协作方式

## 成员A：Hadoop

主要分支：

```text
feature/hadoop-cleaning
feature/hadoop-quality-score
```

主要 Issue：

```text
#1 MovieLens 数据分析
#2 数据格式检查
#3 数据清洗
#4 数据去重
#5 五维质量评分
```

最终通过 Pull Request 合并：

```text
feature/hadoop-cleaning
        ↓
Pull Request
        ↓
main
```

------

## 成员B：Agent

主要分支：

```text
feature/agent-core
feature/hadoop-tool
```

主要 Issue：

```text
#6 Agent 需求解析
#7 Hadoop Tool 封装
#8 任务调度
#9 状态管理
#10 结果解释
#11 评估报告
```

Agent 需要根据 Hadoop 的实际返回结果进行组织和解释，不能自行编造评分或处理结果。

------

## 成员C：Frontend

主要分支：

```text
feature/frontend
feature/frontend-test
```

主要 Issue：

```text
#12 前端输入页面
#13 任务状态页面
#14 五维评分对比
#15 数据变化展示
#16 Agent 对话
#17 测试
```

前端需要重点展示项目要求的五维评分、数据量变化、修复/去重/隔离情况、问题记录和 Agent 解释。

------

# 十四、模块之间的接口协作

三个人开发时，最容易产生的问题不是代码冲突，而是**接口不一致**。

因此必须提前规定接口格式。

建议 Hadoop 返回统一 JSON：

```json
{
  "task_id": "task_001",
  "status": "success",
  "data_version": "movielens-1m-v1",
  "rule_version": "rule-v1",
  "T1": "XXXX-XX-XX",
  "T2": "XXXX-XX-XX",
  "before_score": {
    "accurate": 0,
    "complete": 0,
    "unique": 0,
    "up_to_date": 0,
    "consistent": 0
  },
  "after_score": {
    "accurate": 0,
    "complete": 0,
    "unique": 0,
    "up_to_date": 0,
    "consistent": 0
  },
  "statistics": {
    "before_count": 0,
    "after_count": 0,
    "fixed_count": 0,
    "deduplicated_count": 0,
    "isolated_count": 0
  }
}
```

成员A负责保证 Hadoop 输出格式稳定。

成员B负责解析该格式并提供 API。

成员C只调用成员B提供的 API，不直接访问 Hadoop 内部实现。

这样可以形成：

```text
Hadoop
   ↓
标准 JSON
   ↓
Agent API
   ↓
Frontend
```

三个人只需要约定接口，不需要频繁修改其他人的代码。

------

# 十五、发生代码冲突时的处理方式

多人同时修改同一个文件时可能出现 Merge Conflict。

例如：

```text
成员A修改 README.md
成员B也修改 README.md
        ↓
两人都提交
        ↓
合并时发生冲突
```

解决步骤：

```bash
git checkout feature/xxx
git pull origin main
git merge main
```

出现冲突后：

```text
<<<<<<< HEAD
自己的代码
=======
main中的代码
>>>>>>> main
```

人工确认保留内容，删除冲突标记。

然后：

```bash
git add .
git commit -m "fix: 解决代码合并冲突"
git push
```

原则：

**谁产生冲突，谁负责解决；涉及其他模块时必须与对应负责人沟通。**

------

# 十六、严禁事项

团队开发过程中禁止出现以下情况：

### 1. 禁止直接修改 main

```bash
git push origin main
```

原则上不允许。

### 2. 禁止上传敏感信息

不能把以下内容上传 GitHub：

```text
密码
API Key
Token
数据库密码
个人隐私数据
服务器密钥
```

### 3. 禁止上传大量原始数据

MovieLens 原始数据建议由每个人在本地配置，不放入代码仓库。

### 4. 禁止使用他人的开发分支直接开发

每个人维护自己的功能分支。

### 5. 禁止随意覆盖他人代码

例如：

```bash
git push --force
```

除非经过团队沟通并明确确认。

### 6. 禁止没有测试就提交 PR

代码至少需要通过本人本地测试。

------

# 十七、最终版本管理

项目阶段性完成后，在 `main` 分支形成稳定版本。

例如：

```text
v0.1.0
```

表示：

> 完成基础 Hadoop 数据清洗

```text
v0.2.0
```

表示：

> 完成 Agent 接入

```text
v0.3.0
```

表示：

> 完成前端展示

最终迭代一版本：

```text
v1.0.0
```

建议最终提交结构：

```text
main
 |
 └── v1.0.0
```

README 中说明：

```text
项目名称
项目功能
系统架构
运行环境
安装方法
使用方法
项目成员
三人分工
GitHub 地址
测试结果
```

------

# 十八、最终开发流程

整个项目统一按照以下流程进行：

```text
                GitHub Repository
                       │
                       ▼
                     main
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
     成员A分支      成员B分支      成员C分支
      Hadoop         Agent         Frontend
          │            │            │
          ▼            ▼            ▼
       本地开发       本地开发       本地开发
          │            │            │
       Commit        Commit        Commit
          │            │            │
          ▼            ▼            ▼
         Push         Push         Push
          │            │            │
          └────────────┼────────────┘
                       ▼
                 Pull Request
                       │
                       ▼
                   代码审核
                       │
                       ▼
                    测试通过
                       │
                       ▼
                  Merge to main
                       │
                       ▼
                    Release
                       │
                       ▼
                    v1.0.0
```

------

# 十九、团队每日协作规范

每天开始开发：

```bash
git checkout main
git pull origin main
git checkout 自己的分支
git merge main
```

开发过程中：

```text
完成一个小功能
       ↓
本地测试
       ↓
Commit
       ↓
继续开发
```

功能完成：

```text
Push
 ↓
Pull Request
 ↓
队友审核
 ↓
修改
 ↓
审核通过
 ↓
Merge
```

每天结束时在 GitHub Issue 中更新任务状态：

```text
TODO
 ↓
IN PROGRESS
 ↓
DONE
```

这样老师或者团队成员可以通过 GitHub 看到每个人具体完成了什么任务，而不仅仅是最后只有一个“最终代码”。

------

# 二十、项目提交前检查清单

在最终提交项目之前，三个人共同检查：

### GitHub

-  所有代码已经 Push
-  所有功能分支已经合并
-  main 可以正常运行
-  README 已完成
-  Issues 已关闭
-  Pull Request 记录完整
-  Commit 记录能够体现每个人的实际开发过程

### Hadoop

-  数据能够正确读取
-  数据清洗能够运行
-  五维评分能够运行
-  清洗前后评分均真实产生
-  数据量变化能够统计
-  异常数据能够记录

### Agent

-  能识别用户需求
-  能调用 Hadoop
-  能获取任务状态
-  能获取清洗结果
-  能解释五维评分
-  能说明未解决问题
-  失败时不会生成虚假结果

### Frontend

-  能输入自然语言请求
-  能启动任务
-  能查看任务状态
-  能查看五维评分
-  能查看清洗前后变化
-  能查看数据量变化
-  能查看清洗结果
-  能进行 Agent 追问
-  能查看评估报告

以上内容与项目原始需求中的自动执行、状态反馈、五维评分对比、清洗处置说明和结果追问要求保持一致。

------

# 二十一、总结

本项目采用 GitHub 的 **Issue + Branch + Commit + Pull Request + Code Review + main** 协作模式。

三名成员分别负责：

```text
成员A → Hadoop 数据清洗与五维评分
成员B → Agent 与 Hadoop Tool
成员C → 前端展示与系统测试
```

通过独立分支进行开发，通过 Pull Request 进行代码审核，通过 `main` 保存稳定版本。

最终形成：

```text
Issue
  ↓
Branch
  ↓
Development
  ↓
Commit
  ↓
Push
  ↓
Pull Request
  ↓
Code Review
  ↓
Test
  ↓
Merge
  ↓
main
  ↓
Release
```

该方式能够同时实现**多人并行开发、代码版本控制、开发过程留痕、模块之间协作以及最终项目统一发布**。