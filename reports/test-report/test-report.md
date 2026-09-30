# 系统测试报告（成员C）

- 生成时间：2026-09-29 10:42:39
- 运行环境：Python 3.12.4 · Node v22.17.1
- 用例总数：**90**，失败：**0**，结论：**通过**

## 一、测试范围与结果

| 测试块 | 负责人 | 用例数 | 失败数 | 结果 |
| --- | --- | ---: | ---: | :--: |
| Hadoop 清洗与评分（成员A） | 成员A | 0 | 0 | PASS |
| Agent 接口与调度（成员B） | 成员B | 71 | 0 | PASS |
| 前端渲染逻辑（成员C · Node） | 成员C | 11 | 0 | PASS |
| 三层结果一致性（成员C · Python） | 成员C | 8 | 0 | PASS |

## 二、测试类别说明

本测试覆盖分工文档"第六.5 系统测试"要求的三个类别：

### 1. 功能测试
- 能否提交任务（POST /api/tasks 正常返回 task_id）；
- Agent 能否正常调用 Hadoop（起测试夹具模拟成员A服务）；
- Hadoop 是否成功返回结果；
- 前端是否正确显示结果（渲染逻辑单测 + 端到端代理采样）。

### 2. 异常测试
- Hadoop 执行失败（在 clean / before / after 各环节注入失败）；
- 数据文件不存在 / Hadoop 服务不可用；
- 请求参数非法（缺 prompt、非法 data_version / rule_version / score_config）；
- Agent 调用失败时前端反代返回可解析错误、不崩溃；
- 任务超时（前端轮询上限）。

### 3. 结果一致性测试（成员C 重点）
验证三层数据一致：
```
Hadoop 实际结果  →  Agent 返回结果  →  前端展示结果
```
- 前端代理出口结果与 Agent 直连接口结果**逐字节一致**；
- Agent 结果的五维分值、统计量、变化值与 Hadoop 层输出**逐字段一致**；
- 任务未完成时**不返回任何数值**（接口规范第 2.2 节）。

## 三、复现方式

```bash
# 全部测试
python tests/run_all.py --report reports/test-report/test-report.md

# 仅前端渲染（Node）
node tests/frontend/test_render.mjs

# 仅三层一致性（Python）
python tests/frontend/test_e2e_consistency.py
```


## 四、各测试块原始输出

### Hadoop 清洗与评分（成员A）（0 用例 / 0 失败）

```
（无 test_*.py 用例）
```

### Agent 接口与调度（成员B）（71 用例 / 0 失败）

