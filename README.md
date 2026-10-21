# movielens-data-agent

**Agent 驱动的 MovieLens 数据分析系统（数据治理 · 分类聚类降维）**

本项目以 MovieLens 1M 数据集为基础，分迭代建设一套由 Agent 驱动的大数据处理与分析系统。用户通过前端输入一次自然语言请求，Agent 解析意图并调用相应工具完成计算，返回**实际执行状态、分析结果及其依据**；没有可用数据、模型或结果时明确返回失败原因，不使用占位数据或示例结果。

已完成的能力：

| 迭代 | 能力 | 主要产出 |
| --- | --- | --- |
| 迭代一 | Hadoop 数据清洗 + 五维质量评估（Accurate / Complete / Unique / Up-to-date / Consistent） | 清洗快照、`rule-v2` 规则、`T1/T2`、评估报告 |
| **迭代二** | **分类（是否 ≥4 分）、聚类（用户群体）、降维（PCA / t-SNE）三类分析** | 分类模型、`profile-v1` 画像、簇归属、降维坐标、评价指标与版本登记 |
| 迭代三 | 知识图谱及推荐 / 图挖掘 / 链接分析 | 规划中 |

## 系统架构

```text
用户
 ↓
Frontend（自然语言输入 / 任务状态 / 结果展示 / 追问）
 ↓
Agent API（意图路由 / 任务调度 / 状态管理 / 结果解释）
 ↓
┌──────────────┬────────────────────────────────────┐
│ Hadoop Tool  │ 分析工具（各自独立子进程）            │
│ 清洗+五维评分 │ 聚类 kmeans / dbscan                │
│              │ 分类 gnb / cart                     │
│              │ 降维 pca / tsne                     │
└──────────────┴────────────────────────────────────┘
 ↓
标准 JSON 信封 → Agent 组装（透传算法数值，不改写）→ 前端展示
```

**关键设计**：

- **工具契约同构**：六个分析工具统一 `run(payload) -> 信封 dict`，CLI 为 `python3 -I <tool> --request req.json --output out.json`；注册表 `agent/tools/registry.py` 以 `agent/config/analysis.json` 为单一真源，未登记的算法诚实返回 `MODEL_NOT_FOUND`，绝不借用别的算法顶替。
- **子进程隔离**：每个工具在独立进程执行（`-I` 模式）。WSL2 + Python 3.10 存在非确定性解释器段错误，隔离保证只影响子进程、API 服务恒存活，失败自动重试 1 次（`attempt=2` 属正常兜底）。
- **结果不伪造**：指标不适用时如实填 `null` 并说明（如单簇的轮廓系数）；任务失败保留已完成算法的真实部分结果；`FAILED` 恒带 `error{code,message,stage,detail}`。
- **五级版本可追溯**：数据版本 / 清洗规则版本 / 画像版本 / 模型版本 / 结果版本均登记在 `agent/config/versions.json`，并随每个结果信封返回。

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
├── requirements.txt             # 迭代二分析工具依赖（numpy / scikit-learn）
├── docs/                        # 项目文档（迭代一 / 迭代二）
├── hadoop/                      # Hadoop 数据清洗与五维评分（成员A）
│   ├── src/  ├── config/  └── scripts/
│   ├── output/clean/            # 清洗快照（运行产物，不进 Git）
├── agent/                       # Agent 后端与任务调度（成员B）
│   ├── src/                     # api / router / analysis_runner / explainer
│   ├── tools/                   # 六个分析工具 + cli 工具
│   │   ├── clustering/          #   kmeans / dbscan / 画像构建
│   │   ├── classification/      #   gnb / cart
│   │   ├── dimensionality_reduction/  # pca / tsne
│   │   └── common/              #   数据读取与时间切分（成员A）
│   ├── config/                  # analysis.json（算法注册）/ versions.json（版本登记）
│   └── artifacts/               # 画像、簇归属等工件（随仓库提交，便于复现）
├── frontend/                    # 前端展示（成员C）
│   ├── src/  └── public/
├── tests/                       # 三模块测试用例（成员C 主导）
│   ├── hadoop/  ├── agent/  └── frontend/
├── data/                        # 本地放置原始数据（不上传仓库）
└── reports/                     # 报告输出
    ├── quality-report/          #   迭代一五维质量评估
    ├── classification/          #   分类模型卡片、指标、对比
    ├── analysis/                #   聚类实验记录
    ├── experiments/             #   时间切分快照
    └── test-report/             #   系统测试报告
