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
      ['T1', result.T1],
      ['T2', result.T2],
      ['任务状态', result.status]
    ];
    $('#analysisMeta').innerHTML = meta.map(([k, v]) =>
      `<div class="meta-item"><div class="k">${esc(k)}</div><div class="v">${esc(display(v))}</div></div>`
    ).join('');

    const entries = Array.isArray(result.results) ? result.results : [];
    if (!entries.length) {
      $('#analysisResults').innerHTML =
        '<p class="sub">任务没有返回已完成的算法结果；请检查任务状态和失败原因。</p>';
      return;
    }
    $('#analysisResults').innerHTML = entries.map((entry, index) =>
      analysisEntry(entry, index, result.task_type)
    ).join('');
  }

  function analysisEntry(entry, index, taskType) {
    let html = `<article class="analysis-entry">
      <h3>${esc(entry.algorithm_name || entry.algorithm_tool || entry.algorithm || `算法 ${index + 1}`)}</h3>
      <div class="meta-grid analysis-entry-meta">
        <div class="meta-item"><div class="k">算法工具</div><div class="v">${esc(display(entry.algorithm_tool))}</div></div>
        <div class="meta-item"><div class="k">模型版本</div><div class="v">${esc(display(entry.model_version))}</div></div>
        <div class="meta-item"><div class="k">结果版本</div><div class="v">${esc(display(entry.result_version))}</div></div>
        <div class="meta-item"><div class="k">算法参数</div><div class="v">${esc(display(entry.parameters))}</div></div>
      </div>`;

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
    html += renderClusteringComparison(entry.clustering_comparison);
    return html;
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
    const predictions = entry.results || [];
    const rows = predictions.map(p => `<tr>
      <td>${esc(display(p.user_id || (entry.target || {}).user_id))}</td>
      <td>${esc(display(p.movie_id || (entry.target || {}).movie_id))}</td>
      <td>${esc(display(p.predicted_class))}</td>
      <td>${esc(display(p.positive_probability))}</td>
      <td>${esc(display(p.decision_score))}</td>
    </tr>`).join('');
    return `<h4>分类预测</h4><table class="score"><thead><tr>
      <th>用户</th><th>电影</th><th>预测类别</th><th>正类概率</th><th>决策分数</th>
      </tr></thead><tbody>${rows || '<tr><td colspan="5">接口未返回预测结果</td></tr>'}</tbody></table>
      <p class="sub">评价指标：${esc(display(entry.metrics))}</p>`;
  }

  function renderClustering(entry) {
    const assignments = entry.assignments || [];
    const rows = assignments.map(a => `<tr>
      <td>${esc(display(a.user_id))}</td><td>${esc(display(a.cluster_id))}</td>
      <td>${esc(display(a.is_noise))}</td></tr>`).join('');
    const summaries = (entry.cluster_summaries || []).map(c =>
      `<li>群体 ${esc(display(c.cluster_id))}：${esc(display(c.size || c.n_users))} 人；
      ${esc(display(c.summary || c.preference_summary || c.explanation))}</li>`
    ).join('');
    return `<h4>聚类指标</h4><p class="sub">${esc(display(entry.metrics))}</p>
      <h4>用户群体归属</h4><table class="score"><thead><tr>
      <th>用户</th><th>群体</th><th>噪声点</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="3">接口未返回用户归属</td></tr>'}</tbody></table>
      <h4>群体摘要</h4><ul>${summaries || '<li>接口未返回群体摘要。</li>'}</ul>`;
  }

  function renderLimitations(limitations) {
    if (!limitations || !limitations.length) return '';
    return `<h4>结果局限</h4><ul>${limitations.map(item =>
      `<li>${esc(typeof item === 'object' ? display(item.detail || item.message || item) : item)}</li>`
    ).join('')}</ul>`;
  }

  return { status, scores, versions, statistics, problems, report, sample, analysis, DIMS };
})();
