# Agent 流程与 Prompt 设计（成员B · 迭代一）

本文档是迭代一分工文档中成员B"Prompt / 流程设计"交付物，
描述 `agent/` 模块的完整执行流程、状态机、需求解析规则与 Prompt 设计。
契约字段以 `docs/接口规范文档.md` 为准，评分口径以
`hadoop/config/rules.json` 与 `docs/evaluation-method.md` 为准。

## 1. 总体流程

```text
前端(C) ──POST /api/tasks──▶ Agent(B) ──Hadoop Tool──▶ Hadoop 服务(A)
                                │                          │
                                │ ◀──三个阶段的 HTTP 响应───┘
                                ▼
                     任务状态文件(只读交接)
              reports/quality-report/{task_id}.json
                                ▼
                  组装第13节结果 + 评估报告(复用A的映射与文案)
                                ▼
        GET /api/tasks/{id} / GET /api/tasks/{id}/result / POST .../ask
```

一次完整任务在调度器中的执行序列（单工作线程 FIFO，串行调度）：

```text
PENDING
 └─ RUNNING / PARSE_REQUEST      需求解析完成
     RUNNING / BEFORE_SCORE      POST /hadoop/quality-score/before
     RUNNING / CLEANING          POST /hadoop/clean            （do_clean=true 时）
     RUNNING / AFTER_SCORE       POST /hadoop/quality-score/after
     RUNNING / GENERATE_REPORT   组装第13节结果、生成报告
     SUCCESS / COMPLETED
   任一环节失败 → FAILED（写明环节+错误码+原因+下一步指引，
                              已完成环节以"部分结果"保留，缺失字段为 null）
```

## 2. 为什么 Agent 需要"组装结果"

成员A的 HTTP 端点按契约只返回最小字段（第 9-11 节），
第 13 节的完整结果原本只在 `driver --stage all` 路径组装。
Agent 走三接口 + 状态交接文件，因此由 `result_builder.py` 补上这一步：

- 全部数值取自A写入状态文件的真实执行产物（metrics / scores / statistics）；
- `score_change` 只做四则运算；
- `problems / report` **复用A的 `problems.py` / `report.py`**
  （见 `pipeline_bridge.py` 的理由说明），不重写映射表和文案，
  保证与A的路径产出完全同口径；
- 未执行的环节一律 `null` + `_note`，绝不填 0（接口规范第 2.2 节）。

与A的一处刻意差异：`unresolved_problems` 在清洗完成后按 **after 指标**
计算（"清洗后依然存在"），而A在 all 路径按 before 指标
（"本轮计划处置"）。前者更贴近第 14 节 unresolved 的定义；
该差异已在 PR 描述中向成员A/C说明，待评审确认。

## 3. 需求解析（Prompt → 执行计划）

两级解析，规则优先、模型兜底，输出结构化 `plan`：

| 判定项 | 规则 | 说明 |
| --- | --- | --- |
| 是否清洗 | 命中"不清洗/只评估/仅评分/…"→ `do_clean=false`；命中"清洗/治理/去重/隔离/修复/…"→ true；均未命中→先问 LLM（可用时），否则走项目默认流程（评估+清洗+对比） | LLM 只允许二选一，不允许产生数值 |
| 关注维度 | 关键词表（准确/合法、完整/缺失、唯一/重复、时效/新鲜、一致/引用） | 只影响解释侧重；评分始终五维全量，防止用户话术改变评价口径（第 11 节） |
| 版本 | 正则抽取 `movielens-1m(-clean-vN)?-vN`、`rule-vN`；**请求字段优先**，提示词只作兜底并记录冲突说明 | 未登记版本在创建时直接拒绝（`INVALID_DATA_VERSION`/`INVALID_RULE_VERSION`，第 16 节） |
| score_config | 结构校验（维度→bool）后原样透传给A | A 当前忽略该字段，Agent 不做"假过滤" |

`plan.notes` 记录 Agent 的理解结论，随创建响应返回（`understanding` 字段），
让前端第一时间展示"系统把你理解成了什么"，理解偏差可当场发现。

## 4. Prompt 设计（文件：`agent/config/prompts/`）

**system_intent.txt**（意图分类兜底）：只输出
`{"do_clean": bool, "confidence": ...}`；禁止输出数值；
输出解析失败即回退默认流程。

**system_explain.txt**（结果解释）：
- 只允许引用给定结果 JSON 中的数字，null 必须说"未执行"；
- 隔离≠修复的措辞纪律（迭代一需求第 91 行）；
- 时效性≈21.5 的固定解释义务（分位数切分的客观结果，
  见 evaluation-method 第 4.4 节）；
- 超纲问题必须拒答并说明缺什么数据。

**设计红线：LLM 不进入数据通路。**
数值由 Hadoop 产生、由模板解释；LLM 只做两件事——二选一分类与
证据受限的自然语言改写。未安装 anthropic / 未配置密钥时
`llm.AVAILABLE=False`，全部功能回退确定性模板路径（主路径），
因此评测环境下行为完全一致、可单测。

## 5. 状态管理与失败语义

- 任务记录实时落盘 `agent/runtime/tasks/{task_id}.json`（原子写）；
  结果快照落 `agent/runtime/results/{task_id}.json`。
- 状态机迁移在 `store.py` 集中校验：终态不可再改，非法迁移抛异常。
- 服务重启后仍处于 PENDING/RUNNING 的任务如实改写为
  FAILED(AGENT_EXECUTION_ERROR，"服务重启中断")，不假装可续跑。
- 对A状态文件的写入内容做存在性校验（`_require_state`）：
  HTTP 报成功但交接文件缺关键指标 → 按 `QUALITY_SCORE_ERROR` 失败，
  拒绝输出可疑结果。
- Agent 对 `reports/quality-report/` **只读**，避免与A服务并发写冲突。

## 6. 追问接口（接口文档第 6.2 节新增）

```text
POST /api/tasks/{task_id}/ask   {"question": "..."}
→ {"task_id", "question", "answer", "source": "template|template+llm"}
```

模板路由：维度名→该维前后得分+口径+问题+未解决项；"隔离"→处置统计与
措辞澄清；"版本/T1/T2/划分"→版本与 epoch；"权重"；"局限/不足"→
report.limitations；失败任务→环节+原因+指引+部分结果。
未命中且 LLM 可用时，以证据摘录调用模型，回答标注 `template+llm`。

## 7. 运行与联调

```bash
# 终端1：成员A服务（本地联调用 local 模式）
python3 hadoop/src/server.py --mode local --data-dir data/ml-1m-v2

# 终端2：成员B Agent
python3 agent/src/api.py --port 8090   # ML_HADOOP_URL 可覆盖A服务地址

# 提交默认流程任务
curl -X POST http://127.0.0.1:8090/api/tasks -H 'Content-Type: application/json' \
  -d '{"prompt":"请使用默认规则清洗 MovieLens 1M，评估清洗前后的五个数据质量维度。","data_version":"movielens-1m-v2","rule_version":"default"}'

# 轮询 / 取结果 / 追问
curl http://127.0.0.1:8090/api/tasks/task_YYYYMMDD_0001
curl http://127.0.0.1:8090/api/tasks/task_YYYYMMDD_0001/result
```

单元测试（标准库 unittest）：

```bash
python -m unittest discover -s tests/agent -v
```
