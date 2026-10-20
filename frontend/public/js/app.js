/* MovieLens 数据治理 Agent —— 前端主控（成员C）
 *
 * 交互流程（对应迭代一需求第 5/6 节）：
 *   用户输入自然语言 → 创建任务 → 轮询状态 → 拉取结果 → 渲染 → 支持追问。
 *
 * 关键约束：
 *   - 一次提示发起完整任务，前端不触发任何中间步骤（需求第 5 节）。
 *   - 任务未完成时不显示任何数值（接口规范第 2.2 / 13.3 节）。
 *   - 失败时展示 failed 环节与原因，不显示占位结果。
 */

(function () {
  'use strict';

  let currentTaskId = null;
  let pollTimer = null;

  const $ = s => document.querySelector(s);
  const show = el => el.classList.remove('hidden');
  const hide = el => el.classList.add('hidden');

    // 各任务类型切换时的默认示例提示词
  //
  // ⚠️ 措辞约束：后端 router.CATEGORY_KEYWORDS 按关键词判定任务类别，
  //    一旦一条 query 同时命中多个类别，Agent 会以
  //    "查询同时涉及多个分析类别 … 请拆分提交" 直接拒绝（多类别保护）。
  //    因此每种类型的默认词里**只能出现本类别的关键词**：
  //      · 聚类词：聚类/分群/群体/簇/kmeans/dbscan…
  //      · 降维词：降维/主成分/坐标/二维/投影/可视化/pca/tsne…
  //      · 分类词：分类/预测/高分/是否会喜欢…
  //    例如降维默认词不能写"降维前后聚类结果的变化"——"聚类"会被判成跨类别。
  const DEFAULT_PROMPT = {
    cleaning:
      '请使用默认规则清洗 MovieLens 1M，评估清洗前后的 Accurate、Complete、Unique、' +
      'Up-to-date、Consistent 五个维度，并说明处理了哪些问题、还有哪些问题无法解决。',
    clustering: '对用户做聚类分析，说明分成几个群体以及每个群体的特征。',
    // 特意不出现"聚类"：只保留降维关键词（主成分/二维/投影）
    dimensionality_reduction:
      '对用户画像做 PCA 主成分分析，把用户投影到二维坐标并画出散点图，' +
      '说明主成分保留了多少信息。',
    classification: '预测用户是否会给某部电影打高分，并说明依据。'
  };

  // 各任务类型可一键运行的默认参数（取自真实可跑通的拟合用户与已登记算法）
  // 降维 user_ids 留空 = 使用 profile-v1 全部拟合用户（已验证可跑通）；
  // 聚类 user_ids 必填，这里给一组真实存在且有训练期历史的拟合用户。
  const DEFAULT_ANALYSIS = {
    clustering: {
      userIds: '1161, 1162, 1163, 1164, 1166, 1167, 1168, 1169, 1170, 1171',
      algorithm: 'kmeans',
      parameters: ''
    },
    dimensionality_reduction: {
      userIds: '',
      algorithm: 'pca',
      parameters: ''
    },
    classification: {
      userIds: '',
      algorithm: '',
      parameters: '',
      movieId: '1'
    }
  };

  // ---------- 初始化 ----------
  document.addEventListener('DOMContentLoaded', () => {
    // 默认示例提示，用户可直接点"开始执行"
    $('#prompt').value = DEFAULT_PROMPT.cleaning;

    $('#submitBtn').addEventListener('click', submit);
    $('#taskType').addEventListener('change', () => updateTaskFields(false));
    $('#askBtn').addEventListener('click', ask);
    $('#askInput').addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });

    // 示例填充
    document.querySelectorAll('.examples a[data-fill]').forEach(a => {
      a.addEventListener('click', () => { $('#prompt').value = a.dataset.fill; });
    });

    // 服务健康检查
    checkHealth();
    updateTaskFields(true);
  });

  function updateTaskFields(isInit) {
    const taskType = $('#taskType').value;
    const analysis = taskType !== 'cleaning';
    $('#analysisFields').classList.toggle('hidden', !analysis);
    $('#cleaningFields').classList.toggle('hidden', analysis);
    const movieField = $('#analysisMovieId').closest('label');
    movieField.classList.toggle('hidden', taskType !== 'classification');

    // 提示词：仅当为空或仍是某个默认提示词时替换，避免覆盖用户手写内容
    const cur = $('#prompt').value.trim();
    const isDefaultOrEmpty = !cur ||
      Object.values(DEFAULT_PROMPT).some(t => t === cur);

    if (analysis) {
      const d = DEFAULT_ANALYSIS[taskType] || {};
      if (isDefaultOrEmpty && DEFAULT_PROMPT[taskType]) {
        $('#prompt').value = DEFAULT_PROMPT[taskType];
      }
      // 用户 ID / 算法 / 参数：按任务类型填默认值，切换过去即可直接运行
      $('#analysisUserIds').value = d.userIds || '';
      $('#analysisAlgorithm').value = d.algorithm || '';
      $('#analysisParameters').value = d.parameters || '';
      if (taskType === 'classification') {
        $('#analysisMovieId').value = d.movieId || '';
      }
    } else if (!isInit) {
      // 从分析类型切回清洗：恢复清洗默认提示词
      if (isDefaultOrEmpty) $('#prompt').value = DEFAULT_PROMPT.cleaning;
    }
  }

  async function checkHealth() {
    try {
      const h = await AgentApi.health();
      $('#serviceState').textContent = 'Agent 在线';
      $('#serviceState').style.color = 'var(--up)';
      $('#serviceState').title = `规则版本 ${h.rule_version || '—'} · Hadoop ${h.hadoop_url || '—'}`;
    } catch (e) {
      $('#serviceState').textContent = 'Agent 离线';
      $('#serviceState').style.color = 'var(--down)';
      $('#serviceState').title = e.message || '';
    }
  }

  // ---------- 提交任务 ----------
  async function submit() {
    const prompt = $('#prompt').value.trim();
    if (!prompt) { alert('请输入自然语言需求'); return; }

    const taskType = $('#taskType').value;

    resetPanels();
    $('#submitBtn').disabled = true;
    $('#submitBtn').innerHTML = '<span class="spinner"></span> 执行中';
    hide($('#taskPanel'));
    hide($('#resultPanel'));
    hide($('#analysisResultPanel'));
    show($('#statusPanel'));

    try {
      let created;
      if (taskType === 'cleaning') {
        created = await AgentApi.createTask({
          prompt: prompt,
          data_version: $('#dataVersion').value.trim() || 'movielens-1m-v2',
          rule_version: $('#ruleVersion').value.trim() || 'default'
        });
      } else {
        const rawIds = $('#analysisUserIds').value.trim();
        const userIds = rawIds ? rawIds.split(/[,\s]+/).filter(Boolean) : [];
        let parameters = {};
        const rawParameters = $('#analysisParameters').value.trim();
        if (rawParameters) {
          parameters = JSON.parse(rawParameters);
          if (!parameters || Array.isArray(parameters) || typeof parameters !== 'object') {
            throw new Error('算法参数必须是 JSON 对象');
          }
        }
        const payload = {
          query: prompt,
          data_version: $('#analysisDataVersion').value.trim(),
          profile_version: $('#profileVersion').value.trim() || 'profile-v1',
          user_ids: userIds.length ? userIds : null,
          parameters
        };
        const algorithm = $('#analysisAlgorithm').value.trim();
        if (algorithm) payload.algorithm = algorithm;
        const movieId = $('#analysisMovieId').value.trim();
        if (movieId) payload.movie_id = movieId;
        created = await AgentApi.createAnalysisTask(
          taskType === 'dimensionality_reduction'
            ? 'dimensionality-reduction' : taskType,
          payload);
      }
      currentTaskId = created.task_id;
      show($('#taskPanel'));
      Render.status({ task_id: created.task_id, status: created.status, message: created.message });

            // 展示 Agent 对需求的解析说明（接口附加字段，可缺省）
      //
      // 两条接口的字段形状不同，必须都兼容：
      //   · POST /api/tasks（清洗）                        -> understanding 是数组
      //   · POST /api/analysis/{category}/tasks（分析）    -> understanding 是字符串
      //     （来自 router.plan['notes']）
      // 早期实现直接调 created.understanding.map()，字符串没有 map，
      // 导致聚类/降维/分类一提交就抛 "created.understanding.map is not a function"，
      // 并显示成 UNKNOWN 任务失败——实际任务已建好且在跑。
      const uBox = $('#understandingBox');
      const u = created.understanding;
      let uItems = null;
      if (Array.isArray(u)) {
        uItems = u.filter(x => x !== null && x !== undefined && x !== '');
      } else if (typeof u === 'string' && u.trim()) {
        uItems = [u.trim()];
      }
      if (uItems && uItems.length) {
        uBox.innerHTML = '<b>Agent 需求解析：</b><ul style="margin:6px 0 0;padding-left:20px">' +
          uItems.map(t => `<li>${escapeHtml(t)}</li>`).join('') + '</ul>';
        show(uBox);
      } else {
        hide(uBox);
      }

      startPolling(currentTaskId);
    } catch (err) {
      showError(err);
      finishSubmit();
    }
  }

  // ---------- 轮询 ----------
  function startPolling(taskId) {
    stopPolling();
    let ticks = 0;
    const MAX_TICKS = 600; // 1200s 上限，防止无限轮询

    const tick = async () => {
      ticks++;
      try {
        const st = await AgentApi.getStatus(taskId);
        Render.status(st);

        if (st.status === 'SUCCESS') {
          stopPolling();
          await loadResult(taskId);
          finishSubmit();
          return;
        }
        if (st.status === 'FAILED') {
          stopPolling();
          showError(st.error || { code: 'FAILED', message: st.message, stage: st.stage });
          // 失败也可能有部分结果，如实尝试展示
          try {
            const r = await AgentApi.getResult(taskId);
            if (r.partial_result) renderPartial(r.partial_result);
          } catch (_) { /* 忽略 */ }
          finishSubmit();
          return;
        }
        if (ticks >= MAX_TICKS) {
          stopPolling();
          showError({ code: 'TIMEOUT', message: '前端等待超时，任务仍在后台执行', stage: st.stage });
          finishSubmit();
          return;
        }
        pollTimer = setTimeout(tick, 1000);
      } catch (err) {
        stopPolling();
        showError(err);
        finishSubmit();
      }
    };
    tick();
  }

  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  // ---------- 加载并渲染结果 ----------
  async function loadResult(taskId) {
    const result = await AgentApi.getResult(taskId);
    if (result.status !== 'SUCCESS') {
      // 理论上不会走到这里（状态已 SUCCESS），保守处理
      showError({ code: 'NO_RESULT', message: result.message || '结果不可得', stage: result.stage });
      return;
    }
    renderFull(result);
  }

  function renderFull(result) {
    if (result.task_type && result.task_type !== 'cleaning') {
      Render.analysis(result);
      hide($('#resultPanel'));
      show($('#analysisResultPanel'));
      hide($('#errorBox'));
      show($('#chatPanel'));
      return;
    }
    Render.scores(result);
    Render.versions(result);
    Render.statistics(result);
    Render.problems(result);
    Render.report(result);
    Render.sample(result);

    if (result._note) {
      $('#resultNote').textContent = result._note;
      show($('#resultNote'));
    } else {
      hide($('#resultNote'));
    }

    hide($('#errorBox'));
    show($('#resultPanel'));
    show($('#chatPanel'));
  }

  function renderPartial(partial) {
    if (partial.task_type && partial.task_type !== 'cleaning') {
      Render.analysis(partial);
      show($('#analysisResultPanel'));
      return;
    }
    // 失败时的部分结果：只渲染已完成环节的真实数值
    if (partial.before_score) {
      Render.scores({ before_score: partial.before_score, after_score: {}, score_change: {} });
      show($('#resultPanel'));
      $('#resultPanel').scrollIntoView({ behavior: 'smooth' });
    }
  }

  // ---------- 追问 ----------
  async function ask() {
    const q = $('#askInput').value.trim();
    if (!q) return;
    if (!currentTaskId) { alert('请先创建并完成任务'); return; }

    appendMsg('user', q, null);
    $('#askInput').value = '';
    $('#askBtn').disabled = true;

    try {
      const resp = await AgentApi.ask(currentTaskId, q);
      appendMsg('agent', resp.answer, resp.source);
    } catch (err) {
      appendMsg('agent', '追问失败：' + (err.message || '未知错误'), null, true);
    } finally {
      $('#askBtn').disabled = false;
    }
  }

  function appendMsg(who, text, source, isError) {
    const log = $('#chatLog');
    const div = document.createElement('div');
    div.className = 'msg ' + who;
    const whoLabel = who === 'user' ? '我' : 'Agent';
    const src = source ? `<div class="src">来源：${escapeHtml(source)}</div>` : '';
    div.innerHTML = `<div class="who">${whoLabel}</div>
      <div class="bubble"${isError ? ' style="border-color:#7f1d1d"' : ''}>${escapeHtml(text)}</div>${src}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  // ---------- 辅助 ----------
  function showError(err) {
    const box = $('#errorBox');
    const stage = err.stage ? `（环节：${err.stage}）` : '';
    box.innerHTML = `<b>任务失败</b>${escapeHtml(stage)}<br>
      <span class="code">${escapeHtml(err.code || 'UNKNOWN')}</span>：
      ${escapeHtml(err.message || '未知错误')}
      ${err.detail ? `<details style="margin-top:6px"><summary>详细信息</summary><pre style="white-space:pre-wrap;font-size:11px">${escapeHtml(err.detail)}</pre></details>` : ''}`;
    show(box);
  }

  function finishSubmit() {
    $('#submitBtn').disabled = false;
    $('#submitBtn').textContent = '开始执行';
    checkHealth();
  }

  function resetPanels() {
    $('#chatLog').innerHTML = '';
    hide($('#errorBox'));
    hide($('#resultNote'));
    hide($('#analysisResultPanel'));
  }

  function escapeHtml(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();