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

原始数据**不上传仓库**（`.gitignore` 已排除 `*.zip`、`*.dat`），由每位成员在本地配置：

1. `ml-1m.zip` 来源于**南京大学 Moodle 网站**发布的课程数据（本地存放于 `data/`），放入 `data/` 并解压；
2. 解压后包含三个 `.dat` 文件（MovieLens 1M 格式），**无表头**、字段以 `::` 分隔、编码为 **ISO-8859-1**：

| 文件 | 字段格式 | 内容（本地实测行数） |
| --- | --- | --- |
| `ratings.dat` | `UserID::MovieID::Rating::Timestamp` | 1,150,241 条评分及时间 |
| `movies.dat` | `MovieID::Title::Genres` | 4,465 条电影记录，类型以 `\|` 分隔 |
| `users.dat` | `UserID::Gender::Age::Occupation::Zip-code` | 6,946 位用户的性别、年龄段、职业、邮编 |

3. 注意：邮编按**字符串**处理以免丢失前导零；MovieID 不连续；读取需指定 ISO-8859-1 编码。
4. 本地数据集与 GroupLens 官方版行数不同（官方为 1,000,209 / 3,883 / 6,040），包含待清洗的质量问题记录，这正是本项目的评估与清洗对象；文件指纹（md5）与行数登记见 `agent/config/versions.json`，用于可复现性核对。

## 开发流程

团队采用 **Issue + Branch + Commit + Pull Request + Code Review + main** 协作模式。`main` 为稳定分支，禁止直接提交，所有功能通过 `feature/*`、`fix/*`、`docs/*`、`test/*` 分支经 Pull Request 审核后合并。规范详见 [《GitHub 团队协作开发指导文档》](docs/GitHub%20团队协作开发指导文档.md)。

## 运行环境与使用方法

### 环境要求

- **Python ≥ 3.10**：三个服务（Hadoop 服务层 / Agent API / 前端）全部只用标准库，**零第三方依赖**；
- **清洗任务额外需要**：WSL（Ubuntu）或 Linux 环境 + Hadoop 3.4.1 + JDK（8/11/17 均可）。只评估（不清洗）的任务无需 Hadoop；
- 前端渲染测试可选装 Node（`tests/run_all.py` 会自动检测，无 Node 时跳过该块）。

### 数据准备

使用课程给定数据集 **movielens-1m-v2**（`data/ml-1m.zip` 解压）。服务默认读取仓库内 `data/ml-1m-v2/`（运行 `bash scripts_setup/install_data.sh` 一键解压并校验 SHA256），也可用 `--data-dir` 或环境变量 `ML_DATA_DIR` 指定；指纹与行数登记见 `agent/config/versions.json`。

### 启动顺序（三件套）

```bash
# ① 成员A：Hadoop 服务层（8080）
python3 hadoop/src/server.py --mode local --port 8080 --data-dir data/ml-1m-v2
#    local=评估用本机模拟、清洗仍提交 Hadoop Streaming 作业（需 JAVA_HOME/HADOOP_HOME）；
#    纯演示评估任务时无需 Hadoop。--mode hadoop 目前在部分 WSL 环境评估作业
#    reduce 段异常（reducer 子进程 code 139），排查中，演示统一用 local。
# ② 成员B：Agent API（8090）
python3 agent/src/api.py --port 8090 --hadoop-url http://127.0.0.1:8080
# ③ 成员C：前端静态服务 + 反向代理（8000）
python3 frontend/src/serve.py --port 8000 --agent-url http://127.0.0.1:8090
```

浏览器访问 **http://localhost:8000** 即可使用。三个服务都有 `GET /health` 可用于自检。

WSL 一键脚本（成员C提供）：`scripts_setup/install_hadoop.sh` → `sync_to_wsl.sh` → `start_all_wsl.sh`，停止用 `stop_all_wsl.sh`；注意脚本内路径按执行机环境可能需微调。演示口令与预期输出口径见 `docs/演示脚本.md`。

### 验证与测试

```bash
python3 tests/run_all.py                    # 统一入口：hadoop/agent/frontend/一致性 四块
python3 tests/frontend/smoke_demo.py        # 演示前冒烟（演练模式，无需真实数据）
```

迭代一实测结果：`tests/agent` 71 例全过；全链路（评估→清洗→再评估）在 WSL + Hadoop 3.4.1 实跑 SUCCESS，Agent 组装结果与成员A `task_002.json` 基准逐项一致；测试报告见 `reports/test-report/test-report.md`。

### Windows 直跑注意事项

- 8080/8090 可能落在系统保留端口段（绑定报 `WinError 10013`），改用 `--port 18080/18090`（前端 8000 同理可改 18000，`--agent-url`/`--hadoop-url` 随之调整）；
- 清洗环节在 Windows 本机模式下存在路径兼容问题（driver 经 bash 调用），**完整清洗链路请在 WSL 中运行**。
