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
- [《接口规范文档》](docs/接口规范文档.md) — Frontend ↔ Agent ↔ Hadoop Tool 三层接口定义（三人并行开发共同依据）

## 数据说明

原始数据**不上传仓库**（`.gitignore` 已排除 `*.zip`、`*.dat`）。**数据版本登记见 [data/DATASETS.md](data/DATASETS.md)**（含路径、行数、SHA256），后续迭代不得混用不同版本。

| 版本 | 状态 | 说明 |
| --- | --- | --- |
| `movielens-1m-v1` | 已停用 | GroupLens 官方 `ml-1m.zip`，未改动 |
| `movielens-1m-v2` | **当前使用** | 课程给定版本，在官方数据基础上注入了数据质量问题（分隔符被替换、多余/缺失字段、非法取值、重复与冲突、毫秒时间戳、域外 ID） |
| `movielens-1m-v2-clean-v1` | 当前使用 | v2 经本项目 Hadoop 清洗后的数据，对应规则版本 `rule-v2` |

> ⚠️ 迭代一最初误用了官方未改动的 v1，导致"15 项检查 13 项零违规"——数据本身没有问题，清洗实验也就失去意义。现已切换到 v2，并以 v1 作为"清洗是否无损还原"的对照基准。

三个 `.dat` 文件字段格式（v1/v2 相同，**无表头**、字段以 `::` 分隔、编码为 **ISO-8859-1**）：

| 文件 | 字段格式 | v2 原始行数 | 其中官方记录 |
| --- | --- | --- | --- |
| `ratings.dat` | `UserID::MovieID::Rating::Timestamp` | 1,150,241 | 1,000,209 |
| `movies.dat` | `MovieID::Title::Genres` | 4,465 | 3,883 |
| `users.dat` | `UserID::Gender::Age::Occupation::Zip-code` | 6,946 | 6,040 |

注意：邮编按**字符串**处理以免丢失前导零；MovieID 不连续；读取需指定 ISO-8859-1 编码。

## 开发流程

团队采用 **Issue + Branch + Commit + Pull Request + Code Review + main** 协作模式。`main` 为稳定分支，禁止直接提交，所有功能通过 `feature/*`、`fix/*`、`docs/*`、`test/*` 分支经 Pull Request 审核后合并。规范详见 [《GitHub 团队协作开发指导文档》](docs/GitHub%20团队协作开发指导文档.md)。

## 运行环境与使用方法

运行环境：Windows + WSL2（Ubuntu 22.04），JDK 11 + Hadoop 3.4.1（本地模式 `LocalJobRunner`，`fs.defaultFS=file:///`）。清洗与评分**全部通过 Hadoop Streaming 作业执行**。

```bash
# 0) 数据落位（详见 data/DATASETS.md）
cp /mnt/c/Users/HP/OneDrive/Desktop/LLM/ml-1m/ml-1m/{ratings,movies,users}.dat ~/data/ml-1m-v2/

# 1) 完整流程：清洗前评分 -> 数据清洗 -> 清洗后评分
cd /mnt/c/Users/HP/OneDrive/Desktop/DaShuJu/lab2/movielens-data-agent
python3 hadoop/src/driver.py --mode hadoop --stage all \
  --task-id task_002 --data-dir ~/data/ml-1m-v2

# 2) 也可分阶段执行（对应接口规范第 9-11 节）
python3 hadoop/src/driver.py --mode hadoop --stage before --task-id task_002 --data-dir ~/data/ml-1m-v2
python3 hadoop/src/driver.py --mode hadoop --stage clean  --task-id task_002 --data-dir ~/data/ml-1m-v2
python3 hadoop/src/driver.py --mode hadoop --stage after  --task-id task_002 --data-dir ~/data/ml-1m-v2
```

产物：

| 路径 | 内容 |
| --- | --- |
| `reports/quality-report/task_00N.json` | 完整结果契约（五维得分、问题清单、清洗统计、报告对象） |
| `reports/quality-report/quality-report.md` | 数据质量评估报告（人工撰写，数字来自上述 JSON） |
| `hadoop/output/clean/` | 清洗后数据集 |
| `hadoop/output/isolated/` | 隔离数据集 |
| `hadoop/output/audit/` | 逐条处置审计（`<处置>\t<原因>\t<记录>`），用于核查"改了什么、依据什么" |
