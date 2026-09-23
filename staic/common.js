/* =====================================================================
   DigitalAssetsMetricsBoard 公共前端方法（三个子页面与 Index 共享）
   ---------------------------------------------------------------------
   自 staic/Liquidity.html 提取；同时挂载 window 全局与 Board 命名空间，
   页面脚本可直接使用 nfd / pc / jget / spark 等短名。
   判级阈值属于各页面的公开规则，放在各页脚本内，不在此公共层。
   ===================================================================== */
(function (global) {
  'use strict';

  /* ---- DOM / 数组 ---- */
  const $ = id => document.getElementById(id);
  const last = a => a.at(-1);
  function nearest(arr, d) {                       // 取 ≤ d 的最近观测（非交易日回退）
    let best = null;
    for (const x of arr) if (x.d <= d && (!best || x.d > best.d)) best = x;
    return best ? best.v : null;
  }
  function pctile(arr, v) {                        // v 在 arr 中的分位（0~1）；分位数评分用
    const a = arr.filter(Number.isFinite);
    if (!a.length) return null;
    return a.filter(x => x <= v).length / a.length;
  }

  /* ---- 格式化 ---- */
  const nfd = (x, dp = 1) => x == null ? '—' : x.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const pc = (x, dp = 2) => x == null ? '—' : (x > 0 ? '+' : '') + x.toFixed(dp) + '%';
  const bp = x => x == null ? '—' : (x > 0 ? '+' : '') + Math.round(x * 100) + 'bp';
  const md = d => (d || '').replace(/^\d{4}-0?/, '').replace('-', '/');            // 2026-09-16 -> 9/16
  const us = d => (d || '').replace(/^0?(\d+)\/0?(\d+)\/\d{4}$/, '$1/$2');          // 09/16/2026 -> 9/16
  const ago = d => { if (!d) return ''; const t = Date.parse(d.length === 10 ? d : d.split(' ')[0]); return Number.isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 864e5)) : ''; };

  /* ---- 风险等级常量（展示映射；阈值判定属各页规则） ---- */
  const RISK = { hi: ['r-hi', '🔴 高危'], md: ['r-md', '🟡 中性'], lo: ['r-lo', '🟢 安全'] };
  const RM = { hi: '高危', md: '中性', lo: '安全' };
  const riskColor = r => r === 'hi' ? '#f2555a' : r === 'md' ? '#e8a33d' : '#4ade80';

  /* ---- 取数：所有接口经本地服务同源中转（浏览器直取官方源必被 CORS 拦） ---- */
  async function jget(u, t = 25000) {
    const c = new AbortController(), id = setTimeout(() => c.abort(), t);
    try {
      const r = await fetch(u, { signal: c.signal, cache: 'no-store' });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || r.status);
      return j;
    } finally { clearTimeout(id); }
  }

  /* ---- SVG 基元（无图表库，全部内联） ---- */
  // 读当前主题的 CSS 变量（内联 SVG 的 fill/stroke 在生成时取值，主题切换后由页面重渲染）
  const T = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  function hex(c, a) { const n = parseInt(c.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; }
  function domOf(a, pad = .1) { const v = a.filter(Number.isFinite); if (!v.length) return [0, 1]; const mn = Math.min(...v), mx = Math.max(...v), r = (mx - mn) || 1; return [mn - r * pad, mx + r * pad]; }
  function ticksOf(mn, mx, n = 3) {
    const raw = (mx - mn) / n, pow = Math.pow(10, Math.floor(Math.log10(raw))), c = raw / pow;
    const st = (c >= 5 ? 10 : c >= 2 ? 5 : c >= 1 ? 2 : 1) * pow / 2 || raw;
    const t = []; for (let v = Math.ceil(mn / st) * st; v <= mx + 1e-9; v += st) t.push(+v.toFixed(6));
    return t;
  }
  function svgPath(vals, w, h, pad, dom) {
    const mn = dom ? dom[0] : Math.min(...vals), mx = dom ? dom[1] : Math.max(...vals), r = (mx - mn) || 1;
    const st = (w - pad * 2) / (vals.length - 1);
    return vals.map((v, i) => `${i ? 'L' : 'M'}${(pad + i * st).toFixed(1)},${(h - pad - (v - mn) / r * (h - pad * 2)).toFixed(1)}`).join(' ');
  }
  function spark(vals, color) {
    const a = (vals || []).filter(x => Number.isFinite(x));
    if (a.length < 2) return '';
    return `<svg class="spark" viewBox="0 0 200 26" preserveAspectRatio="none" width="100%" height="26" aria-hidden="true"><path d="${svgPath(a, 200, 26, 3)}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }
  /* 通用折线图：rows=[{d,v}]，dates 取首/中/末三个标签。dom 给了就用它当纵轴范围（放大图按分位截断用），
     不给则按数据全域上下各留 16%。 */
  function lineChart(el, rows, { color = '#d4af37', w = 680, h = 200, pad = 34, fmt = md, area = true, aria = '', dom = null } = {}) {
    if (!el) return;
    const v = rows.map(x => x.v);
    if (v.filter(Number.isFinite).length < 2) { el.innerHTML = ''; return; }
    const [mn, mx] = (dom && dom.length === 2 && Number.isFinite(dom[0]) && Number.isFinite(dom[1])) ? dom : domOf(v, .16);
    const Y = x => h - pad - (x - mn) / (mx - mn) * (h - pad * 2);
    const st = (w - pad * 2) / (v.length - 1), X = i => pad + st * i;
    let g = '';
    ticksOf(mn, mx, 3).forEach(t => { g += `<line x1="${pad}" x2="${w - pad}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="${T('--grid')}" stroke-dasharray="3 4"/><text x="${pad - 5}" y="${(Y(t) + 3.5).toFixed(1)}" fill="${T('--tick')}" font-size="9" text-anchor="end" font-family="monospace">${t}</text>`; });
    const ln = v.map((x, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(x).toFixed(1)}`).join(' ');
    const lbl = [0, Math.floor(v.length / 2), v.length - 1]
      .map(i => `<text x="${X(i).toFixed(1)}" y="${h - 8}" fill="${i === v.length - 1 ? T('--lbl') : T('--tick')}" font-size="9" text-anchor="middle" font-family="monospace">${fmt(rows[i].d)}</text>`).join('');
    el.innerHTML = `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${aria}">
      ${g}${area ? `<path d="${ln} L${X(v.length - 1).toFixed(1)},${h - pad} L${pad},${h - pad} Z" fill="${hex(color, .08)}"/>` : ''}
      <path d="${ln}" fill="none" stroke="${color}" stroke-width="2"/>
      <circle cx="${X(v.length - 1).toFixed(1)}" cy="${Y(v[v.length - 1]).toFixed(1)}" r="3.2" fill="${color}"/>
      ${lbl}</svg>`;
  }

  /* ---- 实时/快照角标：● 实时 才是取到了当前值；○ 快照 一律不得冒充实时值 ---- */
  function cadb(live, src, asOf) {
    const a = ago(asOf);
    const n = asOf ? (a !== '' ? ` · 截至 ${md(asOf)}（${a} 天前）` : ` · ${asOf}`) : '';
    return live
      ? `<div class="cadb live">● 实时 ${src || ''}${n}</div>`
      : `<div class="cadb">○ 快照 ${src || ''}${n}</div>`;
  }

  /* ---- 顶栏：看板导航 + 状态行 + 自动刷新 ---- */
  // Index.html 在项目根、子页在 staic/：ROOT 回到项目根，SUB 进入子页目录
  const IN_SUB = /\/staic\//i.test(location.pathname);
  const ROOT = IN_SUB ? '../' : '';
  const SUB = IN_SUB ? '' : 'staic/';
  const PAGES = [
    { id: 'index', href: ROOT + 'Index.html', label: '看板主页' },
    { id: 'btc', href: SUB + 'btc.html', label: 'BTC监控' },
    { id: 'liquidity', href: SUB + 'Liquidity.html', label: '宏观流动性' },
    { id: 'crash', href: SUB + 'USStockCrashMonitor.html', label: '美股崩盘监测' },
    { id: 'allocation', href: SUB + 'GlobalQualityAssetAllocation.html', label: '资产配置' },
  ];
  function nav(el) {
    const node = typeof el === 'string' ? $(el) : el;
    if (!node) return;
    const here = (decodeURIComponent(location.pathname).split('/').pop() || '').toLowerCase();
    node.innerHTML = PAGES.map(p =>
      `<a href="${p.href}"${p.href.toLowerCase().endsWith(here) ? ' class="on"' : ''}>${p.label}</a>`).join('');
  }
  function setStatus(id, msg, cls) { const s = $(id); if (s) { s.className = 'ls ' + (cls || ''); s.textContent = msg; } }
  function autoSync(fn, ms = 60000) {       // 60 秒自动同步；标签页切走时暂停，切回立即补一次
    let timer = setInterval(() => { if (document.visibilityState === 'visible') fn(); }, ms);
    document.addEventListener('visibilitychange', () => {
      clearInterval(timer);
      if (document.visibilityState === 'visible') fn();
      timer = setInterval(() => { if (document.visibilityState === 'visible') fn(); }, ms);
    });
  }

  /* ---- 亮/暗主题一键切换：状态存 localStorage['board-theme']，<head> 内联片段负责无闪烁初值 ---- */
  const THEME_KEY = 'board-theme';
  const isLight = () => document.documentElement.dataset.theme === 'light';
  function themeLabel(btn) {
    btn.textContent = isLight() ? '☾ 深色' : '☀ 亮色';   // 按钮显示点击后将切入的主题
    btn.setAttribute('aria-pressed', String(isLight()));
    btn.title = '一键切换亮色 / 深色主题';
  }
  function initTheme() {
    const bar = document.querySelector('.lbar'); if (!bar) return;
    const btn = document.createElement('button');
    btn.className = 'rf'; btn.id = 'theme-sw'; btn.type = 'button';
    themeLabel(btn);
    btn.addEventListener('click', () => {
      const next = isLight() ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* 无痕模式降级：本次会话内仍有效 */ }
      themeLabel(btn);
      dispatchEvent(new Event('themechange'));         // 图表 SVG 的取色在生成时写死，页面监听此事件重渲染
    });
    bar.insertBefore(btn, bar.firstChild);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initTheme);
  else initTheme();

  /* status 不设为全局：window.status 是浏览器历史遗留字符串属性，赋值会被强制转成字符串 */
  const Board = { $, last, nearest, pctile, nfd, pc, bp, md, us, ago,
                  RISK, RM, riskColor, jget, hex, domOf, ticksOf, svgPath, spark, lineChart,
                  cadb, nav, setStatus, autoSync, PAGES, T, initTheme };
  const { status: _omit, ...globals } = Board;
  Object.assign(global, globals);
  global.Board = Board;
})(window);
