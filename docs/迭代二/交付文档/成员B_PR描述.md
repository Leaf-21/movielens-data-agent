# PR 描述草稿(成员B → main)

**标题**:`feat: 迭代二 用户画像+聚类工具(K-Means/DBSCAN)与 Agent 统一调度(成员B)`

**源分支**:`feature/iter2-clustering-agent`(14 提交,基于 `b920f1d`,与 main 零冲突)
**创建入口**:https://github.com/Leaf-21/movielens-data-agent/pull/new/feature/iter2-clustering-agent

---

## 正文(可直接粘贴)

### 本次修改内容与对应 Issue

GitHub Issues 尚未创建(仓库无 gh CLI 权限,按《GitHub协作与提交计划》§四建议清单,对应本 PR 的 Issue 为:`[Iteration 2][Clustering] 定义训练期用户画像 / 实现聚类算法一 / 实现聚类算法二`、`[Iteration 2][Agent] 注册六种分析工具并路由请求 / 统一任务状态、错误及结果接口`——合并前由有网页权限的成员补建并关联)。

提交主线(14 个):配置与画像 → 指标库/schemas → K-Means 工具 → DBSCAN 工具 → 注册表/路由 → 执行器(子进程隔离)→ 三类创建接口与 /ask 追问 → 全量真实运行工件与实验记录 → 测试(71 新用例)→ 文档登记 → .gitattributes 跨平台哈希保护 → 复现登记 → 联调说明与验收证据。

### 影响的任务类型/目录

聚类任务全链路;不影响迭代一接口行为。目录:`agent/src/`(router、analysis_runner、explainer、registry、config、models、api 三接口挂载)、`agent/tools/{common,clustering}/`(新)、`agent/config/`(analysis.json、versions.json)、`agent/artifacts/{profiles,clustering}/`(新)、`reports/analysis/`(新)、`tests/agent/`(9 个新文件)、`docs/迭代二/`。

### 所选算法与课程 PPT 页码(如实登记)

| 算法 | 工具 | PPT 出处 |
|---|---|---|
| K-Means(kmeans++ 初始化 + Lloyd,seed 42) | `clustering_kmeans` | **章节/页码待团队核对后登记(不凭惯例声称)** |
| DBSCAN(密度聚类,支持噪声;eps 默认第15近邻 k-距离 P90,seed 42) | `clustering_dbscan` | **同上** |

《分工文档》§七确认状态:"算法实现与运行已完成;PPT 出处核对未完成"。合并前请勿声称满足"来自课程 PPT"。

### 数据、特征/画像与模型版本

- 数据快照 `movielens-1m-v2-clean-v1`(迭代一清洗产出)+ 清洗规则 `rule-v2`;T1=2000-11-22(974862386)/T2=2000-12-10(976422054),特征仅用 `Timestamp≤T1`。
- 画像 `profile-v1`:27 维(9 行为统计+18 类型占比),z-score 仅 OK 用户拟合;OK 4783/历史不足 74/无训练记录 1168,孤儿引用 13 人如实登记;工件 sha256 `b5665c17…` 登记于 `agent/config/versions.json`。
- 模型/结果:K-Means `mdl-a18e5c6560`/`res-4492caf82d7e`;DBSCAN `mdl-168b6fb696`/`res-da0406825eda`。**HEAD 3c7c210 全量复跑:归属与指标零变化、jsonl 字节不变**(提交 `072e654`),复现成立。

### 聚类参数与评价指标(实际计算值)

- K-Means:候选 k=[2..8] 抽样轮廓系数选优 → **k=6**;全量轮廓 **0.11986815**、DBI **1.9345**、SSE **94764.7**;全量轮廓偏低已如实入 limitations(高维 z-score 空间可分性有限,群体主视角为画像占比)。
- DBSCAN:eps=**4.3278**(k-距离 P90)、min_samples=15 → **1 密度巨簇(4560)+223 噪声(4.7%)**,单簇下轮廓/DBI **null(不适用,不补值)**;eps 敏感性探针 P50→1282 噪声(26.8%)、P75→552(11.5%),链接(chaining)效应披露于报告与追问模板。

### 工具调用样例

```bash
curl -X POST localhost:8090/api/analysis/clustering/tasks \
  -H 'Content-Type: application/json' \
  -d '{"user_ids":[1000,6040],"algorithm":"kmeans"}'      # 不传 algorithm=双算法对照
curl localhost:8090/api/tasks/<task_id>                    # 轮询到 SUCCESS/FAILED
curl localhost:8090/api/tasks/<task_id>/result
curl -X POST localhost:8090/api/tasks/<task_id>/ask \
  -H 'Content-Type: application/json' -d '{"question":"群体2有什么特征"}'
```
实测任务:`task_20261018_0003`(双对照)、`0013`/`0014`(指定单算法+追问)。分类/降维接口已挂载,返回 `MODEL_NOT_FOUND` 直至 A/C 工具登记(登记 `analysis.json` 即自动激活,B 侧无需改码)。

### 运行过的测试命令及实际结果

```bash
python3 tests/run_all.py        # 180 用例,失败 0(Agent 161 / 前端渲染 11 / 一致性 8 / Hadoop 0*)
python3 -m unittest discover -s tests/agent -t tests/agent   # 161 全绿
```
*Hadoop 0 用例为迭代一存量现状,本 PR 未改动 hadoop 测试。状态/错误处理重点覆盖:子进程协议五态(成功/语义失败不重试/崩溃重试/超时/违约拒收)、FAILED 保留真实部分结果、四类拒绝路径零僵尸任务、追问无证据不编造——见 `tests/agent/test_analysis_runner.py`、`test_analysis_api.py`。

### 生成的报告/产物路径

- 实验记录:`reports/analysis/clustering-profile-v1-2026-10-18.md`
- 工件:`agent/artifacts/profiles/profile-v1.{jsonl,meta.json}`、`agent/artifacts/clustering/clusters-{kmeans,dbscan}-v1.{json,meta.json}`
- 版本登记:`agent/config/versions.json`(profile_versions / analysis_result_versions,sha256 可核验)
- 交接文档:`docs/迭代二/交付文档/成员B_前端联调说明.md`(给成员C 阶段4)

### 接口是否变更

新增《迭代二接口扩展规范》§三登记的三类 `POST /api/analysis/*/tasks`;**迭代一接口字段与行为零变更**,状态/结果/追问复用 `GET /api/tasks/{id}`、`/result`、`/ask`。`.gitattributes` 对 `*.jsonl`/`agent/artifacts/**` 禁换行转换(保护登记哈希,Windows 检出不受影响)。

### 已知限制 / 未解决

1. PPT 页码待团队核对(CL-01,勾选与分工文档 §七 一致);
2. K-Means 全量轮廓系数低(0.12),DBSCAN 在 27 维 z-score 下呈巨簇——均如实登记,eps 探针供解读;
3. 六工具中四件(分类×2/降维×2)依赖 A/C 交付;`GET /health` 当前仅两聚类工具在注册表;
4. 本 WSL 环境存在非确定性解释器 segfault,已用子进程隔离+自动重试 1 次兜底(报告 §4 披露);
5. GitHub Issues 未创建、README 迭代二段落未更新(发布前检查项,留待合并流程)。

### 审核请求

按协作计划 §六:请至少一名成员审核;涉及公共接口(router/envelope),建议 A、C 各确认§五字段与其模块无冲突。
