/* 前端渲染「契约测试」（成员C）
 *
 * 运行：node tests/frontend/test_render_contract.mjs
 * 零依赖：Node 内置 assert + 极简 DOM stub。
 *
 * 与 test_render.mjs 的区别：
 *   test_render.mjs 用的是**构造数据**（字段名按渲染代码的期望写），
 *   因此渲染端字段错配时仍会全绿。本文件改用**真实任务结果的字段名**驱动渲染，
 *   断言页面上不应出现 "—" 占位（代表"有结果但读不出来"）。
 *
 * fixture 来源（均为真实运行输出，已裁剪体积，未改动字段名）：
 *   clustering_real.json     <- agent/runtime/results/task_20261020_0026.json（kmeans）
 *   classification_real.json <- docs/迭代二/交付/分类结果样例.json（gnb，历史不足回退）
 *   dr_real.json             <- agent/runtime/results/task_20261020_0045.json（pca）
 */

import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RENDER_SRC = path.resolve(__dirname, '../../frontend/public/js/render.js');
const FIXTURES = path.resolve(__dirname, 'fixtures');

class El {
  constructor() {
    this.innerHTML = '';
    this.textContent = '';
    this.className = '';
    this.style = {};
    this.classList = {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    };
  }
}
const registry = {};
global.document = {
  querySelector(sel) {
    if (!registry[sel]) registry[sel] = new El();
    return registry[sel];
  },
  querySelectorAll() { return []; },
};
function resetDom() { for (const k in registry) delete registry[k]; }

const code = fs.readFileSync(RENDER_SRC, 'utf8');
const factory = new Function(code + '\nreturn Render;');
const Render = factory();

function fixture(name) {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), 'utf8'));
}

let passed = 0, failed = 0;
function test(name, fn) {
  resetDom();
  try { fn(); passed++; console.log('  PASS  ' + name); }
  catch (e) { failed++; console.error('  FAIL  ' + name + '\n        ' + e.message); }
}

// 渲染结果 HTML。注意 esc() 会把 "<=" 转成 "&lt;="，断言口径原文时按转义后形式比对。
function visibleText() {
  return document.querySelector('#analysisResults').innerHTML;
}

console.log('前端渲染契约测试（真实字段驱动） (tests/frontend/test_render_contract.mjs)\n');