```
test_ask_endpoint (test_api.TestAgentApi.test_ask_endpoint) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20260929_0001/ask HTTP/1.1" 200 -
ok
test_ask_requires_question (test_api.TestAgentApi.test_ask_requires_question) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20260929_0001/ask HTTP/1.1" 200 -
ok
test_bad_score_config (test_api.TestAgentApi.test_bad_score_config) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_evaluate_only_leaves_after_null (test_api.TestAgentApi.test_evaluate_only_leaves_after_null) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001/result HTTP/1.1" 200 -
ok
test_failure_at_before_has_no_partial (test_api.TestAgentApi.test_failure_at_before_has_no_partial) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001/result HTTP/1.1" 200 -
ok
test_failure_reports_stage_and_cause (test_api.TestAgentApi.test_failure_reports_stage_and_cause) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001/result HTTP/1.1" 200 -
ok
test_full_pipeline_success (test_api.TestAgentApi.test_full_pipeline_success) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001/result HTTP/1.1" 200 -
ok
test_hadoop_down_fails_cleanly (test_api.TestAgentApi.test_hadoop_down_fails_cleanly) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
ok
test_invalid_json_body_is_protocol_error (test_api.TestAgentApi.test_invalid_json_body_is_protocol_error) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 400 -
ok
test_list_and_health (test_api.TestAgentApi.test_list_and_health) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_missing_data_version (test_api.TestAgentApi.test_missing_data_version) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_missing_prompt (test_api.TestAgentApi.test_missing_prompt) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_result_before_completion (test_api.TestAgentApi.test_result_before_completion) ... [agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001/result HTTP/1.1" 200 -
ok
test_unknown_path_404 (test_api.TestAgentApi.test_unknown_path_404) ... [agent] 127.0.0.1 - "GET /api/nonexistent HTTP/1.1" 404 -
ok
test_unknown_task (test_api.TestAgentApi.test_unknown_task) ... [agent] 127.0.0.1 - "GET /api/tasks/task_19700101_9999 HTTP/1.1" 200 -
ok
test_unregistered_data_version (test_api.TestAgentApi.test_unregistered_data_version) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_unregistered_rule_version (test_api.TestAgentApi.test_unregistered_rule_version) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_dimension_question_uses_real_numbers (test_explainer.TestAnswerRouting.test_dimension_question_uses_real_numbers) ... ok
test_isolation_not_fix (test_explainer.TestAnswerRouting.test_isolation_not_fix) ... ok
test_limitations_question (test_explainer.TestAnswerRouting.test_limitations_question) ... ok
test_no_fabricated_numbers (test_explainer.TestAnswerRouting.test_no_fabricated_numbers) ... ok
test_unmatched_falls_back_to_summary (test_explainer.TestAnswerRouting.test_unmatched_falls_back_to_summary) ... ok
test_version_question (test_explainer.TestAnswerRouting.test_version_question) ... ok
test_weights_question (test_explainer.TestAnswerRouting.test_weights_question) ... ok
test_failed_record_explains_stage_and_guidance (test_explainer.TestNonSuccessRecords.test_failed_record_explains_stage_and_guidance) ... ok
test_failed_with_partial_result (test_explainer.TestNonSuccessRecords.test_failed_with_partial_result) ... ok
test_pending_record (test_explainer.TestNonSuccessRecords.test_pending_record) ... ok
test_running_record (test_explainer.TestNonSuccessRecords.test_running_record) ... ok
test_summarize_no_cleaning_shows_null_note (test_explainer.TestSummarize.test_summarize_no_cleaning_shows_null_note) ... ok
test_business_failure_translated_to_exception (test_hadoop_tool.TestHadoopTool.test_business_failure_translated_to_exception) ... ok
test_clean_dataset_success (test_hadoop_tool.TestHadoopTool.test_clean_dataset_success) ... ok
test_clean_failure_keeps_stage_and_code (test_hadoop_tool.TestHadoopTool.test_clean_failure_keeps_stage_and_code) ... ok
test_connection_refused_gives_guidance (test_hadoop_tool.TestHadoopTool.test_connection_refused_gives_guidance) ... ok
test_health (test_hadoop_tool.TestHadoopTool.test_health) ... ok
test_health_never_raises (test_hadoop_tool.TestHadoopTool.test_health_never_raises) ... ok
test_quality_score_after_success (test_hadoop_tool.TestHadoopTool.test_quality_score_after_success) ... ok
test_quality_score_before_success (test_hadoop_tool.TestHadoopTool.test_quality_score_before_success) ... ok
test_read_state_after_calls (test_hadoop_tool.TestHadoopTool.test_read_state_after_calls) ... ok
test_read_state_does_not_write (test_hadoop_tool.TestHadoopTool.test_read_state_does_not_write) ... ok
test_read_state_missing_returns_none (test_hadoop_tool.TestHadoopTool.test_read_state_missing_returns_none) ... ok
test_require_keys_missing (test_hadoop_tool.TestHadoopTool.test_require_keys_missing) ... ok
test_require_scores_allows_none_values (test_hadoop_tool.TestHadoopTool.test_require_scores_allows_none_values) ... ok
test_require_scores_missing_dimension (test_hadoop_tool.TestHadoopTool.test_require_scores_missing_dimension) ... ok
test_state_path_normal (test_hadoop_tool.TestHadoopTool.test_state_path_normal) ... ok
test_task_id_path_traversal_blocked (test_hadoop_tool.TestHadoopTool.test_task_id_path_traversal_blocked) ... ok
test_default_prompt_full_pipeline (test_parser.TestBuildPlan.test_default_prompt_full_pipeline) ... ok
test_evaluate_only (test_parser.TestBuildPlan.test_evaluate_only) ... ok
test_focus_dimensions (test_parser.TestBuildPlan.test_focus_dimensions) ... ok
test_no_keyword_falls_back_to_default (test_parser.TestBuildPlan.test_no_keyword_falls_back_to_default) ... ok
test_prompt_version_used_when_request_missing (test_parser.TestBuildPlan.test_prompt_version_used_when_request_missing) ... ok
test_score_config_passthrough (test_parser.TestBuildPlan.test_score_config_passthrough) ... ok
test_versions_from_prompt_recorded_but_request_wins (test_parser.TestBuildPlan.test_versions_from_prompt_recorded_but_request_wins) ... ok
test_absent (test_parser.TestDetectVersions.test_absent) ... ok
test_clean_version_regex (test_parser.TestDetectVersions.test_clean_version_regex) ... ok
test_before_only_has_nulls_not_zeros (test_result_builder.TestBuild.test_before_only_has_nulls_not_zeros) ... ok
test_clean_done_but_after_failed (test_result_builder.TestBuild.test_clean_done_but_after_failed) ... ok
test_full_result_contract_fields (test_result_builder.TestBuild.test_full_result_contract_fields) ... ok
test_missing_before_raises (test_result_builder.TestBuild.test_missing_before_raises) ... ok
test_problems_and_unresolved (test_result_builder.TestBuild.test_problems_and_unresolved) ... ok
test_report_structure (test_result_builder.TestBuild.test_report_structure) ... ok
test_score_change_arithmetic (test_result_builder.TestBuild.test_score_change_arithmetic) ... ok
test_statistics_passthrough (test_result_builder.TestBuild.test_statistics_passthrough) ... ok
test_versions_and_time_boundaries (test_result_builder.TestBuild.test_versions_and_time_boundaries) ... ok
test_create_then_pending (test_store.TestTaskStore.test_create_then_pending) ... ok
test_illegal_transition_rejected (test_store.TestTaskStore.test_illegal_transition_rejected) ... ok
test_legal_transitions (test_store.TestTaskStore.test_legal_transitions) ... ok
test_new_task_id_format (test_store.TestTaskStore.test_new_task_id_format) ... ok
test_persistence_and_restart_marks_interrupted (test_store.TestTaskStore.test_persistence_and_restart_marks_interrupted) ... ok
test_queue_position (test_store.TestTaskStore.test_queue_position) ... ok
test_result_file_written (test_store.TestTaskStore.test_result_file_written) ... ok
test_terminal_is_frozen (test_store.TestTaskStore.test_terminal_is_frozen) ... ok

----------------------------------------------------------------------
Ran 71 tests in 33.028s

OK
```

