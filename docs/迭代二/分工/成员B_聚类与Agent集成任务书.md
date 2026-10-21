# 成员B任务书：用户聚类与 Agent 集成

## 一、职责目标

负责用户历史偏好画像和聚类的两种算法工具，并维护 Agent 的工具注册、自然语言请求路由、任务状态及结果统一封装。Agent 只能返回工具的实际结果；输入数据缺失、算法未完成或结果不可用时，必须明确返回状态。

## 二、工作范围

### 1. 用户画像输入

- 使用迭代一清洗数据及本轮统一的数据版本、`T1/T2`。
- 用户画像和聚类拟合只能使用训练期数据构造，不能把验证期/测试期行为泄漏到训练画像中。
- 画像应围绕历史观影偏好构建，记录画像字段的定义、统计时间范围、缺失处理方法和画像版本。
- 用户偏好可依据已登记的特征工程方案表示；具体字段和数值变换须写入特征字典，不将用户 ID 当作偏好值。
- 对历史不足的用户，应根据项目定义标记为 `INSUFFICIENT_HISTORY` 或使用可解释的最小历史规则，不应强行返回可信群体结论。

### 2. 聚类算法

从课程 PPT 中选择两种聚类算法，并分别封装为 Agent 可独立调用工具。具体算法名称须在核对课程 PPT 后登记。

每种算法应输出：
- 算法名称、版本、参数；
- 聚类结果版本和输入画像版本；
- 每个目标用户的群体归属；若算法支持噪声点识别，提供噪声标记；
- 群体规模及群体摘要；
- 能够支撑摘要的代表性偏好/内容；
- 实际计算的聚类评价指标和其适用说明；
- 无法聚类、参数无效、输入不足等异常状态。

群体解释应以真实群体统计和代表性内容为依据，不得凭模型名生成未经验证的用户画像描述。

### 3. Agent 工具注册和路由

建议工具逻辑目录：`agent/tools/clustering/`；Agent 调度主代码放在 `agent/src/`，配置放在 `agent/config/`。

Agent 应支持：
- 用户用自然语言发起分类、聚类或降维请求；
- 用户指定某一种已实现算法和参数；
- 未指定算法时，依照需求调用该任务的两种算法并提供对照；
- 将 `user_id`、`user_ids`、算法参数、数据版本等传递给对应工具；
- 对工具结果做字段校验和统一封装，不篡改原始指标；
- 用统一任务 ID 和状态让前端查询执行情况；
- 通过结果中的依据、限制和实际指标回答后续追问；无法从已有证据得出的结论要明确说明。

### 4. 统一状态和错误处理

至少统一以下状态：`PENDING`、`RUNNING`、`SUCCESS`、`FAILED`。出现数据不可用时可以通过 `error.code = DATA_UNAVAILABLE` 等可枚举错误码表达；具体协议见《迭代二接口扩展规范.md》。

不得在后台任务失败后返回 `SUCCESS`，也不得用假分数、空的成功结果或示例结果伪装成真实结果。

### 5. 接口兼容

迭代一已有任务接口如已在代码中实现，应优先复用任务状态查询等公共机制；迭代二新增的分析接口按《迭代二接口扩展规范.md》扩展。接口字段如需变更，先开 Issue、修改规范并与 A/C 同步，再合并代码。

## 三、建议工具结构

```text
agent/
├── src/
│   ├── router.py                 # 自然语言任务路由（按实际语言/框架调整）
│   ├── task_manager.py           # 任务状态、任务 ID、错误处理
│   └── result_service.py         # 结果封装和查询
├── tools/
│   ├── clustering/
│   │   ├── algorithm_one.py
│   │   ├── algorithm_two.py
│   │   ├── build_profile.py
│   │   └── schemas.py
│   ├── classification/           # 成员A负责实现，B负责接入
│   └── dimensionality_reduction/ # 成员C负责实现，B负责接入
└── config/
```

此结构为建议的内部组织方式，若仓库现有代码已有对应模块，可沿用已有结构，但需保持职责和协议一致。

## 四、交付清单

