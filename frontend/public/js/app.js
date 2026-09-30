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

  // ---------- 初始化 ----------
  document.addEventListener('DOMContentLoaded', () => {
    // 默认示例提示，用户可直接点"开始执行"
    $('#prompt').value =
      '请使用默认规则清洗 MovieLens 1M，评估清洗前后的 Accurate、Complete、Unique、' +
      'Up-to-date、Consistent 五个维度，并说明处理了哪些问题、还有哪些问题无法解决。';

    $('#submitBtn').addEventListener('click', submit);
    $('#askBtn').addEventListener('click', ask);
    $('#askInput').addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });

    // 示例填充
    document.querySelectorAll('.examples a[data-fill]').forEach(a => {
      a.addEventListener('click', () => { $('#prompt').value = a.dataset.fill; });
    });

    // 服务健康检查
    checkHealth();
  });

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

    const dataVersion = $('#dataVersion').value.trim() || 'movielens-1m-v2';
    const ruleVersion = $('#ruleVersion').value.trim() || 'default';

    resetPanels();
    $('#submitBtn').disabled = true;
    $('#submitBtn').innerHTML = '<span class="spinner"></span> 执行中';
    hide($('#taskPanel'));
    hide($('#resultPanel'));
    show($('#statusPanel'));

    try {
      const created = await AgentApi.createTask({
        prompt: prompt,
        data_version: dataVersion,
        rule_version: ruleVersion
      });
      currentTaskId = created.task_id;
      show($('#taskPanel'));
      Render.status({ task_id: created.task_id, status: created.status, message: created.message });

      // 展示 Agent 对需求的解析说明（接口附加字段，可缺省）
      const uBox = $('#understandingBox');
      if (created.understanding && created.understanding.length) {
        uBox.innerHTML = '<b>Agent 需求解析：</b><ul style="margin:6px 0 0;padding-left:20px">' +
          created.understanding.map(t => `<li>${escapeHtml(t)}</li>`).join('') + '</ul>';
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
  }

  function escapeHtml(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
