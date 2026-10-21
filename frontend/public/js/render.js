/* MovieLens 数据治理 Agent —— 渲染层（成员C）
 *
 * 只负责把接口返回的 JSON 转成 DOM，不做任何计算/编造。
 * 所有数值均来自接口；缺失值（null/undefined）统一显示为 "—"，
 * 不显示 0，以免把"未执行"误呈现为"得分为 0"。
 */

const Render = (function () {
  'use strict';

  const DIMS = [
    { key: 'accurate', cn: '准确性', en: 'Accurate' },
    { key: 'complete', cn: '完整性', en: 'Complete' },
    { key: 'unique', cn: '唯一性', en: 'Unique' },
    { key: 'up_to_date', cn: '时效性', en: 'Up-to-date' },
    { key: 'consistent', cn: '一致性', en: 'Consistent' }
  ];

  const STATUS_CN = {
    PENDING: '排队中', RUNNING: '运行中', SUCCESS: '已完成', FAILED: '失败'
  };

  const STAGES = [
    { key: 'PARSE_REQUEST', cn: '解析需求' },
    { key: 'PROFILE_BUILD', cn: '构建用户画像' },
    { key: 'CLUSTER_FIT', cn: '运行分析算法' },
    { key: 'BEFORE_SCORE', cn: '清洗前评分' },
    { key: 'CLEANING', cn: '数据清洗' },
    { key: 'AFTER_SCORE', cn: '清洗后评分' },
    { key: 'GENERATE_REPORT', cn: '生成报告' },
    { key: 'COMPLETED', cn: '完成' }
  ];

  const ACTION_CN = { fix: '修复', dedupe: '去重', isolate: '隔离', keep: '保留' };
  const SEV_CN = { high: '高', medium: '中', low: '低', info: '提示' };

  function $(sel, root) { return (root || document).querySelector(sel); }

  function num(v) {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'number') {
      return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toFixed(2);
    }
    return String(v);
  }

  function raw(v) { return (v === null || v === undefined) ? '—' : v; }

  // ---------- 分析结果格式化（成员C，依据成员B联调说明 §5） ----------
  // 数值格式化：不做任何推算，只改变呈现精度；缺失值仍显示 "—"
  function fixed(v, digits) {
    if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
    return v.toFixed(digits === undefined ? 2 : digits);
  }

  function pct(v, digits) {
    if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
    return (v * 100).toFixed(digits === undefined ? 1 : digits) + '%';
  }

  function intNum(v) {
    if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
    return Math.round(v).toLocaleString('en-US');
  }

  // 标签中文化：聚类 assignments[].status（联调说明 §5 枚举）
  const ASSIGN_STATUS_CN = {
    SUCCESS: '正常归属',
    ASSIGNED_FROM_FITTED_CENTROIDS: '样本外投影（基于拟合质心）',
    INSUFFICIENT_HISTORY: '历史不足',
    NO_TRAIN_HISTORY: '训练期无记录',
    UNASSIGNED_BY_DENSITY: '密度噪声点'
  };

  // 分类评价指标中文化（键名来自真实分类信封 results[i].metrics）
  const CLASS_METRIC_CN = [
    ['threshold', '决策阈值', '验证期选定的正类判定阈值'],
    ['valid_roc_auc', '验证期 ROC-AUC', 'T1 < ts <= T2 上的 ROC-AUC'],
    ['valid_pr_auc', '验证期 PR-AUC', 'T1 < ts <= T2 上的 PR-AUC'],
    ['test_roc_auc', '测试期 ROC-AUC', 'ts > T2 上的 ROC-AUC（方案冻结后计算）'],
    ['test_pr_auc', '测试期 PR-AUC', 'ts > T2 上的 PR-AUC（方案冻结后计算）']
  ];

  // 聚类 metrics 里的标量键中文化（键名来自真实聚类信封 metrics）
  const CLUSTER_METRIC_CN = [
    ['silhouette_full', '全量轮廓系数', 4],
    ['davies_bouldin_full', '全量 Davies-Bouldin 指数', 4],
    ['sse_full', '全量簇内平方误差和 SSE', 2],
    ['k_selected', '选定簇数 k', 0],
    ['n_fit_users', '拟合用户数', 0],
    ['n_non_fit_reference', '非拟合参考用户数', 0],
    ['eps_used', 'DBSCAN eps', 4],
    ['eps_method', 'eps 选择方法', null],
    ['noise_ratio', '噪声点占比', 4]
  ];

  // 键值网格（用于指标；null 明确标"不适用"，绝不补 0）
  function kvGrid(items) {
    return `<div class="meta-grid">${items.map(([k, v, hint]) =>
      `<div class="meta-item"><div class="k">${esc(k)}</div>
       <div class="v">${esc(v === null || v === undefined || v === '' ? '不适用' : v)}</div>
       ${hint ? `<div class="k hint">${esc(hint)}</div>` : ''}</div>`
    ).join('')}</div>`;
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ---------- 状态区 ----------
  function status(resp) {
    const badge = $('#statusBadge');
    badge.textContent = STATUS_CN[resp.status] || resp.status;
    badge.className = 'badge ' + (resp.status || 'PENDING');
    $('#statusMsg').textContent = resp.message || '';

    // 阶段进度条
    const box = $('#stageBox');
    if (resp.status === 'PENDING' || resp.status === 'SUCCESS' || resp.status === 'FAILED') {
      // 完成/失败/排队时也照常渲染，便于看清走到哪一步
    }
    const cur = resp.stage;
    const curIdx = STAGES.findIndex(s => s.key === cur);
    box.innerHTML = STAGES.map((s, i) => {
      let cls = 'stage-chip';
      if (resp.status === 'SUCCESS') cls += ' done';
      else if (curIdx >= 0) {
        if (i < curIdx) cls += ' done';
        else if (i === curIdx) cls += ' active';
      }
      return `<span class="${cls}">${esc(s.cn)}</span>`;
    }).join('');

    // 任务元信息
    const meta = $('#metaGrid');
    const items = [
      ['任务 ID', raw(resp.task_id)],
      ['任务类型', raw(resp.task_type)],
      ['状态', STATUS_CN[resp.status] || raw(resp.status)],
      ['当前阶段', cur ? (STAGES.find(s => s.key === cur) || {}).cn || cur : '—']
    ];
    if (resp.queue_position !== undefined && resp.queue_position !== null) {
      items.push(['队列位置', raw(resp.queue_position)]);
    }
    meta.innerHTML = items.map(([k, v]) =>
      `<div class="meta-item"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`
    ).join('');
  }

  // ---------- 五维评分表 ----------
  function scores(result) {
    const before = result.before_score || {};
    const after = result.after_score || {};
    const change = result.score_change || {};
    const tbody = $('#scoreBody');

    tbody.innerHTML = DIMS.map(d => {
      const b = before[d.key];
      const a = after[d.key];
      let delta = change[d.key];
      if (delta === undefined || delta === null) {
        if (typeof b === 'number' && typeof a === 'number') delta = a - b;
        else delta = null;
      }
      let dcls = 'flat', dtext = '—';
      if (typeof delta === 'number') {
        dcls = delta > 0.0001 ? 'up' : (delta < -0.0001 ? 'down' : 'flat');
        dtext = (delta > 0 ? '+' : '') + delta.toFixed(4);
      }
      const barPct = typeof a === 'number' ? Math.max(0, Math.min(100, a)) : 0;
      return `<tr>
        <td><span class="dim-name">${d.en}</span><span class="cn">${d.cn}</span></td>
        <td>${num(b)}</td>
        <td>${num(a)}</td>
        <td class="delta ${dcls}">${esc(dtext)}</td>
        <td style="width:22%"><div class="bar-wrap"><div class="bar" style="width:${barPct}%"></div></div></td>
      </tr>`;
    }).join('');

    // 综合分（若接口提供）
    const overallRow = $('#overallRow');
    const ob = before.overall, oa = after.overall;
    if (typeof ob === 'number' || typeof oa === 'number') {
      const oc = (typeof ob === 'number' && typeof oa === 'number') ? oa - ob : null;
      let dcls = 'flat', dtext = '—';
      if (oc !== null) {
        dcls = oc > 0.0001 ? 'up' : (oc < -0.0001 ? 'down' : 'flat');
        dtext = (oc > 0 ? '+' : '') + oc.toFixed(4);
      }
      overallRow.classList.remove('hidden');
      $('#overallBody').innerHTML = `<tr class="overall-row">
        <td>综合分（加权）</td><td>${num(ob)}</td><td>${num(oa)}</td>
        <td class="delta ${dcls}">${esc(dtext)}</td><td></td></tr>`;
    } else {
      overallRow.classList.add('hidden');
    }

    // 方法/权重/时间边界
    const w = result.weights || (result.report && result.report.method && result.report.method.weights) || {};
    $('#methodNote').innerHTML = result.report && result.report.method && result.report.method.summary
      ? `<b>评价方法：</b>${esc(result.report.method.summary)}<br>
         <b>权重：</b>${DIMS.map(d => d.cn + ' ' + (w[d.key] !== undefined ? w[d.key] : '—')).join(' · ')}`
      : '';
  }

  // ---------- 元信息（版本 / T1T2） ----------
  function versions(result) {
    const items = [
      ['数据版本', raw(result.data_version)],
      ['规则版本', raw(result.rule_version)],
      ['Time T1（训练期截止）', raw(result.T1)],
      ['Time T2（验证期截止）', raw(result.T2)]
    ];
    if (result.split_rule) items.push(['切分规则', raw(result.split_rule)]);
    $('#versionGrid').innerHTML = items.map(([k, v]) =>
      `<div class="meta-item"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`
    ).join('');
  }

  // ---------- 清洗统计 ----------
  function statistics(result) {
    const s = result.statistics || {};
    const items = [
      ['原始数据量', s.before_count],
      ['清洗后数据量', s.after_count],
      ['修复', s.fixed_count],
      ['去重', s.deduplicated_count],
      ['隔离', s.isolated_count]
    ];
    if (s.conflict_key_count !== undefined) {
      items.push(['未解决冲突主键', s.conflict_key_count]);
    }
    $('#statGrid').innerHTML = items.map(([k, v]) =>
      `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(num(v))}</div></div>`
    ).join('');

    // 分表统计（若接口提供 per_table）
    const pt = s.per_table;
    const ptBox = $('#perTableBox');
    if (pt && typeof pt === 'object') {
      const rows = Object.keys(pt).map(tbl => {
        const r = pt[tbl] || {};
        return `<tr><td>${esc(tbl)}</td>
          <td>${esc(num(r.input))}</td>
          <td>${esc(num(r.after))}</td>
          <td>${esc(num(r.fixed))}</td>
          <td>${esc(num(r.deduped))}</td>
          <td>${esc(num(r.isolated))}</td></tr>`;
      }).join('');
      ptBox.classList.remove('hidden');
      $('#perTableBody').innerHTML = rows;
    } else {
      ptBox.classList.add('hidden');
    }
  }

  // ---------- 问题与处置 ----------
  function problems(result) {
    const list = result.problems || [];
    const box = $('#problemBox');
    if (!list.length) {
      box.innerHTML = '<p style="color:var(--muted);font-size:13px">本次结果未返回问题明细。</p>';
    } else {
      box.innerHTML = list.map(p => `
        <div class="problem">
          <div class="head">
            <span class="tag ${esc(p.action)}">${esc(ACTION_CN[p.action] || p.action)}</span>
            <span class="tag sev-${esc(p.severity)}">严重度 ${esc(SEV_CN[p.severity] || p.severity)}</span>
            <span>${esc(p.subject)}</span>
            <span style="color:var(--muted);font-weight:400">× ${esc(num(p.count))}</span>
          </div>
          <div class="reason">${esc(p.reason)}</div>
        </div>`).join('');
    }

    // 未解决问题（单独强调）
    const un = result.unresolved_problems || [];
    const unBox = $('#unresolvedBox');
    const unCount = $('#unresolvedCount');
    unCount.textContent = String(un.length);
    if (!un.length) {
      unBox.innerHTML = '<p style="color:var(--muted);font-size:13px">接口未返回未解决问题列表。</p>';
    } else {
      unBox.innerHTML = un.map(p => `
        <div class="problem" style="border-left-color:var(--warn)">
          <div class="head">
            <span class="tag ${esc(p.action)}">${esc(ACTION_CN[p.action] || p.action)}</span>
            <span>${esc(p.subject)}</span>
            <span style="color:var(--muted);font-weight:400">× ${esc(num(p.count))}</span>
          </div>
          <div class="reason">${esc(p.reason)}</div>
        </div>`).join('');
    }
  }

  // ---------- 评估报告 ----------
  function report(result) {
    const r = result.report || {};
    const box = $('#reportBox');

    let html = '';

    if (r.improvements && r.improvements.length) {
      html += '<h3>改善项（清洗前后变化）</h3><ul>';
      html += r.improvements.map(x =>
        `<li><span class="topic">${esc(x.dimension_cn || x.dimension)}</span>：${esc(x.description)}</li>`
      ).join('');
      html += '</ul>';
    }

    if (r.unresolved && r.unresolved.length) {
      html += '<h3>未解决问题</h3><ul>';
      html += r.unresolved.map(x =>
        `<li><span class="topic">${esc(x.subject)}</span>：${esc(x.disposition || x.reason || '')}</li>`
      ).join('');
      html += '</ul>';
    }

    if (r.limitations && r.limitations.length) {
      html += '<h3>评价局限（哪些情况无法验证）</h3><ul>';
      html += r.limitations.map(x =>
        `<li><span class="topic">${esc(x.topic)}</span>：${esc(x.detail || '')}</li>`
      ).join('');
      html += '</ul>';
    }

    box.innerHTML = html || '<p style="color:var(--muted);font-size:13px">接口未返回评估报告。</p>';
  }

  // ---------- 数据样例 ----------
  function sample(result) {
    // 样例来自 result.sample（若成员B/ A 提供）；否则明确标注不可得，绝不编造
    const box = $('#sampleBox');
    const s = result.sample || result.clean_sample;
    if (!s || (Array.isArray(s) && !s.length)) {
      box.innerHTML = '<p style="color:var(--muted);font-size:13px">本次接口未返回清洗后数据样例。清洗后数据可在 Hadoop 输出目录查看。</p>';
      return;
    }
    // 支持 [{table, columns, rows}]
    if (Array.isArray(s) && s.length && s[0].columns) {
      box.innerHTML = s.map(block => `
        <div style="margin-bottom:12px">
          <div style="font-size:12px;color:var(--muted);margin:6px 0">${esc(block.table || '')}</div>
          <table class="sample-table">
            <thead><tr>${block.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
            <tbody>${(block.rows || []).map(r =>
              `<tr>${r.map(c => `<td class="mono">${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>
          </table>
        </div>`).join('');
      return;
    }
    box.innerHTML = '<p style="color:var(--muted);font-size:13px">样例数据格式未识别。</p>';
  }

  function display(value) {
    if (value === null || value === undefined || value === '') return '—';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }

    function analysis(result) {
      const meta = [
        ['任务类型', result.task_type],
        ['数据版本', result.data_version],
        ['画像版本', result.profile_version],
        ['T1（训练期截止）', result.T1],
        ['T2（验证期截止）', result.T2],
        ['任务状态', result.status]
      ];
      // 仅在接口给出时才展示的附加元信息（不编造）
      if (result.analysis_version) meta.push(['分析口径版本', result.analysis_version]);
      if (result.requested_user_ids && result.requested_user_ids.length) {
        meta.push(['本次覆盖用户数', result.requested_user_ids.length]);
      }
      $('#analysisMeta').innerHTML = meta.map(([k, v]) =>
        `<div class="meta-item"><div class="k">${esc(k)}</div><div class="v">${esc(display(v))}</div></div>`
      ).join('');

      const entries = normalizeEntries(result);
      if (!entries.length) {
        $('#analysisResults').innerHTML =
          '<p class="sub">任务没有返回已完成的算法结果；请检查任务状态和失败原因。</p>';
        $('#analysisSample').innerHTML = '';
        $('#analysisReport').innerHTML = '';
        return;
      }
      $('#analysisResults').innerHTML = entries.map((entry, index) =>
        analysisEntry(entry, index, result.task_type, result)
      ).join('');

      // 结果获取（需求第 8 项）：样例 + 报告 + 图表说明
      $('#analysisSample').innerHTML = analysisSample(result, entries);
      $('#analysisReport').innerHTML = analysisReport(result, entries);
    }

    // 兼容两种真实信封层级：
    //   ① 任务级：results[] 为算法信封，信封内 predictions 为预测列表
    //      （聚类/降维任务级信封、成员B联调说明 §5）
    //   ② 算法级：results[] 本身就是预测列表，算法字段在顶层
    //      （docs/迭代二/交付/分类结果样例.json）
    // 判断依据是结构本身，不做字段名猜测；两种情况都不改数值。
    function normalizeEntries(result) {
      const list = Array.isArray(result.results) ? result.results : [];
      if (!list.length) return [];
      const looksPrediction = p => p && typeof p === 'object' &&
        ('predicted_class' in p || 'positive_probability' in p || 'decision_score' in p);
      const isAlgorithmLevel = list.every(looksPrediction);
      if (isAlgorithmLevel) {
        const envelope = {};
        Object.keys(result).forEach(k => { if (k !== 'results') envelope[k] = result[k]; });
        envelope.results = null;           // 占位，下面重建
        envelope.predictions = list;       // 预测列表挂在信封上
        // 用第一个预测补齐算法级字段（多为同名同值字段）
        const p0 = list[0];
        ['algorithm_name', 'algorithm', 'algorithm_tool', 'model_version',
         'result_version', 'parameters', 'limitations', 'created_at'].forEach(k => {
          if (envelope[k] === undefined && p0[k] !== undefined) envelope[k] = p0[k];
        });
        envelope.results = list;
        return [envelope];
      }
      return list;
    }

    // 预测列表：兼容 predictions（任务级信封）与 results（算法级信封）
    function predictionsOf(entry) {
      if (Array.isArray(entry.predictions)) return entry.predictions;
      if (Array.isArray(entry.results)) return entry.results;
      return [];
    }

  // 数据切分方式（需求第 6 项；口径原文依据《迭代二数据与实验规范 §二》）
  function splitBanner(entry, task) {
    const split = entry.split_version || task.split_version || 'split-v1';
    const feat = entry.feature_version || task.feature_version || 'profile-v1';
    const data = entry.data_version || task.data_version;
    const rule = entry.cleaning_rule_version || task.cleaning_rule_version;
    const t1 = entry.T1 !== undefined ? entry.T1 : task.T1;
    const t2 = entry.T2 !== undefined ? entry.T2 : task.T2;
    // 分类/降维信封里的 T1/T2 是 epoch，任务级是日期字符串；两者都如实展示
    const t1Text = typeof t1 === 'number' ? `${t1}（epoch 秒）` : (t1 || '—');
    const t2Text = typeof t2 === 'number' ? `${t2}（epoch 秒）` : (t2 || '—');
    const items = [
      ['数据切分版本', split],
      ['训练集', `Timestamp <= T1（T1 = ${t1Text}）`],
      ['验证集', `T1 < Timestamp <= T2（T2 = ${t2Text}）`],
      ['测试集', 'Timestamp > T2'],
      ['特征/画像版本', feat]
    ];
    if (rule) items.push(['清洗规则版本', rule]);
    items.push(['数据版本', data]);
    return `<div class="split-banner">
      <div class="split-title">数据切分方式（口径：训练期拟合 / 验证期选参 / 测试期最终评价）</div>
      <div class="meta-grid">${items.map(([k, v]) =>
        `<div class="meta-item"><div class="k">${esc(k)}</div><div class="v">${esc(display(v))}</div></div>`
      ).join('')}</div></div>`;
  }

    function analysisEntry(entry, index, taskType, task) {
    // 标题优先级：algorithm_name → algorithm → algorithm_tool（工具名放最后，避免只显示内部名）
    const title = entry.algorithm_name || entry.algorithm || entry.algorithm_tool
      || `算法 ${index + 1}`;
    let html = `<article class="analysis-entry">
      <h3>${esc(title)}</h3>
      <div class="meta-grid analysis-entry-meta">
        <div class="meta-item"><div class="k">算法</div><div class="v">${esc(display(entry.algorithm))}</div></div>
        <div class="meta-item"><div class="k">算法工具</div><div class="v">${esc(display(entry.algorithm_tool))}</div></div>
        <div class="meta-item"><div class="k">模型版本</div><div class="v">${esc(display(entry.model_version))}</div></div>
        <div class="meta-item"><div class="k">结果版本</div><div class="v">${esc(display(entry.result_version))}</div></div>
        <div class="meta-item"><div class="k">算法参数</div><div class="v">${esc(display(entry.parameters))}</div></div>
      </div>`;
    html += splitBanner(entry, task || {});

    if (taskType === 'dimensionality_reduction') {
      html += renderDimensionalityReduction(entry);
    } else if (taskType === 'clustering') {
      html += renderClustering(entry);
    } else if (taskType === 'classification') {
      html += renderClassification(entry);
    }
    html += renderLimitations(entry.limitations);
    html += '</article>';
    return html;
  }

  function renderDimensionalityReduction(entry) {
    const info = entry.information_retention || {};
    const usage = entry.resource_usage || {};
    const retention = [
      ['指标', info.metric],
      ['信息保留值', info.top2_cumulative !== undefined
        ? info.top2_cumulative : info.knn_agreement],
      ['指标定义', info.definition],
      ['原始维数', entry.original_dimensions],
      ['降维维数', entry.reduced_dimensions],
      ['运行时间 (ms)', usage.elapsed_ms],
      ['峰值 Python 分配 (bytes)', usage.peak_alloc_bytes],
      ['内存测量方法', usage.memory_method]
    ];
    let html = `<h4>降维与资源指标</h4><div class="meta-grid">${retention.map(([k, v]) =>
      `<div class="meta-item"><div class="k">${esc(k)}</div><div class="v">${esc(display(v))}</div></div>`
    ).join('')}</div>`;
        html += renderScatter(entry);
    html += renderLoadings(entry.axis_meaning);
    html += renderClusteringComparison(entry.clustering_comparison);
    return html;
  }

  // 主成分载荷表：PCA 轴含义的唯一可解释依据（数据规范 §五.6）
  function renderLoadings(axisMeaning) {
    const loadings = axisMeaning && Array.isArray(axisMeaning.loadings)
      ? axisMeaning.loadings : [];
    if (!loadings.length) return '';
    return `<h4>主成分载荷（轴含义依据）
      <span class="sub">（主成分是原始特征的线性组合，"意义"只能由载荷解释，不能靠图形猜测）</span></h4>
      <div class="loading-grid">${loadings.map(pc => `
        <div class="loading-card">
          <div class="loading-head"><b>${esc(display(pc.component))}</b>
            <span class="sub">解释方差比 ${esc(pct(pc.explained_variance_ratio, 2))}</span></div>
          <table class="score metric-table"><thead><tr><th>特征</th><th>载荷</th></tr></thead>
          <tbody>${(pc.top_features || []).map(f => `<tr>
            <td class="mono">${esc(display(f.feature))}</td>
            <td class="mono ${f.loading < 0 ? 'delta down' : ''}">${esc(fixed(f.loading, 4))}</td>
          </tr>`).join('')}</tbody></table>
        </div>`).join('')}</div>`;
  }

  function renderScatter(entry) {
    const coords = (entry.coordinates || []).filter(c =>
      typeof c.x === 'number' && Number.isFinite(c.x) &&
      typeof c.y === 'number' && Number.isFinite(c.y));
    if (!coords.length) {
      return '<h4>二维坐标</h4><p class="sub">当前没有可绘制的有效坐标。</p>';
    }
    const width = 620, height = 340, pad = 36;
    const xs = coords.map(c => c.x), ys = coords.map(c => c.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const xScale = x => pad + (maxX === minX ? 0.5 : (x - minX) / (maxX - minX))
      * (width - 2 * pad);
    const yScale = y => height - pad - (maxY === minY ? 0.5 : (y - minY) / (maxY - minY))
      * (height - 2 * pad);
    const points = coords.map(c => {
      const fit = c.is_fit_user !== false;
      const color = fit ? '#38bdf8' : '#fbbf24';
      return `<circle cx="${xScale(c.x).toFixed(2)}" cy="${yScale(c.y).toFixed(2)}"
        r="4.5" fill="${color}"><title>${esc(`用户 ${c.user_id} · ${c.status}`)}</title></circle>`;
    }).join('');
    const axis = entry.axis_meaning || {};
    return `<h4>二维坐标可视化</h4>
      <div class="scatter-legend"><span><i class="fit-dot"></i>拟合用户</span>
      <span><i class="projected-dot"></i>样本外投影</span>
      <span>有效坐标 ${coords.length} / ${esc(display((entry.coordinates || []).length))}</span></div>
      <svg class="scatter-plot" viewBox="0 0 ${width} ${height}" role="img"
        aria-label="${esc(`${axis.x || 'x'} / ${axis.y || 'y'} 降维散点图`)}">
        <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" />
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" />
        ${points}
        <text x="${width / 2}" y="${height - 6}">${esc(axis.x || 'x')}</text>
        <text x="8" y="${height / 2}" transform="rotate(-90 8 ${height / 2})">${esc(axis.y || 'y')}</text>
      </svg>`;
  }

  function renderClusteringComparison(comparison) {
    if (!comparison || typeof comparison !== 'object') {
      return '<h4>降维前后聚类对照</h4><p class="sub">接口未返回聚类对照结果。</p>';
    }
    return `<h4>降维前后聚类对照</h4>${Object.entries(comparison).map(([name, c]) => {
      const before = c.before || {};
      const after = c.after || {};
      const metricNames = new Set([...Object.keys(before.metrics || {}),
                                    ...Object.keys(after.metrics || {})]);
      if (!metricNames.size) {
        for (const k of ['silhouette', 'davies_bouldin', 'sse', 'n_clusters', 'noise_ratio']) {
          if (before[k] !== undefined || after[k] !== undefined) metricNames.add(k);
        }
      }
      const rows = [...metricNames].map(k => `<tr><td>${esc(k)}</td>
        <td>${esc(display((before.metrics || before)[k]))}</td>
        <td>${esc(display((after.metrics || after)[k]))}</td></tr>`).join('');
      return `<div class="comparison-block"><b>${esc(c.algorithm || name)}</b>
        <span class="sub">参数：${esc(display(c.parameters))}</span>
        <table class="score"><thead><tr><th>指标</th><th>降维前</th><th>降维后</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="3">无可用指标</td></tr>'}</tbody></table>
        <p class="sub">${esc(display(c.comparability_note))}</p></div>`;
    }).join('')}`;
  }

    function renderClassification(entry) {
      const predictions = predictionsOf(entry);
      const target = entry.target || {};

    // 每条预测只渲染自己的 metrics / limitations（不再回落到 entry.metrics 的原始 JSON）
    const cards = predictions.map((p, i) => {
      const user = p.user_id !== undefined ? p.user_id : target.user_id;
      const movie = p.movie_id !== undefined ? p.movie_id : target.movie_id;
      const m = p.metrics || {};
      const metricRows = CLASS_METRIC_CN.map(([key, cn, hint]) => {
        const v = m[key];
        return `<tr><td>${esc(cn)}</td>
          <td class="mono">${esc(v === null || v === undefined ? '不适用' : v)}</td>
          <td class="sub">${esc(hint)}</td></tr>`;
      }).join('');
      // 记录 metrics 里未登记的新键，如实展示，避免静默丢弃
      const extra = Object.keys(m).filter(k => !CLASS_METRIC_CN.some(([kk]) => kk === k));
      const extraRows = extra.map(k => `<tr><td>${esc(k)}</td>
        <td class="mono">${esc(display(m[k]))}</td><td class="sub">接口附加指标</td></tr>`).join('');

      const prob = p.positive_probability;
      return `<div class="pred-card">
        <div class="pred-head">
          <b>${esc(p.algorithm || entry.algorithm_name || entry.algorithm || `预测 ${i + 1}`)}</b>
          <span class="tag keep">${esc(p.predicted_class === undefined ? '—' : p.predicted_class)}</span>
          <span class="sub">目标用户 ${esc(display(user))} · 电影 ${esc(display(movie))}</span>
        </div>
        <div class="meta-grid">
          <div class="meta-item"><div class="k">正类概率（未校准）</div>
            <div class="v">${esc(display(prob))}</div></div>
          <div class="meta-item"><div class="k">决策分数</div>
            <div class="v">${esc(display(p.decision_score))}</div></div>
          <div class="meta-item"><div class="k">决策阈值</div>
            <div class="v">${esc(display(m.threshold))}</div></div>
          <div class="meta-item"><div class="k">模型版本</div>
            <div class="v">${esc(display(p.model_version || entry.model_version))}</div></div>
        </div>
        ${typeof prob === 'number'
          ? '<p class="sub warn-line">注意：该概率未经校准，不能当作真实概率直接展示；仅用于同一模型内的相对比较。</p>'
          : ''}
        <h4>评价指标</h4>
        <table class="score metric-table"><thead><tr>
          <th>指标</th><th>值</th><th>说明</th></tr></thead>
          <tbody>${metricRows}${extraRows}</tbody></table>
        ${Array.isArray(p.limitations) && p.limitations.length
          ? `<h4>本预测适用限制</h4><ul class="lim-list">${
              p.limitations.map(x => `<li>${esc(display(x))}</li>`).join('')}</ul>`
          : ''}
        ${p.features_used ? `<details class="fold"><summary>预测使用的特征（如实透传）</summary>
          <pre class="fold-pre">${esc(JSON.stringify(p.features_used, null, 2))}</pre></details>` : ''}
      </div>`;
    }).join('');

    return `<h4>分类预测</h4>${cards || '<p class="sub">接口未返回预测结果。</p>'}`;
  }

    function renderClustering(entry) {
    let html = '<h4>聚类指标</h4>' + renderClusterMetrics(entry.metrics);
    html += renderAssignments(entry.assignments || []);
    html += renderClusterSummaries(entry.cluster_summaries || []);
    return html;
  }

  // 聚类指标：标量键中文化 + null 明确"不适用" + k 选择表折叠展示
  function renderClusterMetrics(metrics) {
    const m = metrics || {};
    if (!Object.keys(m).length) return '<p class="sub">接口未返回聚类指标。</p>';

    const known = new Set();
    const items = [];
    CLUSTER_METRIC_CN.forEach(([key, cn, digits]) => {
      if (m[key] === undefined) return;
      known.add(key);
      let v;
      if (typeof m[key] === 'number' && digits !== null) {
        v = digits === 0 ? String(m[key]) : fixed(m[key], digits);
      } else {
        v = display(m[key]);
      }
      // 指标为 null → 不适用（联调说明 §5 渲染红线：不能补 0）
      items.push([cn, m[key] === null ? null : v]);
    });
        Object.keys(m).forEach(key => {
      if (known.has(key)) return;
      const v = m[key];
      // k_selection_rule 已在候选 k 表标题里完整展示，这里不再重复
      if (key === 'k_selection_rule') return;
      if (v === null || typeof v !== 'object') {
        items.push([key, v === null ? null : display(v)]);
      }
    });

    let html = kvGrid(items);

    // 各簇全量轮廓系数（对象形式，单独小表）
    if (m.silhouette_per_cluster_full && typeof m.silhouette_per_cluster_full === 'object') {
      html += `<div class="sub" style="margin-top:10px">各群体全量轮廓系数（负数表示该簇内样本更接近其他簇）</div>
        <table class="score metric-table"><thead><tr><th>群体</th><th>轮廓系数</th></tr></thead>
        <tbody>${Object.entries(m.silhouette_per_cluster_full).map(([k, v]) =>
          `<tr><td>群体 ${esc(k)}</td><td class="mono">${esc(fixed(v, 4))}</td></tr>`
        ).join('')}</tbody></table>`;
    }

    // 候选 k 选择表
    if (Array.isArray(m.k_selection_table) && m.k_selection_table.length) {
            html += `<details class="fold"><summary>候选 k 的实测指标（k 选择依据）
        ${m.k_selection_rule ? `<span class="sub">：${esc(m.k_selection_rule)}</span>` : ''}</summary>
        <table class="score metric-table"><thead><tr>
          <th>k</th><th>抽样轮廓系数</th><th>DBI</th><th>SSE</th><th>迭代</th><th>收敛</th>
        </tr></thead><tbody>${m.k_selection_table.map(r => `<tr>
          <td>${esc(display(r.k))}</td>
          <td class="mono">${esc(fixed(r.silhouette_sampled, 4))}</td>
          <td class="mono">${esc(fixed(r.davies_bouldin, 4))}</td>
          <td class="mono">${esc(fixed(r.sse, 2))}</td>
          <td class="mono">${esc(display(r.iterations))}</td>
          <td>${r.converged === true ? '是' : (r.converged === false ? '否' : '—')}</td>
        </tr>`).join('')}</tbody></table></details>`;
    }

    // 指标定义（联调说明 §5 要求：每个指标带 definition）
    if (m.definition && typeof m.definition === 'object') {
      html += `<details class="fold"><summary>指标定义与适用条件</summary><ul class="lim-list">${
        Object.entries(m.definition).map(([k, v]) =>
          `<li><b>${esc(k)}</b>：${esc(display(v))}</li>`).join('')}</ul></details>`;
    }
    return html;
  }

  // 用户群体归属：按 status 判定，未归属用户单列
  function renderAssignments(assignments) {
    const assigned = [];
    const unassigned = [];
    assignments.forEach(a => {
      const status = a.status || '';
      const isUnassigned = a.cluster_id === null || a.cluster_id === undefined ||
        (status && status !== 'SUCCESS' && status !== 'ASSIGNED_FROM_FITTED_CENTROIDS') ||
        a.is_noise === true || status === 'UNASSIGNED_BY_DENSITY';
      (isUnassigned ? unassigned : assigned).push(a);
    });

    const rows = assigned.map(a => `<tr>
      <td>${esc(display(a.user_id))}</td>
      <td>${esc(display(a.cluster_id))}</td>
      <td>${esc(display(ASSIGN_STATUS_CN[a.status] || a.status))}</td>
      <td class="mono">${esc(fixed(a.distance_to_centroid, 4))}</td>
      <td>${a.reliability_low === true ? '<span class="tag sev-medium">可靠性低</span>' : ''}</td>
    </tr>`).join('');

    const unRows = unassigned.map(a => `<tr>
      <td>${esc(display(a.user_id))}</td>
      <td>${esc(display(ASSIGN_STATUS_CN[a.status] || a.status))}</td>
      <td>${a.reliability_low === true ? '<span class="tag sev-medium">可靠性低</span>' : ''}</td>
      <td class="sub">${esc(display(a.note))}</td>
    </tr>`).join('');

    const assignedIds = new Set(assigned.map(a => a.user_id));
    const noiseCount = unassigned.filter(a => a.status === 'UNASSIGNED_BY_DENSITY' ||
      a.is_noise === true).length;

    let html = `<h4>用户群体归属
      <span class="sub">（已归属 ${assigned.length} 人${unassigned.length ? ` · 未归属 ${unassigned.length} 人` : ''}${noiseCount ? ` · 其中噪声点 ${noiseCount}` : ''}）</span></h4>`;
    html += `<div class="table-scroll"><table class="score"><thead><tr>
      <th>用户</th><th>群体</th><th>归属状态</th><th>到质心距离</th><th>标记</th>
      </tr></thead><tbody>${rows || `<tr><td colspan="5">接口未返回已归属用户</td></tr>`}</tbody></table></div>`;

    if (unassigned.length) {
      html += `<h4 class="warn-line">未归属用户（历史不足 / 无训练记录 / 噪声点，不计入任何群体结论）</h4>
        <div class="table-scroll"><table class="score"><thead><tr>
        <th>用户</th><th>未归属原因</th><th>标记</th><th>说明（原文）</th>
        </tr></thead><tbody>${unRows}</tbody></table></div>`;
    } else if (!assignedIds.size) {
      html += '<p class="sub">接口未返回用户归属。</p>';
    }
    return html;
  }

  // 群体摘要：用真实统计字段拼装 + 代表性作品 + 口径原文
  function renderClusterSummaries(summaries) {
    if (!summaries.length) {
      return '<h4>群体摘要</h4><p class="sub">接口未返回群体摘要。</p>';
    }
    const cards = summaries.map(c => {
      const size = c.size !== undefined ? c.size : c.n_users;
      const stats = [
        ['平均评分', fixed(c.avg_rating_mean)],
        ['人均评分数', fixed(c.n_ratings_mean, 1)],
        ['高分占比', pct(c.high_share_mean)],
        ['活跃跨度（天）', fixed(c.active_span_days_mean, 1)]
      ];
      const genres = Array.isArray(c.top_genre_shares) && c.top_genre_shares.length
        ? `<div class="chips">${c.top_genre_shares.map(g =>
            `<span class="chip">${esc(g.genre)} ${esc(pct(g.v))}</span>`).join('')}</div>`
        : '<span class="sub">接口未返回类型占比</span>';
            const movies = Array.isArray(c.representative_movies) && c.representative_movies.length
        ? `<ul class="rep-list">${c.representative_movies.map(mv => {
            // 真实数据里 title 已含年份（如 "... (1977)"），避免重复追加
            const title = String(mv.title === undefined || mv.title === null ? '—' : mv.title);
            const hasYear = mv.year !== undefined && mv.year !== null &&
              title.includes(String(mv.year));
            return `<li>${esc(title)}${mv.year && !hasYear ? `（${esc(mv.year)}）` : ''}
             ${mv.high_raters_in_cluster !== undefined
               ? `：群内评分≥4 者 ${esc(intNum(mv.high_raters_in_cluster))} 人` : ''}</li>`;
          }).join('')}</ul>`
        : '<span class="sub">接口未返回代表性作品</span>';

      return `<div class="cluster-card">
        <div class="cluster-head"><b>群体 ${esc(display(c.cluster_id))}</b>
          <span class="sub">${esc(intNum(size))} 人</span></div>
        <div class="stat-grid cluster-stats">${stats.map(([k, v]) =>
          `<div class="stat"><div class="k">${esc(k)}</div><div class="v small">${esc(v)}</div></div>`
        ).join('')}</div>
        <div class="cluster-sub">主要类型 Top${Array.isArray(c.top_genre_shares) ? c.top_genre_shares.length : 0}</div>
        ${genres}
        <div class="cluster-sub">代表性作品（按群内评分≥4 人数排序）</div>
        ${movies}
        ${c.summary_basis ? `<div class="basis">口径（原文）：${esc(c.summary_basis)}</div>` : ''}
      </div>`;
    }).join('');

    return `<h4>群体摘要（群体解释）</h4><div class="cluster-cards">${cards}</div>
      <p class="sub">说明：以上为群体内真实统计，属"观测到的群体偏好"，不推断用户动机；
      不同算法的簇号互不相通，不能按编号对齐或比较大小。</p>`;
  }

    function renderLimitations(limitations) {
    if (!limitations || !limitations.length) return '';
    return `<h4>结果局限</h4><ul class="lim-list">${limitations.map(item =>
      `<li>${esc(typeof item === 'object' ? display(item.detail || item.message || item) : item)}</li>`
    ).join('')}</ul>`;
  }

  // ---------- 分析任务的结果获取（需求第 8 项） ----------
  // 只重排接口已返回的真实数据，不新增/推算任何数值
  function analysisSample(result, entries) {
    const blocks = [];
        if (result.task_type === 'classification') {
      entries.forEach(entry => {
        predictionsOf(entry).forEach(p => {
          blocks.push({
            table: `预测样例 · ${p.algorithm || entry.algorithm || ''}`,
            columns: ['用户', '电影', '预测类别', '正类概率（未校准）', '决策分数',
                      '决策阈值', '模型版本'],
            rows: [[
              display(p.user_id !== undefined ? p.user_id : (entry.target || {}).user_id),
              display(p.movie_id !== undefined ? p.movie_id : (entry.target || {}).movie_id),
              display(p.predicted_class),
              display(p.positive_probability),
              display(p.decision_score),
              display((p.metrics || {}).threshold),
              display(p.model_version || entry.model_version)
            ]]
          });
        });
      });
    } else if (result.task_type === 'clustering') {
      entries.forEach(entry => {
        (entry.cluster_summaries || []).forEach(c => {
          blocks.push({
            table: `群体 ${c.cluster_id} 成员样例（前 5 位，共 ${display(c.size)} 人）`
              + ` · ${entry.algorithm || ''}`,
            columns: ['用户', '群体', '归属状态', '到质心距离', '可靠性低'],
            rows: (entry.assignments || [])
              .filter(a => a.cluster_id === c.cluster_id)
              .slice(0, 5)
              .map(a => [display(a.user_id), display(a.cluster_id),
                         ASSIGN_STATUS_CN[a.status] || display(a.status),
                         fixed(a.distance_to_centroid, 4),
                         a.reliability_low === true ? '是' : '否'])
          });
        });
      });
    } else if (result.task_type === 'dimensionality_reduction') {
      entries.forEach(entry => {
        blocks.push({
          table: `降维坐标样例（前 10 位，共 ${(entry.coordinates || []).length} 个坐标）`
            + ` · ${entry.algorithm || ''}`,
          columns: ['用户', 'x（第1主成分）', 'y（第2主成分）', '状态', '拟合用户'],
          rows: (entry.coordinates || []).slice(0, 10).map(c => [
            display(c.user_id), fixed(c.x, 4), fixed(c.y, 4),
            display(c.status), c.is_fit_user === true ? '是' : (c.is_fit_user === false ? '否' : '—')
          ])
        });
      });
    }

    if (!blocks.length) {
      return '<p class="sub">本次接口未返回可用于样例展示的记录。</p>';
    }
    return blocks.map(block => `
      <div style="margin-bottom:12px">
        <div style="font-size:12px;color:var(--muted);margin:6px 0">${esc(block.table)}</div>
        <div class="table-scroll"><table class="sample-table">
          <thead><tr>${block.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
          <tbody>${block.rows.map(r =>
            `<tr>${r.map(c => `<td class="mono">${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>
        </table></div>
      </div>`).join('');
  }

  function analysisReport(result, entries) {
    const versionRows = [
      ['任务 ID', result.task_id],
      ['分析口径版本', result.analysis_version],
      ['数据版本', result.data_version],
      ['画像版本', result.profile_version],
      ['代码版本', result.code_version],
      ['T1', result.T1],
      ['T2', result.T2]
    ].filter(([, v]) => v !== undefined && v !== null && v !== '');

    let html = '<h4>版本与追溯信息</h4>' + kvGrid(versionRows);

    html += '<h4>已产出结果列表</h4><div class="table-scroll"><table class="score metric-table">'
      + '<thead><tr><th>算法</th><th>工具</th><th>模型版本</th><th>结果版本</th><th>说明</th></tr></thead><tbody>'
      + entries.map(e => `<tr>
          <td>${esc(display(e.algorithm_name || e.algorithm))}</td>
          <td class="mono">${esc(display(e.algorithm_tool))}</td>
          <td class="mono">${esc(display(e.model_version))}</td>
          <td class="mono">${esc(display(e.result_version))}</td>
          <td class="sub">${esc(display(e.algorithm_source))}</td>
        </tr>`).join('')
      + '</tbody></table></div>';

    // 必要的图表：本页二维图仅降维任务有；如实说明而非占位
    html += `<h4>必要图表</h4><ul class="lim-list"><li>${
      result.task_type === 'dimensionality_reduction'
        ? '二维坐标图：见上方「二维坐标可视化」（含图例、样本范围与轴含义）；主成分载荷表见「主成分载荷」。'
        : '本类任务的接口结果中不含坐标类图表数据；页面未生成任何示意性图形。'
    }</li></ul>`;

    if (result._note) html += `<p class="sub warn-line">${esc(result._note)}</p>`;

    html += '<h4>导出</h4><p class="sub">如需完整结果 JSON，可通过 '
      + `<span class="mono">GET /api/tasks/${esc(display(result.task_id))}/result</span> 获取（本页所有数值均来自该接口）。</p>`;

    return html;
  }

  return { status, scores, versions, statistics, problems, report, sample, analysis, DIMS };
})();
