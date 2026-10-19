# 特征字典 feat-v1（成员A）

> 适用任务：分类（高分预测）。版本号 `feature_version = feat-v1`，与
> `data_version = movielens-1m-v2-clean-v1`、`cleaning_rule_version = rule-v2`、
> `split_version = split-v1` 绑定。特征实现见 `agent/tools/classification/common_features.py`。

## 一、标签与预测时点

- 预测对象：一次评分事件 `(UserID, MovieID, Timestamp)`。
- 标签：`label = 1` 当且仅当该事件 `Rating >= 4`，否则 `0`；标签只用于训练与评价，不进入特征。
- 预测时点：早于目标事件发生。历史统计只使用**严格早于**目标事件时间戳的评分。
- 交互式预测未给出目标时间时，按训练期快照（`Timestamp <= T1`）计算，并在
  `prediction_time_basis` 中标明 `train_snapshot(T1=974862386)`。

## 二、特征清单（45 维）

| 编号 | 特征 | 维度 | 来源 | 类型 | 时间窗口 | 缺失/回退处理 |
|---|---|---:|---|---|---|---|
| F1 | `user_mean` | 1 | ratings | 数值（1–5） | 严格早于目标事件 | 无历史 → 训练期全局均分，标记 `fallback_global_mean` |
| F2 | `movie_mean` | 1 | ratings | 数值（1–5） | 严格早于目标事件 | 无历史 → 训练期全局均分，同上 |
| F3 | `log1p_movie_count` | 1 | ratings | 数值（计数取对数） | 严格早于目标事件 | 无历史 → 0 |
| F4 | `genre_*` | 18 | movies.Genres | 类别（多值） | 静态属性 | 未知类型 → 全 0；取值域来自 `rules.json` |
| F5 | `occupation_*` | 21 + 1 | users.Occupation | 类别（无序） | 静态属性 | 用户无属性 → `occupation_unknown = 1` |
| F6 | `age_ordinal` | 1 | users.Age | 类别（有序） | 静态属性 | 缺失 → -1；顺序固定为 1,18,25,35,45,50,56 |
| — | `has_user_attrs` | 1 | users | 布尔 | 静态属性 | 用户是否在 `users.dat` 中，用于显式标记缺失 |

维度核对：3（数值）+ 18（类型）+ 22（职业含 unknown）+ 1（年龄段）+ 1（属性缺失标志）= **45**。

## 三、编码与拟合范围

| 处理 | 方式 | 拟合范围 |
|---|---|---|
| 电影类型 | multi-hot，18 维 0/1 | 取值域来自规则文件，无学习参数 |
| 职业 | one-hot，21 类 + `unknown` | 取值域来自规则文件（0–20），无学习参数 |
| 年龄段 | ordinal，7 档 + 缺失 -1 | 顺序由 `rules.json` 的 `valid_age` 固定 |
| 数值特征 | 仅 GNB 使用 `StandardScaler` | **只在训练期 fit**（sklearn Pipeline 内） |
| 决策树 | 数值特征保持原始量纲 | 不涉及拟合 |

结论：唯一带学习参数的步骤是 GNB 的标准化，且其 fit 范围被限制在训练期，
不存在"先对全量数据 fit 再切分"的泄漏路径。

## 四、时间安全实现

1. 按 `Timestamp` 稳定排序后，**按秒分组**处理：同一秒的所有事件先统一读取
   "该秒之前"的累计状态（用户评分和/次数、电影评分和/次数），再统一写回累计状态。
2. 因此同一秒内的其它事件不参与该事件的特征——比"按行顺序"更严格。
3. 未来事件（`ts` 更大）在结构上不可能影响已计算特征；`tests/agent/test_classification_features.py`
   用"加入一条更晚的评分后重算，历史特征不变"的用例验证。

## 五、冷启动与缺失属性

| 情形 | 规模（实测） | 处理 | 影响 |
|---|---|---|---|
| 用户训练期无评分 | 1,140 位（18.97%） | F1 回退全局均分，`features_used.user_mean_source` 标记 | 该用户相关样本的可信度下降，需分层评价 |
| 电影训练期无评分 | 73 部（1.97%） | F2 回退全局均分，F3 = 0 | 同上 |
| 用户无属性 | 2,994 条评分 / 15 个 UserID | F5 `unknown` 列、F6 = -1、`has_user_attrs = 0` | 不静默编码为全 0 |

## 六、与作业四的对应

作业四定义 F1–F6 六项特征，本文件与其一一对应：

- F1 用户历史均分 → `user_mean`
- F2 电影历史均分 → `movie_mean`
- F3 电影历史评分次数 → `log1p_movie_count`（取对数抑制长尾，理由：每电影评分次数最小 1、中位 123、最大 3,407）
- F4 电影类型 → `genre_*`（18 维）
- F5 职业 → `occupation_*`（21+1 维）
- F6 年龄段 → `age_ordinal`

相较作业四增加了 `has_user_attrs` 一维，用于显式表达"用户属性缺失"，
避免 `handle_unknown="ignore"` 把缺失与"未知类别"混为一谈。

## 七、复现

```bash
python3 agent/tools/classification/train.py --algorithm both
# 训练矩阵维度、缺失计数等元数据写入 artifacts/classification/<algo>/<model_version>/meta.json
```
