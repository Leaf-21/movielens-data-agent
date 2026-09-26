# 数据版本登记表（DATASETS）

> 依据《迭代一_Hadoop数据清洗与Agent基础》第 13 行："后续迭代不得混用不同数据版本或时间范围的产物"。
> 本文件是**唯一的数据版本登记处**，版本号在 `hadoop/config/rules.json` 与 `docs/接口规范文档.md` 中引用。
> `.dat` 原始数据不进仓库（`.gitignore` 已排除），因此这里记录**路径 + 行数 + SHA256** 以便核对与复现。

## 版本一览

| 版本号 | 状态 | 来源 | 说明 |
| --- | --- | --- | --- |
| `movielens-1m-v1` | **已停用** | GroupLens 官方 `ml-1m.zip` | 官方未改动版本。迭代一曾误用此版本，导致"15 项检查 13 项零违规"的结论不成立（清洗实验失去意义） |
| `movielens-1m-v2` | **当前使用** | 课程给定：`C:\Users\HP\OneDrive\Desktop\LLM\ml-1m` | 在官方数据基础上**注入了数据质量问题**（分隔符被替换、多余/缺失字段、非法取值、重复与冲突、毫秒时间戳、域外 ID 等）。清洗与五维评估均以本版本为输入 |
| `movielens-1m-v2-clean-v1` | 当前使用 | 本项目 Hadoop 清洗产物 | v2 的清洗后数据，对应规则版本 `rule-v2` |

## 文件清单与校验和

数据在工作机上的实际位置：WSL `Ubuntu-22.04` 的 `~/data/` 目录（`hadoop/scripts/*.sh` 默认从 `ML_DATA_DIR` 读取）。

### movielens-1m-v2（当前使用）

| 文件 | 行数 | 字节 | SHA256 |
| --- | --- | --- | --- |
| `ratings.dat` | 1,150,241 | 28,060,211 | `1b3c4690b619d5f6bead9283d02ad12460da88bd3087ac2a93959bb37f4995d2` |
| `movies.dat` | 4,465 | 199,463 | `e256099e0a8f2d7cdc4b97ac94864c5f05795b929a97b045516ac86303931e18` |
| `users.dat` | 6,946 | 154,374 | `c0397b2eb6210f14a683c65d15d7d927aaffac0c08bcbefddb8cc2063a988279` |

### movielens-1m-v1（已停用，仅作还原基准保留）

| 文件 | 行数 | 字节 | SHA256 |
| --- | --- | --- | --- |
| `ratings.dat` | 1,000,209 | 24,594,131 | `506d64ca44484487c11dc2d9a28de5c54948213e6b96285e298afe28d6ea4e0f` |
| `movies.dat` | 3,883 | 171,308 | `1dc3a95300cb19f7c10e027daf29b8cdf1d908dab65b5edfb45950aa389a10a3` |
| `users.dat` | 6,040 | 134,368 | `0140fc2356357c1a851d0f52e893a1e4d3696df632c4141cea8d5bc3d621f0b9` |

> ⚠️ v1 的 `users.dat` 为 6,040 行；本项目上一轮清洗产物（`_baseline_v1/`）中的 6,025 行是"15 条 Zip-code 异常被隔离"之后的结果，二者不是同一层级，比较时不要混用。

## v2 相对 v1 的差异（实测）

v2 = 官方 v1 全量记录 + 注入记录，注入内容按表统计如下（明细见 `reports/quality-report/quality-report.md`）：

| 表 | 原始行数 | 其中官方记录 | 注入记录 |
| --- | --- | --- | --- |
| `ratings.dat` | 1,150,241 | 1,000,209 | +150,032 |
| `movies.dat` | 4,465 | 3,883 | +582 |
| `users.dat` | 6,946 | 6,040 | +906 |

## 落位与复现步骤

```bash
# 在 WSL Ubuntu-22.04 中执行（Windows 侧路径通过 /mnt/c 访问）

# 1) 官方 v1（如需保留作基准）
mkdir -p ~/data/ml-1m-v1

# 2) 课程给定的 v2
mkdir -p ~/data/ml-1m-v2
cp /mnt/c/Users/HP/OneDrive/Desktop/LLM/ml-1m/ml-1m/{ratings,movies,users}.dat ~/data/ml-1m-v2/

# 3) 核对校验和（应与上表一致）
sha256sum ~/data/ml-1m-v2/*.dat

# 4) 跑完整流程（清洗前评分 → 清洗 → 清洗后评分）
cd /mnt/c/Users/HP/OneDrive/Desktop/DaShuJu/lab2/movielens-data-agent
python3 hadoop/src/driver.py --mode hadoop --stage all \
  --task-id task_002 --data-dir ~/data/ml-1m-v2
```

## 注意

1. **不要**把 v1 与 v2 的产物混用（例如用 v2 的清洗结果去套 v1 的 T1/T2 统计）。
2. 时间边界 `T1/T2` 必须按**清洗后合法记录**的分位数计算；直接用 v2 原始数据计算会被毫秒/越界时间戳拉偏。
3. 数据来自课程给定目录，**不得再上传仓库**；仓库内只保留本清单与统计结论。
