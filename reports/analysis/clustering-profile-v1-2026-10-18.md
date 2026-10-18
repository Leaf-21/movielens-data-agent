# 迭代二聚类真实运行记录（clustering / profile-v1 / 2026-10-18）

- 生成时间（UTC）：2026-10-18T11:37:16Z；代码 commit：3c7c210
- 分析口径：iter2-analysis-v1；数据版本：movielens-1m-v2-clean-v1；画像版本：profile-v1
- 时间边界：T1=2000-11-22（epoch 974862386）/ T2=2000-12-10（epoch 976422054）；画像特征只使用 Timestamp<=T1 的训练期记录。
- 运行方式：`python3 -I agent/tools/clustering/run_fit.py`（本报告全部数字来自本次真实运行，非示例/非估算）。

## 1. 画像 profile-v1

| 项目 | 值 |
|---|---|
| users.dat 用户数 | 6025 |
| 拟合用户（OK） | 4783 |
| 历史不足（INSUFFICIENT） | 74 |
| 无训练记录（NO_TRAIN） | 1168 |
| 训练期评分用户数（users.dat 内） | 4857 |
| 孤儿引用（评分但不在 users.dat） | 13：[1259, 1434, 2106, 2853, 3355, 3905, 4454, 4538, 4913, 4973, 5100, 5510, 5904] |
| 特征维度 | 27 |
| 训练期全局均分 | 3.6019 |
| 构建耗时 | 1.4 s |
| 画像文件 | agent/artifacts/profiles/profile-v1.jsonl（6025 行） |
| 画像 sha256 | `b5665c179a831ab968201e4ff7c2044d9b86e155368486b685479386a8b72b6d` |

## 2. K-Means（clustering_kmeans）

- 模型版本 `mdl-a18e5c6560` / 结果版本 `res-4492caf82d7e`，生效参数：`{"k_candidates": [2, 3, 4, 5, 6, 7, 8], "seed": 42, "max_iter": 100, "tol": 1e-06, "init": "kmeans++", "silhouette_sample_size": 800, "timeout_s": 600}`
- 候选 k 选择（确定性 800 抽样轮廓估计，平手取小 k）：

| k | silhouette(抽样) | SSE | DBI | 迭代数 | 收敛 | 空簇修复 |
|---|---|---|---|---|---|---|
| 2 | 0.1001 | 117070.716 | 2.812 | 24 | True | 0 |
| 3 | 0.1062 | 107503.6759 | 2.398 | 26 | True | 0 |
| 4 | 0.1095 | 100953.7567 | 2.11 | 19 | True | 0 |
| 5 | 0.1127 | 96417.328 | 2.01 | 19 | True | 0 |
| 6 | 0.1185 | 94764.7476 | 1.935 | 23 | True | 0 |
| 7 | 0.0912 | 92269.505 | 1.936 | 32 | True | 0 |
| 8 | 0.092 | 88406.1488 | 2.044 | 34 | True | 0 |

- 选定 **k=6**；全量轮廓系数 **0.1199**，DBI **1.935**，SSE **94764.7**；拟合 4783 人，耗时 18713 ms。
- 本次目标用户 6025 人全部有归属（含按最近质心参考分配的历史不足/无训练记录用户，其 reliability_low 标注见工件）。
- 群体摘要（真实统计）：

| 簇 | 人数 | 均分 | 高分占比 | 类型Top3 | 代表作品（群内高分人数） |
|---|---|---|---|---|---|
| 0 | 977 | 3.761 | 0.642 | action 0.517、sci-fi 0.369、adventure 0.273 | Star Wars: Episode IV - A New Hope (1977)(682)；Star Wars: Episode V - The Empire Strikes Back (1980)(606)；Matrix, The (1999)(592) |
| 1 | 235 | 3.89 | 0.691 | thriller 0.394、drama 0.389、action 0.231 | L.A. Confidential (1997)(156)；Chinatown (1974)(104)；Usual Suspects, The (1995)(98) |
| 2 | 307 | 3.753 | 0.644 | drama 0.394、comedy 0.367、action 0.224 | American Beauty (1999)(193)；Star Wars: Episode IV - A New Hope (1977)(172)；Fargo (1996)(169) |
| 3 | 1780 | 3.982 | 0.733 | drama 0.458、comedy 0.379、action 0.177 | American Beauty (1999)(920)；Silence of the Lambs, The (1991)(720)；Schindler's List (1993)(708) |
| 4 | 103 | 3.461 | 0.533 | horror 0.612、sci-fi 0.237、thriller 0.235 | Shining, The (1980)(57)；Jaws (1975)(56)；Exorcist, The (1973)(55) |
| 5 | 1381 | 3.302 | 0.465 | comedy 0.416、drama 0.339、action 0.218 | American Beauty (1999)(673)；Sixth Sense, The (1999)(482)；Star Wars: Episode IV - A New Hope (1977)(469) |

