/* 前端渲染逻辑单元测试（成员C）
 *
 * 运行：node tests/frontend/test_render.mjs
 * 零依赖：使用 Node 内置 assert + 极简 DOM stub。
 *
 * 覆盖点：
 *   1. 五维表：清洗前/后/变化 三列数值正确，缺失值显示为 "—" 而非 0
 *   2. 变化方向着色：涨=up 跌=down 平=flat
 *   3. 综合分（overall）仅在接口提供时才渲染
 *   4. 统计区：null 显示 "—"
 *   5. 问题列表：动作标签（修复/去重/隔离）与名称
 *   6. 未解决问题计数
 *   7. 版本/T1/T2 渲染
 *   8. HTML 注入转义（XSS 防护）
 */

import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RENDER_SRC = path.resolve(__dirname, '../../frontend/public/js/render.js');

// ---------- 极简 DOM stub ----------
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

// ---------- 加载被测算模块 ----------
const code = fs.readFileSync(RENDER_SRC, 'utf8');
const factory = new Function(code + '\nreturn Render;');
const Render = factory();

let passed = 0, failed = 0;
function test(name, fn) {
  resetDom();
  try { fn(); passed++; console.log('  PASS  ' + name); }
  catch (e) { failed++; console.error('  FAIL  ' + name + '\n        ' + e.message); }
}

function fullResult() {
  return {
    task_id: 'task_20260926_0001',
    status: 'SUCCESS',
    data_version: 'movielens-1m-v2-clean-v1',
    rule_version: 'rule-v2',
    T1: '2000-11-22', T2: '2000-12-10',
    before_score: { accurate: 97.74, complete: 97.99, unique: 99.47,
                    up_to_date: 29.59, consistent: 96.79, overall: 91.01 },
    after_score:  { accurate: 99.95, complete: 100.0, unique: 100.0,
                    up_to_date: 21.21, consistent: 99.92, overall: 92.09 },
    score_change: { accurate: 2.2083, complete: 2.0094, unique: 0.525,
                    up_to_date: -8.3746, consistent: 3.1254 },
    statistics: { before_count: 1161652, after_count: 1006021,
                  fixed_count: 65, deduplicated_count: 55739, isolated_count: 99892,
                  conflict_key_count: 4328 },
    weights: { accurate: 0.25, complete: 0.25, unique: 0.15,
               up_to_date: 0.1, consistent: 0.25 },
    problems: [
      { code: 'x', action: 'isolate', severity: 'high', count: 9377,
        subject: 'ratings.UserID 不是正整数', reason: '格式异常' },
      { code: 'y', action: 'fix', severity: 'low', count: 47,
        subject: '标题含空白', reason: '可安全去除' },
    ],
    unresolved_problems: [
      { code: 'clean_conflict_keys', action: 'dedupe', count: 4328,
        subject: '主键冲突', reason: '未真正解决' },
    ],
    report: {
      method: { summary: '违规率扣分模型', weights: { accurate: 0.25 } },
      improvements: [{ dimension: 'accurate', dimension_cn: '准确性',
                       description: '准确性提升' }],
      unresolved: [{ subject: '主键冲突', disposition: '仅确定性选择' }],
      limitations: [{ topic: '时区', detail: '未声明时区' }],
    },
  };
}

console.log('前端渲染逻辑测试 (tests/frontend/test_render.mjs)\n');

test('五维表渲染 5 行，含前后与变化数值', () => {
  const r = fullResult();
  Render.scores(r);
  const html = document.querySelector('#scoreBody').innerHTML;
  assert.strictEqual((html.match(/<tr>/g) || []).length, 5, '应有 5 行维度');
  assert.ok(html.includes('97.74'), '应含清洗前 accurate');
  assert.ok(html.includes('99.95'), '应含清洗后 accurate');
  assert.ok(html.includes('+2.2083'), '应含变化 +2.2083');
});

