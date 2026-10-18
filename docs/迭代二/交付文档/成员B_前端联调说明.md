# 成员B → 前端(成员C)联调说明:迭代二分析任务

读者:成员C(或接手前端的同学)。用途:把聚类任务(以及后续分类/降维任务)从后端字段映射到页面渲染。
对应版本:分析口径 `iter2-analysis-v1`;画像 `profile-v1`;已注册工具 `clustering_dbscan`(mdl-168b6fb696)/ `clustering_kmeans`(mdl-a18e5c6560);接口协议见《迭代二接口扩展规范.md》。

## 0. 服务拓扑与启动

| 层 | 端口 | 聚类任务是否需要 |
|---|---|---|
| hadoop 数据服务 `hadoop/src/server.py` | 8080 | **不需要**。聚类画像工具直接读本地快照 `hadoop/output/clean/` |
| Agent API `agent/src/api.py` | 8090 | 需要(唯一联调对象) |
| 前端 `frontend/src/serve.py --port 8000 --agent-url http://127.0.0.1:8090` | 8000 | 展示层 |

注意:迭代一的**质量检查任务**才依赖 8080,且启动 8080 的 shell 必须有 `JAVA_HOME`/`HADOOP_HOME`(已写入 `~/.bashrc`;缺失时报 `HADOOP_EXECUTION_ERROR: 找不到 Hadoop Streaming JAR`)。

## 1. 接口清单

| 方法/路径 | 语义 |
|---|---|
| `POST /api/analysis/clustering/tasks` | 创建聚类任务(异步,立即返回 task_id) |
| `POST /api/analysis/classification/tasks` | 已挂载;成员A工具登记前返回 `MODEL_NOT_FOUND`,`task_id=null` |
| `POST /api/analysis/dimensionality-reduction/tasks` | 同上,登记后自动激活 |
| `GET /api/tasks/{task_id}` | **复用迭代一公共状态接口**(注意不是 /api/analysis/...) |
| `GET /api/tasks/{task_id}/result` | 任务结果(结构见 §4/§5) |
| `POST /api/tasks/{task_id}/ask` | 追问,体 `{"question":"..."}`(见 §6) |
| `GET /api/tasks` | 任务列表(含 task_id/status,可用于调试面板) |
| `GET /health` | 含 `analysis` 块:当前 analysis_version、profile_version、已注册工具 |

业务失败一律 **HTTP 200 + `{status:"FAILED", error:{code,message,stage,detail}}`**,前端按 JSON 统一解析,不要按状态码分支。

## 2. 创建任务:请求字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `user_id` 或 `user_ids` | 是* | 整数列表;也可只在 `query` 里写"用户 1000"(路由会抽取并以显式字段优先) |
| `query` | 否 | 自然语言,≤2000 字符 |
| `algorithm` | 否 | `"kmeans"`/`"K-Means"`/`"dbscan"`(别名兼容);**不传=双算法对照**,执行顺序固定为登记顺序 `["dbscan","kmeans"]` |
| `parameters` | 否 | 白名单:kmeans `{k:2..30, max_iter, seed}`;dbscan `{eps>0, min_samples≥2}`。双算法时按算法过滤无关键并在 notes 提示;单算法时出现外算法参数直接 `INVALID_PARAMETER`(不静默丢弃) |
| `data_version` | 否 | 默认登记值 `movielens-1m-v2-clean-v1`,不符→`VERSION_MISMATCH` |
| `profile_version` | 否 | 默认 `profile-v1`,不符→`VERSION_MISMATCH` |

*缺用户时后端**不会代选用户**,返回 `INVALID_REQUEST`(合规行为,勿在页面填默认 ID 掩盖)。

## 3. 状态机与轮询

```
PENDING → RUNNING(stage: PARSE_REQUEST → PROFILE_BUILD → CLUSTER_FIT → GENERATE_REPORT) → SUCCESS(COMPLETED)
                                                                                          ↘ FAILED(error)
```
- 建议 1~3 秒轮询;实测小目标集(≤10 用户)约 20~40 秒,含画像缓存复用。
- `FAILED` 时 `result` 可能仍存在**部分结果**(`status=FAILED` + `_note` 说明哪个环节失败):页面必须**同时**显示失败原因和已完成算法的真实结果,不得只显示失败或只显示成功。
- 执行日志 `execution.log` 会记录"第N次尝试":WSL 环境有已知非确定性解释器崩溃,自动重试 1 次属正常兜底,`attempt=2` 不是缺陷,可原样展示。

## 4. 任务级结果字段(result 顶层)

| 字段 | 渲染建议 |
|---|---|
| `task_type` / `analysis_version` / `data_version` / `profile_version` | 版本条 |
| `T1` / `T2` / `T1_epoch` / `T2_epoch` | "画像仅使用 ≤T1 训练期记录" 提示 |
| `requested_user_ids` | 本次覆盖用户 |
| `results[]` | **逐算法渲染,见 §5;顺序与 algorithms 一致** |
| `result_versions` | `{clustering_dbscan: res-…, clustering_kmeans: res-…}` |
| `understanding` | 路由解释(含"未指定算法,做对照"等),放任务详情 |
| `execution` | 模式 subprocess_isolated、耗时、log,可折叠 |
| `code_version` | 追溯用,页脚 |

## 5. 算法信封字段(results[] 每一项)