## 3. DBSCAN（clustering_dbscan）

- 模型版本 `mdl-168b6fb696` / 结果版本 `res-da0406825eda`，生效参数：`{"min_samples": 15, "eps_method": "kdistance_p90", "eps_sample_size": 800, "seed": 42, "timeout_s": 900}`
- eps 选定口径：kdistance_p90（第15近邻距离的P90，不含自身）；k-距离分位（第 15 近邻、seed 42 抽样 800 人）：

| 分位 | k-距离 |
|---|---|
| min | 1.7304 |
| p50 | 2.86 |
| p75 | 3.4829 |
| p90 | 4.3278 |
| p95 | 5.2834 |
| max | 11.8554 |

- 默认 eps=**4.3278**（k-距离 P90）下：簇数 **1**、噪声 **223**（占比 0.047）、轮廓系数 null；耗时 18450 ms。
- 如实结论：当前画像特征 + 默认参数下 DBSCAN 只形成 1 个密度巨簇（chaining 效应），群体划分主视角应以 K-Means 为准；DBSCAN 的价值在噪声侧写（223 个孤立用户未强塞进群）。

### 3.1 eps 敏感性探针（同一 min_samples=15）

| 探针 | eps | 簇数 | 噪声 | 噪声占比 | 轮廓系数 |
|---|---|---|---|---|---|
| 默认 P90 | 4.3278 | 1 | 223 | 0.047 | null |
| P50 | 2.86 | 1 | 1282 | 0.268 | null |
| P75 | 3.4829 | 1 | 552 | 0.115 | null |

探针仅用于团队调参讨论，不改变登记默认值（P90 为登记口径，变更需走配置评审）。

## 4. 执行环境如实登记

- 本机 WSL2（内核 6.18.33.2-microsoft-standard-WSL2）+ Python 3.10.12 存在**非确定性解释器级崩溃**：同一命令先 segfault 后连续多次字节级一致成功（dmesg 有 CaptureCrash signal 11 记录），与数据/算法无关。
- 因此 API 侧聚类任务一律**子进程隔离 + 自动重试 1 次**（agent/src/analysis_runner.py），本次编排运行 未观察到崩溃（若观察到会自动重试并在此登记）。
- 本记录中的两次单算法线上任务复跑结果与此处工件的簇结构一致（确定性种子 42）。

## 5. 工件清单

- `agent/artifacts/clustering/clusters-kmeans-v1.json`（sha256 `78bc35f533bcfc0d1d8e2266d8fdca175084a4976ee5655de721e5d7282b52b1`）— 统一结果信封（全量 6025 用户归属 + 群体摘要）
- `agent/artifacts/clustering/clusters-kmeans-v1.meta.json`（sha256 `c3422014cd1be236bed1249eb26264dea31987b2238e6edc27148d91dcfd22aa`）— 工件登记（版本/哈希/指标摘要）
- `agent/artifacts/clustering/clusters-dbscan-v1.json`（sha256 `58a48aaf7958e7caf70f8235935b8860fb79f92b6dd3d6f0f67561e5c1255938`）— 统一结果信封（全量 6025 用户归属 + 群体摘要）
- `agent/artifacts/clustering/clusters-dbscan-v1.meta.json`（sha256 `f973df53651e2e63578d771ad3cb199969b9454b54a199c523ce9e574d12aa14`）— 工件登记（版本/哈希/指标摘要）

## 6. 复现命令

```bash
python3 -I agent/tools/clustering/build_profile.py   # 画像
python3 -I agent/tools/clustering/run_fit.py          # 本记录
curl -s localhost:8090/api/analysis/clustering/tasks -d '{"query":"把用户 1000 和 2000 聚类","user_ids":[1000,2000]}'  # 服务侧同口径
```
