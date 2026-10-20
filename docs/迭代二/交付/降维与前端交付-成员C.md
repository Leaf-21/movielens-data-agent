# 降维与前端交付（成员C，迭代二）

> 对应任务书：`docs/迭代二/分工/成员C_降维与前端展示任务书.md`
> 交付内容：两种降维算法工具、降维前后聚类对照、二维可视化、前端三类结果区、系统测试与验收。
> 版本口径：`data_version=movielens-1m-v2-clean-v1`、`cleaning_rule_version=rule-v2`、
> `profile_version=profile-v1`、`feature_version=profile-v1`、`analysis_version=iter2-analysis-v1`、
> `split_version=split-v1`。
> **本文件所有数值均来自真实运行产物（`agent/tools/dimensionality_reduction/out_{pca,tsne}_full.json`），
> 非示例、非估算。**

## 一、交付清单对照

| 交付清单项 | 状态 | 证据 / 位置 |
|---|---|---|
| 两种降维算法可独立调用 | 已交付 | `pca_tool.py` / `tsne_tool.py`，支持命令行与 registry 契约 |
| 降维模型、坐标、参数、输入画像版本、输出版本可追溯 | 已交付 | 每种算法信封含 `model_version` / `result_version` / 全部版本号，坐标逐用户落盘 |
| 降维前/后聚类对照结果及评价口径 | 已交付 | 同一用户集合 + 同一 K-Means（k=6, seed=42），见第三节 |
| 信息保留情况和资源开销（无法测量项需标注） | 已交付 | PCA 报告解释方差；t-SNE 报告 kNN 一致率并声明无统一信息保留指标，见第四节 |
| 二维可视化与清晰图例 | 已交付 | 坐标字段 `x`/`y`，PCA 每轴有载荷解释，t-SNE 声明轴为抽象坐标，见第五节 |
| 分类、聚类、降维三个结果区 | 已交付 | `frontend/public/js/render.js` 的 `Render.analysis()` 按 `task_type` 分派 |
| 任务状态、失败原因、数据不可用提示 | 已交付 | `app.js` 轮询 + 失败展示 `error.code/message/stage` |
| 算法对照、结果依据、局限与追问入口 | 已交付 | 结果区展示对照指标与 limitations；`POST /api/tasks/{id}/ask` 追问 |
| 前端与 Agent 的真实接口联调 | 已交付 | 前端反代 → Agent(8090) → Hadoop(8080) 全链路真实运行 |
| 系统测试报告、图表与结果报告索引 | 已交付 | `reports/test-report/test-report.md`（261 用例全过） |

## 二、两种降维算法

| 项目 | PCA | t-SNE |
|---|---|---|
| 工具实现 | `agent/tools/dimensionality_reduction/pca_tool.py` | `agent/tools/dimensionality_reduction/tsne_tool.py` |
| 共用底座 | `dr_common.py`（参数白名单、坐标投影、聚类对照、信封与版本派生） | 同左 |
| 工具名（registry 契约） | `dimensionality_reduction_pca` | `dimensionality_reduction_tsne` |
| 算法出处处 | 课程课件（主成分分析）；**PPT 章节/页码待与团队核对后登记，当前不声称已核实** | van der Maaten & Hinton, JMLR 2008；**课件页码待核实** |
| 输入维度 | 27 维（profile-v1：9 个行为统计 + 18 个类型占比） | 同左 |
| 输出维度 | 2 维（默认，用于可视化；可配 `target_dimensions`） | 2 维 |
| 拟合样本 | profile-v1 中 `status=OK` 的训练期画像用户，**4783 人** | 同左 |
| 关键参数 | `target_dimensions=2`, `information_retention_threshold=0.8`, `clustering_k=6` | `perplexity=30`, `n_iter=1000`, `learning_rate=200`, `early_exaggeration=12`, `random_state=42`, `knn_k=10` |
| 样本外用户处理 | 用已拟合的均值/主成分做投影，标记 `reliability_low=true` | **不投影**（无复用投影矩阵），坐标 `null`、`status=NOT_PROJECTED_BY_TSNE`，不伪造坐标 |
| 确定性 | 主成分符号规范化（每成分内 \|载荷\| 最大者取正），逐位可复现 | 固定 `random_state=42`，同机可复现 |

