# 系统测试报告（成员C）

- 生成时间：2026-10-21 13:42:39
- 运行环境：Python 3.10.12 · Node v22.23.2
- 用例总数：**291**，失败：**0**，结论：**通过**

## 一、测试范围与结果

| 测试块 | 负责人 | 用例数 | 失败数 | 结果 |
| --- | --- | ---: | ---: | :--: |
| Hadoop 清洗与评分（成员A） | 成员A | 7 | 0 | PASS |
| Agent 接口与调度（成员B） | 成员B | 248 | 0 | PASS |
| 前端渲染逻辑（成员C · Node） | 成员C | 28 | 0 | PASS |
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
test_every_split_has_both_classes (test_clean_snapshot.TestCleanSnapshot) ... skipped '清洗快照不在本机（data/<output_version>），跳过'
test_no_duplicate_pairs (test_clean_snapshot.TestCleanSnapshot) ... skipped '清洗快照不在本机（data/<output_version>），跳过'
test_no_invalid_rows (test_clean_snapshot.TestCleanSnapshot) ... skipped '清洗快照不在本机（data/<output_version>），跳过'
test_record_count_matches_iteration_one (test_clean_snapshot.TestCleanSnapshot) ... skipped '清洗快照不在本机（data/<output_version>），跳过'
test_split_counts_match_registered_expectation (test_clean_snapshot.TestCleanSnapshot) ... skipped '清洗快照不在本机（data/<output_version>），跳过'
test_split_windows_do_not_overlap (test_clean_snapshot.TestCleanSnapshot) ... skipped '清洗快照不在本机（data/<output_version>），跳过'
test_three_tables_present (test_clean_snapshot.TestCleanSnapshot) ... skipped '清洗快照不在本机（data/<output_version>），跳过'

----------------------------------------------------------------------
Ran 7 tests in 0.000s