```

## 项目文档

- [《引言_项目总体要求与汇报安排》](docs/引言_项目总体要求与汇报安排.md) — 课程总体要求与汇报安排

迭代一（docs/迭代一/）：
- [《迭代一_Hadoop数据清洗与Agent基础》](docs/迭代一/迭代一_Hadoop数据清洗与Agent基础.md) — 迭代一需求说明
- [《迭代一项目分工文档》](docs/迭代一/分工/迭代一项目分工文档.md) — 三人分工与职责
- [《接口规范文档》](docs/迭代一/分工/接口规范文档.md) — Frontend ↔ Agent ↔ Hadoop Tool 三层接口定义（三人并行开发共同依据）
- [《GitHub 团队协作开发指导文档》](docs/迭代一/分工/GitHub%20团队协作开发指导文档.md) — 团队协作与 GitHub 开发规范
- [《evaluation-method》](docs/迭代一/交付文档/evaluation-method.md) · [《流程与Prompt设计》](docs/迭代一/交付文档/流程与Prompt设计.md) · [《演示脚本》](docs/迭代一/交付文档/演示脚本.md) — 成员交付文档

迭代二（docs/迭代二/）：

需求与规范（`docs/迭代二/分工/`）：
- [《迭代二_分类聚类降维与分析Agent》](docs/迭代二/迭代二_分类聚类降维与分析Agent.md) — 迭代二需求说明
- [《迭代二项目分工文档》](docs/迭代二/分工/迭代二项目分工文档.md) — 三人分工与职责
- 《迭代二接口扩展规范》 · 《迭代二数据与实验规范》 · 《迭代二测试与验收清单》 · 《迭代二GitHub协作与提交计划》 · 三份成员任务书

交付文档（`docs/迭代二/交付/`）：
- [《成员B_前端联调说明》](docs/迭代二/交付文档/成员B_前端联调说明.md) — 三类任务的字段语义、状态机、渲染红线与错误码文案
- [《特征字典-feat-v1》](docs/迭代二/交付/特征字典-feat-v1.md) — 分类特征定义与防泄漏口径
- [《数据就绪检查》](docs/迭代二/交付/数据就绪检查.md) — 清洗快照校验和与时间切分
- [《分类工具交接》](docs/迭代二/交付/分类工具交接.md) — 分类工具契约与端到端复核
- [《降维与前端交付-成员C》](docs/迭代二/交付/降维与前端交付-成员C.md) — 两种降维算法、信息保留指标与可视化
- [《前端渲染修复记录-成员C》](docs/迭代二/交付/前端渲染修复记录-成员C.md) — 由真实字段错配驱动的修复与契约测试

实验与评价结果：
- 聚类：`reports/analysis/clustering-profile-v1-2026-10-18.md`（含复跑零漂移实证）
- 分类：`reports/classification/`（模型卡片、指标、双算法对比、`model-registry.json`）
- 时间切分：`reports/experiments/split-v1.json`
- 系统测试：`reports/test-report/test-report.md`

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

## 迭代二：分类 / 聚类 / 降维分析

### 三类任务与六种算法

| 类别 | 任务 | 算法（各两种） | 工具名 | 算法出处 |
| --- | --- | --- | --- | --- |
| 分类 | 预测用户对某电影评分是否 `>= 4` | 高斯朴素贝叶斯 / 决策树（信息增益） | `classification_gnb` / `classification_cart` | 课程课件《26Fall-008-分类1010+1014》第 25–36 / 38–61 页 |
| 聚类 | 按训练期观影偏好划分用户群体 | K-Means（kmeans++）/ DBSCAN | `clustering_kmeans` / `clustering_dbscan` | 经典划分聚类 / 经典密度聚类；**课程 PPT 章节页码待团队核对后登记**（不凭惯例声称） |
| 降维 | 压缩 27 维画像并对照降维前后聚类 | PCA（对称特征分解）/ t-SNE | `dimensionality_reduction_pca` / `dimensionality_reduction_tsne` | PCA 标准定义；t-SNE 见 van der Maaten & Hinton, JMLR 2008；**PPT 页码待核对** |

### 数据口径

- **输入**：迭代一清洗快照 `movielens-1m-v2-clean-v1`（996,113 评分 / 3,883 电影 / 6,025 用户），清洗规则 `rule-v2`。
- **时间边界**：`T1 = 2000-11-22`（训练期截止）、`T2 = 2000-12-10`（验证期截止），运行期从 `hadoop/config/rules.json` 读取，代码不硬编码日期。
- **画像 `profile-v1`**：27 维 = 9 个行为统计 + 18 个类型占比，**只用训练期（`Timestamp <= T1`）记录**；z-score 的均值/标准差只用画像可用（训练期评分 `>= 10` 条）用户拟合。可用 4783 / 历史不足 74 / 训练期无记录 1168，另有 13 个孤儿引用用户如实登记。
- **特征字典**：`docs/迭代二/交付/特征字典-feat-v1.md`；人口学属性（性别/年龄/职业）未纳入聚类特征，原因见 `analysis.json` 的 `feature_dict._excluded`。

### 接口

| 方法/路径 | 说明 |
| --- | --- |
| `POST /api/analysis/clustering/tasks` | 创建聚类任务 |
| `POST /api/analysis/classification/tasks` | 创建分类任务（需 `user_id` + `movie_id`） |
| `POST /api/analysis/dimensionality-reduction/tasks` | 创建降维任务 |
| `GET /api/tasks/{id}` | 查询状态（**复用迭代一接口**，不是 `/api/analysis/...`） |
| `GET /api/tasks/{id}/result` | 任务结果 |
| `POST /api/tasks/{id}/ask` | 对已有结果追问 |
| `GET /health` | 含 `analysis` 块：当前版本与已注册工具 |

- **不传 `algorithm`** = 双算法对照，执行顺序为登记顺序：聚类 `['dbscan','kmeans']`、分类 `['cart','gnb']`、降维 `['pca','tsne']`。
- 业务失败一律 **HTTP 200 + `{status:"FAILED", error:{code,message,stage,detail}}`**，前端按 JSON 统一解析，不要按状态码分支。
- 完整字段说明（含每个渲染红线）见 `docs/迭代二/交付文档/成员B_前端联调说明.md`。

### 已知限制（如实登记）

- **聚类算法 PPT 页码未登记**：K-Means / DBSCAN 的课程 PPT 章节页码待团队核对，文档中一律写“待核对后登记”，未声称“来自 PPT”。
- **降维的样本量门槛（实测确认）**：降维模型只在画像拟合用户上训练，**用户数 < 3 直接拒绝**；工具内置的「降维前后聚类对照」使用固定的 `clustering_k`（默认 6），因此：

  | 场景 | 最小拟合用户数 | 不满足时的报错 |
  | --- | --- | --- |
  | 只跑 PCA | **≥ 7** | `clustering_k=6 需满足 2<=k<=用户数(N)` |
  | 跑 t-SNE 或双算法 | **≥ 91**（默认 `perplexity=30`，要求 `3*perplexity < 样本数`） | `perplexity=30.0 需要 3*perplexity < 样本数(N)` |

  已知缺陷：`clustering_k` 未按用户数自适应（应取 `min(k, 用户数)` 或跳过对照），当前只能靠多选用户绕过。可用下面这 20 个拟合用户（面板里做快速演示）：
  ```
  1161,1162,1163,1164,1166,1167,1168,1169,1170,1171,1172,1173,1174,1175,1176,1177,1178,1179,1180,1181
  ```

  需要跑 t-SNE / 双算法时，直接取画像里前 120 个拟合用户：

  ```bash
  python3 -c "import json;ids=[json.loads(l)['user_id'] for l in open('agent/artifacts/profiles/profile-v1.jsonl',encoding='utf-8') if json.loads(l).get('fit') and json.loads(l).get('vector')][:120];print(','.join(map(str,ids)))"
  ```
- **DBSCAN 无「到质心距离」**：密度聚类没有质心概念，该字段不适用（如实为空，不补 0）。
- **聚类是在全部拟合用户（4783 人）上拟合的**，请求里的 `user_ids` 只是查询对象，因此群体规模（977/235/307/1780/103/1381）不是对请求用户的划分。
- **分类概率未经校准**，不能当作真实概率直接解读；阈值在验证期选定。
- 执行日志中的 `attempt=2` 是环境级崩溃后的正常重试，不是缺陷。

## 开发流程

团队采用 **Issue + Branch + Commit + Pull Request + Code Review + main** 协作模式。`main` 为稳定分支，禁止直接提交，所有功能通过 `feature/*`、`fix/*`、`docs/*`、`test/*` 分支经 Pull Request 审核后合并。规范详见 [《GitHub 团队协作开发指导文档》](docs/迭代一/分工/GitHub%20团队协作开发指导文档.md)。

## 运行环境与使用方法

### 环境要求

- **Python ≥ 3.10**：三个服务（Hadoop 服务层 / Agent API / 前端）全部只用标准库，**零第三方依赖**；
- **迭代二分析工具额外需要** `requirements.txt`（numpy、scikit-learn）：分类、聚类、降维的训练与预测要用，
  `python3 -m pip install -r requirements.txt` 即可；不安装不影响迭代一三件套的运行。
  装好后可用 `bash check_env.sh` 自检（会分别验证普通模式与 `-I` 隔离模式下能否 import numpy）；
- **清洗任务额外需要**：WSL（Ubuntu）或 Linux 环境 + Hadoop 3.4.1 + JDK（8/11/17 均可）。只评估（不清洗）的任务无需 Hadoop；
- 前端渲染测试可选装 Node（`tests/run_all.py` 会自动检测，无 Node 时跳过该块）；
- **大模型增强层（可选，零依赖）**：只用标准库 HTTP，不需要装任何包，配置 `.env` 即可，
  支持 Anthropic 与所有 OpenAI 兼容服务（DeepSeek / 通义千问 / Moonshot / 智谱 / Ollama 等），
  详见下一节。不配置不影响任何功能，追问走确定性模板。

> **依赖可见性说明**：分析工具按契约以 `python3 -I` 在子进程中运行（隔离模式）。`-I` 隐含 `-s`，**不含用户级
> site-packages**；调度器已自动把用户级目录补回子进程的 `sys.path`，所以 `pip install --user` 装的 numpy 也能用。
> 若依赖装在别处，可用 `ML_TOOL_EXTRA_PATH`（`os.pathsep` 分隔）追加。手工裸跑 `python3 -I <tool>` 时不含该补丁，
> 需要自行使用带 numpy 的解释器——这是 CLI 直跑与 Agent 调用的唯一差异。

### 数据准备

使用课程给定数据集 **movielens-1m-v2**（`data/ml-1m.zip` 解压）。服务默认读取仓库内 `data/ml-1m-v2/`（运行 `bash scripts_setup/install_data.sh` 一键解压并校验 SHA256），也可用 `--data-dir` 或环境变量 `ML_DATA_DIR` 指定；指纹与行数登记见 `agent/config/versions.json`。

迭代二的分类 / 聚类 / 降维读取**清洗后快照**。默认位置为 `hadoop/output/clean/`（由 `agent/config/analysis.json` 的 `input.clean_dir` 指定），也可用 `ML_CLEAN_DIR` 覆盖。Agent 执行分析任务时会自动按该登记值注入，**无需手工设置**。

### 启动顺序（三件套）

```bash
# 清洗任务需要 Hadoop 环境；仅做三类分析任务时可跳过 ① 与下面的 export
export JAVA_HOME=$HOME/opt/jdk-17.0.20.1+1
export HADOOP_HOME=$HOME/opt/hadoop
export PATH=$JAVA_HOME/bin:$HADOOP_HOME/bin:$PATH

# ① 成员A：Hadoop 服务层（8080）
#    --mode hadoop：评估用本机模拟，清洗提交真实 Hadoop Streaming 作业
python3 hadoop/src/server.py --port 8080 --mode hadoop --data-dir "$PWD/data/ml-1m-v2" &

# ② 成员B：Agent API（8090）
python3 agent/src/api.py --port 8090 --hadoop-url http://127.0.0.1:8080 &

# ③ 成员C：前端静态服务 + 反向代理（8000）
python3 frontend/src/serve.py --port 8000 --agent-url http://127.0.0.1:8090 &
```

浏览器访问 **http://localhost:8000** 即可使用。三个服务都有 `GET /health` 可用于自检（Agent 的 `/health` 还会列出当前已注册的六个分析工具）。

> `JAVA_HOME` / `HADOOP_HOME` 写在 `~/.bashrc` 中，**只对交互式 shell 生效**。用脚本或非交互方式启动 8080 时必须显式 `export`，否则清洗任务会报 `HADOOP_EXECUTION_ERROR: 找不到 Hadoop Streaming JAR`。

WSL 一键脚本（成员C提供）：`scripts_setup/install_hadoop.sh` → `sync_to_wsl.sh` → `start_all_wsl.sh`，停止用 `stop_all_wsl.sh`；注意脚本内路径按执行机环境可能需微调。演示口令与预期输出口径见 `docs/迭代一/交付文档/演示脚本.md`。

### 大模型增强层（可选，多服务商）

系统默认走**确定性模板**路径回答追问，不依赖任何外部服务。配置大模型后，
模板未命中的问题会追加一段由模型生成、且被强制只引用真实结果的解释。

**为什么是"可选增强"而不是主路径**：项目纪律要求"不得编造结果"，
LLM 一旦不可用（未配置 / 网络不通 / 限流 / 鉴权失败）就必须能无感降级，
所以模板是主路径，模型只做补充。四条红线写在 `agent/src/llm.py` 头部：

1. 只用于【理解用户表述】和【解释已真实执行的结果】，绝不生成或修改任何评分、条数、版本、时间边界；
2. 传给模型的是结果 JSON 的**只读摘录** + 强制"只引用给定数字"的系统提示；
3. 任何失败一律返回 `None`，调用方回退模板；
4. Prompt 全文公开在 `agent/config/prompts/`，便于评审。

#### 支持的服务商

实现上只有两种协议，都用标准库 `urllib` 发请求，**不依赖任何第三方包**：

| 协议 | 接口 | 覆盖 |
| --- | --- | --- |
| `anthropic` | `POST {base}/v1/messages` | Anthropic Claude（官方或中转） |
| `openai` | `POST {base}/chat/completions` | OpenAI、DeepSeek、通义千问（DashScope 兼容模式）、Moonshot、智谱 GLM、SiliconFlow、火山方舟、Ollama / vLLM / OneAPI 等自建网关 |

内置服务商预设（`ML_LLM_PROVIDER` 可选值）及其默认地址：

| 值 | 默认 base_url | 默认模型 |
| --- | --- | --- |
| `anthropic` | `https://api.anthropic.com` | `claude-opus-5` |
| `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| `deepseek` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| `moonshot` | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` |
| `ollama` | `http://127.0.0.1:11434/v1` | `qwen2.5`（本地，无需密钥） |

> 默认模型名可能随服务商调整而过时，**建议显式设置 `ML_LLM_MODEL`** 为你账号可用的模型。
> 不在表里的 OpenAI 兼容服务，用 `ML_LLM_PROVIDER=openai` + 自定义 `ML_LLM_BASE_URL` 即可接入。

#### 配置步骤

```bash
# ① 复制模板
cp .env.example .env

# ② 编辑 .env，填三行（以 DeepSeek 为例）
#    ML_LLM_PROVIDER=deepseek
#    ML_LLM_API_KEY=sk-你的密钥
#    ML_LLM_MODEL=deepseek-chat

# ③ 重启 Agent（.env 在进程启动时加载）
python3 agent/src/api.py --port 8090 --hadoop-url http://127.0.0.1:8080
```

`.env` 已被 `.gitignore` 排除，**不会进仓库**；`.env.example` 是不含真实密钥的模板，
里面列了七种服务商的完整示例，复制对应一组即可。

**最省事的写法**：只填统一变量 `ML_LLM_API_KEY`，代码会按密钥自动推断服务商
（`ANTHROPIC_*` → anthropic，其余 → openai）。

#### 可配置项

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `ML_LLM_PROVIDER` | 服务商，见上表；不填则按凭据自动判断 | 自动 |
| `ML_LLM_API_KEY` | 统一凭据（优先于各家专用变量） | 无 |
| `ML_LLM_BASE_URL` | 接口地址（走代理/自建网关时用） | 按服务商 |
| `ML_LLM_MODEL` | 模型名 | 按服务商 |
| `ML_LLM_TIMEOUT` | 单次调用超时（秒） | `60` |
| `ML_LLM_MAX_RETRIES` | 网络类失败的重试次数（4xx 不重试） | `1` |
| `ML_LLM_TEMPERATURE` | 采样温度；**不设则不下发该字段**（兼容推理型模型） | 未设 |
| `ML_LLM_DISABLE` | 设为 `1` 强制关闭（即使配了凭据） | 未设 |

**兼容旧变量**：`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` / `OPENAI_API_KEY`。

**优先级：真实环境变量 > `.env` > 代码默认值。** 所以 `export ML_LLM_API_KEY=...`
永远覆盖 `.env`，便于临时切换或多环境调试。`.env` 中的空值视为"未配置"，不会注入。

#### 怎么确认接好了

```bash
curl -s localhost:8090/health | python3 -m json.tool | sed -n '/"llm"/,/^    }/p'
```

会看到 `llm` 诊断块（**只暴露"有没有"，不回显密钥**）：

```json
"llm": {
  "enabled": true,
  "disabled_by_flag": false,
  "supported_providers": ["anthropic", "deepseek", "moonshot", "ollama",
                          "openai", "qwen", "zhipu"],
  "env_file_keys": ["ML_LLM_PROVIDER", "ML_LLM_API_KEY", "ML_LLM_MODEL"],
  "provider": "deepseek",
  "protocol": "openai",
  "model": "deepseek-chat",
  "base_url_host": "api.deepseek.com",
  "credential_var": "ML_LLM_API_KEY",
  "credential_masked": "sk-xxx***abcd",
  "timeout_s": 60.0,
  "max_retries": 1,
  "temperature": null
}
```

`llm_enabled: true` 且追问返回的 `source` 为 `template+llm`，说明已在用模型。

若 `enabled` 为 `false`，按 `reason` 字段排查：

| `reason` / 现象 | 原因 | 处置 |
| --- | --- | --- |
| `未配置任何凭据` | 没读到密钥 | 检查 `.env` 是否在仓库根、键名是否拼错、值是否为空 |
| `未知服务商 'xxx'` | `ML_LLM_PROVIDER` 拼错 | 改为上表中的值，或留空让其自动判断 |
| `ML_LLM_DISABLE 已开启` | 显式关了 | 去掉该变量或设为 `0` |
| `env_file_keys` 为空 | `.env` 未被加载 | 确认文件名是 `.env` 且在仓库根；或用 `export` 注入 |
| `enabled: true` 但 `source` 仍是 `template` | 问题命中了模板，本就不调用模型 | 正常行为 |
| 日志出现 `调用失败（provider），回退到模板路径` | 鉴权 / 网络 / 限流 / 模型名错 | 按日志里的 HTTP 码排查；`401` 多为密钥错，`404` 多为 base_url 或模型名错 |

> 模板未命中时才调用模型（`explainer.py` 里 `if not matched` 分支），
> 所以大部分标准问法（归属、群体特征、指标、参数、局限、版本）根本不会产生 API 调用。

### 验证与测试

```bash
python3 tests/run_all.py                    # 统一入口：hadoop/agent/frontend/一致性 四块
python3 tests/run_all.py --only agent       # 只跑某一块
python3 tests/run_all.py --report reports/test-report/test-report.md   # 同时生成报告
python3 tests/frontend/smoke_demo.py        # 演示前冒烟（演练模式，无需真实数据）
```

**当前实测（2026-10-21）**：全套 **291 用例 / 0 失败**（Hadoop 7 · Agent 248 · 前端 28 · 三层一致性 8），测试报告见 `reports/test-report/test-report.md`。

前端除常规渲染单测外，另有 **28 项含契约测试**（`tests/frontend/test_render_contract.mjs`）：用真实任务结果裁剪出的 fixtures 驱动渲染，断言结果页不出现 `—` 占位、代表性作品与类型占比等关键内容确实渲染出来——这是为了避免「测试用构造数据、字段名按渲染代码的期望写，导致字段错配测不出来」这一盲区。

### 快速上手：跑一个分析任务

```bash
# 聚类（不传 algorithm = 双算法对照）
curl -X POST localhost:8090/api/analysis/clustering/tasks \
  -H 'Content-Type: application/json' -d '{"user_ids":[1000,6040]}'

# 分类（需 user_id + movie_id）
curl -X POST localhost:8090/api/analysis/classification/tasks \
  -H 'Content-Type: application/json' -d '{"user_id":1000,"movie_id":1}'

# 降维：只跑 PCA 时 >= 7 个拟合用户即可（内部聚类对照默认 k=6）
curl -X POST localhost:8090/api/analysis/dimensionality-reduction/tasks \
  -H 'Content-Type: application/json' \
  -d '{"user_ids":[1161,1162,1163,1164,1166,1167,1168],"algorithm":"pca"}'

# 降维双算法（含 t-SNE）：需 >= 91 个拟合用户（默认 perplexity=30，要求 3p < 样本数）
curl -X POST localhost:8090/api/analysis/dimensionality-reduction/tasks \
  -H 'Content-Type: application/json' \
  -d '{"user_ids":[1161,1162,1163,1164,1166,1167,1168,1169,1170,1171,1172,1173,1174,1175,1176,1177,1178,1179,1180,1181,1182,1183,1184,1185,1186,1188,1189,1190,1191,1192,1193,1194,1195,1196,1197,1199,1200,1202,1203,1204,1205,1206,1207,1208,1209,1211,1212,1213,1214,1215,1216,1217,1218,1219,1220,1221,1222,1223,1224,1225,1226,1227,1228,1229,1230,1231,1232,1233,1234,1235,1236,1237,1238,1239,1240,1241,1242,1243,1244,1245,1246,1247,1248,1249,1250,1253,1254,1255,1258,1260,1261,1262,1263,1264,1266,1267,1268,1269,1270,1271,1272,1273,1274,1275,1276,1277,1278,1279,1280,1281,1282,1283,1284,1285,1286,1288,1289,1290,1291,1292]}'

# 查询状态 → 取结果 → 追问
curl localhost:8090/api/tasks/<task_id>
curl localhost:8090/api/tasks/<task_id>/result
curl -X POST localhost:8090/api/tasks/<task_id>/ask \
  -H 'Content-Type: application/json' -d '{"question":"群体2有什么特征"}'
```

> 以上命令在 WSL 中整行复制执行；**不要在行尾加反斜杠续行**（部分终端粘贴会出错）。

### Windows 直跑注意事项

- 8080/8090 可能落在系统保留端口段（绑定报 `WinError 10013`），改用 `--port 18080/18090`（前端 8000 同理可改 18000，`--agent-url`/`--hadoop-url` 随之调整）；
- 清洗环节在 Windows 本机模式下存在路径兼容问题（driver 经 bash 调用），**完整清洗链路请在 WSL 中运行**。
