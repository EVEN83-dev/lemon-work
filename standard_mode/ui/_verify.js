// 浏览器脚本加载模拟：所有 <script> 在全局作用域共享 var/function/直接赋值
// 关键：浏览器中顶层 var/function 都挂到全局 window；这里用同一个 global context 串联执行
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const dir = __dirname;
const noop = () => {};
const ctx2d = new Proxy({}, {
  get: (t, p) => {
    if (p === 'createLinearGradient' || p === 'createRadialGradient')
      return () => ({ addColorStop: noop });
    if (p === 'getImageData') return () => ({ data: [] });
    if (p === 'canvas') return { width: 1920, height: 1080 };
    return noop;
  },
  set: () => true,
});
const fakeEl = new Proxy({}, {
  get: (t, p) => {
    if (p === 'style') return {};
    if (p === 'classList') return { add: noop, remove: noop, toggle: noop, contains: () => false };
    if (p === 'getContext') return () => ctx2d;
    if (p === 'addEventListener') return noop;
    if (p === 'appendChild') return noop;
    if (p === 'setAttribute') return noop;
    if (p === 'getAttribute') return () => null;
    if (p === 'querySelector') return () => fakeEl;
    if (p === 'querySelectorAll') return () => [];
    if (p === 'width' || p === 'height') return 800;
    return noop;
  },
  set: () => true,
});
const ctx = {
  console,
  document: {
    getElementById: () => fakeEl,
    querySelector: () => fakeEl,
    querySelectorAll: () => [],
    addEventListener: noop,
    createElement: () => fakeEl,
    createTextNode: () => fakeEl,
    body: fakeEl,
  },
  setTimeout, clearTimeout, setInterval, clearInterval,
  navigator: { userAgent: 'node' },
  requestAnimationFrame: (cb) => setTimeout(cb, 0),
  Math, Date, JSON, Object, Array, String, Number, Boolean, RegExp, Error, TypeError,
};
ctx.window = ctx; // 浏览器里 window === global
ctx.self = ctx;
ctx.addEventListener = noop;
ctx.removeEventListener = noop;
ctx.dispatchEvent = noop;
ctx.localStorage = { getItem: () => null, setItem: noop, removeItem: noop };
ctx.location = { href: '', search: '', hash: '' };
ctx.performance = { now: () => Date.now() };
ctx.fetch = () => Promise.resolve({ json: () => Promise.resolve({}), text: () => Promise.resolve('') });
vm.createContext(ctx);

function read(file) {
  const p = path.join(dir, file);
  if (!fs.existsSync(p)) { console.log('[skip] 不存在:', file); return ''; }
  const code = fs.readFileSync(p, 'utf8');
  console.log('[ok] read', file, '(' + code.length + ' bytes)');
  return '\n// ===== ' + file + ' =====\n' + code;
}

// 浏览器加载顺序（来自 mimo_page.html）：所有 <script> 共享同一全局词法环境
// 拼接成单一脚本后一次性执行，顶层 var/function 才能像真实浏览器那样互通
try {
  const combined = read('svg_icons.js') + read('mimo_core.js') + read('mimo_app.js');
  vm.runInContext(combined, ctx, { filename: 'combined.html-scripts' });
  console.log('=== 全部脚本加载完成 ===');
  console.log('typeof SVG_ICONS =', typeof ctx.SVG_ICONS, '(keys:', ctx.SVG_ICONS ? Object.keys(ctx.SVG_ICONS).length : 0, ')');
  console.log('typeof MIEMIE_SVG =', typeof ctx.MIEMIE_SVG, '(file_default:', ctx.MIEMIE_SVG ? typeof ctx.MIEMIE_SVG.file_default : 'N/A', ')');
  console.log('typeof initStarfield =', typeof ctx.initStarfield);
  console.log('typeof render =', typeof ctx.render);
  console.log('typeof ThemeManager =', typeof ctx.ThemeManager);
  // 触发主题应用/星空初始化（如果 ThemeManager 存在）
  if (typeof ctx.ThemeManager !== 'undefined' && ctx.ThemeManager && typeof ctx.ThemeManager.init === 'function') {
    try { ctx.ThemeManager.init(); console.log('[ok] ThemeManager.init() 执行成功'); }
    catch (e) { console.log('[err] ThemeManager.init():', e.message); }
  }
  console.log('=== mimo_app.js OK ===');
} catch (e) {
  console.log('=== 脚本执行错误 ===');
  console.log(e && e.stack ? e.stack : e);
  console.log('--- 中断后检查已执行的全局状态 ---');
  console.log('typeof MIEMIE_SVG =', typeof ctx.MIEMIE_SVG, ctx.MIEMIE_SVG ? 'keys='+Object.keys(ctx.MIEMIE_SVG).length : '');
  console.log('typeof SVG_ICONS =', typeof ctx.SVG_ICONS, ctx.SVG_ICONS ? 'keys='+Object.keys(ctx.SVG_ICONS).length : '');
  console.log('typeof MIEMIE_TOOL_TYPES =', typeof ctx.MIEMIE_TOOL_TYPES);
  console.log('_svgIconsAlreadyDefined =', ctx._svgIconsAlreadyDefined);
}