OK (skipped=7)
```

### Agent 接口与调度（成员B）（248 用例 / 0 失败）

```
--- test_analysis_api ---
test_classification_model_not_found_sync (test_analysis_api.TestAnalysisApi) ... [agent] 127.0.0.1 - "POST /api/analysis/classification/tasks HTTP/1.1" 200 -
ok
test_clustering_dual_algorithm_e2e (test_analysis_api.TestAnalysisApi) ... [agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001/result HTTP/1.1" 200 -
ok
test_dimensionality_reduction_model_not_found (test_analysis_api.TestAnalysisApi) ... [agent] 127.0.0.1 - "POST /api/analysis/dimensionality-reduction/tasks HTTP/1.1" 200 -
ok
test_health_exposes_analysis (test_analysis_api.TestAnalysisApi) ... [agent] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_invalid_requests_sync (test_analysis_api.TestAnalysisApi) ... [agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
ok
test_single_algorithm_query_and_ask (test_analysis_api.TestAnalysisApi) ... [agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261021_0002/ask HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261021_0002/ask HTTP/1.1" 200 -
ok
test_task_list_exposes_task_type (test_analysis_api.TestAnalysisApi) ... [agent] 127.0.0.1 - "POST /api/analysis/clustering/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0003 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0003 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
ok

----------------------------------------------------------------------
Ran 7 tests in 2.507s

OK

--- test_analysis_runner ---
test_failure_keeps_completed_algorithm (test_analysis_runner.TestRunTask) ... ok
test_success_assembly (test_analysis_runner.TestRunTask) ... ok
test_crash_then_retry_success (test_analysis_runner.TestSubprocessProtocol) ... ok
test_missing_keys_rejected_as_contract_violation (test_analysis_runner.TestSubprocessProtocol) ... ok
test_persistent_failure_algorithm_error (test_analysis_runner.TestSubprocessProtocol) ... ok
test_required_envelope_keys_follow_task_type (test_analysis_runner.TestSubprocessProtocol) ... ok
test_semantic_failure_no_retry (test_analysis_runner.TestSubprocessProtocol) ... ok
test_success_attempt_1 (test_analysis_runner.TestSubprocessProtocol) ... ok
test_child_can_import_user_site_package (test_analysis_runner.TestToolSubprocessEnv)
端到端：`-I` 子进程里能否 import numpy（缺依赖则跳过，不伪装通过）。 ... ok
test_child_receives_clean_dir (test_analysis_runner.TestToolSubprocessEnv) ... ok
test_dependency_hint_is_actionable (test_analysis_runner.TestToolSubprocessEnv)
提示必须同时给出装依赖与加路径两条修法，并能用 ML_TOOL_EXTRA_PATH。 ... ok
test_extra_path_env_appended_without_duplicates (test_analysis_runner.TestToolSubprocessEnv) ... ok
test_missing_dependency_detected (test_analysis_runner.TestToolSubprocessEnv)
依赖缺失要从 stderr 里认出来（numpy/sklearn 两种写法）。 ... ok
test_real_missing_dependency_surfaces_actionable_error (test_analysis_runner.TestToolSubprocessEnv)
端到端：子进程真缺模块时，错误消息应含修法而不是只报"退出码 1"。 ... ok
test_tool_command_carries_user_site (test_analysis_runner.TestToolSubprocessEnv) ... ok
test_tool_command_keeps_isolation_flag (test_analysis_runner.TestToolSubprocessEnv) ... ok
test_tool_env_injects_clean_dir_from_analysis_config (test_analysis_runner.TestToolSubprocessEnv) ... ok
test_tool_env_never_overrides_explicit_clean_dir (test_analysis_runner.TestToolSubprocessEnv) ... ok

----------------------------------------------------------------------
Ran 18 tests in 0.544s

OK

--- test_api ---
test_ask_endpoint (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261021_0001/ask HTTP/1.1" 200 -
ok
test_ask_requires_question (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261021_0001/ask HTTP/1.1" 200 -
ok
test_bad_score_config (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_evaluate_only_leaves_after_null (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001/result HTTP/1.1" 200 -
ok
test_failure_at_before_has_no_partial (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001/result HTTP/1.1" 200 -
ok
test_failure_reports_stage_and_cause (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001/result HTTP/1.1" 200 -
ok
test_full_pipeline_success (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001/result HTTP/1.1" 200 -
ok
test_hadoop_down_fails_cleanly (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
ok
test_invalid_json_body_is_protocol_error (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 400 -
ok
test_list_and_health (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_missing_data_version (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_missing_prompt (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_result_before_completion (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001/result HTTP/1.1" 200 -
ok
test_unknown_path_404 (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "GET /api/nonexistent HTTP/1.1" 404 -
ok
test_unknown_task (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "GET /api/tasks/task_19700101_9999 HTTP/1.1" 200 -
ok
test_unregistered_data_version (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_unregistered_rule_version (test_api.TestAgentApi) ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok

----------------------------------------------------------------------
Ran 17 tests in 15.605s

OK

--- test_classification_features ---
test_default_basis_uses_train_snapshot (test_classification_features.TestLeakage) ... ok
test_future_events_do_not_change_past_features (test_classification_features.TestLeakage) ... ok
test_same_second_events_excluded (test_classification_features.TestLeakage)
同一秒的另一条评分（1::11::4::300）也不得参与该秒事件的特征。 ... ok
test_target_rating_not_in_own_features (test_classification_features.TestLeakage)
目标事件 Rating=5，但此前只有 1 分，用户均分应为 1.0。 ... ok
test_no_nan (test_classification_features.TestMatrixShape) ... ok
test_shape_and_labels (test_classification_features.TestMatrixShape) ... ok
test_split_counts (test_classification_features.TestMatrixShape) ... ok
test_matrix_counts_missing_rows (test_classification_features.TestMissingAttributes) ... ok
test_user_without_attrs_flagged (test_classification_features.TestMissingAttributes) ... ok
test_model_not_found (test_classification_features.TestModelMissing) ... ok
test_legacy_mapping_keeps_sub_code (test_classification_features.TestUnknownIds) ... ok
test_unknown_movie (test_classification_features.TestUnknownIds) ... ok
test_unknown_user (test_classification_features.TestUnknownIds) ... ok

----------------------------------------------------------------------
Ran 13 tests in 0.006s

OK

--- test_classification_integration ---
test_both_algorithms_registered (test_classification_integration.TestClassificationRegistration) ... ok
test_module_file_exists (test_classification_integration.TestClassificationRegistration) ... ok
test_classification_payload_has_algorithm_and_target (test_classification_integration.TestRunnerPayload) ... ok
test_clustering_payload_unchanged (test_classification_integration.TestRunnerPayload) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.004s

OK

--- test_classification_modeling ---
test_metrics_include_confusion_and_rate (test_classification_modeling.TestEvaluationShape) ... ok
test_all_negative_labels_do_not_crash (test_classification_modeling.TestThresholdPolicy) ... ok
test_positive_rate_constraint_is_applied (test_classification_modeling.TestThresholdPolicy) ... ok
test_separable_case_returns_sane_threshold (test_classification_modeling.TestThresholdPolicy) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.005s

OK

--- test_classification_tool ---
test_envelope_shape (test_classification_tool.TestEnvelope) ... ok
test_result_version_is_deterministic (test_classification_tool.TestEnvelope) ... ok
test_tool_error_is_converted (test_classification_tool.TestEnvelope) ... ok
test_data_version_mismatch (test_classification_tool.TestPayloadValidation) ... ok
test_feature_version_mismatch (test_classification_tool.TestPayloadValidation) ... ok
test_missing_algorithm (test_classification_tool.TestPayloadValidation) ... ok
test_missing_ids (test_classification_tool.TestPayloadValidation) ... ok
test_unknown_algorithm (test_classification_tool.TestPayloadValidation) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.007s

OK

--- test_dbscan_tool ---
test_default_eps_from_kdistance (test_dbscan_tool.TestDBScanTool) ... ok
test_envelope_contract (test_dbscan_tool.TestDBScanTool) ... ok
test_metrics_fields_and_determinism (test_dbscan_tool.TestDBScanTool) ... ok
test_min_samples_below_fit_users_errors (test_dbscan_tool.TestDBScanTool) ... ok
test_no_out_of_sample_projection (test_dbscan_tool.TestDBScanTool) ... ok
test_two_blobs_and_noise (test_dbscan_tool.TestDBScanTool) ... ok
test_unknown_user_and_invalid_param (test_dbscan_tool.TestDBScanTool) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.004s

OK

--- test_dimensionality_reduction ---
test_pca_invalid_parameter_exit_2 (test_dimensionality_reduction.TestCliProtocol) ... ok
test_tsne_unknown_parameter_exit_2 (test_dimensionality_reduction.TestCliProtocol) ... ok
test_empty_ok (test_dimensionality_reduction.TestDrParams) ... ok
test_non_numeric_rejected (test_dimensionality_reduction.TestDrParams) ... ok
test_out_of_range_rejected (test_dimensionality_reduction.TestDrParams) ... ok
test_unknown_key_rejected (test_dimensionality_reduction.TestDrParams) ... ok
test_valid_passthrough (test_dimensionality_reduction.TestDrParams) ... ok
test_components_orthonormal (test_dimensionality_reduction.TestPcaMath) ... ok
test_explained_variance_properties (test_dimensionality_reduction.TestPcaMath) ... ok
test_keep_dimensions_for_threshold (test_dimensionality_reduction.TestPcaMath) ... ok
test_loading_sign_convention_deterministic (test_dimensionality_reduction.TestPcaMath) ... ok
test_projection_reproduces_coords (test_dimensionality_reduction.TestPcaMath)
用 mean+components 手动投影，应与 fit 返回的 coords 一致（样本内）。 ... ok
test_target_dim_bounds (test_dimensionality_reduction.TestPcaMath) ... ok
test_too_few_users (test_dimensionality_reduction.TestPcaMath) ... ok
test_pca_tool_envelope_includes_comparison_and_coordinates (test_dimensionality_reduction.TestToolEnvelopes) ... ok
test_tsne_params_checked_before_numpy (test_dimensionality_reduction.TestToolEnvelopes)
报错语义（回归 test_tsne_unknown_parameter_exit_2）。 ... ok
test_tsne_tool_envelope_does_not_claim_explained_variance (test_dimensionality_reduction.TestToolEnvelopes) ... ok
test_deterministic_with_seed (test_dimensionality_reduction.TestTsneMath) ... ok
test_different_seed_differs (test_dimensionality_reduction.TestTsneMath) ... ok
test_fit_accepts_plain_lists (test_dimensionality_reduction.TestTsneMath)
不依赖调用方预转 numpy（工具边界要健壮）。 ... ok
test_knn_agreement_bounds (test_dimensionality_reduction.TestTsneMath) ... ok
test_knn_agreement_none_when_too_small (test_dimensionality_reduction.TestTsneMath) ... ok
test_perplexity_boundary_just_accepted (test_dimensionality_reduction.TestTsneMath) ... ok
test_perplexity_constraint (test_dimensionality_reduction.TestTsneMath) ... ok
test_student_t_gradient_matches_finite_difference (test_dimensionality_reduction.TestTsneMath) ... ok
test_student_t_probabilities_use_pairwise_distances (test_dimensionality_reduction.TestTsneMath) ... ok
test_too_few_users (test_dimensionality_reduction.TestTsneMath) ... ok
test_pca_projects_out_of_sample_cold_user (test_dimensionality_reduction.TestWithSnapshot) ... ok
test_pca_unknown_user_reported_not_faked (test_dimensionality_reduction.TestWithSnapshot) ... ok
test_tsne_does_not_project_out_of_sample (test_dimensionality_reduction.TestWithSnapshot) ... ok

----------------------------------------------------------------------
Ran 30 tests in 0.892s

OK

--- test_explainer ---
test_dimension_question_uses_real_numbers (test_explainer.TestAnswerRouting) ... ok
test_isolation_not_fix (test_explainer.TestAnswerRouting) ... ok
test_limitations_question (test_explainer.TestAnswerRouting) ... ok
test_no_fabricated_numbers (test_explainer.TestAnswerRouting) ... ok
test_unmatched_falls_back_to_summary (test_explainer.TestAnswerRouting) ... ok
test_version_question (test_explainer.TestAnswerRouting) ... ok
test_weights_question (test_explainer.TestAnswerRouting) ... ok
test_failed_record_explains_stage_and_guidance (test_explainer.TestNonSuccessRecords) ... ok
test_failed_with_partial_result (test_explainer.TestNonSuccessRecords) ... ok
test_pending_record (test_explainer.TestNonSuccessRecords) ... ok
test_running_record (test_explainer.TestNonSuccessRecords) ... ok
test_summarize_no_cleaning_shows_null_note (test_explainer.TestSummarize) ... ok

----------------------------------------------------------------------
Ran 12 tests in 0.001s

OK

--- test_hadoop_tool ---
test_business_failure_translated_to_exception (test_hadoop_tool.TestHadoopTool) ... ok
test_clean_dataset_success (test_hadoop_tool.TestHadoopTool) ... ok
test_clean_failure_keeps_stage_and_code (test_hadoop_tool.TestHadoopTool) ... ok
test_connection_refused_gives_guidance (test_hadoop_tool.TestHadoopTool) ... ok
test_health (test_hadoop_tool.TestHadoopTool) ... ok
test_health_never_raises (test_hadoop_tool.TestHadoopTool) ... ok
test_quality_score_after_success (test_hadoop_tool.TestHadoopTool) ... ok
test_quality_score_before_success (test_hadoop_tool.TestHadoopTool) ... ok
test_read_state_after_calls (test_hadoop_tool.TestHadoopTool) ... ok
test_read_state_does_not_write (test_hadoop_tool.TestHadoopTool) ... ok
test_read_state_missing_returns_none (test_hadoop_tool.TestHadoopTool) ... ok
test_require_keys_missing (test_hadoop_tool.TestHadoopTool) ... ok
test_require_scores_allows_none_values (test_hadoop_tool.TestHadoopTool) ... ok
test_require_scores_missing_dimension (test_hadoop_tool.TestHadoopTool) ... ok
test_state_path_normal (test_hadoop_tool.TestHadoopTool) ... ok
test_task_id_path_traversal_blocked (test_hadoop_tool.TestHadoopTool) ... ok

----------------------------------------------------------------------
Ran 16 tests in 8.530s

OK

--- test_kmeans_tool ---
test_blob_assignment_and_honest_statuses (test_kmeans_tool.TestKMeansTool) ... ok
test_determinism_and_result_version_stability (test_kmeans_tool.TestKMeansTool) ... ok
test_envelope_contract (test_kmeans_tool.TestKMeansTool) ... ok
test_explicit_k_fixes_candidates (test_kmeans_tool.TestKMeansTool) ... ok
test_invalid_parameter_range_and_key (test_kmeans_tool.TestKMeansTool) ... ok
test_metrics_and_definitions (test_kmeans_tool.TestKMeansTool) ... ok
test_no_targets_invalid_request (test_kmeans_tool.TestKMeansTool) ... ok
test_summaries_real_stats (test_kmeans_tool.TestKMeansTool) ... ok
test_unknown_user (test_kmeans_tool.TestKMeansTool) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.007s

OK

--- test_metrics ---
test_centroid (test_metrics.TestBasics) ... ok
test_euclid_equals_math_dist (test_metrics.TestBasics) ... ok
test_sse_skips_noise (test_metrics.TestBasics) ... ok
test_coincident_centroids_none (test_metrics.TestDaviesBouldin) ... ok
test_null_centroid_none (test_metrics.TestDaviesBouldin) ... ok
test_single_cluster_none (test_metrics.TestDaviesBouldin) ... ok
test_symmetric_two_clusters_positive (test_metrics.TestDaviesBouldin) ... ok
test_definitions_registered (test_metrics.TestDefinitions) ... ok
test_deterministic_and_sorted (test_metrics.TestSample) ... ok
test_full_when_size_ge_n (test_metrics.TestSample) ... ok
test_seed_formula_stability (test_metrics.TestSample) ... ok
test_noise_excluded (test_metrics.TestSilhouette) ... ok
test_sampled_matches_full_when_sample_is_all (test_metrics.TestSilhouette) ... ok
test_sampled_single_cluster_none (test_metrics.TestSilhouette) ... ok
test_single_cluster_returns_none (test_metrics.TestSilhouette) ... ok
test_singleton_convention_zero (test_metrics.TestSilhouette) ... ok
test_two_clean_blobs_positive (test_metrics.TestSilhouette) ... ok

----------------------------------------------------------------------
Ran 17 tests in 0.001s

OK

--- test_parser ---
test_default_prompt_full_pipeline (test_parser.TestBuildPlan) ... ok
test_evaluate_only (test_parser.TestBuildPlan) ... ok
test_focus_dimensions (test_parser.TestBuildPlan) ... ok
test_no_keyword_falls_back_to_default (test_parser.TestBuildPlan) ... ok
test_prompt_version_used_when_request_missing (test_parser.TestBuildPlan) ... ok
test_score_config_passthrough (test_parser.TestBuildPlan) ... ok
test_versions_from_prompt_recorded_but_request_wins (test_parser.TestBuildPlan) ... ok
test_absent (test_parser.TestDetectVersions) ... ok
test_clean_version_regex (test_parser.TestDetectVersions) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.000s

OK

--- test_profiler ---
test_cache_reuse_when_inputs_unchanged (test_profiler.TestProfile) ... ok
test_determinism_same_input (test_profiler.TestProfile) ... ok
test_feature_values_hand_check (test_profiler.TestProfile) ... ok
test_global_mean_hand_check (test_profiler.TestProfile) ... ok
test_insufficient_user (test_profiler.TestProfile) ... ok
test_missing_snapshot_raises_data_unavailable (test_profiler.TestProfile) ... ok
test_no_ratings_user (test_profiler.TestProfile) ... ok
test_orphans_registered_not_dropped (test_profiler.TestProfile) ... ok
test_scaler_fitted_on_ok_users_only (test_profiler.TestProfile) ... ok
test_status_counts (test_profiler.TestProfile) ... ok
test_t1_boundary_only_training_window (test_profiler.TestProfile) ... ok

----------------------------------------------------------------------
Ran 11 tests in 0.005s

OK

--- test_registry_router ---
test_algorithm_names_single_source (test_registry_router.TestRegistry) ... ok
test_category_slugs (test_registry_router.TestRegistry) ... ok
test_require_registered (test_registry_router.TestRegistry) ... ok
test_require_unregistered_model_not_found (test_registry_router.TestRegistry) ... ok
test_tool_naming_convention (test_registry_router.TestRegistry) ... ok
test_all_unknown_users_rejected_at_creation (test_registry_router.TestRouter) ... ok
test_body_algorithm_field_authoritative (test_registry_router.TestRouter) ... ok
test_category_consistency_guidance (test_registry_router.TestRouter) ... ok
test_classification_plan_with_target (test_registry_router.TestRouter) ... ok
test_classification_requires_movie_id (test_registry_router.TestRouter) ... ok
test_default_runs_both_algorithms (test_registry_router.TestRouter) ... ok
test_dimensionality_reduction_defaults_to_registered_population (test_registry_router.TestRouter) ... ok
test_no_users_invalid_request (test_registry_router.TestRouter) ... ok
test_parameters_pruned_per_algorithm (test_registry_router.TestRouter) ... ok
test_partial_unknown_filtered_with_note (test_registry_router.TestRouter) ... ok
test_query_algorithm_keywords (test_registry_router.TestRouter) ... ok
test_query_length_cap (test_registry_router.TestRouter) ... ok
test_query_user_extraction_and_body_priority (test_registry_router.TestRouter) ... ok
test_unregistered_algorithm_model_not_found (test_registry_router.TestRouter) ... ok
test_user_ids_must_be_list (test_registry_router.TestRouter) ... ok
test_version_mismatches (test_registry_router.TestRouter) ... ok

----------------------------------------------------------------------
Ran 21 tests in 0.019s

OK

--- test_result_builder ---
test_before_only_has_nulls_not_zeros (test_result_builder.TestBuild) ... ok
test_clean_done_but_after_failed (test_result_builder.TestBuild) ... ok
test_full_result_contract_fields (test_result_builder.TestBuild) ... ok
test_missing_before_raises (test_result_builder.TestBuild) ... ok
test_problems_and_unresolved (test_result_builder.TestBuild) ... ok
test_report_structure (test_result_builder.TestBuild) ... ok
test_score_change_arithmetic (test_result_builder.TestBuild) ... ok
test_statistics_passthrough (test_result_builder.TestBuild) ... ok
test_versions_and_time_boundaries (test_result_builder.TestBuild) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.001s

OK

--- test_schemas ---
test_cap_20000 (test_schemas.TestNormalizeTargets) ... ok
test_dedupe_sort_and_str (test_schemas.TestNormalizeTargets) ... ok
test_garbage_and_nonpositive (test_schemas.TestNormalizeTargets) ... ok
test_missing_both (test_schemas.TestNormalizeTargets) ... ok
test_non_list_user_ids (test_schemas.TestNormalizeTargets) ... ok
test_envelope_required_fields_doc_sync (test_schemas.TestToolName) ... ok
test_all_unknown_is_request_level_error (test_schemas.TestUserStatuses) ... ok
test_partial_unknown_returns_split (test_schemas.TestUserStatuses) ... ok
test_bool_not_number (test_schemas.TestValidateParameters) ... ok
test_out_of_range_rejected (test_schemas.TestValidateParameters) ... ok
test_passthrough_subset (test_schemas.TestValidateParameters) ... ok
test_string_number_rejected (test_schemas.TestValidateParameters) ... ok
test_unknown_key_rejected (test_schemas.TestValidateParameters) ... ok

----------------------------------------------------------------------
Ran 13 tests in 0.004s

OK

--- test_split ---
test_missing_snapshot_raises (test_split.TestDataUnavailable) ... ok
test_positive_rate_matches_definition (test_split.TestLabelRule) ... ok
test_rating_four_and_five_are_positive (test_split.TestLabelRule) ... ok
test_rating_three_is_negative (test_split.TestLabelRule) ... ok
test_split_version_declared (test_split.TestRulesSource) ... ok
test_time_bounds_from_rules (test_split.TestRulesSource) ... ok
test_epoch_equal_t1_is_train (test_split.TestSplitBoundary) ... ok
test_epoch_equal_t2_is_validate (test_split.TestSplitBoundary) ... ok
test_one_second_after_t1_is_validate (test_split.TestSplitBoundary) ... ok
test_one_second_after_t2_is_test (test_split.TestSplitBoundary) ... ok
test_one_second_before_t1_is_train (test_split.TestSplitBoundary) ... ok
test_sets_do_not_overlap (test_split.TestSplitBoundary) ... ok
test_counts_and_unique_sets (test_split.TestSummaryShape) ... ok
test_ratios_sum_to_one (test_split.TestSummaryShape) ... ok
test_time_range_per_split (test_split.TestSummaryShape) ... ok

----------------------------------------------------------------------
Ran 15 tests in 0.001s

OK

--- test_store ---
test_create_then_pending (test_store.TestTaskStore) ... ok
test_illegal_transition_rejected (test_store.TestTaskStore) ... ok
test_legal_transitions (test_store.TestTaskStore) ... ok
test_new_task_id_format (test_store.TestTaskStore) ... ok
test_persistence_and_restart_marks_interrupted (test_store.TestTaskStore) ... ok
test_queue_position (test_store.TestTaskStore) ... ok
test_result_file_written (test_store.TestTaskStore) ... ok
test_terminal_is_frozen (test_store.TestTaskStore) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.005s

OK
```

### 前端渲染逻辑（成员C · Node）（28 用例 / 0 失败）

```
--- test_render.mjs ---
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

--- test_render_contract.mjs ---
前端渲染契约测试（真实字段驱动） (tests/frontend/test_render_contract.mjs)

  PASS  聚类：群体归属按 status 判定，噪声/历史不足不再整列 "—"
  PASS  聚类：历史不足用户单列并可显示 note 原文与"可靠性低"徽标
  PASS  聚类：群体摘要用真实统计字段拼装（不再找 summary/preference_summary/explanation）
  PASS  聚类：代表性作品必须渲染（此前完全缺失）
  PASS  聚类：summary_basis 口径原文必须可见
  PASS  聚类：整体渲染不出现 "—" 占位（不把"未执行"当"读不出来"）
  PASS  聚类：null 指标显示"不适用"，不补 0
  PASS  分类：评价指标不再渲染成原始 JSON 字符串
  PASS  分类：正类概率旁必须带"未经校准"说明
  PASS  分类：单条预测的限制与目标 user/movie 均可见
  PASS  实验对照：数据切分方式必须展示（需求第 6 项）
  PASS  降维：主成分载荷表必须渲染（轴含义依据）
  PASS  降维：仍保留二维图与聚类前后对照
  PASS  结果获取：分析任务必须有样例区与报告/追溯区（需求第 8 项）

结果：14 通过, 0 失败
```

### 三层结果一致性（成员C · Python）（8 用例 / 0 失败）

```
--- test_e2e_consistency ---
test_frontend_ask_endpoint_roundtrip (test_e2e_consistency.TestE2EConsistency)
追问经前端反代往返正常。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0001 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "POST /api/tasks/task_20261021_0001/ask HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "POST /api/tasks/task_20261021_0001/ask HTTP/1.1" 200 -
ok
test_frontend_proxy_forwards_health (test_e2e_consistency.TestE2EConsistency)
前端 /health 反代到 Agent，证明三层连通。 ... [agent] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_frontend_proxy_forwards_task_errors (test_e2e_consistency.TestE2EConsistency)
异常测试：非法 data_version 的错误经前端透传，前端可展示。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
ok
test_frontend_proxy_reports_backend_down (test_e2e_consistency.TestE2EConsistency)
异常测试：Agent 不可用时前端不应崩溃，应返回可解析的错误 JSON。 ... [frontend] 127.0.0.1 - "GET /health HTTP/1.1" 200 -
ok
test_frontend_sees_null_not_zero_for_evaluate_only (test_e2e_consistency.TestE2EConsistency)
只评估不清洗：after 必须为 null，前端应渲染占位符而非 0。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0002 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0002/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20261021_0002/result HTTP/1.1" 200 -
ok
test_frontend_static_assets_served (test_e2e_consistency.TestE2EConsistency)
前端服务能正确托管页面与三类静态资源。 ... [frontend] 127.0.0.1 - "GET / HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /style.css HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /js/api.js HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /js/render.js HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /js/app.js HTTP/1.1" 200 -
ok
test_no_numbers_before_completion (test_e2e_consistency.TestE2EConsistency)
任务未完成时前端出口不得返回任何数值（接口规范第 2.2 节）。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0003/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20261021_0003/result HTTP/1.1" 200 -
ok
test_three_layer_values_identical (test_e2e_consistency.TestE2EConsistency)
核心：Hadoop → Agent → 前端 三层数值完全一致。 ... [agent] 127.0.0.1 - "POST /api/tasks HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0004 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0004 HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0004/result HTTP/1.1" 200 -
[frontend] 127.0.0.1 - "GET /api/tasks/task_20261021_0004/result HTTP/1.1" 200 -
[agent] 127.0.0.1 - "GET /api/tasks/task_20261021_0004/result HTTP/1.1" 200 -
ok

----------------------------------------------------------------------
Ran 8 tests in 1.091s

OK
```