必需键(后端已校验,前端可信赖):`algorithm`、`algorithm_tool`、`model_version`、`result_version`、`parameters`(生效值,含默认回填)、`data_version`、`profile_version`、`T1`、`T2`、`code_version`、`created_at`、`metrics`、`assignments`、`cluster_summaries`、`limitations`。另有:`feature_names`(27维)、`fit_scope`、`centroids`(仅 kmeans)、`elapsed_ms`。

### assignments[].status 枚举与显示

| status | cluster_id | 显示规则 |
|---|---|---|
| `SUCCESS` | 有 | 正常渲染 |
| `ASSIGNED_FROM_FITTED_CENTROIDS` | 有 | 样本外投影(仅 kmeans),加"基于拟合质心"轻标签 |
| `INSUFFICIENT_HISTORY` | null | 历史不足提示,**不得**画进任何簇;`reliability_low=true` 时加徽标 |
| `NO_TRAIN_HISTORY` | null | 训练期无记录说明(如实,非错误) |
| `UNASSIGNED_BY_DENSITY` | null | DBSCAN 噪声点:单独图例,不计入群体统计 |

### metrics 渲染红线

- 每个指标带 `definition`(定义与适用条件),建议悬浮/折叠展示。
- **null = 不适用/未测量**(如单簇轮廓系数),显示"不适用",绝不能补 0 或占位值。
- kmeans:`k_selection_table`(候选 k 与抽样轮廓系数)、`silhouette_full`/`davies_bouldin_full`/`sse_full`;dbscan:`eps_used`/`eps_method`(kdistance_p90 或 user_provided)/`noise_ratio`/`cluster_sizes`;eps 敏感性探针在工件 meta 与报告 §3.1。

### cluster_summaries[]

`cluster_id, size, avg_rating, high_ratio, active_span_days_mean, genre_top(前3), representative_movies[{title, movie_id, high_raters}], summary_basis`。
- `summary_basis` 是口径原文("真实统计;代表作品=群内训练期 Rating≥4 计数,≥3人,取前5"),结果页必须可见。
- **不同算法的簇号互不相通**(数据规范 §四.6):禁止把 dbscan 的簇0与 kmeans 的簇0并排对齐或按编号比大小;两算法结果分栏/分页签。

### limitations

字符串数组,如实转达(含"全量轮廓系数低""chaining 对 eps 敏感"等),不要润色成"效果良好"。

## 6. 追问(/ask)

- 仅终态(SUCCESS/FAILED)任务可答;回答只基于该任务已计算结果。
- 请求 `{"question": "自然语言"}`;响应 `{answer, source}`;`source` 为 `template` / `template+llm`,答案区标注来源。
- 建议示例问法:归属("用户1000属于哪个群体")、群体("群体2有什么特征")、指标("评价指标和k选择依据")、参数、局限、版本。注意关键词需命中模板(如"k选择依据"而非"怎么选的",后者走摘要兜底)。
- 结果里没有的用户/簇号会得到明确"无记录/不存在"回答,这是合规行为。

## 7. 错误码 → 页面文案建议

| code | 建议文案 |
|---|---|
| INVALID_REQUEST | 提示补 user_ids 或改写 query |
| INVALID_PARAMETER | 展示 details 里的允许范围 |
| VERSION_MISMATCH | 展示期望版本,禁止强跑 |
| UNKNOWN_USER | 列出未知 ID,保留其余用户结果 |
| MODEL_NOT_FOUND | "该任务类型算法尚未登记(A/C 模块)",非"系统坏了" |
| DATA_UNAVAILABLE | 指引重跑迭代一清洗 |
| ALGORITHM_ERROR | 展示 stage 与重试信息 |
| INTERNAL_ERROR | 保留 task_id 供排查 |

## 8. 可复现调用样例(实测通过)

```bash
curl -X POST localhost:8090/api/analysis/clustering/tasks -H 'Content-Type: application/json' -d '{"user_ids":[1000,6040],"algorithm":"kmeans"}'
curl localhost:8090/api/tasks/task_20261018_0013
curl localhost:8090/api/tasks/task_20261018_0013/result
curl -X POST localhost:8090/api/tasks/task_20261018_0013/ask -H 'Content-Type: application/json' -d '{"question":"群体2有什么特征"}'
```
实测记录:`task_20261018_0003`(双算法)、`0013`/`0014`(单算法+追问)。

## 9. A/C 工具接入时前端需要改什么

**几乎不用改**:算法登记进 `agent/config/analysis.json` 后注册表/路由/执行器/接口自动激活,URL 与状态机不变;只需按各自信封新增渲染器(分类预测字段、降维坐标/轴含义/信息保留指标,均已在接口扩展规范 §4.3/§4.4 预留)。降维前后聚类对照(DR-05)使用相同用户集合时,聚类侧参数与指标可直接引用本文 §5 与工件。

## 10. 版本与证据索引

- 工件与哈希:`agent/config/versions.json`(profile_versions / analysis_result_versions);工件在 `agent/artifacts/{profiles,clustering}/`。
- 实验记录:`reports/analysis/clustering-profile-v1-2026-10-18.md`(含复现命令与执行环境如实登记)。
- 测试:`tests/agent/test_analysis_api.py`(接口E2E)、`test_registry_router.py`(路由)、`test_analysis_runner.py`(状态/错误/部分结果)、两工具与画像/指标测试,合计 agent 套件 161 用例。
- 提交:`3c7c210`(功能全量)/ `072e654`(HEAD 上复现登记)。
