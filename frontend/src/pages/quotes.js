import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {quotesAPI, nodesAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {esc} from '../utils/html.js';
import {message} from '../hooks/action.js';

// 页面级状态：游标固定后，翻页永远读打开时的旧价与旧版本。
const view = {columns: null, current: null, pages: [], cursor: null, done: false, note: '', swapRequestId: null, failover: null, flash: null};

export function resetQuoteView() {
  Object.assign(view, {columns: null, current: null, pages: [], cursor: null, done: false, note: '', swapRequestId: null, failover: null, flash: null});
}

const pageTable = p => table(['序号', '标的物', '价格', '版本', '列代', '读取时刻'],
  p.rows.map(r => [r.seq, esc(r.symbol), r.price ?? '—', `v${r.version ?? '—'}`, `g${r.generation}`,
    new Date().toLocaleTimeString('zh-CN')]));

function columnsLine() {
  if (!view.columns) return '<span class="chip">尚未载入报价列</span>';
  return view.columns.columns.map(c =>
    `<span class="chip ${c.status}">g${c.generation} · ${esc(c.label)} · ${c.status === 'active' ? '生效' : '已退役'}</span>`).join(' ');
}

function failoverBlock() {
  const f = view.failover;
  if (!f) return '';
  const verdict = f.decision === 'approved' ? `允许切主 · 接任 ${esc(f.winner)}`
    : f.decision === 'deferred' ? '暂缓切主' : '安全阻断';
  return `<section class="verdict"><div><p>游标感知切主</p><h2>${verdict}</h2></div>
    <p>${esc(f.defer_reason || (f.winner ? '旧价数据完整，可接住所有游标' : '检查规则'))}<br>
    ${f.open_cursors?.length ? `未读完旧游标 ${f.open_cursors.length} 个` : '无未读完旧游标'}</p></section>
    ${table(['规则', '判定', '证据'], f.checks.map(c => [esc(c.rule), c.pass ? '通过' : '阻断', esc(c.evidence)]))}`;
}

export function quotesPage() {
  const canWrite = session.role !== 'viewer';
  const canAdmin = session.role === 'admin';
  const active = view.columns?.active_generation;
  const successors = store.nodes.filter(n => n.role !== 'leader');
  return `
<section class="split compact"><div>
  <h2>报价口径沙盘</h2>
  <p>逻辑列名始终是 <code>price</code>。换列只新增一代物理列并把旧代退役：新查询立即读新价，旧游标继续读打开时的旧价；改价追加版本，不覆盖历史。</p>
  <p class="big-note">新查询读新价 · 旧游标读旧价</p>
  <div class="chips">${columnsLine()}</div>
</div><div>
  ${view.flash ? `<div class="notice ${view.flash.error ? 'error' : ''}">${esc(view.flash.text)}</div>` : ''}
  <div class="panel"><h3>改价（活跃列 g${active ?? '—'}）</h3>
  ${canAdmin ? `<form id="price-form" class="inline-form">
    <label>标的物<select name="symbol">${(view.current?.rows || []).map(r => `<option value="${esc(r.symbol)}">${esc(r.symbol)}</option>`).join('')}</select></label>
    <label>新价<input name="value" type="number" min="0" value="1200" required></label>
    <button type="submit">写入新版本</button></form>` : '<p class="readonly">改价需管理员账号。</p>'}
  </div>
  <div class="panel"><h3>换列与故障模拟</h3>
  ${canAdmin ? '<button id="swap">换列到新口径 →</button>' : ''}
  ${canWrite ? `<button class="secondary" id="reclaim">回收旧数据</button>
    <button class="secondary" id="failover">模拟切主</button>
    ${canAdmin ? `<label class="check"><input type="checkbox" id="drop-legacy"> 让备库缺旧数据（${successors.map(n => esc(n.name)).join('、') || '无备库'}）</label>` : ''}` : '<p class="readonly">观察员可查看并翻页。</p>'}
  </div>
</div></section>

<div class="section-title"><h2>快照游标分页</h2><span>${view.pages.length} 页 · ${view.pages.reduce((n, p) => n + p.rows.length, 0)} 行</span></div>
<div class="toolbar">
  <button id="open-cursor">${view.pages.length ? '重新开始' : '打开新查询'}</button>
  <button class="secondary" id="next-page" ${view.done ? 'disabled' : ''}>读取下一页 →</button>
  <button class="secondary" id="close-cursor" ${view.cursor ? '' : 'disabled'}>关闭游标</button>
</div>
${view.note ? `<div class="notice">${esc(view.note)}</div>` : ''}
${view.pages.length ? view.pages.map((p, i) => `<div class="page-block">
  <div class="page-head">第 ${i + 1} 页 · 列「${esc(p.column_label)}」 g${p.cursor.generation} · 快照版本 v${p.cursor.snapshot_version}</div>
  ${pageTable(p)}</div>`).join('') : '<p class="readonly">点击「打开新查询」开始。之后无论改价还是换列，本次分页都读打开时的价格与版本。</p>'}
${failoverBlock()}
`;
}

export function bindQuotes(render) {
  const on = (sel, ev, fn) => document.querySelector(sel)?.addEventListener(ev, fn);
  const flash = (text, error = false) => { view.flash = {text, error}; render(); };
  // 首次进入尚无行数据时惰性载入，让改价下拉框可用。
  if (!view.current || !view.columns) {
    Promise.all([quotesAPI.rows(), quotesAPI.columns()]).then(([rows, columns]) => {
      view.current = rows; view.columns = columns; render();
    }).catch(e => message(e.message, true));
  }
  on('#open-cursor', 'click', async () => {
    try {
      const p = await quotesAPI.page(4);
      Object.assign(view, {
        pages: [p], cursor: p.next_cursor, done: p.done, note: p.note,
        columns: await quotesAPI.columns(), current: await quotesAPI.rows(), failover: null,
      });
      render();
    } catch (e) { message(e.message, true); }
  });
  on('#next-page', 'click', async () => {
    try {
      const p = await quotesAPI.page(4, view.cursor);
      view.pages.push(p); view.cursor = p.next_cursor; view.done = p.done; view.note = p.note;
      render();
    } catch (e) { message(e.message, true); }
  });
  on('#close-cursor', 'click', async () => {
    try { await quotesAPI.closeCursor(view.cursor); view.cursor = null; view.done = true; message('游标已关闭，旧数据可被回收'); render(); }
    catch (e) { message(e.message, true); }
  });
  on('#price-form', 'submit', async e => {
    e.preventDefault(); const f = e.target;
    try {
      const out = await quotesAPI.setPrice(f.elements.symbol.value, Number(f.elements.value.value));
      view.current = await quotesAPI.rows(); flash(`已写入 ${out.symbol} = ${out.price}（版本 v${out.version}，列 g${out.generation}）`);
    } catch (e) { message(e.message, true); }
  });
  on('#swap', 'click', async () => {
    // 复用同一个 request_id：落盘后中断，再次点击也只换一次列。
    view.swapRequestId ||= 'swap-' + Date.now() + '-' + Math.random().toString(16).slice(2);
    try {
      const out = await quotesAPI.swap(view.swapRequestId, '换列 ' + new Date().toLocaleTimeString('zh-CN'));
      view.swapRequestId = null;
      view.columns = await quotesAPI.columns(); view.current = await quotesAPI.rows();
      flash(`已换列：g${out.swap.from_generation} → g${out.swap.to_generation}${out.swap.replayed ? '（幂等重放，未重复换列）' : ''}`);
    } catch (e) { message(e.message + '（重试将复用同一 request_id）', true); }
  });
  on('#reclaim', 'click', async () => {
    try {
      const out = await quotesAPI.reclaim();
      view.columns = await quotesAPI.columns(); flash(`回收完成：删除 ${out.removed_versions} 条旧版本；为 ${out.open_cursors} 个打开游标保留所需旧数据。`);
    } catch (e) { message(e.message, true); }
  });
  on('#failover', 'click', async () => {
    try {
      view.failover = await quotesAPI.failover(store.scenarios[0]?.id);
      flash(view.failover.decision === 'deferred' ? '接不住旧游标，已暂缓切主'
        : view.failover.decision === 'blocked' ? '安全规则未通过，已阻断' : '可以安全切主',
        view.failover.decision === 'blocked');
    } catch (e) { message(e.message, true); }
  });
  on('#drop-legacy', 'change', async e => {
    const missing = e.target.checked;
    try {
      for (const n of store.nodes.filter(n => n.role !== 'leader')) {
        await nodesAPI.save({...n, has_legacy: !missing}, n.id);
      }
      await store.refresh();
      view.flash = {text: `备库 has_legacy 已设为 ${!missing}；切换主前会检查接任副本是否保留旧价`, error: false};
      render();
    } catch (err) { message(err.message, true); }
  });
}
