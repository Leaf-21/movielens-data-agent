# 系统测试报告（成员C）

- 生成时间：2026-10-20 22:25:22
- 运行环境：Python 3.12.4 · Node v22.17.1
- 用例总数：**261**，失败：**0**，结论：**通过**

## 一、测试范围与结果

| 测试块 | 负责人 | 用例数 | 失败数 | 结果 |
| --- | --- | ---: | ---: | :--: |
| Hadoop 清洗与评分（成员A） | 成员A | 7 | 0 | PASS |
| Agent 接口与调度（成员B） | 成员B | 232 | 0 | PASS |
| 前端渲染逻辑（成员C · Node） | 成员C | 14 | 0 | PASS |
| 三层结果一致性（成员C · Python） | 成员C | 8 | 0 | PASS |

## 二、测试类别说明

本测试覆盖分工文档"第六.5 系统测试"要求的三个类别：

### 1. 功能测试
- 能否提交任务（POST /api/tasks 正常返回 task_id）；
- Agent 能否正常调用 Hadoop（起测试夹具模拟成员A服务）；
- Hadoop 是否成功返回结果；
- 前端是否正确显示结果（渲染逻辑单测 + 端到端代理采样）。
- 迭代二 PCA/t-SNE 数学性质、参数边界、可复现性与 CLI 子进程协议；
- 迭代二分类、聚类、降维结果字段及降维坐标图例/指标的前端渲染。

### 2. 异常测试
- Hadoop 执行失败（在 clean / before / after 各环节注入失败）；
- 数据文件不存在 / Hadoop 服务不可用；
- 请求参数非法（缺 prompt、非法 data_version / rule_version / score_config）；
- Agent 调用失败时前端反代返回可解析错误、不崩溃；
- 任务超时（前端轮询上限）。
- 分析工具信封按任务类别校验；不把聚类专属字段强加给分类或降维工具；
- 快照缺失、未知用户和模型不可用时返回明确失败，不生成虚构分析结果。

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

### Hadoop 清洗与评分（成员A）（7 用例 / 0 失败）

```
--- test_clean_snapshot ---
test_every_split_has_both_classes (test_clean_snapshot.TestCleanSnapshot.test_every_split_has_both_classes) ... ok
test_no_duplicate_pairs (test_clean_snapshot.TestCleanSnapshot.test_no_duplicate_pairs) ... ok
test_no_invalid_rows (test_clean_snapshot.TestCleanSnapshot.test_no_invalid_rows) ... ok
test_record_count_matches_iteration_one (test_clean_snapshot.TestCleanSnapshot.test_record_count_matches_iteration_one) ... ok
test_split_counts_match_registered_expectation (test_clean_snapshot.TestCleanSnapshot.test_split_counts_match_registered_expectation) ... ok
test_split_windows_do_not_overlap (test_clean_snapshot.TestCleanSnapshot.test_split_windows_do_not_overlap) ... ok
test_three_tables_present (test_clean_snapshot.TestCleanSnapshot.test_three_tables_present) ... ok

----------------------------------------------------------------------
Ran 7 tests in 1.900s

OK
```

### Agent 接口与调度（成员B）（232 用例 / 0 失败）

