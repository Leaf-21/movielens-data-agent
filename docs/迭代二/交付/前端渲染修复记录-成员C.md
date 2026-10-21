# 迭代二 · 前端分析结果渲染修复记录（成员C）

## 一、背景：为什么改了

`frontend/public/js/render.js` 的分析渲染部分（`renderClassification` / `renderClustering` 等）
是在后端**任务级信封**尚未定型时写的，字段名按当时的猜测写死；而后端实际交付的字段
（见《成员B_前端联调说明.md》§5、《分类结果样例.json》、`agent/runtime/results/*.json`）与之不一致。

后果是：页面**有结果但读不出来**——大量单元格显示 `—`，代表性作品、群体统计
这类需求明确要求的内容完全缺失。`test_render.mjs` 当时全绿，因为它用构造数据、
字段名按渲染代码的期望写，测不出错配。

## 二、逐项修复

| # | 问题 | 依据（真实字段） | 修复 |
|---|---|---|---|
| 1 | 用户归属表"读者点"列整列 `—` | 真实 `assignments[]` 只有 `status`，没有 `is_noise` | 改按 `status` 判定归属（`SUCCESS` / `ASSIGNED_FROM_FITTED_CENTROIDS` 为已归属），状态中文化 |
| 2 | 历史不足用户混进群体结论 | `INSUFFICIENT_HISTORY` / `NO_TRAIN_HISTORY` / `UNASSIGNED_BY_DENSITY`，`cluster_id=null` | 单列"未归属用户"分区，显示原因原文与"可靠性低"徽标 |
| 3 | 群体摘要整段不显示 | 真实字段是 `avg_rating_mean` / `n_ratings_mean` / `high_share_mean` / `active_span_days_mean` / `top_genre_shares`，代码却在找 `summary` | 改用真实统计字段拼装卡片 |
| 4 | 代表性作品完全缺失 | `representative_movies[{title, year, high_raters_in_cluster}]` | 按群内评分≥4 人数展示，并去掉 title 里重复的年份 |
| 5 | `summary_basis` 口径不可见（联调说明要求必须可见） | `cluster_summaries[].summary_basis` | 每个群体卡片底部展示口径原文 |
| 6 | 分类评价指标显示成 `{"threshold":...}` 原始 JSON | `预测.metrics` 内是多个标量键 | 改成"指标 / 值 / 说明"表格，并附"概率未经校准"提示 |
| 7 | 单条预测的 `limitations` 被丢弃 | `预测.limitations[]` | 每个预测卡片单独展示 |
| 8 | 缺少"数据切分方式"（需求第 6 项） | `split_version` / `feature_version` / 顶层 `T1`、`T2` | 新增切分条：训练/验证/测试三段条件 |
| 9 | 缺少"结果样例 / 报告获取"（需求第 8 项） | 各任务信封已有 `assignments` / `coordinates` / 预测 | 新增"结果样例与导出"与"评价报告与追溯信息"两节 |
| 10 | 降维轴含义只能看图猜 | `axis_meaning.loadings[]` | 新增主成分载荷表（特征 + 载荷 + 解释方差比） |
| 11 | 分类 `results[]` 存在两种信封层级 | 任务级信封内预测在 `results`；算法级信封 `results` 本身就是预测数组 | `normalizeEntries` / `predictionsOf` 双结构兼容，不做字段名猜测 |

## 三、渲染红线（保持）

- 页面任何数值只来自接口；**缺失值显示 `—`，指标 `null` 显示"不适用"**，绝不补 0。
- 不推断用户动机；注明"不同算法的簇号互不相通"。
- 所有文本经 `esc()` 转义（含 SVG `<title>`）。
- 二维图仅用于观察结构，优劣一律以 `clustering_comparison` 指标为准。

## 四、验证

新增 **契约测试** `tests/frontend/test_render_contract.mjs`：用真实任务结果
（`tests/frontend/fixtures/*.json`，从 `agent/runtime/results/` 与
`docs/迭代二/交付/分类结果样例.json` 复制并裁剪体积，字段名未改）驱动渲染，
断言"有结果但显示成 `—`"这类问题不再出现。

```bash
node tests/frontend/test_render.mjs            # 14 项
node tests/frontend/test_render_contract.mjs   # 14 项（真实字段）
python tests/run_all.py --only frontend        # 28 项
python tests/run_all.py                        # 291 项
```

`tests/run_all.py` 的 `run_node_frontend()` 已改为跑上述两个文件。

## 五、已知限制

- `test_render_contract.mjs` 里的分类 fixture 没有 `task_id`（算法级信封本身不带），
  测试里在内存中补一个假 ID 仅用于断言报告区，**不写入 fixture 文件**。
- 分类任务在当前仓库的 `agent/runtime/results/` 里没有真实任务级结果文件，
  故分类契约测试用的是成员A 的样例信封；若后端日后调整分类信封层级，该测试会先失败。