### 版本戳（真实运行）

| 算法 | model_version | result_version |
|---|---|---|
| PCA | `dr-3de89cb741` | `drres-dcbac876692d` |
| t-SNE | `dr-43ef26e13a` | `drres-e5db1e473368` |

## 三、降维前后聚类对照

**对照口径**：降维前后使用**完全相同的 4783 名用户集合**、同一 K-Means 实现（`init=kmeans++`, `max_iter=100`, `tol=1e-6`）、同一 `k=6`、同一 `seed=42`。SSE 在低维空间天然更小，**不能跨空间比较绝对值**，应以无量纲的轮廓系数与 DBI 为主要参照。

### PCA 前后对照

| 指标 | 原始 27 维 | 降维后 2 维 | 变化 |
|---|---:|---:|---:|
| 轮廓系数 silhouette（越高越好） | 0.11987 | **0.33761** | +0.21774 |
| Davies-Bouldin DBI（越低越好） | 1.93451 | **0.87814** | −1.05637 |
| 簇内平方误差 SSE（仅参考，勿跨空间比较） | 94764.75 | 8816.13 | −85948.61 |

### t-SNE 前后对照

| 指标 | 原始 27 维 | 降维后 2 维 | 变化 |
|---|---:|---:|---:|
| 轮廓系数 silhouette | 0.11987 | **0.35821** | +0.23834 |
| Davies-Bouldin DBI | 1.93451 | **0.86706** | −1.06745 |
| 簇内平方误差 SSE（仅参考） | 94764.75 | 10623.35 | −84141.40 |

**诚实结论**：
- 两种降维后的轮廓系数都明显高于原始 27 维、DBI 都明显更低，说明两类算法把用户压到 2 维后，K-Means 的簇**在 2 维指标意义上更「紧凑可分」**。
- 但这**不等于「降维更优」**：轮廓系数在低维空间系统性偏高是已知现象，且 t-SNE 不保留全局结构（见第四节）。对照只说明「降维表示上簇结构更清晰」，**不得据此宣称某算法必然更好**。
- 二维图仅用于观察结构；优劣结论须同时参考本表指标与局限说明（数据与实验规范 §五.6）。

## 四、信息保留与资源开销

### PCA

- 指标：**解释方差比**（第 i 个特征值 / 全部特征值之和）。
- PC1 + PC2 累计解释方差 = **0.2866**（约 28.7%）。
- 达 80% 累计解释方差需 **12 维**（`dimensions_for_threshold=12`）。
- 零方差方向 **1 个**：验证 18 个类型占比之和恒为 1 导致的线性冗余（有效自由度 17），PCA 把冗余反映到零方差方向上，**不视为信息丢失**。
- 前 10 个主成分解释方差比：0.1497, 0.1369, 0.1145, 0.0686, 0.0612, 0.0558, 0.0486, 0.0423, 0.0366, 0.0365。
- 资源：耗时 **45422 ms**（约 45 秒），`tracemalloc` 进程内峰值分配约 **23.9 MB**（仅计 Python 分配，不含解释器与 NumPy C 层分配）。

### t-SNE

- **不报告解释方差**（t-SNE 无线性特征，`explained_variance_ratio=null`，不伪造）。
- 结构保留参考指标：**kNN 一致率**（高维 k 近邻在低维是否仍近邻），`knn_k=10`。
  - `knn_agreement = 0.00274`，`knn_baseline = 0.00209`。
  - **如实说明：kNN 一致率几乎等同随机基线**，表明在本 27 维画像上，t-SNE 的 2 维嵌入未能保住局部邻域结构。这是必须如实报告的科学结论，不美化。
