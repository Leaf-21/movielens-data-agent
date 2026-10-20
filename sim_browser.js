// 模拟浏览器：完整走一遍 app.js 的渲染路径，检查页面真实内容
const fs = require('fs');

const store = {};
function el(name) {
  return {
    _n: name, innerHTML: '', textContent: '', value: '', style: {}, dataset: {},
    disabled: false,
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      toggle(c, f) { f ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    closest() { return el('closest'); },
    addEventListener() {},
    appendChild() {},
    scrollIntoView() {},
    querySelector() { return el('q'); },
    set scrollTop(v) {}, get scrollTop() { return 0; },
    set scrollHeight(v) {}, get scrollHeight() { return 0; },
  };
}
global.document = {
  querySelector(sel) {
    if (!store[sel]) store[sel] = el(sel);
    return store[sel];
  },
  querySelectorAll() { return []; },
  createElement() { return el('created'); },
  addEventListener() {},
};
global.window = { location: { search: '' } };
global.location = { search: '' };
global.fetch = async () => { throw new Error('no network'); };
global.alert = () => {};

// 加载 render.js（app.js 依赖它）
const renderSrc = fs.readFileSync('frontend/public/js/render.js', 'utf8');
const Render = eval(renderSrc + '\n;Render;');
global.Render = Render;

const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

console.log('========== 模拟 Render.analysis() ==========');
Render.analysis(data);

const meta = store['#analysisMeta'];
const results = store['#analysisResults'];

console.log('\n--- #analysisMeta 内容 ---');
console.log(meta ? meta.innerHTML.replace(/<[^>]+>/g, ' | ').replace(/\s+/g, ' ') : '(未渲染)');

console.log('\n--- #analysisResults 内容（去掉标签）---');
const text = (results ? results.innerHTML : '')
  .replace(/<[^>]+>/g, ' ')
  .replace(/&quot;/g, '"')
  .replace(/&times;/g, 'x')
  .replace(/\s+/g, ' ')
  .trim();
console.log(text.slice(0, 2500));

console.log('\n--- 是否出现大量 "—" 占位 ---');
const dashCount = (text.match(/—/g) || []).length;
console.log('"—" 出现次数:', dashCount);