### 前端渲染逻辑（成员C · Node）（11 用例 / 0 失败）

```
前端渲染逻辑测试 (tests/frontend/test_render.mjs)

  PASS  五维表渲染 5 行，含前后与变化数值
  PASS  变化方向着色：涨/跌/平
  PASS  综合分 overall 提供时渲染
  PASS  缺失分数显示 "—" 而非 0（只评估不清洗场景）
  PASS  统计区显示修复/去重/隔离与未解决冲突主键
  PASS  问题列表动作标签中文化
  PASS  未解决问题计数正确
  PASS  版本与 T1/T2 渲染
  PASS  评估报告四段渲染
  PASS  HTML 注入被转义（XSS 防护）
  PASS  未知状态阶段容错

结果：11 通过, 0 失败
```

### 三层结果一致性（成员C · Python）（8 用例 / 0 失败）

```
test_frontend_ask_endpoint_roundtrip (test_e2e_consistency.TestE2EConsistency.test_frontend_ask_endpoint_roundtrip)
追问经前端反代往返正常。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20260929_0001/ask HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "POST /api/tasks/task_20260929_0001/ask HTTP/1.1" 200 -
ok
test_frontend_proxy_forwards_health (test_e2e_consistency.TestE2EConsistency.test_frontend_proxy_forwards_health)
前端 /health 反代到 Agent，证明三层连通。 ... [agent] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_frontend_proxy_forwards_task_errors (test_e2e_consistency.TestE2EConsistency.test_frontend_proxy_forwards_task_errors)
异常测试：非法 data_version 的错误经前端透传，前端可展示。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_frontend_proxy_reports_backend_down (test_e2e_consistency.TestE2EConsistency.test_frontend_proxy_reports_backend_down)
异常测试：Agent 不可用时前端不应崩溃，应返回可解析的错误 JSON。 ... [frontend] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_frontend_sees_null_not_zero_for_evaluate_only (test_e2e_consistency.TestE2EConsistency.test_frontend_sees_null_not_zero_for_evaluate_only)
只评估不清洗：after 必须为 null，前端应渲染占位符而非 0。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0002/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20260929_0002/result HTTP/1.1" 200 -
ok
test_frontend_static_assets_served (test_e2e_consistency.TestE2EConsistency.test_frontend_static_assets_served)
前端服务能正确托管页面与三类静态资源。 ... [frontend] 127.0.0.1 - "GET / HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /style.css HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /js/api.js HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /js/render.js HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /js/app.js HTTP/1.1" 200 -
ok
test_no_numbers_before_completion (test_e2e_consistency.TestE2EConsistency.test_no_numbers_before_completion)
任务未完成时前端出口不得返回任何数值（接口规范第 2.2 节）。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0003/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20260929_0003/result HTTP/1.1" 200 -
ok
test_three_layer_values_identical (test_e2e_consistency.TestE2EConsistency.test_three_layer_values_identical)
核心：Hadoop → Agent → 前端 三层数值完全一致。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0004 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0004 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0004/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20260929_0004/result HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20260929_0004/result HTTP/1.1" 200 -
ok

----------------------------------------------------------------------
Ran 8 tests in 3.936s

OK
```
