# movielens-data-agent

**Agent 驱动的 Hadoop 数据清洗与五维质量评估系统**

本项目以 MovieLens 1M 数据集为基础。用户通过前端输入一次自然语言请求，Agent 自动调用 Hadoop 完成清洗前五维质量评分、数据清洗、清洗后评分和结果对比，并在前端展示任务状态、五维评分、数据变化及评估报告。

## 系统架构

```text
用户
 ↓
Frontend（自然语言输入 / 结果展示）
 ↓
Agent API（任务解析 / 调度 / 状态管理 / 结果解释）
 ↓
Hadoop Tool（实际清洗与五维评分计算）
 ↓
标准 JSON 结果 → Agent 解释 → 前端展示
```

## 项目成员与分工

| 成员 | 负责模块 | 核心任务 |
| --- | --- | --- |
| 成员A | `hadoop/` | 数据分析、MapReduce 清洗、五维质量评分 |
| 成员B | `agent/` | Agent 核心、Hadoop Tool 封装、任务调度、结果解释 |
| 成员C | `frontend/`、`tests/` | 前端页面、接口联调、系统测试 |

## 目录结构

```text
movielens-data-agent/
├── README.md
├── .gitignore
├── docs/                        # 项目文档
├── hadoop/                      # Hadoop 数据清洗与五维评分（成员A）
│   ├── src/  ├── config/  └── scripts/
├── agent/                       # Agent 后端与任务调度（成员B）
│   ├── src/  ├── tools/  └── config/
├── frontend/                    # 前端展示（成员C）
│   ├── src/  └── public/
├── tests/                       # 三模块测试用例（成员C 主导）
│   ├── hadoop/  ├── agent/  └── frontend/
├── data/                        # 本地放置原始数据（不上传仓库）
└── reports/                     # 质量报告与测试报告输出
    ├── quality-report/  └── test-report/
```

## 项目文档

- [《GitHub 团队协作开发指导文档》](docs/GitHub%20团队协作开发指导文档.md) — 团队协作与 GitHub 开发规范
- [《迭代一项目分工文档》](docs/迭代一项目分工文档.md) — 三人分工与职责
- [《引言_项目总体要求与汇报安排》](docs/引言_项目总体要求与汇报安排.md) — 课程总体要求与汇报安排
- [《迭代一_Hadoop数据清洗与Agent基础》](docs/迭代一_Hadoop数据清洗与Agent基础.md) — 迭代一需求说明

## 数据说明

原始 MovieLens 1M 数据**不上传仓库**（`.gitignore` 已排除 `*.zip`、`*.dat`），由每位成员在本地配置：

1. 从 GroupLens 官方下载 `ml-1m.zip`（`https://files.grouplens.org/datasets/movielens/ml-1m.zip`），放入 `data/` 并解压；
2. 解压后包含三个 `.dat` 文件，**无表头**、字段以 `::` 分隔、编码为 **ISO-8859-1**：

| 文件 | 字段格式 | 内容 |
| --- | --- | --- |
| `ratings.dat` | `UserID::MovieID::Rating::Timestamp` | 1,000,209 条整数评分（1—5）及时间 |
| `movies.dat` | `MovieID::Title::Genres` | 3,883 条电影记录，类型以 `\|` 分隔 |
| `users.dat` | `UserID::Gender::Age::Occupation::Zip-code` | 6,040 位用户的性别、年龄段、职业、邮编 |

3. 注意：邮编按**字符串**处理以免丢失前导零；MovieID 不连续；读取需指定 ISO-8859-1 编码。

## 开发流程

团队采用 **Issue + Branch + Commit + Pull Request + Code Review + main** 协作模式。`main` 为稳定分支，禁止直接提交，所有功能通过 `feature/*`、`fix/*`、`docs/*`、`test/*` 分支经 Pull Request 审核后合并。规范详见 [《GitHub 团队协作开发指导文档》](docs/GitHub%20团队协作开发指导文档.md)。

## 运行环境与使用方法

> 待迭代一核心开发完成后，在此补充：运行环境、安装方法、使用方法和测试结果。