test('聚类：群体归属按 status 判定，噪声/历史不足不再整列 "—"', () => {
  const real = fixture('clustering_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(!/<td>—<\/td>/.test(html), '归属表不应出现整列 — 占位');
  assert.ok(html.includes('正常归属'), 'SUCCESS 应中文化为"正常归属"');
  assert.ok(html.includes('训练期无记录'), 'NO_TRAIN_HISTORY 应显示为"训练期无记录"');
});

test('聚类：历史不足用户单列并可显示 note 原文与"可靠性低"徽标', () => {
  const real = fixture('clustering_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(html.includes('未归属用户'), '应有"未归属用户"分区');
  assert.ok(html.includes('无法构造画像向量'), '应显示 note 原文');
  assert.ok(html.includes('可靠性低'), 'reliability_low=true 应有徽标');
});

test('聚类：群体摘要用真实统计字段拼装（不再找 summary/preference_summary/explanation）', () => {
  const real = fixture('clustering_real.json');
  Render.analysis(real);
  const html = visibleText();
  const c0 = real.results[0].cluster_summaries[0];
  assert.ok(html.includes('平均评分'), '应有平均评分');
  assert.ok(html.includes(c0.avg_rating_mean.toFixed(2)), '平均评分应来自 avg_rating_mean');
  assert.ok(html.includes(c0.n_ratings_mean.toFixed(1)), '人均评分数应来自 n_ratings_mean');
  assert.ok(html.includes('高分占比'), '应有高分占比');
  assert.ok(html.includes('活跃跨度'), '应有活跃跨度');
  assert.ok(html.includes('action'), '类型占比必须渲染');
  assert.ok(html.includes(c0.top_genre_shares[0].genre), '类型名应来自 top_genre_shares');
});

test('聚类：代表性作品必须渲染（此前完全缺失）', () => {
  const real = fixture('clustering_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(html.includes('Star Wars'), '代表性作品标题必须渲染');
  assert.ok(html.includes('682'), '群内评分≥4 人数必须渲染');
});

test('聚类：summary_basis 口径原文必须可见', () => {
  const real = fixture('clustering_real.json');
  Render.analysis(real);
  const html = visibleText();
  // 口径原文含 ">="，esc() 会转义为 "&gt;="，按转义后形式比对
  const basis = real.results[0].cluster_summaries[0].summary_basis;
  const escapedBasis = basis.replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  assert.ok(html.includes(escapedBasis), 'summary_basis 原文必须可见（按转义后形式比对）');
});

test('聚类：整体渲染不出现 "—" 占位（不把"未执行"当"读不出来"）', () => {
  const real = fixture('clustering_real.json');
  Render.analysis(real);
  const html = document.querySelector('#analysisResults').innerHTML;
  assert.ok(!/\u2014/.test(html), '渲染结果不应出现 — 占位符');
});

test('聚类：null 指标显示"不适用"，不补 0', () => {
  const real = fixture('clustering_real.json');
  real.results[0].metrics = { ...real.results[0].metrics, silhouette_full: null, sse_full: null };
  Render.analysis(real);
  const html = visibleText();
  assert.ok(html.includes('不适用'), 'null 指标应显示"不适用"');
});

test('分类：评价指标不再渲染成原始 JSON 字符串', () => {
  const real = fixture('classification_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(!html.includes('{"threshold"'), '不得出现原始 JSON 片段');
  assert.ok(html.includes('决策阈值'), '应有决策阈值行');
  assert.ok(html.includes('验证期 ROC-AUC'), '应有验证期 ROC-AUC 行');
  assert.ok(html.includes('测试期 PR-AUC'), '应有测试期 PR-AUC 行');
  const m = real.results[0].metrics;   // 分类样例是算法级信封：算法字段与 metrics 在顶层
  assert.ok(html.includes(String(m.test_pr_auc)), '指标值应来自预测自身的 metrics');
});

test('分类：正类概率旁必须带"未经校准"说明', () => {
  const real = fixture('classification_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(html.includes('正类概率'), '应展示正类概率');
  assert.ok(html.includes('未经校准'), '必须提示概率未经校准');
  assert.ok(html.includes('HIGH_RATING'), '预测类别应渲染');
});

test('分类：单条预测的限制与目标 user/movie 均可见', () => {
  const real = fixture('classification_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(html.includes('本预测适用限制'), '应展示该预测的 limitations');
  assert.ok(html.includes(String(real.target.user_id)), '目标用户应渲染');
  assert.ok(html.includes(String(real.target.movie_id)), '目标电影应渲染');
});

test('实验对照：数据切分方式必须展示（需求第 6 项）', () => {
  const real = fixture('classification_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(html.includes('数据切分版本'), '应有数据切分版本');
  assert.ok(html.includes(real.split_version), '应取真实 split_version');
  assert.ok(html.includes('训练集') && html.includes('验证集') && html.includes('测试集'),
    '应展示训练/验证/测试三段的切分条件');
  assert.ok(html.includes('Timestamp &lt;= T1'), '训练集条件口径原文（按转义后形式比对）');
});

test('降维：主成分载荷表必须渲染（轴含义依据）', () => {
  const real = fixture('dr_real.json');
  Render.analysis(real);
  const html = visibleText();
  const loadings = real.results[0].axis_meaning.loadings;
  assert.ok(html.includes('主成分载荷'), '应有载荷表标题');
  assert.ok(html.includes(loadings[0].component), '应展示 PC 名称');
  assert.ok(html.includes(loadings[0].top_features[0].feature), '应展示载荷特征名');
  assert.ok(html.includes('解释方差比'), '应展示解释方差比');
});

test('降维：仍保留二维图与聚类前后对照', () => {
  const real = fixture('dr_real.json');
  Render.analysis(real);
  const html = visibleText();
  assert.ok(html.includes('<svg'), '应绘制二维图');
  assert.ok(html.includes('降维前后聚类对照'), '应有前后对照');
});

test('结果获取：分析任务必须有样例区与报告/追溯区（需求第 8 项）', () => {
  ['clustering_real.json', 'classification_real.json', 'dr_real.json'].forEach(f => {
    resetDom();
    const real = fixture(f);
    if (!real.task_id) real.task_id = 'fixture-' + f;   // 分类样例自身无 task_id
    Render.analysis(real);
    const sample = document.querySelector('#analysisSample').innerHTML;
    const report = document.querySelector('#analysisReport').innerHTML;
    assert.ok(sample && sample.length > 0, `${f} 应有结果样例`);
    assert.ok(sample.includes('<table'), `${f} 样例应为表格`);
    assert.ok(report.includes('版本与追溯信息'), `${f} 应有版本追溯`);
    assert.ok(report.includes(real.task_id), `${f} 报告应含 task_id`);
  });
});

console.log(`\n结果：${passed} 通过, ${failed} 失败`);
process.exit(failed === 0 ? 0 : 1);