- `final_kl = 4.8052`，`perplexity = 30.0`。
- 资源：耗时 **1063540 ms**（约 17.7 分钟），`tracemalloc` 峰值分配约 **1.84 GB**（仅计 Python 分配）。

## 五、二维可视化

### 坐标字段

坐标数组每个元素形如：

```json
{"user_id": 1161, "x": -0.1470, "y": -0.2166, "status": "SUCCESS",
 "reliability_low": false, "is_fit_user": true}
```

- `x` / `y`：二维图横纵坐标（前端散点图直接使用）。
- `status`：`SUCCESS` 为正常投影；t-SNE 的样本外用户为 `NOT_PROJECTED_BY_TSNE`（坐标 `null`）。
- `reliability_low`：`true` 表示样本外投影，可信度低，图中应作区分（如空心点）。
- 颜色/图例含义：按 K-Means 簇归属着色（k=6），样本外/低可靠度单独图例。

### 轴含义

- **PCA**：
  - PC1（横轴）主轴载荷：`rating_bias`(0.4085)、`avg_rating`(0.4085)、`high_share`(0.3977)、`avg_movie_pop`(0.3236) → 语义上近似「评分松紧轴」。
  - PC2（纵轴）主轴载荷：`genre_share_action`(0.4084)、`genre_share_sci-fi`(0.3977)、`genre_share_adventure`(0.3928)、`genre_share_drama`(−0.3259) → 语义上近似「类型口味轴」。
  - **注意**：主成分轴的意义是载荷的线性组合，具体语义需查 `axis_meaning.loadings`，不能仅用单个原特征名命名。
- **t-SNE**：两轴均为**抽象嵌入坐标，无线性特征含义**（`axis_meaning` 已显式声明，`loadings=null`）。簇的位置/朝向可旋转翻转，仅固定 `random_state` 保证同机可复现。

## 六、前端展示（三类结果区）

前端在 `frontend/public/js/`：

- `app.js`：提交、轮询、失败处理、追问；按 `task_type` 分派渲染。
- `render.js`：`Render.scores/versions/statistics/problems/report/sample`（迭代一清洗）与 `Render.analysis()`（迭代二分类/聚类/降维）。
- `api.js`：封装 Agent 接口（`createTask`、`createAnalysisTask`、`getStatus`、`getResult`、`ask`、`health`）。

**结果区实现要点**：
- 三类分析任务共用 `GET /api/tasks/{id}` 与 `/result`，按 `task_type` 决定渲染分支。
- 降维结果区展示：二维散点图、原始/目标维度、信息保留（PCA 解释方差 / t-SNE kNN 一致率并声明局限）、降维前后聚类对照指标、资源开销、模型/结果版本、限制说明。
- 前端字段全部来自 Agent 接口，**页面不硬编码任何示例数据作为成功结果**。
- 失败时展示 `stage` + `error.code` + `error.message`，不显示占位数值；任务未完成时不显示任何数值（接口规范第 2.2 节）。

## 七、测试与验收

- 系统测试报告：`reports/test-report/test-report.md`。
- 用例总数 **261，失败 0，结论通过**（生成于 2026-10-20 22:25，Python 3.12.4 / Node v22.17.1）。

| 测试块 | 负责人 | 用例数 | 失败数 | 结果 |
|---|---|---:|---:|---:|
| Hadoop 清洗与评分 | 成员A | 7 | 0 | PASS |
| Agent 接口与调度 | 成员B | 232 | 0 | PASS |
| 前端渲染逻辑（Node） | 成员C | 14 | 0 | PASS |
| 三层结果一致性（Python） | 成员C | 8 | 0 | PASS |

- 降维算法单测：`tests/agent/test_dimensionality_reduction.py`（25 个用例，覆盖 PCA/t-SNE 数学性质、perplexity 约束、种子可复现、kNN 一致率边界、CLI 子进程协议）。该文件属于「Agent 接口与调度」块内的降维子项。
- 三层一致性：`Hadoop 实际结果 → Agent 返回结果 → 前端展示结果`，前端代理出口与 Agent 直连逐字节一致；五维分值/统计量/变化值与 Hadoop 层逐字段一致；任务未完成时不返回数值。