test('变化方向着色：涨/跌/平', () => {
  const r = fullResult();
  Render.scores(r);
  const html = document.querySelector('#scoreBody').innerHTML;
  assert.ok(html.includes('delta up'), 'accurate 应标 up');
  assert.ok(html.includes('delta down'), 'up_to_date 应标 down');
});

test('综合分 overall 提供时渲染', () => {
  Render.scores(fullResult());
  const oc = document.querySelector('#overallBody').innerHTML;
  assert.ok(oc.includes('91.01'), '应含 before overall');
  assert.ok(oc.includes('92.09'), '应含 after overall');
  assert.ok(!document.querySelector('#overallRow').classList.contains('hidden'));
});

test('缺失分数显示 "—" 而非 0（只评估不清洗场景）', () => {
  const r = fullResult();
  r.after_score = {}; r.score_change = {};
  r.statistics = { before_count: 1161652, after_count: null,
                   fixed_count: null, deduplicated_count: null, isolated_count: null };
  Render.scores(r);
  Render.statistics(r);
  const scoreHtml = document.querySelector('#scoreBody').innerHTML;
  const statHtml = document.querySelector('#statGrid').innerHTML;
  assert.ok(scoreHtml.includes('—'), '五维表应显示占位符');
  assert.ok(statHtml.includes('—'), '统计区应显示占位符');
  // 关键：不能把未执行的 after 显示成 0
  assert.ok(!/<td>0<\/td>/.test(scoreHtml), '不得把缺失值渲染为 0');
});

test('统计区显示修复/去重/隔离与未解决冲突主键', () => {
  Render.statistics(fullResult());
  const html = document.querySelector('#statGrid').innerHTML;
  assert.ok(html.includes('修复'));
  assert.ok(html.includes('去重'));
  assert.ok(html.includes('隔离'));
  assert.ok(html.includes('未解决冲突主键'));
  assert.ok(html.includes('4,328'));
});

test('问题列表动作标签中文化', () => {
  Render.problems(fullResult());
  const html = document.querySelector('#problemBox').innerHTML;
  assert.ok(html.includes('隔离'), 'isolate -> 隔离');
  assert.ok(html.includes('修复'), 'fix -> 修复');
  assert.ok(html.includes('ratings.UserID 不是正整数'));
});

test('未解决问题计数正确', () => {
  Render.problems(fullResult());
  assert.strictEqual(document.querySelector('#unresolvedCount').textContent, '1');
  const html = document.querySelector('#unresolvedBox').innerHTML;
  assert.ok(html.includes('主键冲突'));
});

test('版本与 T1/T2 渲染', () => {
  Render.versions(fullResult());
  const html = document.querySelector('#versionGrid').innerHTML;
  assert.ok(html.includes('movielens-1m-v2-clean-v1'));
  assert.ok(html.includes('rule-v2'));
  assert.ok(html.includes('2000-11-22'));
  assert.ok(html.includes('2000-12-10'));
});

test('评估报告四段渲染', () => {
  Render.report(fullResult());
  const html = document.querySelector('#reportBox').innerHTML;
  assert.ok(html.includes('准确性'), '改善项');
  assert.ok(html.includes('主键冲突'), '未解决');
  assert.ok(html.includes('时区'), '局限');
});

test('HTML 注入被转义（XSS 防护）', () => {
  const r = fullResult();
  r.problems = [{ code: 'x', action: 'keep', severity: 'info', count: 1,
                  subject: '<img src=x onerror=alert(1)>', reason: '</script>' }];
  Render.problems(r);
  const html = document.querySelector('#problemBox').innerHTML;
  assert.ok(!html.includes('<img src=x'), '原始 <img> 不应出现');
  assert.ok(html.includes('&lt;img'), '应被转义');
});

test('未知状态阶段容错', () => {
  Render.status({ task_id: 't1', status: 'RUNNING', stage: 'CLEANING',
                  message: '正在执行' });
  assert.strictEqual(document.querySelector('#statusBadge').textContent, '运行中');
});

console.log(`\n结果：${passed} 通过, ${failed} 失败`);
process.exit(failed === 0 ? 0 : 1);