```
--- test_analysis_api ---
test_classification_model_not_found_sync (test_analysis_api.TestAnalysisApi.test_classification_model_not_found_sync) ... [agent] 127.0.0.1 - "POST /api/analysis/classification/tasks HTTP/1.1" 200 -
ok
test_clustering_dual_algorithm_e2e (test_analysis_api.TestAnalysisApi.test_clustering_dual_algorithm_e2e) ... [agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001/result HTTP/1.1" 200 -
ok
test_dimensionality_reduction_model_not_found (test_analysis_api.TestAnalysisApi.test_dimensionality_reduction_model_not_found) ... [agent] 127.0.0.1 - "POST /api/analysis/dimensionality-reduction/tasks HTTP/1.1" 200 -
ok
test_health_exposes_analysis (test_analysis_api.TestAnalysisApi.test_health_exposes_analysis) ... [agent] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_invalid_requests_sync (test_analysis_api.TestAnalysisApi.test_invalid_requests_sync) ... [agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
ok
test_single_algorithm_query_and_ask (test_analysis_api.TestAnalysisApi.test_single_algorithm_query_and_ask) ... [agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261020_0002/ask HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261020_0002/ask HTTP/1.1" 200 -
ok
test_task_list_exposes_task_type (test_analysis_api.TestAnalysisApi.test_task_list_exposes_task_type) ... [agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0003 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0003 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
ok

----------------------------------------------------------------------
Ran 7 tests in 2.579s

OK

--- test_analysis_runner ---
test_failure_keeps_completed_algorithm (test_analysis_runner.TestRunTask.test_failure_keeps_completed_algorithm) ... ok
test_success_assembly (test_analysis_runner.TestRunTask.test_success_assembly) ... ok
test_crash_then_retry_success (test_analysis_runner.TestSubprocessProtocol.test_crash_then_retry_success) ... ok
test_missing_keys_rejected_as_contract_violation (test_analysis_runner.TestSubprocessProtocol.test_missing_keys_rejected_as_contract_violation) ... ok
test_persistent_failure_algorithm_error (test_analysis_runner.TestSubprocessProtocol.test_persistent_failure_algorithm_error) ... ok
test_required_envelope_keys_follow_task_type (test_analysis_runner.TestSubprocessProtocol.test_required_envelope_keys_follow_task_type) ... ok
test_semantic_failure_no_retry (test_analysis_runner.TestSubprocessProtocol.test_semantic_failure_no_retry) ... ok
test_success_attempt_1 (test_analysis_runner.TestSubprocessProtocol.test_success_attempt_1) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.698s

OK

--- test_api ---
test_ask_endpoint (test_api.TestAgentApi.test_ask_endpoint) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261020_0001/ask HTTP/1.1" 200 -
ok
test_ask_requires_question (test_api.TestAgentApi.test_ask_requires_question) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261020_0001/ask HTTP/1.1" 200 -
ok
test_bad_score_config (test_api.TestAgentApi.test_bad_score_config) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_evaluate_only_leaves_after_null (test_api.TestAgentApi.test_evaluate_only_leaves_after_null) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001/result HTTP/1.1" 200 -
ok
test_failure_at_before_has_no_partial (test_api.TestAgentApi.test_failure_at_before_has_no_partial) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001/result HTTP/1.1" 200 -
ok
test_failure_reports_stage_and_cause (test_api.TestAgentApi.test_failure_reports_stage_and_cause) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001/result HTTP/1.1" 200 -
ok
test_full_pipeline_success (test_api.TestAgentApi.test_full_pipeline_success) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001/result HTTP/1.1" 200 -
ok
test_hadoop_down_fails_cleanly (test_api.TestAgentApi.test_hadoop_down_fails_cleanly) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
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
test_result_before_completion (test_api.TestAgentApi.test_result_before_completion) ... [agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001/result HTTP/1.1" 200 -
ok
test_unknown_path_404 (test_api.TestAgentApi.test_unknown_path_404) ... [agent] 127.0.0.1 - "GET /api/nonexistent HTTP/1.1" 404 -
ok
test_unknown_task (test_api.TestAgentApi.test_unknown_task) ... [agent] 127.0.0.1 - "GET /api/tasks/task_19700101_9999 HTTP/1.1" 200 -
ok
test_unregistered_data_version (test_api.TestAgentApi.test_unregistered_data_version) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_unregistered_rule_version (test_api.TestAgentApi.test_unregistered_rule_version) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok

----------------------------------------------------------------------
Ran 17 tests in 18.713s

OK

--- test_classification_features ---
test_default_basis_uses_train_snapshot (test_classification_features.TestLeakage.test_default_basis_uses_train_snapshot) ... ok
test_future_events_do_not_change_past_features (test_classification_features.TestLeakage.test_future_events_do_not_change_past_features) ... ok
test_same_second_events_excluded (test_classification_features.TestLeakage.test_same_second_events_excluded)
同一秒的另一条评分（1::11::4::300）也不得参与该秒事件的特征。 ... ok
test_target_rating_not_in_own_features (test_classification_features.TestLeakage.test_target_rating_not_in_own_features)
目标事件 Rating=5，但此前只有 1 分，用户均分应为 1.0。 ... ok
test_no_nan (test_classification_features.TestMatrixShape.test_no_nan) ... ok
test_shape_and_labels (test_classification_features.TestMatrixShape.test_shape_and_labels) ... ok
test_split_counts (test_classification_features.TestMatrixShape.test_split_counts) ... ok
test_matrix_counts_missing_rows (test_classification_features.TestMissingAttributes.test_matrix_counts_missing_rows) ... ok
test_user_without_attrs_flagged (test_classification_features.TestMissingAttributes.test_user_without_attrs_flagged) ... ok
test_model_not_found (test_classification_features.TestModelMissing.test_model_not_found) ... skipped '未安装 scikit-learn'
test_legacy_mapping_keeps_sub_code (test_classification_features.TestUnknownIds.test_legacy_mapping_keeps_sub_code) ... ok
test_unknown_movie (test_classification_features.TestUnknownIds.test_unknown_movie) ... ok
test_unknown_user (test_classification_features.TestUnknownIds.test_unknown_user) ... ok

----------------------------------------------------------------------
Ran 13 tests in 0.073s

OK (skipped=1)

--- test_classification_modeling ---
test_metrics_include_confusion_and_rate (test_classification_modeling.TestEvaluationShape.test_metrics_include_confusion_and_rate) ... skipped '未安装 scikit-learn'
test_all_negative_labels_do_not_crash (test_classification_modeling.TestThresholdPolicy.test_all_negative_labels_do_not_crash) ... skipped '未安装 scikit-learn'
test_positive_rate_constraint_is_applied (test_classification_modeling.TestThresholdPolicy.test_positive_rate_constraint_is_applied) ... skipped '未安装 scikit-learn'
test_separable_case_returns_sane_threshold (test_classification_modeling.TestThresholdPolicy.test_separable_case_returns_sane_threshold) ... skipped '未安装 scikit-learn'

----------------------------------------------------------------------
Ran 4 tests in 0.000s

OK (skipped=4)

--- test_classification_tool ---
test_envelope_shape (test_classification_tool.TestEnvelope.test_envelope_shape) ... ok
test_result_version_is_deterministic (test_classification_tool.TestEnvelope.test_result_version_is_deterministic) ... ok
test_tool_error_is_converted (test_classification_tool.TestEnvelope.test_tool_error_is_converted) ... ok
test_data_version_mismatch (test_classification_tool.TestPayloadValidation.test_data_version_mismatch) ... ok
test_feature_version_mismatch (test_classification_tool.TestPayloadValidation.test_feature_version_mismatch) ... ok
test_missing_algorithm (test_classification_tool.TestPayloadValidation.test_missing_algorithm) ... ok
test_missing_ids (test_classification_tool.TestPayloadValidation.test_missing_ids) ... ok
test_unknown_algorithm (test_classification_tool.TestPayloadValidation.test_unknown_algorithm) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.003s

OK

--- test_dbscan_tool ---
test_default_eps_from_kdistance (test_dbscan_tool.TestDBScanTool.test_default_eps_from_kdistance) ... ok
test_envelope_contract (test_dbscan_tool.TestDBScanTool.test_envelope_contract) ... ok
test_metrics_fields_and_determinism (test_dbscan_tool.TestDBScanTool.test_metrics_fields_and_determinism) ... ok
test_min_samples_below_fit_users_errors (test_dbscan_tool.TestDBScanTool.test_min_samples_below_fit_users_errors) ... ok
test_no_out_of_sample_projection (test_dbscan_tool.TestDBScanTool.test_no_out_of_sample_projection) ... ok
test_two_blobs_and_noise (test_dbscan_tool.TestDBScanTool.test_two_blobs_and_noise) ... ok
test_unknown_user_and_invalid_param (test_dbscan_tool.TestDBScanTool.test_unknown_user_and_invalid_param) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.066s

OK

--- test_dimensionality_reduction ---
test_pca_invalid_parameter_exit_2 (test_dimensionality_reduction.TestCliProtocol.test_pca_invalid_parameter_exit_2) ... ok
test_tsne_unknown_parameter_exit_2 (test_dimensionality_reduction.TestCliProtocol.test_tsne_unknown_parameter_exit_2) ... ok
test_empty_ok (test_dimensionality_reduction.TestDrParams.test_empty_ok) ... ok
test_non_numeric_rejected (test_dimensionality_reduction.TestDrParams.test_non_numeric_rejected) ... ok
test_out_of_range_rejected (test_dimensionality_reduction.TestDrParams.test_out_of_range_rejected) ... ok
test_unknown_key_rejected (test_dimensionality_reduction.TestDrParams.test_unknown_key_rejected) ... ok
test_valid_passthrough (test_dimensionality_reduction.TestDrParams.test_valid_passthrough) ... ok
test_components_orthonormal (test_dimensionality_reduction.TestPcaMath.test_components_orthonormal) ... ok
test_explained_variance_properties (test_dimensionality_reduction.TestPcaMath.test_explained_variance_properties) ... ok
test_keep_dimensions_for_threshold (test_dimensionality_reduction.TestPcaMath.test_keep_dimensions_for_threshold) ... ok
test_loading_sign_convention_deterministic (test_dimensionality_reduction.TestPcaMath.test_loading_sign_convention_deterministic) ... ok
test_projection_reproduces_coords (test_dimensionality_reduction.TestPcaMath.test_projection_reproduces_coords)
用 mean+components 手动投影，应与 fit 返回的 coords 一致（样本内）。 ... ok
test_target_dim_bounds (test_dimensionality_reduction.TestPcaMath.test_target_dim_bounds) ... ok
test_too_few_users (test_dimensionality_reduction.TestPcaMath.test_too_few_users) ... ok
test_pca_tool_envelope_includes_comparison_and_coordinates (test_dimensionality_reduction.TestToolEnvelopes.test_pca_tool_envelope_includes_comparison_and_coordinates) ... ok
test_tsne_tool_envelope_does_not_claim_explained_variance (test_dimensionality_reduction.TestToolEnvelopes.test_tsne_tool_envelope_does_not_claim_explained_variance) ... ok
test_deterministic_with_seed (test_dimensionality_reduction.TestTsneMath.test_deterministic_with_seed) ... ok
test_different_seed_differs (test_dimensionality_reduction.TestTsneMath.test_different_seed_differs) ... ok
test_fit_accepts_plain_lists (test_dimensionality_reduction.TestTsneMath.test_fit_accepts_plain_lists)
不依赖调用方预转 numpy（工具边界要健壮）。 ... ok
test_knn_agreement_bounds (test_dimensionality_reduction.TestTsneMath.test_knn_agreement_bounds) ... ok
test_knn_agreement_none_when_too_small (test_dimensionality_reduction.TestTsneMath.test_knn_agreement_none_when_too_small) ... ok
test_perplexity_boundary_just_accepted (test_dimensionality_reduction.TestTsneMath.test_perplexity_boundary_just_accepted) ... ok
test_perplexity_constraint (test_dimensionality_reduction.TestTsneMath.test_perplexity_constraint) ... ok
test_student_t_gradient_matches_finite_difference (test_dimensionality_reduction.TestTsneMath.test_student_t_gradient_matches_finite_difference) ... ok
test_student_t_probabilities_use_pairwise_distances (test_dimensionality_reduction.TestTsneMath.test_student_t_probabilities_use_pairwise_distances) ... ok
test_too_few_users (test_dimensionality_reduction.TestTsneMath.test_too_few_users) ... ok
test_pca_projects_out_of_sample_cold_user (test_dimensionality_reduction.TestWithSnapshot.test_pca_projects_out_of_sample_cold_user) ... ok
test_pca_unknown_user_reported_not_faked (test_dimensionality_reduction.TestWithSnapshot.test_pca_unknown_user_reported_not_faked) ... ok
test_tsne_does_not_project_out_of_sample (test_dimensionality_reduction.TestWithSnapshot.test_tsne_does_not_project_out_of_sample) ... ok

----------------------------------------------------------------------
Ran 29 tests in 2.243s

OK

--- test_explainer ---
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

----------------------------------------------------------------------
Ran 12 tests in 0.001s

OK

--- test_hadoop_tool ---
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

----------------------------------------------------------------------
Ran 16 tests in 13.858s

OK

--- test_kmeans_tool ---
test_blob_assignment_and_honest_statuses (test_kmeans_tool.TestKMeansTool.test_blob_assignment_and_honest_statuses) ... ok
test_determinism_and_result_version_stability (test_kmeans_tool.TestKMeansTool.test_determinism_and_result_version_stability) ... ok
test_envelope_contract (test_kmeans_tool.TestKMeansTool.test_envelope_contract) ... ok
test_explicit_k_fixes_candidates (test_kmeans_tool.TestKMeansTool.test_explicit_k_fixes_candidates) ... ok
test_invalid_parameter_range_and_key (test_kmeans_tool.TestKMeansTool.test_invalid_parameter_range_and_key) ... ok
test_metrics_and_definitions (test_kmeans_tool.TestKMeansTool.test_metrics_and_definitions) ... ok
test_no_targets_invalid_request (test_kmeans_tool.TestKMeansTool.test_no_targets_invalid_request) ... ok
test_summaries_real_stats (test_kmeans_tool.TestKMeansTool.test_summaries_real_stats) ... ok
test_unknown_user (test_kmeans_tool.TestKMeansTool.test_unknown_user) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.073s

OK

--- test_metrics ---
test_centroid (test_metrics.TestBasics.test_centroid) ... ok
test_euclid_equals_math_dist (test_metrics.TestBasics.test_euclid_equals_math_dist) ... ok
test_sse_skips_noise (test_metrics.TestBasics.test_sse_skips_noise) ... ok
test_coincident_centroids_none (test_metrics.TestDaviesBouldin.test_coincident_centroids_none) ... ok
test_null_centroid_none (test_metrics.TestDaviesBouldin.test_null_centroid_none) ... ok
test_single_cluster_none (test_metrics.TestDaviesBouldin.test_single_cluster_none) ... ok
test_symmetric_two_clusters_positive (test_metrics.TestDaviesBouldin.test_symmetric_two_clusters_positive) ... ok
test_definitions_registered (test_metrics.TestDefinitions.test_definitions_registered) ... ok
test_deterministic_and_sorted (test_metrics.TestSample.test_deterministic_and_sorted) ... ok
test_full_when_size_ge_n (test_metrics.TestSample.test_full_when_size_ge_n) ... ok
test_seed_formula_stability (test_metrics.TestSample.test_seed_formula_stability) ... ok
test_noise_excluded (test_metrics.TestSilhouette.test_noise_excluded) ... ok
test_sampled_matches_full_when_sample_is_all (test_metrics.TestSilhouette.test_sampled_matches_full_when_sample_is_all) ... ok
test_sampled_single_cluster_none (test_metrics.TestSilhouette.test_sampled_single_cluster_none) ... ok
test_single_cluster_returns_none (test_metrics.TestSilhouette.test_single_cluster_returns_none) ... ok
test_singleton_convention_zero (test_metrics.TestSilhouette.test_singleton_convention_zero) ... ok
test_two_clean_blobs_positive (test_metrics.TestSilhouette.test_two_clean_blobs_positive) ... ok

----------------------------------------------------------------------
Ran 17 tests in 0.002s

OK

--- test_parser ---
test_default_prompt_full_pipeline (test_parser.TestBuildPlan.test_default_prompt_full_pipeline) ... ok
test_evaluate_only (test_parser.TestBuildPlan.test_evaluate_only) ... ok
test_focus_dimensions (test_parser.TestBuildPlan.test_focus_dimensions) ... ok
test_no_keyword_falls_back_to_default (test_parser.TestBuildPlan.test_no_keyword_falls_back_to_default) ... ok
test_prompt_version_used_when_request_missing (test_parser.TestBuildPlan.test_prompt_version_used_when_request_missing) ... ok
test_score_config_passthrough (test_parser.TestBuildPlan.test_score_config_passthrough) ... ok
test_versions_from_prompt_recorded_but_request_wins (test_parser.TestBuildPlan.test_versions_from_prompt_recorded_but_request_wins) ... ok
test_absent (test_parser.TestDetectVersions.test_absent) ... ok
test_clean_version_regex (test_parser.TestDetectVersions.test_clean_version_regex) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.000s

OK

--- test_profiler ---
test_cache_reuse_when_inputs_unchanged (test_profiler.TestProfile.test_cache_reuse_when_inputs_unchanged) ... ok
test_determinism_same_input (test_profiler.TestProfile.test_determinism_same_input) ... ok
test_feature_values_hand_check (test_profiler.TestProfile.test_feature_values_hand_check) ... ok
test_global_mean_hand_check (test_profiler.TestProfile.test_global_mean_hand_check) ... ok
test_insufficient_user (test_profiler.TestProfile.test_insufficient_user) ... ok
test_missing_snapshot_raises_data_unavailable (test_profiler.TestProfile.test_missing_snapshot_raises_data_unavailable) ... ok
test_no_ratings_user (test_profiler.TestProfile.test_no_ratings_user) ... ok
test_orphans_registered_not_dropped (test_profiler.TestProfile.test_orphans_registered_not_dropped) ... ok
test_scaler_fitted_on_ok_users_only (test_profiler.TestProfile.test_scaler_fitted_on_ok_users_only) ... ok
test_status_counts (test_profiler.TestProfile.test_status_counts) ... ok
test_t1_boundary_only_training_window (test_profiler.TestProfile.test_t1_boundary_only_training_window) ... ok

----------------------------------------------------------------------
Ran 11 tests in 0.091s

OK

--- test_registry_router ---
test_algorithm_names_single_source (test_registry_router.TestRegistry.test_algorithm_names_single_source) ... ok
test_category_slugs (test_registry_router.TestRegistry.test_category_slugs) ... ok
test_require_registered (test_registry_router.TestRegistry.test_require_registered) ... ok
test_require_unregistered_model_not_found (test_registry_router.TestRegistry.test_require_unregistered_model_not_found) ... ok
test_tool_naming_convention (test_registry_router.TestRegistry.test_tool_naming_convention) ... ok
test_all_unknown_users_rejected_at_creation (test_registry_router.TestRouter.test_all_unknown_users_rejected_at_creation) ... ok
test_body_algorithm_field_authoritative (test_registry_router.TestRouter.test_body_algorithm_field_authoritative) ... ok
test_category_consistency_guidance (test_registry_router.TestRouter.test_category_consistency_guidance) ... ok
test_classification_not_implemented (test_registry_router.TestRouter.test_classification_not_implemented) ... ok
test_default_runs_both_algorithms (test_registry_router.TestRouter.test_default_runs_both_algorithms) ... ok
test_dimensionality_reduction_defaults_to_registered_population (test_registry_router.TestRouter.test_dimensionality_reduction_defaults_to_registered_population) ... ok
test_no_users_invalid_request (test_registry_router.TestRouter.test_no_users_invalid_request) ... ok
test_parameters_pruned_per_algorithm (test_registry_router.TestRouter.test_parameters_pruned_per_algorithm) ... ok
test_partial_unknown_filtered_with_note (test_registry_router.TestRouter.test_partial_unknown_filtered_with_note) ... ok
test_query_algorithm_keywords (test_registry_router.TestRouter.test_query_algorithm_keywords) ... ok
test_query_length_cap (test_registry_router.TestRouter.test_query_length_cap) ... ok
test_query_user_extraction_and_body_priority (test_registry_router.TestRouter.test_query_user_extraction_and_body_priority) ... ok
test_unregistered_algorithm_model_not_found (test_registry_router.TestRouter.test_unregistered_algorithm_model_not_found) ... ok
test_user_ids_must_be_list (test_registry_router.TestRouter.test_user_ids_must_be_list) ... ok
test_version_mismatches (test_registry_router.TestRouter.test_version_mismatches) ... ok

----------------------------------------------------------------------
Ran 20 tests in 0.032s

OK

--- test_result_builder ---
test_before_only_has_nulls_not_zeros (test_result_builder.TestBuild.test_before_only_has_nulls_not_zeros) ... ok
test_clean_done_but_after_failed (test_result_builder.TestBuild.test_clean_done_but_after_failed) ... ok
test_full_result_contract_fields (test_result_builder.TestBuild.test_full_result_contract_fields) ... ok
test_missing_before_raises (test_result_builder.TestBuild.test_missing_before_raises) ... ok
test_problems_and_unresolved (test_result_builder.TestBuild.test_problems_and_unresolved) ... ok
test_report_structure (test_result_builder.TestBuild.test_report_structure) ... ok
test_score_change_arithmetic (test_result_builder.TestBuild.test_score_change_arithmetic) ... ok
test_statistics_passthrough (test_result_builder.TestBuild.test_statistics_passthrough) ... ok
test_versions_and_time_boundaries (test_result_builder.TestBuild.test_versions_and_time_boundaries) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.001s

OK

--- test_schemas ---
test_cap_20000 (test_schemas.TestNormalizeTargets.test_cap_20000) ... ok
test_dedupe_sort_and_str (test_schemas.TestNormalizeTargets.test_dedupe_sort_and_str) ... ok
test_garbage_and_nonpositive (test_schemas.TestNormalizeTargets.test_garbage_and_nonpositive) ... ok
test_missing_both (test_schemas.TestNormalizeTargets.test_missing_both) ... ok
test_non_list_user_ids (test_schemas.TestNormalizeTargets.test_non_list_user_ids) ... ok
test_envelope_required_fields_doc_sync (test_schemas.TestToolName.test_envelope_required_fields_doc_sync) ... ok
test_all_unknown_is_request_level_error (test_schemas.TestUserStatuses.test_all_unknown_is_request_level_error) ... ok
test_partial_unknown_returns_split (test_schemas.TestUserStatuses.test_partial_unknown_returns_split) ... ok
test_bool_not_number (test_schemas.TestValidateParameters.test_bool_not_number) ... ok
test_out_of_range_rejected (test_schemas.TestValidateParameters.test_out_of_range_rejected) ... ok
test_passthrough_subset (test_schemas.TestValidateParameters.test_passthrough_subset) ... ok
test_string_number_rejected (test_schemas.TestValidateParameters.test_string_number_rejected) ... ok
test_unknown_key_rejected (test_schemas.TestValidateParameters.test_unknown_key_rejected) ... ok

----------------------------------------------------------------------
Ran 13 tests in 0.005s

OK

--- test_split ---
test_missing_snapshot_raises (test_split.TestDataUnavailable.test_missing_snapshot_raises) ... ok
test_positive_rate_matches_definition (test_split.TestLabelRule.test_positive_rate_matches_definition) ... ok
test_rating_four_and_five_are_positive (test_split.TestLabelRule.test_rating_four_and_five_are_positive) ... ok
test_rating_three_is_negative (test_split.TestLabelRule.test_rating_three_is_negative) ... ok
test_split_version_declared (test_split.TestRulesSource.test_split_version_declared) ... ok
test_time_bounds_from_rules (test_split.TestRulesSource.test_time_bounds_from_rules) ... ok
test_epoch_equal_t1_is_train (test_split.TestSplitBoundary.test_epoch_equal_t1_is_train) ... ok
test_epoch_equal_t2_is_validate (test_split.TestSplitBoundary.test_epoch_equal_t2_is_validate) ... ok
test_one_second_after_t1_is_validate (test_split.TestSplitBoundary.test_one_second_after_t1_is_validate) ... ok
test_one_second_after_t2_is_test (test_split.TestSplitBoundary.test_one_second_after_t2_is_test) ... ok
test_one_second_before_t1_is_train (test_split.TestSplitBoundary.test_one_second_before_t1_is_train) ... ok
test_sets_do_not_overlap (test_split.TestSplitBoundary.test_sets_do_not_overlap) ... ok
test_counts_and_unique_sets (test_split.TestSummaryShape.test_counts_and_unique_sets) ... ok
test_ratios_sum_to_one (test_split.TestSummaryShape.test_ratios_sum_to_one) ... ok
test_time_range_per_split (test_split.TestSummaryShape.test_time_range_per_split) ... ok

----------------------------------------------------------------------
Ran 15 tests in 0.001s

OK

--- test_store ---
test_create_then_pending (test_store.TestTaskStore.test_create_then_pending) ... ok
test_illegal_transition_rejected (test_store.TestTaskStore.test_illegal_transition_rejected) ... ok
test_legal_transitions (test_store.TestTaskStore.test_legal_transitions) ... ok
test_new_task_id_format (test_store.TestTaskStore.test_new_task_id_format) ... ok
test_persistence_and_restart_marks_interrupted (test_store.TestTaskStore.test_persistence_and_restart_marks_interrupted) ... ok
test_queue_position (test_store.TestTaskStore.test_queue_position) ... ok
test_result_file_written (test_store.TestTaskStore.test_result_file_written) ... ok
test_terminal_is_frozen (test_store.TestTaskStore.test_terminal_is_frozen) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.029s

OK
```

### 前端渲染逻辑（成员C · Node）（14 用例 / 0 失败）

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
  PASS  分析任务进度显示画像构建和算法执行阶段
  PASS  降维结果渲染实际坐标、图例、指标和版本
  PASS  分类和聚类分析结果字段可展示

结果：14 通过, 0 失败
```

### 三层结果一致性（成员C · Python）（8 用例 / 0 失败）

```
--- test_e2e_consistency ---
test_frontend_ask_endpoint_roundtrip (test_e2e_consistency.TestE2EConsistency.test_frontend_ask_endpoint_roundtrip)
追问经前端反代往返正常。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261020_0001/ask HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "POST /api/tasks/task_20261020_0001/ask HTTP/1.1" 200 -
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
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0002/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20261020_0002/result HTTP/1.1" 200 -
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
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0003/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20261020_0003/result HTTP/1.1" 200 -
ok
test_three_layer_values_identical (test_e2e_consistency.TestE2EConsistency.test_three_layer_values_identical)
核心：Hadoop → Agent → 前端 三层数值完全一致。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0004 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0004 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0004 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0004/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20261020_0004/result HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261020_0004/result HTTP/1.1" 200 -
ok

----------------------------------------------------------------------
Ran 8 tests in 3.350s

OK
```
