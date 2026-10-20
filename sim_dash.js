const fs = require('fs');
const store = {};
function el(n) {
  return {
    innerHTML: '', textContent: '', value: '', style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {} },
    closest() { return el('c'); }, addEventListener() {}, appendChild() {},
    querySelector() { return el('q'); },
    set scrollTop(v) {}, get scrollTop() { return 0; },
    set scrollHeight(v) {}, get scrollHeight() { return 0; },
  };
}
global.document = {
  querySelector(s) { return store[s] || (store[s] = el(s)); },
  querySelectorAll() { return []; },
  createElement() { return el('x'); },
  addEventListener() {},
};
global.window = { location: { search: '' } };
global.location = { search: '' };

const src = fs.readFileSync('frontend/public/js/render.js', 'utf8');
const Render = eval(src + '\n;Render;');
const d = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
Render.analysis(d);

const html = store['#analysisResults'].innerHTML;
const idx = [...html.matchAll(/—/g)].map(m => m.index);
console.log('"—" 总数:', idx.length);
for (const i of idx.slice(0, 8)) {
  const ctx = html.slice(Math.max(0, i - 100), i + 10).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  console.log('  ...' + ctx + '...');
}
const m = html.match(/<h4>群体摘要<\/h4><ul>[\s\S]{0,800}/);
console.log('\n=== 群体摘要渲染结果 ===');
console.log((m ? m[0] : '(未找到)').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 800));

const rows = html.match(/<h4>用户群体归属<\/h4>[\s\S]{0,700}/);
console.log('\n=== 用户群体归属渲染结果 ===');
console.log((rows ? rows[0] : '(未找到)').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 400));