- [x] 两种聚类算法工具独立运行并记录参数/版本（`agent/tools/clustering/`；mdl/res 版本见 §六与 `versions.json`；测试 `test_kmeans_tool.py`/`test_dbscan_tool.py`）
- [x] 可复现的用户画像构建流程（`build_profile.py` + `run_fit.py`；profile-v1 sha256 登记，HEAD 3c7c210 复跑字节不变，见提交 072e654）
- [x] 用户群体归属、群体摘要和代表性内容（信封 `assignments`/`cluster_summaries`，`summary_basis` 口径原文；报告 §1/§2）
- [x] 聚类评价指标及适用限制（`metrics.definition` 逐指标；不适用如实 null；噪声/eps 敏感性见报告 §3）
- [x] 六种算法工具注册表/调用映射——B 侧统一注册机制已完成并有测试（`registry.py`+`analysis.json`，未登记类别诚实回 `MODEL_NOT_FOUND`）；**六工具已全部登记激活**：聚类 `clustering_kmeans`/`clustering_dbscan`（B）、分类 `classification_gnb`/`classification_cart`（A，`fa51d76` 接通）、降维 `dimensionality_reduction_pca`/`dimensionality_reduction_tsne`（C，`e2e59e2`）。`GET /health` 的 `analysis.registered_tools` 实测返回六项；三类任务端到端实测 分类 task_20261021_0013 / 聚类 _0012 / 降维 _0014 均 SUCCESS（Agent 调用链）。**注**:六工具 CLI 独立调用时,聚类两工具纯标准库可直接跑;分类/降维四工具需指定带 numpy 的解释器（裸 `python3 -I` 会因用户级 site-packages 不在路径而报 `ModuleNotFoundError`,详见验收清单 I-01）
- [x] 三类自然语言请求的路由规则（`router.py`；聚类/分类/降维识别、误类别引导、指定/默认双算法；`test_registry_router.py` 19 用例）
- [x] 统一任务 ID、状态、结果查询和错误封装（复用迭代一 `GET /api/tasks/{id}`；§2.1 错误码；拒绝路径零僵尸任务实测）
- [x] 未指定算法时双算法对照；指定算法时仅调用对应算法（实测 task_20261018_0003 双对照 / _0013、_0014 指定单算法）
- [x] 数据不可用、用户不存在、历史不足、模型未生成等异常行为（`test_analysis_api.py` E2E + 联调会话实测：UNKNOWN_USER/INVALID_PARAMETER/VERSION_MISMATCH/MODEL_NOT_FOUND；NO_TRAIN/INSUFFICIENT 状态见真实任务）
- [x] 与前端联调说明和可复现调用示例（**`docs/迭代二/交付文档/成员B_前端联调说明.md`**；复现命令见实验记录 §6 与联调说明 §8）

## 五、提交与协作

建议分支：`feature/iter2-clustering-agent`。聚类工具测试放在 `tests/agent/`；Agent 任务、路由和结果协议也需补充测试。

PR 描述至少包含：算法名和 PPT 页码、画像版本、聚类参数、评价指标、工具调用样例、状态/错误处理测试结果。与 A/C 的接口不一致时先通过 Issue 明确，不要以临时字段绕过公共规范。

## 六、算法选择记录

| 项目 | 记录 |
|---|---|
| 聚类算法一 | K-Means（kmeans++ 初始化 + Lloyd 迭代，固定种子 42 保证可复现；工具 `clustering_kmeans`）。课程 PPT 章节/页码：待团队核对后登记（不凭惯例声称） |
| 聚类算法二 | DBSCAN（密度聚类，支持噪声标记；eps 默认取第 15 近邻 k-距离 P90；工具 `clustering_dbscan`）。课程 PPT 章节/页码：待团队核对后登记 |
| 画像特征版本 | `profile-v1`：训练期（Timestamp≤T1=2000-11-22）27 维=9 行为统计+18 类型占比，z-score 仅用 OK 用户拟合；OK 4783 / 历史不足 74 / 无训练记录 1168；孤儿引用 13 人如实登记；工件 `agent/artifacts/profiles/profile-v1.jsonl`（sha256 `b5665c17…`，全文见 `agent/config/versions.json`） |
| 群体解释方法 | 群成员真实统计（人数、平均评分、高分占比、活跃跨度、类型占比 Top3）+ 代表性内容=群成员训练期 Rating≥4 计数前列电影（≥3 人群内高分、取前 5）；口径写入 `cluster_summaries[*].summary_basis`，无凭模型名生成的描述 |
| 最终聚类结果版本 | 全量真实运行（`python3 -I agent/tools/clustering/run_fit.py`）：`clustering_kmeans` 模型 `mdl-a18e5c6560` / 结果 `res-4492caf82d7e`（k=6，全量轮廓系数 0.1199，DBI 1.935，SSE 94764.7）；`clustering_dbscan` 模型 `mdl-168b6fb696` / 结果 `res-da0406825eda`（eps=4.3278，1 密度巨簇+223 噪声，轮廓/DBI 如实 null）。实验记录：`reports/analysis/clustering-profile-v1-2026-10-18.md`；工件：`agent/artifacts/clustering/` |