## 八、职责边界说明（重要）

| 模块 | 负责成员 | 说明 |
|---|---|---|
| 分类算法（gnb/cart） | 成员A | 成员C仅负责**前端展示**分类结果，不实现分类算法 |
| 聚类算法（kmeans/dbscan） | 成员B | 成员C负责前端展示 + 降维前后聚类**对照指标**的计算调用 |
| **降维（pca/tsne）** | **成员C** | 本文件核心交付 |
| **前端展示（三类结果区）** | **成员C** | 本文件核心交付 |
| 系统测试与验收组织 | 成员C牵头 | A/B 各自模块问题由 A/B 修复 |

> 说明：截至交付时，`agent/config/analysis.json` 的 `algorithms.classification` 登记位为空，
> 分类工具的 registry 登记与 `analysis_runner` 的 classification 分支属于**成员B的接入工作**
> （见 `docs/迭代二/交付/分类工具交接.md` 第八节），不在成员C范围内。
> 因此前端分类结果区在**接口接通后即可展示**，当前 `GET /health` 的 `registered_tools`
> 只含聚类与降维工具。

## 九、已知局限（必须在界面上可见）

1. **t-SNE 不保留全局结构**：点间距离、簇间距离不能直接当作相似度或簇大小解读；不同运行的簇位置/朝向可旋转翻转。
2. **t-SNE 无统一信息保留指标**：本工具不报告解释方差，只报告 kNN 一致率（相对参考），不构成优于/劣于 PCA 的绝对证据。
3. **t-SNE kNN 一致率接近随机基线**：本数据上局部邻域结构保留很弱，须如实说明，不得宣称 t-SNE 有效保留了结构。
4. **t-SNE 不投影样本外用户**：无复用投影矩阵，强行给坐标为伪造；这类用户坐标为 `null`。
5. **PCA 轴语义需查载荷**：不能用单个原特征名直接命名主成分轴。
6. **低维 SSE 不可跨空间比较**：降维前后 SSE 绝对值无比较意义，以轮廓系数与 DBI 为准。
7. **样本外投影可靠性低**：历史不足/无训练记录用户为样本外投影（`reliability_low=true`），不得据此下群体结论。
8. **二维图仅观察结构**：不能仅凭视觉分离宣称算法更优（数据与实验规范 §五.6）。

## 十、复现命令

```bash
# PCA 全量（4783 用户）
python3 -I agent/tools/dimensionality_reduction/pca_tool.py --request req_pca.json --output out_pca.json

# t-SNE 全量（4783 用户；perplexity=30 需 3*perplexity < 样本数）
python3 -I agent/tools/dimensionality_reduction/tsne_tool.py --request req_tsne.json --output out_tsne.json

# 降维单测（25 个用例）
python3 -m unittest tests.agent.test_dimensionality_reduction

# 全量系统测试
python tests/run_all.py --report reports/test-report/test-report.md
```

## 十一、提交信息建议

- 建议分支：`feature/iter2-dimensionality-frontend`
- 核心改动：
  - 新增 `agent/tools/dimensionality_reduction/`（`dr_common.py`, `pca_tool.py`, `tsne_tool.py`, `run_fit.py`）
  - 修改 `agent/config/analysis.json`（登记 pca/tsne 及 `allowed_parameters`）
  - 修改 `agent/src/router.py`（降维关键词与参数分流校验）
  - 修改 `tests/agent/test_registry_router.py`（降维工具断言）
  - 新增 `tests/agent/test_dimensionality_reduction.py`（25 用例）
- PR 描述须包含：算法名称与 PPT 页码（页码待核对，需如实标注「待核实」）、输入/输出版本、参数、坐标可视化生成路径、降维前后评价对照、前端测试结果、已知局限。
