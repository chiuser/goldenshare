'use strict';

const TOKEN_KEY = 'goldenshare_ops_console_token';

const ROUTE_META = {
  overview: {
    title: '运维系统总览',
    copy: '把执行状态、失败概览和数据新鲜度放到同一张控制面里，方便我们判断今天系统到底运行得怎么样。',
  },
  freshness: {
    title: '数据新鲜度',
    copy: '基于 sync_job_state、sync_run_log 和交易日历，观察各类数据集是不是已经更新到预期业务日期。',
  },
  schedules: {
    title: '调度配置',
    copy: '把 job spec 和 workflow spec 落成真实调度实例，并保留变更历史与启停控制。',
  },
  executions: {
    title: '执行中心',
    copy: '查看执行请求、手动触发任务，并围绕 execution 统一做重试与取消。',
  },
  executionDetail: {
    title: '执行详情',
    copy: '聚焦单次 execution 的参数、步骤、事件和结果摘要，是运维排障的核心视图。',
  },
  catalog: {
    title: '资源目录',
    copy: '用注册表视角查看当前系统支持哪些 job/workflow、参数模型是什么、哪些能力允许调度。',
  },
};

let currentToken = localStorage.getItem(TOKEN_KEY) || '';
let currentSession = null;
let opsCatalogCache = null;
let latestRequestId = '';
let executionDetailAutoRefreshTimer = null;
const EXECUTION_AUTO_REFRESH_ENABLED_KEY = 'goldenshare_execution_auto_refresh_enabled';
const EXECUTION_AUTO_REFRESH_INTERVAL_KEY = 'goldenshare_execution_auto_refresh_interval';
const EXECUTION_PREFILL_KEY = 'goldenshare_execution_prefill';
const OPS_EXECUTION_FILTERS_KEY = 'goldenshare_ops_execution_filters';
const OPS_EXECUTION_LIST_CONTEXT_KEY = 'goldenshare_ops_execution_list_context';
const OPS_RECENT_EXECUTIONS_KEY = 'goldenshare_ops_recent_executions';
const SCHEDULE_EDITOR_DRAFT_KEY = 'goldenshare_ops_schedule_editor_draft';
const SCHEDULE_SELECTED_ID_KEY = 'goldenshare_ops_schedule_selected_id';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function setLatestRequestId(requestId) {
  latestRequestId = requestId || latestRequestId || '';
  const input = document.getElementById('request-id-output');
  if (input) input.value = latestRequestId || '';
}

function setNotice(message, type = '') {
  const node = document.getElementById('global-notice');
  if (!node) return;
  if (!message) {
    node.innerHTML = '';
    return;
  }
  const cls = type === 'error' ? 'notice error' : 'notice';
  node.innerHTML = `<div class="${cls}">${escapeHtml(message)}</div>`;
}

function clearActionSummary() {
  const node = document.getElementById('action-summary');
  if (node) node.innerHTML = '';
}

function setActionSummary(title, payload, tone = 'info') {
  const node = document.getElementById('action-summary');
  if (!node) return;
  const detail = typeof payload === 'string' ? payload : formatJson(payload);
  node.innerHTML = `
    <section class="panel action-summary ${tone === 'error' ? 'error' : ''}">
      <h2>${escapeHtml(title)}</h2>
      <p class="muted">最近一次控制台操作结果会展示在这里，方便我们复核本次动作到底改了什么。</p>
      <pre>${escapeHtml(detail)}</pre>
    </section>
  `;
}

function setViewContent(html) {
  const root = document.getElementById('ops-view-root');
  root.innerHTML = html;
  root.onclick = null;
}

function clearExecutionDetailAutoRefresh() {
  if (executionDetailAutoRefreshTimer) {
    window.clearTimeout(executionDetailAutoRefreshTimer);
    executionDetailAutoRefreshTimer = null;
  }
}

function readJsonStorage(storage, key, fallback) {
  const raw = storage.getItem(key);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writeJsonStorage(storage, key, value) {
  storage.setItem(key, JSON.stringify(value));
}

function compactObject(input) {
  return Object.fromEntries(
    Object.entries(input || {}).filter(([, value]) => value !== '' && value !== null && value !== undefined),
  );
}

function saveExecutionPrefill(prefill) {
  sessionStorage.setItem(EXECUTION_PREFILL_KEY, JSON.stringify(prefill));
}

function consumeExecutionPrefill() {
  const raw = sessionStorage.getItem(EXECUTION_PREFILL_KEY);
  if (!raw) return null;
  sessionStorage.removeItem(EXECUTION_PREFILL_KEY);
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function normalizeExecutionFilters(filters = {}) {
  return compactObject({
    status: String(filters.status || '').trim(),
    trigger_source: String(filters.trigger_source || '').trim(),
    spec_key: String(filters.spec_key || '').trim(),
  });
}

function saveExecutionFilters(filters) {
  writeJsonStorage(localStorage, OPS_EXECUTION_FILTERS_KEY, normalizeExecutionFilters(filters));
}

function loadExecutionFilters() {
  return normalizeExecutionFilters(readJsonStorage(localStorage, OPS_EXECUTION_FILTERS_KEY, {}));
}

function executionRouteFromFilters(filters) {
  const normalized = normalizeExecutionFilters(filters);
  const search = new URLSearchParams(normalized);
  const query = search.toString();
  return query ? `/ops/executions?${query}` : '/ops/executions';
}

function rememberExecutionListContext(filters) {
  const route = executionRouteFromFilters(filters);
  localStorage.setItem(OPS_EXECUTION_LIST_CONTEXT_KEY, route);
  saveExecutionFilters(filters);
  const currentUrl = `${window.location.pathname}${window.location.search}`;
  if (currentUrl !== route) {
    window.history.replaceState({}, '', route);
    syncRouteMeta();
  }
}

function loadExecutionListContext() {
  return localStorage.getItem(OPS_EXECUTION_LIST_CONTEXT_KEY) || '/ops/executions';
}

function recentExecutions() {
  return readJsonStorage(localStorage, OPS_RECENT_EXECUTIONS_KEY, []);
}

function rememberRecentExecution(item) {
  if (!item?.id) return;
  const normalized = {
    id: Number(item.id),
    spec_display_name: item.spec_display_name || item.spec_key || `execution #${item.id}`,
    status: item.status || 'unknown',
    requested_at: item.requested_at || null,
    viewed_at: new Date().toISOString(),
  };
  const merged = [
    normalized,
    ...recentExecutions().filter((candidate) => Number(candidate.id) !== normalized.id),
  ].slice(0, 6);
  writeJsonStorage(localStorage, OPS_RECENT_EXECUTIONS_KEY, merged);
}

function recentExecutionsPanelHtml() {
  const items = recentExecutions();
  if (!items.length) {
    return `
      <section class="panel">
        <h2>最近查看</h2>
        <div class="empty">最近还没有查看过 execution。后面我们排障时，这里会自动形成快捷入口。</div>
      </section>
    `;
  }
  const rows = items
    .map(
      (item) => `
        <tr>
          <td><a href="/ops/executions/${item.id}"><code>#${item.id}</code></a></td>
          <td>${escapeHtml(item.spec_display_name)}</td>
          <td>${badge(item.status)}</td>
          <td>${formatDateTime(item.viewed_at)}</td>
        </tr>
      `,
    )
    .join('');
  return `
    <section class="panel">
      <h2>最近查看</h2>
      ${tableOrEmpty(['执行', '目标', '状态', '最近查看'], rows, '最近还没有查看过 execution。')}
    </section>
  `;
}

function saveScheduleEditorDraft(draft) {
  writeJsonStorage(localStorage, SCHEDULE_EDITOR_DRAFT_KEY, draft);
}

function loadScheduleEditorDraft() {
  return readJsonStorage(localStorage, SCHEDULE_EDITOR_DRAFT_KEY, null);
}

function clearScheduleEditorDraft() {
  localStorage.removeItem(SCHEDULE_EDITOR_DRAFT_KEY);
}

function saveSelectedScheduleId(id) {
  if (id == null || id === '') {
    localStorage.removeItem(SCHEDULE_SELECTED_ID_KEY);
    return;
  }
  localStorage.setItem(SCHEDULE_SELECTED_ID_KEY, String(id));
}

function loadSelectedScheduleId() {
  const raw = localStorage.getItem(SCHEDULE_SELECTED_ID_KEY);
  return raw ? Number(raw) : null;
}

function openConfirmModal({
  title,
  copy,
  detail = '',
  confirmLabel = '确认执行',
  confirmClass = 'danger',
}) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirm-modal');
    const titleNode = document.getElementById('confirm-modal-title');
    const copyNode = document.getElementById('confirm-modal-copy');
    const detailNode = document.getElementById('confirm-modal-detail');
    const confirmButton = document.getElementById('btn-confirm-modal');
    const cancelButton = document.getElementById('btn-cancel-modal');
    if (!modal || !titleNode || !copyNode || !detailNode || !confirmButton || !cancelButton) {
      resolve(window.confirm(copy || title || '请确认操作'));
      return;
    }

    titleNode.textContent = title || '请确认操作';
    copyNode.textContent = copy || '';
    if (detail) {
      detailNode.textContent = typeof detail === 'string' ? detail : formatJson(detail);
      detailNode.classList.remove('hidden');
    } else {
      detailNode.textContent = '';
      detailNode.classList.add('hidden');
    }
    confirmButton.textContent = confirmLabel;
    confirmButton.className = confirmClass;
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');

    let closed = false;
    const cleanup = (result) => {
      if (closed) return;
      closed = true;
      modal.classList.add('hidden');
      modal.setAttribute('aria-hidden', 'true');
      confirmButton.removeEventListener('click', onConfirm);
      cancelButton.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKeydown);
      resolve(result);
    };
    const onConfirm = () => cleanup(true);
    const onCancel = () => cleanup(false);
    const onBackdrop = (event) => {
      if (event.target === modal) cleanup(false);
    };
    const onKeydown = (event) => {
      if (event.key === 'Escape') cleanup(false);
    };

    confirmButton.addEventListener('click', onConfirm);
    cancelButton.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKeydown);
  });
}

async function confirmThenRun(config, runner) {
  const confirmed = await openConfirmModal(config);
  if (!confirmed) {
    setNotice('已取消本次操作。');
    return null;
  }
  return runner();
}

function badge(status) {
  const text = escapeHtml(status || 'unknown');
  const normalized = String(status || 'unknown').replaceAll(' ', '_');
  return `<span class="badge status-${normalized}">${text}</span>`;
}

function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return `${date.toLocaleDateString('zh-CN')} ${date.toLocaleTimeString('zh-CN', { hour12: false })}`;
}

function formatDate(value) {
  if (!value) return '—';
  return escapeHtml(value);
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN');
}

function formatJson(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

async function callApi(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (currentToken) headers.Authorization = `Bearer ${currentToken}`;
  const response = await fetch(url, { ...options, headers });
  const requestId = response.headers.get('X-Request-ID') || '';
  setLatestRequestId(requestId);
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, requestId, body };
}

async function loadHealth() {
  const chip = document.getElementById('env-chip');
  const result = await callApi('/api/health');
  if (!chip) return;
  if (result.ok) {
    chip.textContent = `${result.body.service || 'web'} · env=${result.body.env || 'unknown'}`;
  } else {
    chip.textContent = '健康检查失败';
  }
}

function updateAuthChip() {
  const chip = document.getElementById('auth-chip');
  if (!chip) return;
  if (!currentSession) {
    chip.textContent = '尚未登录';
    return;
  }
  const role = currentSession.is_admin ? 'admin' : 'user';
  chip.textContent = `${currentSession.username} · ${role}`;
}

async function refreshSession() {
  currentSession = null;
  updateAuthChip();
  if (!currentToken) return null;

  const me = await callApi('/api/v1/auth/me');
  if (!me.ok) {
    localStorage.removeItem(TOKEN_KEY);
    currentToken = '';
    setNotice(`当前 token 已失效：${me.body.message || me.status}`, 'error');
    updateAuthChip();
    return null;
  }

  const admin = await callApi('/api/v1/admin/ping');
  if (!admin.ok) {
    currentSession = { ...me.body, is_admin: false };
    updateAuthChip();
    return currentSession;
  }

  currentSession = { ...me.body, is_admin: true };
  updateAuthChip();
  return currentSession;
}

function currentRoute() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/ops';
  if (path === '/ops') return { name: 'overview' };
  if (path === '/ops/freshness') return { name: 'freshness' };
  if (path === '/ops/schedules') return { name: 'schedules' };
  if (path === '/ops/executions') return { name: 'executions' };
  if (path === '/ops/catalog') return { name: 'catalog' };
  const executionDetailMatch = path.match(/^\/ops\/executions\/(\d+)$/);
  if (executionDetailMatch) {
    return { name: 'executionDetail', executionId: Number(executionDetailMatch[1]) };
  }
  return { name: 'overview' };
}

function syncRouteMeta() {
  const route = currentRoute();
  const meta = ROUTE_META[route.name] || ROUTE_META.overview;
  document.getElementById('page-title').textContent = meta.title;
  document.getElementById('page-copy').textContent = meta.copy;
  document.querySelectorAll('[data-route]').forEach((node) => {
    const routeName = node.getAttribute('data-route');
    const active =
      route.name === routeName ||
      (route.name === 'executionDetail' && routeName === 'executions');
    node.classList.toggle('active', active);
  });
}

function renderAuthRequired(kind = '登录') {
  setViewContent(`
    <section class="panel">
      <div class="empty">
        <h2>先完成管理员${escapeHtml(kind)}</h2>
        <p>运维系统页面壳子已经可访问，但真正的数据和控制能力都严格收敛在管理员 API 上。</p>
      </div>
    </section>
  `);
}

function renderUnauthorized() {
  setViewContent(`
    <section class="panel">
      <div class="empty">
        <h2>当前用户没有管理员权限</h2>
        <p>运维系统一期默认只向管理员角色开放。你可以继续使用平台验证页，但这里不会展示运维控制数据。</p>
      </div>
    </section>
  `);
}

async function ensureAdminSession() {
  const session = await refreshSession();
  if (!session) {
    renderAuthRequired();
    return null;
  }
  if (!session.is_admin) {
    renderUnauthorized();
    return null;
  }
  return session;
}

async function getCatalog() {
  if (opsCatalogCache) return opsCatalogCache;
  const result = await callApi('/api/v1/ops/catalog');
  if (!result.ok) throw new Error(result.body.message || `catalog request failed (${result.status})`);
  opsCatalogCache = result.body;
  return opsCatalogCache;
}

function specOptionsFromCatalog(catalog, options = {}) {
  const { supportsSchedule = false } = options;
  const items = [];
  for (const item of catalog.job_specs || []) {
    if (!supportsSchedule || item.supports_schedule) {
      items.push({ spec_type: 'job', spec_key: item.key, display_name: item.display_name });
    }
  }
  for (const item of catalog.workflow_specs || []) {
    if (!supportsSchedule || item.supports_schedule) {
      items.push({ spec_type: 'workflow', spec_key: item.key, display_name: item.display_name });
    }
  }
  return items.sort((left, right) => left.display_name.localeCompare(right.display_name, 'zh-CN'));
}

function optionHtml(options) {
  return options
    .map(
      (item) =>
        `<option value="${escapeHtml(item.spec_key)}" data-display-name="${escapeHtml(item.display_name)}">${escapeHtml(item.display_name)} · ${escapeHtml(item.spec_key)}</option>`,
    )
    .join('');
}

function tableOrEmpty(headers, rowsHtml, emptyText) {
  if (!rowsHtml.length) {
    return `<div class="empty">${escapeHtml(emptyText)}</div>`;
  }
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
  `;
}

function summarizeByKey(items, key) {
  const summary = {};
  for (const item of items || []) {
    const value = item?.[key] || 'unknown';
    summary[value] = (summary[value] || 0) + 1;
  }
  return summary;
}

function summaryCardsHtml(entries) {
  return `
    <div class="summary-strip">
      ${entries
        .map(
          (entry) => `
            <div class="summary-chip">
              <span class="label">${escapeHtml(entry.label)}</span>
              <span class="value">${formatNumber(entry.value)}</span>
            </div>
          `,
        )
        .join('')}
    </div>
  `;
}

function keyValueGridHtml(items) {
  return `
    <div class="kv-grid">
      ${items
        .map(
          (item) => `
            <div class="kv-item">
              <span class="kv-label">${escapeHtml(item.label)}</span>
              <span class="kv-value">${item.html ?? escapeHtml(item.value ?? '—')}</span>
            </div>
          `,
        )
        .join('')}
    </div>
  `;
}

function timelineHtml(events) {
  if (!events.length) {
    return '<div class="empty">当前 execution 还没有可展示的时间线节点。</div>';
  }
  return `
    <div class="timeline">
      ${events
        .map(
          (item) => `
            <div class="timeline-item">
              <div class="timeline-dot ${escapeHtml(item.tone || 'default')}"></div>
              <div class="timeline-body">
                <div class="timeline-title">${escapeHtml(item.title)}</div>
                <div class="timeline-meta">${formatDateTime(item.at)}</div>
                <div class="timeline-copy">${escapeHtml(item.copy || '—')}</div>
              </div>
            </div>
          `,
        )
        .join('')}
    </div>
  `;
}

function runtimeControlsHtml(outputId = 'runtime-action-output') {
  return `
    <section class="panel">
      <h2>Runtime 控制</h2>
      <div class="form-grid three">
        <div class="field">
          <label for="runtime-scheduler-limit">scheduler tick limit</label>
          <input id="runtime-scheduler-limit" type="number" min="1" max="1000" value="10">
        </div>
        <div class="field">
          <label for="runtime-worker-limit">worker run limit</label>
          <input id="runtime-worker-limit" type="number" min="1" max="1000" value="1">
        </div>
      </div>
      <div class="actions" style="margin-top:12px">
        <button id="btn-runtime-scheduler" class="secondary">扫描到期调度</button>
        <button id="btn-runtime-worker" class="secondary">消费队列</button>
      </div>
      <pre id="${escapeHtml(outputId)}">这里会显示最近一次 runtime 操作结果。</pre>
    </section>
  `;
}

function setPreText(id, payload) {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = typeof payload === 'string' ? payload : formatJson(payload);
}

function bindRuntimeControls({ outputId = 'runtime-action-output', onAfterAction } = {}) {
  const schedulerButton = document.getElementById('btn-runtime-scheduler');
  const workerButton = document.getElementById('btn-runtime-worker');
  const schedulerInput = document.getElementById('runtime-scheduler-limit');
  const workerInput = document.getElementById('runtime-worker-limit');

  if (schedulerButton) {
    schedulerButton.addEventListener('click', async () => {
      try {
        const limit = Number(schedulerInput?.value || '10') || 10;
        const result = await confirmThenRun(
          {
            title: '确认执行 scheduler tick',
            copy: '这会扫描当前到期的调度实例，并为它们创建 execution。',
            detail: { limit },
            confirmLabel: '开始扫描',
            confirmClass: 'warn',
          },
          () =>
            callApi('/api/v1/ops/runtime/scheduler-tick', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ limit }),
            }),
        );
        if (!result) return;
        if (!result.ok) throw new Error(result.body.message || `scheduler tick 失败 (${result.status})`);
        setPreText(outputId, result.body);
        setNotice(`scheduler tick 完成，本次创建 ${result.body.scheduled_count} 条 execution。`);
        setActionSummary('scheduler tick 完成', result.body);
        if (onAfterAction) await onAfterAction();
      } catch (error) {
        setNotice(error.message, 'error');
        setActionSummary('scheduler tick 失败', error.message || String(error), 'error');
      }
    });
  }

  if (workerButton) {
    workerButton.addEventListener('click', async () => {
      try {
        const limit = Number(workerInput?.value || '1') || 1;
        const result = await confirmThenRun(
          {
            title: '确认执行 worker run',
            copy: '这会立即消费 queued execution，并推进底层同步运行。',
            detail: { limit },
            confirmLabel: '开始消费',
            confirmClass: 'warn',
          },
          () =>
            callApi('/api/v1/ops/runtime/worker-run', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ limit }),
            }),
        );
        if (!result) return;
        if (!result.ok) throw new Error(result.body.message || `worker run 失败 (${result.status})`);
        setPreText(outputId, result.body);
        setNotice(`worker run 完成，本次处理 ${result.body.processed_count} 条 execution。`);
        setActionSummary('worker run 完成', result.body);
        if (onAfterAction) await onAfterAction();
      } catch (error) {
        setNotice(error.message, 'error');
        setActionSummary('worker run 失败', error.message || String(error), 'error');
      }
    });
  }
}

function renderOverview(payload) {
  const kpis = payload.kpis || {};
  const freshness = payload.freshness_summary || {};
  const laggingRows = (payload.lagging_datasets || [])
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.display_name)}</td>
          <td>${badge(item.freshness_status)}</td>
          <td>${formatDate(item.latest_business_date)}</td>
          <td>${formatDate(item.expected_business_date)}</td>
          <td>${item.lag_days == null ? '—' : formatNumber(item.lag_days)}</td>
          <td>${escapeHtml(item.recent_failure_message || '—')}</td>
        </tr>
      `,
    )
    .join('');
  const executionRows = (payload.recent_executions || [])
    .map(
      (item) => `
        <tr>
          <td><a href="/ops/executions/${item.id}"><code>#${item.id}</code></a></td>
          <td>${escapeHtml(item.spec_display_name || item.spec_key)}</td>
          <td>${badge(item.status)}</td>
          <td>${escapeHtml(item.trigger_source)}</td>
          <td>${escapeHtml(item.requested_by_username || 'system')}</td>
          <td>${formatDateTime(item.requested_at)}</td>
        </tr>
      `,
    )
    .join('');
  const failureRows = (payload.recent_failures || [])
    .map(
      (item) => `
        <tr>
          <td><a href="/ops/executions/${item.id}"><code>#${item.id}</code></a></td>
          <td>${escapeHtml(item.spec_display_name || item.spec_key)}</td>
          <td>${escapeHtml(item.error_code || '—')}</td>
          <td>${formatDateTime(item.requested_at)}</td>
        </tr>
      `,
    )
    .join('');

  setViewContent(`
    <section class="panel">
      <h2>执行总览</h2>
      <div class="grid-cards">
        <div class="metric-card"><span class="label">总执行数</span><span class="value">${formatNumber(kpis.total_executions)}</span></div>
        <div class="metric-card"><span class="label">运行中</span><span class="value">${formatNumber(kpis.running_executions)}</span></div>
        <div class="metric-card"><span class="label">排队中</span><span class="value">${formatNumber(kpis.queued_executions)}</span></div>
        <div class="metric-card"><span class="label">失败</span><span class="value">${formatNumber(kpis.failed_executions)}</span></div>
        <div class="metric-card"><span class="label">部分成功</span><span class="value">${formatNumber(kpis.partial_success_executions)}</span></div>
        <div class="metric-card"><span class="label">已取消</span><span class="value">${formatNumber(kpis.canceled_executions)}</span></div>
      </div>
    </section>

    ${runtimeControlsHtml('overview-runtime-output')}

    <section class="panel">
      <h2>新鲜度摘要</h2>
      <div class="grid-cards">
        <div class="metric-card"><span class="label">数据集总数</span><span class="value">${formatNumber(freshness.total_datasets)}</span></div>
        <div class="metric-card"><span class="label">Fresh</span><span class="value">${formatNumber(freshness.fresh_datasets)}</span></div>
        <div class="metric-card"><span class="label">Lagging</span><span class="value">${formatNumber(freshness.lagging_datasets)}</span></div>
        <div class="metric-card"><span class="label">Stale</span><span class="value">${formatNumber(freshness.stale_datasets)}</span></div>
        <div class="metric-card"><span class="label">Unknown</span><span class="value">${formatNumber(freshness.unknown_datasets)}</span></div>
      </div>
    </section>

    <div class="split-layout">
      <section class="panel">
        <h2>滞后数据集</h2>
        ${tableOrEmpty(['数据集', '状态', '最新业务日期', '预期日期', '滞后天数', '最近失败'], laggingRows, '当前没有 lagging/stale 数据集。')}
      </section>
      <div class="stack">
        <section class="panel">
          <h2>最近执行</h2>
          ${tableOrEmpty(['执行', '目标', '状态', '来源', '发起人', '请求时间'], executionRows, '暂无执行记录。')}
        </section>
        <section class="panel">
          <h2>最近失败</h2>
          ${tableOrEmpty(['执行', '目标', '错误码', '请求时间'], failureRows, '当前没有失败 execution。')}
        </section>
      </div>
    </div>
  `);

  bindRuntimeControls({ outputId: 'overview-runtime-output', onAfterAction: loadAndRenderCurrentRoute });
}

function renderFreshness(payload) {
  const summary = payload.summary || {};
  const groups = payload.groups || [];
  const groupHtml = groups
    .map((group) => {
      const rows = (group.items || [])
        .map(
          (item) => `
            <tr>
              <td>${escapeHtml(item.display_name)}</td>
              <td><code>${escapeHtml(item.target_table)}</code></td>
              <td>${badge(item.freshness_status)}</td>
              <td>${formatDate(item.latest_business_date)}</td>
              <td>${formatDate(item.expected_business_date)}</td>
              <td>${item.lag_days == null ? '—' : formatNumber(item.lag_days)}</td>
              <td>${formatDateTime(item.latest_success_at)}</td>
              <td>${escapeHtml(item.recent_failure_message || '—')}</td>
            </tr>
          `,
        )
        .join('');
      return `
        <section class="panel">
          <h2>${escapeHtml(group.domain_display_name)}</h2>
          ${tableOrEmpty(['数据集', '目标表', '状态', '最新业务日期', '预期日期', '滞后天数', '最新成功时间', '最近失败'], rows, '该分组暂无数据集。')}
        </section>
      `;
    })
    .join('');

  setViewContent(`
    <section class="panel">
      <h2>全局摘要</h2>
      <div class="grid-cards">
        <div class="metric-card"><span class="label">总数</span><span class="value">${formatNumber(summary.total_datasets)}</span></div>
        <div class="metric-card"><span class="label">Fresh</span><span class="value">${formatNumber(summary.fresh_datasets)}</span></div>
        <div class="metric-card"><span class="label">Lagging</span><span class="value">${formatNumber(summary.lagging_datasets)}</span></div>
        <div class="metric-card"><span class="label">Stale</span><span class="value">${formatNumber(summary.stale_datasets)}</span></div>
        <div class="metric-card"><span class="label">Unknown</span><span class="value">${formatNumber(summary.unknown_datasets)}</span></div>
      </div>
    </section>
    ${groupHtml}
  `);
}

function renderSchedulesPage(catalog, schedulesPayload) {
  const scheduleableSpecs = specOptionsFromCatalog(catalog, { supportsSchedule: true });
  const schedules = schedulesPayload.items || [];
  const byStatus = summarizeByKey(schedules, 'status');
  const byType = summarizeByKey(schedules, 'schedule_type');
  const rows = (schedulesPayload.items || [])
    .map(
      (item) => `
        <tr>
          <td><code>#${item.id}</code></td>
          <td>${escapeHtml(item.display_name)}</td>
          <td>${escapeHtml(item.spec_display_name || item.spec_key)}</td>
          <td>${badge(item.status)}</td>
          <td>${escapeHtml(item.schedule_type)}</td>
          <td>${escapeHtml(item.cron_expr || '—')}</td>
          <td>${formatDateTime(item.next_run_at)}</td>
          <td>${formatDateTime(item.last_triggered_at)}</td>
          <td>
            <div class="inline-actions">
              <button data-action="edit-schedule" data-id="${item.id}" class="secondary">编辑</button>
              ${item.status === 'active' ? `<button data-action="pause-schedule" data-id="${item.id}" class="warn">暂停</button>` : `<button data-action="resume-schedule" data-id="${item.id}">恢复</button>`}
              <button data-action="show-revisions" data-id="${item.id}" class="secondary">变更</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join('');

  setViewContent(`
    <section class="panel">
      <h2>调度摘要</h2>
      ${summaryCardsHtml([
        { label: '总调度数', value: schedulesPayload.total || 0 },
        { label: 'Active', value: byStatus.active || 0 },
        { label: 'Paused', value: byStatus.paused || 0 },
        { label: 'Cron', value: byType.cron || 0 },
        { label: 'Once', value: byType.once || 0 },
      ])}
    </section>

    <div class="split-layout">
      <section class="panel">
        <h2 id="schedule-editor-title">新建调度</h2>
        <input id="schedule-edit-id" type="hidden" value="">
        <div class="form-grid three">
          <div class="field">
            <label for="schedule-spec-type">spec_type</label>
            <select id="schedule-spec-type">
              <option value="job">job</option>
              <option value="workflow">workflow</option>
            </select>
          </div>
          <div class="field">
            <label for="schedule-spec-key">spec_key</label>
            <select id="schedule-spec-key"></select>
          </div>
          <div class="field">
            <label for="schedule-display-name">显示名称</label>
            <input id="schedule-display-name" placeholder="例如：每日收盘同步">
          </div>
          <div class="field">
            <label for="schedule-type">schedule_type</label>
            <select id="schedule-type">
              <option value="cron">cron</option>
              <option value="once">once</option>
            </select>
          </div>
          <div class="field">
            <label for="schedule-cron-expr">cron_expr</label>
            <input id="schedule-cron-expr" placeholder="0 19 * * 1-5">
          </div>
          <div class="field">
            <label for="schedule-next-run-at">next_run_at</label>
            <input id="schedule-next-run-at" placeholder="2026-03-31T19:00:00+08:00">
          </div>
          <div class="field">
            <label for="schedule-timezone">timezone</label>
            <input id="schedule-timezone" value="Asia/Shanghai">
          </div>
          <div class="field">
            <label for="schedule-calendar-policy">calendar_policy</label>
            <input id="schedule-calendar-policy" placeholder="可留空">
          </div>
        </div>
        <div class="field" style="margin-top:12px">
          <label for="schedule-params-json">params_json</label>
          <textarea id="schedule-params-json">{}</textarea>
        </div>
        <div class="field" style="margin-top:12px">
          <label for="schedule-retry-policy-json">retry_policy_json</label>
          <textarea id="schedule-retry-policy-json">{}</textarea>
        </div>
        <div class="field" style="margin-top:12px">
          <label for="schedule-concurrency-policy-json">concurrency_policy_json</label>
          <textarea id="schedule-concurrency-policy-json">{}</textarea>
        </div>
        <div class="actions" style="margin-top:12px">
          <button id="btn-save-schedule">创建调度</button>
          <button id="btn-preview-schedule" class="secondary">预览未来 5 次运行</button>
          <button id="btn-reset-schedule-editor" class="secondary">清空表单</button>
          <button id="btn-refresh-schedules" class="secondary">刷新列表</button>
        </div>
        <p class="muted">phase 1 当前真正可工作的调度类型是 <code>once</code> 和 <code>cron</code>。</p>
      </section>

      <section class="panel">
        <h2>调度详情 / 变更历史</h2>
        <div id="schedule-detail-output" class="empty">选择一条调度后，这里会显示结构化 schedule detail。</div>
        <h3 style="margin-top:18px">未来运行预览</h3>
        <pre id="schedule-preview-output">调整或选择调度后，这里会显示未来几次计划运行时间。</pre>
        <h3 style="margin-top:18px">变更历史</h3>
        <pre id="schedule-revisions-output">选择一条调度后，这里会显示 config revision。</pre>
      </section>
    </div>

    <section class="panel">
      <h2>调度列表</h2>
      ${tableOrEmpty(['ID', '显示名称', '目标', '状态', '类型', '表达式', '下次执行', '上次触发', '操作'], rows, '当前还没有调度实例。')}
    </section>
  `);

  const typeSelect = document.getElementById('schedule-spec-type');
  const keySelect = document.getElementById('schedule-spec-key');
  const displayNameInput = document.getElementById('schedule-display-name');
  const cronInput = document.getElementById('schedule-cron-expr');
  const nextRunInput = document.getElementById('schedule-next-run-at');
  const scheduleTypeSelect = document.getElementById('schedule-type');
  const editIdInput = document.getElementById('schedule-edit-id');
  const editorTitle = document.getElementById('schedule-editor-title');
  const saveButton = document.getElementById('btn-save-schedule');
  const retryPolicyInput = document.getElementById('schedule-retry-policy-json');
  const concurrencyPolicyInput = document.getElementById('schedule-concurrency-policy-json');
  const timezoneInput = document.getElementById('schedule-timezone');
  const calendarPolicyInput = document.getElementById('schedule-calendar-policy');
  const paramsJsonInput = document.getElementById('schedule-params-json');
  const revisionsOutput = document.getElementById('schedule-revisions-output');
  const detailOutput = document.getElementById('schedule-detail-output');
  const previewOutput = document.getElementById('schedule-preview-output');

  function currentDraft() {
    return {
      editing_id: editIdInput.value.trim() || null,
      spec_type: typeSelect.value,
      spec_key: keySelect.value,
      display_name: displayNameInput.value,
      schedule_type: scheduleTypeSelect.value,
      cron_expr: cronInput.value,
      next_run_at: nextRunInput.value,
      timezone: timezoneInput.value,
      calendar_policy: calendarPolicyInput.value,
      params_json_raw: paramsJsonInput.value,
      retry_policy_json_raw: retryPolicyInput.value,
      concurrency_policy_json_raw: concurrencyPolicyInput.value,
    };
  }

  function persistDraft() {
    saveScheduleEditorDraft(currentDraft());
  }

  function schedulePreviewPayload() {
    return {
      schedule_type: scheduleTypeSelect.value,
      cron_expr: cronInput.value.trim() || null,
      timezone: timezoneInput.value.trim() || 'Asia/Shanghai',
      next_run_at: nextRunInput.value.trim() || null,
      count: 5,
    };
  }

  async function loadSchedulePreview(payload, summaryTitle = null) {
    const result = await callApi('/api/v1/ops/schedules/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!result.ok) throw new Error(result.body.message || `调度预览失败 (${result.status})`);
    setPreText('schedule-preview-output', result.body);
    if (summaryTitle) {
      setActionSummary(summaryTitle, result.body);
    }
  }

  function refreshSpecOptions(preferredKey = null) {
    const selectedType = typeSelect.value;
    const filtered = scheduleableSpecs.filter((item) => item.spec_type === selectedType);
    keySelect.innerHTML = optionHtml(filtered);
    if (preferredKey) keySelect.value = preferredKey;
    if (filtered[0] && !displayNameInput.value.trim()) {
      displayNameInput.value = filtered[0].display_name;
    }
    persistDraft();
  }

  function resetEditor() {
    editIdInput.value = '';
    editorTitle.textContent = '新建调度';
    saveButton.textContent = '创建调度';
    typeSelect.disabled = false;
    keySelect.disabled = false;
    typeSelect.value = 'job';
    displayNameInput.value = '';
    scheduleTypeSelect.value = 'cron';
    cronInput.value = '';
    nextRunInput.value = '';
    document.getElementById('schedule-timezone').value = 'Asia/Shanghai';
    document.getElementById('schedule-calendar-policy').value = '';
    document.getElementById('schedule-params-json').value = '{}';
    retryPolicyInput.value = '{}';
    concurrencyPolicyInput.value = '{}';
    refreshSpecOptions();
    detailOutput.innerHTML = '<div class="empty">选择一条调度后，这里会显示结构化 schedule detail。</div>';
    revisionsOutput.textContent = '选择一条调度后，这里会显示 config revision。';
    previewOutput.textContent = '调整或选择调度后，这里会显示未来几次计划运行时间。';
    clearScheduleEditorDraft();
    saveSelectedScheduleId(null);
  }

  function populateEditor(detail) {
    editIdInput.value = String(detail.id);
    saveSelectedScheduleId(detail.id);
    editorTitle.textContent = `编辑调度 #${detail.id}`;
    saveButton.textContent = '保存修改';
    typeSelect.disabled = true;
    keySelect.disabled = true;
    typeSelect.value = detail.spec_type;
    refreshSpecOptions(detail.spec_key);
    displayNameInput.value = detail.display_name || '';
    scheduleTypeSelect.value = detail.schedule_type;
    cronInput.value = detail.cron_expr || '';
    nextRunInput.value = detail.next_run_at || '';
    document.getElementById('schedule-timezone').value = detail.timezone || 'Asia/Shanghai';
    document.getElementById('schedule-calendar-policy').value = detail.calendar_policy || '';
    document.getElementById('schedule-params-json').value = formatJson(detail.params_json || {});
    retryPolicyInput.value = formatJson(detail.retry_policy_json || {});
    concurrencyPolicyInput.value = formatJson(detail.concurrency_policy_json || {});
    detailOutput.innerHTML = `
      ${keyValueGridHtml([
        { label: '显示名称', value: detail.display_name },
        { label: '目标', value: detail.spec_display_name || detail.spec_key },
        { label: '状态', html: badge(detail.status) },
        { label: '调度类型', value: detail.schedule_type },
        { label: 'cron_expr', value: detail.cron_expr || '—' },
        { label: '时区', value: detail.timezone || '—' },
        { label: '下次执行', value: formatDateTime(detail.next_run_at) },
        { label: '上次触发', value: formatDateTime(detail.last_triggered_at) },
        { label: '创建人', value: detail.created_by_username || '—' },
        { label: '更新人', value: detail.updated_by_username || '—' },
      ])}
      <div class="detail-stack" style="margin-top:14px">
        <pre>${escapeHtml(formatJson({
  params_json: detail.params_json || {},
  retry_policy_json: detail.retry_policy_json || {},
  concurrency_policy_json: detail.concurrency_policy_json || {},
}))}</pre>
      </div>
    `;
    persistDraft();
    loadSchedulePreview(
      {
        schedule_type: detail.schedule_type,
        cron_expr: detail.cron_expr,
        timezone: detail.timezone || 'Asia/Shanghai',
        next_run_at: detail.next_run_at,
        count: 5,
      },
      null,
    ).catch((error) => {
      previewOutput.textContent = error.message || String(error);
    });
  }

  async function loadScheduleContext(id) {
    const [detail, revisions] = await Promise.all([
      callApi(`/api/v1/ops/schedules/${id}`),
      callApi(`/api/v1/ops/schedules/${id}/revisions`),
    ]);
    if (!detail.ok) throw new Error(detail.body.message || `读取 schedule detail 失败 (${detail.status})`);
    if (!revisions.ok) throw new Error(revisions.body.message || `读取 revision 失败 (${revisions.status})`);
    populateEditor(detail.body);
    setPreText('schedule-revisions-output', revisions.body);
  }

  function restoreDraft() {
    const draft = loadScheduleEditorDraft();
    if (!draft) {
      refreshSpecOptions();
      return;
    }
    typeSelect.value = draft.spec_type || 'job';
    refreshSpecOptions(draft.spec_key || null);
    editIdInput.value = draft.editing_id || '';
    displayNameInput.value = draft.display_name || '';
    scheduleTypeSelect.value = draft.schedule_type || 'cron';
    cronInput.value = draft.cron_expr || '';
    nextRunInput.value = draft.next_run_at || '';
    timezoneInput.value = draft.timezone || 'Asia/Shanghai';
    calendarPolicyInput.value = draft.calendar_policy || '';
    paramsJsonInput.value = draft.params_json_raw || '{}';
    retryPolicyInput.value = draft.retry_policy_json_raw || '{}';
    concurrencyPolicyInput.value = draft.concurrency_policy_json_raw || '{}';
    if (draft.editing_id) {
      editorTitle.textContent = `继续编辑调度 #${draft.editing_id}`;
      saveButton.textContent = '保存修改';
      typeSelect.disabled = true;
      keySelect.disabled = true;
    }
  }

  typeSelect.addEventListener('change', refreshSpecOptions);
  keySelect.addEventListener('change', () => {
    const option = keySelect.selectedOptions[0];
    if (option && !displayNameInput.value.trim()) {
      displayNameInput.value = option.dataset.displayName || '';
    }
    persistDraft();
  });
  scheduleTypeSelect.addEventListener('change', () => {
    const isCron = scheduleTypeSelect.value === 'cron';
    cronInput.disabled = !isCron;
    nextRunInput.disabled = false;
    persistDraft();
  });
  restoreDraft();

  for (const input of [displayNameInput, cronInput, nextRunInput, timezoneInput, calendarPolicyInput, paramsJsonInput, retryPolicyInput, concurrencyPolicyInput]) {
    input.addEventListener('input', persistDraft);
    input.addEventListener('change', persistDraft);
  }

  saveButton.addEventListener('click', async () => {
    try {
      const payload = {
        display_name: displayNameInput.value.trim() || (keySelect.selectedOptions[0]?.dataset.displayName || keySelect.value),
        schedule_type: scheduleTypeSelect.value,
        cron_expr: cronInput.value.trim() || null,
        next_run_at: nextRunInput.value.trim() || null,
        timezone: document.getElementById('schedule-timezone').value.trim() || 'Asia/Shanghai',
        calendar_policy: document.getElementById('schedule-calendar-policy').value.trim() || null,
        params_json: parseJsonInput('schedule-params-json'),
        retry_policy_json: parseJsonInput('schedule-retry-policy-json'),
        concurrency_policy_json: parseJsonInput('schedule-concurrency-policy-json'),
      };
      const editingId = editIdInput.value.trim();
      if (!editingId) {
        payload.spec_type = typeSelect.value;
        payload.spec_key = keySelect.value;
      }
      const result = await confirmThenRun(
        {
          title: editingId ? `确认更新调度 #${editingId}` : '确认创建调度',
          copy: editingId ? '这会更新现有调度实例配置，并写入 config revision。' : '这会创建新的调度实例，并进入运维控制面。',
          detail: payload,
          confirmLabel: editingId ? '保存修改' : '创建调度',
          confirmClass: editingId ? 'warn' : 'danger',
        },
        () =>
          callApi(editingId ? `/api/v1/ops/schedules/${editingId}` : '/api/v1/ops/schedules', {
            method: editingId ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }),
      );
      if (!result) return;
      if (!result.ok) throw new Error(result.body.message || `${editingId ? '保存' : '创建'}失败 (${result.status})`);
      setNotice(editingId ? `调度 #${editingId} 已更新。` : '调度创建成功。');
      opsCatalogCache = null;
      setActionSummary(editingId ? `调度 #${editingId} 已更新` : '调度创建成功', result.body);
      clearScheduleEditorDraft();
      saveSelectedScheduleId(result.body.id);
      await loadAndRenderCurrentRoute();
    } catch (error) {
      setNotice(error.message, 'error');
      setActionSummary('调度保存失败', error.message || String(error), 'error');
    }
  });

  document.getElementById('btn-reset-schedule-editor').addEventListener('click', () => {
    resetEditor();
  });

  document.getElementById('btn-refresh-schedules').addEventListener('click', async () => {
    await loadAndRenderCurrentRoute();
  });

  document.getElementById('btn-preview-schedule').addEventListener('click', async () => {
    try {
      await loadSchedulePreview(schedulePreviewPayload(), '调度预览已更新');
      setNotice('调度预览已更新。');
    } catch (error) {
      setNotice(error.message, 'error');
      setActionSummary('调度预览失败', error.message || String(error), 'error');
    }
  });

  document.getElementById('ops-view-root').onclick = async (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    const id = button.dataset.id;
    if (!id) return;

    try {
      if (action === 'edit-schedule') {
        await loadScheduleContext(id);
      }
      if (action === 'pause-schedule') {
        const result = await confirmThenRun(
          {
            title: `确认暂停调度 #${id}`,
            copy: '暂停后 scheduler 不会再为这条调度创建新的 execution。',
            detail: { schedule_id: Number(id) },
            confirmLabel: '确认暂停',
            confirmClass: 'danger',
          },
          () => callApi(`/api/v1/ops/schedules/${id}/pause`, { method: 'POST' }),
        );
        if (!result) return;
        if (!result.ok) throw new Error(result.body.message || `暂停失败 (${result.status})`);
        setNotice(`调度 #${id} 已暂停。`);
        opsCatalogCache = null;
        setActionSummary(`调度 #${id} 已暂停`, result.body);
        await loadAndRenderCurrentRoute();
      }
      if (action === 'resume-schedule') {
        const result = await confirmThenRun(
          {
            title: `确认恢复调度 #${id}`,
            copy: '恢复后 scheduler 将重新按当前配置继续扫描这条调度。',
            detail: { schedule_id: Number(id) },
            confirmLabel: '确认恢复',
            confirmClass: 'warn',
          },
          () => callApi(`/api/v1/ops/schedules/${id}/resume`, { method: 'POST' }),
        );
        if (!result) return;
        if (!result.ok) throw new Error(result.body.message || `恢复失败 (${result.status})`);
        setNotice(`调度 #${id} 已恢复。`);
        opsCatalogCache = null;
        setActionSummary(`调度 #${id} 已恢复`, result.body);
        await loadAndRenderCurrentRoute();
      }
      if (action === 'show-revisions') {
        await loadScheduleContext(id);
      }
    } catch (error) {
      setNotice(error.message, 'error');
      setActionSummary('调度操作失败', error.message || String(error), 'error');
    }
  };

  const selectedId = loadSelectedScheduleId();
  if (selectedId) {
    loadScheduleContext(selectedId).catch((error) => {
      setNotice(error.message, 'error');
      setActionSummary('调度上下文恢复失败', error.message || String(error), 'error');
    });
  }
}

function renderExecutionsPage(catalog, executionsPayload, filters = {}) {
  const specOptions = specOptionsFromCatalog(catalog);
  const executions = executionsPayload.items || [];
  const byStatus = summarizeByKey(executions, 'status');
  const knownStatuses = ['queued', 'running', 'canceling', 'success', 'failed', 'canceled', 'partial_success'];
  const dynamicStatuses = Object.keys(byStatus || {});
  const statusOptions = Array.from(new Set([...knownStatuses, ...dynamicStatuses])).filter(Boolean);
  const selectedStatus = String(filters.status || '').trim();
  if (selectedStatus && !statusOptions.includes(selectedStatus)) {
    statusOptions.push(selectedStatus);
  }
  const statusOptionsHtml = [
    '<option value="">全部</option>',
    ...statusOptions.map((status) => `<option value="${escapeHtml(status)}" ${selectedStatus === status ? 'selected' : ''}>${escapeHtml(status)}</option>`),
  ].join('');
  const rows = (executionsPayload.items || [])
    .map(
      (item) => `
        <tr>
          <td><a href="/ops/executions/${item.id}"><code>#${item.id}</code></a></td>
          <td>${escapeHtml(item.spec_display_name || item.spec_key)}</td>
          <td>${badge(item.status)}</td>
          <td>${escapeHtml(item.trigger_source)}</td>
          <td>${escapeHtml(item.requested_by_username || 'system')}</td>
          <td>${formatDateTime(item.requested_at)}</td>
          <td>${formatNumber(item.rows_written)}</td>
          <td>
            <div class="inline-actions">
              <a class="secondary" href="/ops/executions/${item.id}">详情</a>
              <button data-action="retry-execution" data-id="${item.id}" class="secondary">重试</button>
              <button data-action="clone-execution" data-id="${item.id}" class="secondary">复制为新执行</button>
              ${item.status === 'queued' || item.status === 'running' ? `<button data-action="cancel-execution" data-id="${item.id}" class="danger">取消</button>` : ''}
            </div>
          </td>
        </tr>
      `,
    )
    .join('');

  setViewContent(`
    <section class="panel">
      <h2>执行摘要</h2>
      ${summaryCardsHtml([
        { label: '总数', value: executionsPayload.total || 0 },
        { label: 'Queued', value: byStatus.queued || 0 },
        { label: 'Running', value: byStatus.running || 0 },
        { label: 'Success', value: byStatus.success || 0 },
        { label: 'Failed', value: byStatus.failed || 0 },
        { label: 'Canceled', value: byStatus.canceled || 0 },
      ])}
    </section>

    ${recentExecutionsPanelHtml()}

    <div class="split-layout">
      ${runtimeControlsHtml('executions-runtime-output')}
      <section class="panel">
        <h2>手动执行</h2>
        <div class="form-grid three">
          <div class="field">
            <label for="execution-spec-type">spec_type</label>
            <select id="execution-spec-type">
              <option value="job">job</option>
              <option value="workflow">workflow</option>
            </select>
          </div>
          <div class="field">
            <label for="execution-spec-key">spec_key</label>
            <select id="execution-spec-key"></select>
          </div>
        </div>
        <div class="field" style="margin-top:12px">
          <label for="execution-params-json">params_json</label>
          <textarea id="execution-params-json">{}</textarea>
        </div>
        <div class="actions" style="margin-top:12px">
          <button id="btn-create-execution">创建 execution</button>
        </div>
      </section>

      <section class="panel">
        <h2>筛选</h2>
        <div class="form-grid three">
          <div class="field">
            <label for="execution-filter-status">status</label>
            <select id="execution-filter-status">
              ${statusOptionsHtml}
            </select>
          </div>
          <div class="field">
            <label for="execution-filter-trigger">trigger_source</label>
            <input id="execution-filter-trigger" value="${escapeHtml(filters.trigger_source || '')}" placeholder="manual / scheduled / retry">
          </div>
          <div class="field">
            <label for="execution-filter-spec-key">spec_key</label>
            <input id="execution-filter-spec-key" value="${escapeHtml(filters.spec_key || '')}" placeholder="sync_history.stock_basic">
          </div>
        </div>
        <div class="actions" style="margin-top:12px">
          <button id="btn-apply-execution-filters" class="secondary">应用筛选</button>
          <button id="btn-reset-execution-filters" class="secondary">重置</button>
        </div>
        <p class="muted">筛选条件会保存在当前浏览器里，方便我们在 execution 列表和详情页之间来回排障。</p>
      </section>
    </div>

    <section class="panel">
      <h2>执行列表</h2>
      <p class="muted">如果某条 execution 失败了，我们可以直接重试，也可以把原始参数复制回手动执行表单里，调整后重新发起。</p>
      ${tableOrEmpty(['ID', '目标', '状态', '来源', '发起人', '请求时间', 'rows_written', '操作'], rows, '当前没有 execution。')}
    </section>
  `);

  const typeSelect = document.getElementById('execution-spec-type');
  const keySelect = document.getElementById('execution-spec-key');
  const paramsTextarea = document.getElementById('execution-params-json');
  function refreshExecutionOptions() {
    const selectedType = typeSelect.value;
    const filtered = specOptions.filter((item) => item.spec_type === selectedType);
    keySelect.innerHTML = optionHtml(filtered);
  }
  typeSelect.addEventListener('change', refreshExecutionOptions);
  refreshExecutionOptions();

  const prefill = consumeExecutionPrefill();
  if (prefill) {
    typeSelect.value = prefill.spec_type || 'job';
    refreshExecutionOptions();
    if (prefill.spec_key) keySelect.value = prefill.spec_key;
    paramsTextarea.value = formatJson(prefill.params_json || {});
    setActionSummary(
      '已载入 execution 参数',
      {
        source_execution_id: prefill.source_execution_id,
        spec_type: prefill.spec_type,
        spec_key: prefill.spec_key,
        params_json: prefill.params_json || {},
      },
    );
  }

  document.getElementById('btn-create-execution').addEventListener('click', async () => {
    try {
      const payload = {
        spec_type: typeSelect.value,
        spec_key: keySelect.value,
        params_json: parseJsonInput('execution-params-json'),
      };
      const result = await confirmThenRun(
        {
          title: '确认创建 execution',
          copy: '这会立刻创建一条新的 execution 请求，并进入统一执行队列。',
          detail: payload,
          confirmLabel: '创建 execution',
          confirmClass: 'danger',
        },
        () =>
          callApi('/api/v1/ops/executions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }),
      );
      if (!result) return;
      if (!result.ok) throw new Error(result.body.message || `创建 execution 失败 (${result.status})`);
      setActionSummary('execution 创建成功', result.body);
      window.location.assign(`/ops/executions/${result.body.id}`);
    } catch (error) {
      setNotice(error.message, 'error');
      setActionSummary('execution 创建失败', error.message || String(error), 'error');
    }
  });

  document.getElementById('btn-apply-execution-filters').addEventListener('click', async () => {
    const nextFilters = {
      status: document.getElementById('execution-filter-status').value.trim(),
      trigger_source: document.getElementById('execution-filter-trigger').value.trim(),
      spec_key: document.getElementById('execution-filter-spec-key').value.trim(),
    };
    await loadAndRenderExecutions(nextFilters);
  });

  document.getElementById('btn-reset-execution-filters').addEventListener('click', async () => {
    localStorage.removeItem(OPS_EXECUTION_FILTERS_KEY);
    localStorage.setItem(OPS_EXECUTION_LIST_CONTEXT_KEY, '/ops/executions');
    window.history.replaceState({}, '', '/ops/executions');
    await loadAndRenderExecutions({});
  });

  bindRuntimeControls({ outputId: 'executions-runtime-output', onAfterAction: () => loadAndRenderExecutions(filters) });

  document.getElementById('ops-view-root').onclick = async (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    const id = button.dataset.id;
    if (!id) return;
    try {
      if (action === 'retry-execution') {
        const result = await confirmThenRun(
          {
            title: `确认重试 execution #${id}`,
            copy: '这会基于原 execution 的 spec 和 params 创建一条新的 retry execution。',
            detail: { execution_id: Number(id), trigger_source: 'retry' },
            confirmLabel: '确认重试',
            confirmClass: 'warn',
          },
          () => callApi(`/api/v1/ops/executions/${id}/retry`, { method: 'POST' }),
        );
        if (!result) return;
        if (!result.ok) throw new Error(result.body.message || `重试失败 (${result.status})`);
        setActionSummary(`execution #${id} 已重试`, result.body);
        window.location.assign(`/ops/executions/${result.body.id}`);
      }
      if (action === 'clone-execution') {
        const item = executions.find((candidate) => String(candidate.id) === id);
        if (!item) throw new Error('无法找到要复制的 execution。');
        const detail = await callApi(`/api/v1/ops/executions/${id}`);
        if (!detail.ok) throw new Error(detail.body.message || `读取 execution 详情失败 (${detail.status})`);
        saveExecutionPrefill({
          source_execution_id: Number(id),
          spec_type: detail.body.spec_type,
          spec_key: detail.body.spec_key,
          params_json: detail.body.params_json || {},
        });
        setNotice(`execution #${id} 的参数已加载到手动执行表单。`);
        setActionSummary(`execution #${id} 参数已复制`, detail.body.params_json || {});
        await loadAndRenderExecutions(filters);
      }
      if (action === 'cancel-execution') {
        const result = await confirmThenRun(
          {
            title: `确认取消 execution #${id}`,
            copy: '这会发出 cancel_requested，worker 会在可中断点协作式停止。',
            detail: { execution_id: Number(id) },
            confirmLabel: '确认取消',
            confirmClass: 'danger',
          },
          () => callApi(`/api/v1/ops/executions/${id}/cancel`, { method: 'POST' }),
        );
        if (!result) return;
        if (!result.ok) throw new Error(result.body.message || `取消失败 (${result.status})`);
        setNotice(`execution #${id} 已请求取消。`);
        setActionSummary(`execution #${id} 已请求取消`, result.body);
        await loadAndRenderExecutions(filters);
      }
    } catch (error) {
      setNotice(error.message, 'error');
      setActionSummary('execution 操作失败', error.message || String(error), 'error');
    }
  };
}

function renderExecutionDetail(detail, stepsPayload, eventsPayload, logsPayload) {
  rememberRecentExecution(detail);
  const allSteps = stepsPayload.items || [];
  const allEvents = eventsPayload.items || [];
  const allLogs = logsPayload.items || [];
  const isActiveExecution = detail.status === 'queued' || detail.status === 'running';
  const autoRefreshEnabled = localStorage.getItem(EXECUTION_AUTO_REFRESH_ENABLED_KEY) !== 'false';
  const refreshInterval = Number(localStorage.getItem(EXECUTION_AUTO_REFRESH_INTERVAL_KEY) || '10') || 10;
  const executionListHref = loadExecutionListContext();
  const timelineEntries = [
    { title: '请求创建', at: detail.requested_at, copy: `trigger_source=${detail.trigger_source}`, tone: 'default' },
    ...(detail.queued_at ? [{ title: '进入队列', at: detail.queued_at, copy: 'execution 已进入 queued 状态', tone: 'queued' }] : []),
    ...(detail.started_at ? [{ title: '开始执行', at: detail.started_at, copy: 'worker 已领取该 execution', tone: 'running' }] : []),
    ...(detail.cancel_requested_at
      ? [{ title: '请求取消', at: detail.cancel_requested_at, copy: '已发出 cancel_requested', tone: 'warning' }]
      : []),
    ...(detail.canceled_at ? [{ title: '执行取消', at: detail.canceled_at, copy: detail.summary_message || 'execution canceled', tone: 'failed' }] : []),
    ...(detail.ended_at
      ? [
          {
            title: '执行结束',
            at: detail.ended_at,
            copy: detail.summary_message || detail.error_message || 'execution finished',
            tone: detail.status === 'success' ? 'success' : detail.status === 'failed' ? 'failed' : 'default',
          },
        ]
      : []),
  ];

  setViewContent(`
    <div class="split-layout">
      <section class="panel">
        <h2>${escapeHtml(detail.spec_display_name || detail.spec_key)}</h2>
        <div class="grid-cards">
          <div class="metric-card"><span class="label">Execution ID</span><span class="value">${detail.id}</span></div>
          <div class="metric-card"><span class="label">状态</span><span class="value">${escapeHtml(detail.status)}</span></div>
          <div class="metric-card"><span class="label">rows_fetched</span><span class="value">${formatNumber(detail.rows_fetched)}</span></div>
          <div class="metric-card"><span class="label">rows_written</span><span class="value">${formatNumber(detail.rows_written)}</span></div>
        </div>
        <div class="actions" style="margin-top:14px">
          <button id="btn-refresh-detail" class="secondary">刷新详情</button>
          <button id="btn-copy-params" class="secondary">复制参数</button>
          <button id="btn-clone-detail" class="secondary">复制为新执行</button>
          <button id="btn-retry-detail" class="secondary">重试</button>
          ${(detail.status === 'queued' || detail.status === 'running') ? '<button id="btn-cancel-detail" class="danger">请求取消</button>' : ''}
          <a href="${escapeHtml(executionListHref)}" class="secondary">返回列表</a>
        </div>
      </section>
      <section class="panel">
        <h2>执行元信息</h2>
        <pre>${escapeHtml(formatJson({
    id: detail.id,
    spec_type: detail.spec_type,
    spec_key: detail.spec_key,
    trigger_source: detail.trigger_source,
    status: detail.status,
    schedule_id: detail.schedule_id,
    schedule_display_name: detail.schedule_display_name,
    requested_by_username: detail.requested_by_username,
    requested_at: detail.requested_at,
    started_at: detail.started_at,
    ended_at: detail.ended_at,
    summary_message: detail.summary_message,
    error_code: detail.error_code,
    error_message: detail.error_message,
    params_json: detail.params_json,
  }))}</pre>
      </section>
    </div>

    <section class="panel">
      <h2>执行时间线</h2>
      ${timelineHtml(timelineEntries)}
    </section>

    ${
      detail.status === 'failed'
        ? `
      <section class="panel">
        <h2>失败恢复建议</h2>
        <div class="detail-stack">
          ${keyValueGridHtml([
            { label: '错误码', value: detail.error_code || '—' },
            { label: '错误信息', value: detail.error_message || detail.summary_message || '—' },
            { label: '推荐动作', value: '先查看事件流与底层日志，再决定直接重试，还是复制参数后调整再新开 execution。' },
          ])}
        </div>
      </section>
    `
        : ''
    }

    ${recentExecutionsPanelHtml()}

    <section class="panel">
      <h2>详情刷新与筛选</h2>
      <div class="form-grid three">
        <div class="field">
          <label for="execution-detail-auto-refresh">
            <input id="execution-detail-auto-refresh" type="checkbox" ${autoRefreshEnabled ? 'checked' : ''} ${!isActiveExecution ? 'disabled' : ''}>
            自动刷新运行中 execution
          </label>
        </div>
        <div class="field">
          <label for="execution-detail-refresh-interval">刷新间隔（秒）</label>
          <select id="execution-detail-refresh-interval" ${!isActiveExecution ? 'disabled' : ''}>
            <option value="5" ${refreshInterval === 5 ? 'selected' : ''}>5</option>
            <option value="10" ${refreshInterval === 10 ? 'selected' : ''}>10</option>
            <option value="20" ${refreshInterval === 20 ? 'selected' : ''}>20</option>
            <option value="30" ${refreshInterval === 30 ? 'selected' : ''}>30</option>
          </select>
        </div>
        <div class="field">
          <label for="execution-event-level-filter">事件级别筛选</label>
          <select id="execution-event-level-filter">
            <option value="">全部</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
        <div class="field">
          <label for="execution-event-search">事件搜索</label>
          <input id="execution-event-search" placeholder="按事件类型 / message 搜索">
        </div>
        <div class="field">
          <label for="execution-log-status-filter">日志状态筛选</label>
          <select id="execution-log-status-filter">
            <option value="">全部</option>
            <option value="RUNNING">RUNNING</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="FAILED">FAILED</option>
          </select>
        </div>
        <div class="field">
          <label for="execution-log-search">日志搜索</label>
          <input id="execution-log-search" placeholder="按 job_name / message 搜索">
        </div>
      </div>
      <p class="muted">${isActiveExecution ? '当前 execution 仍在进行中，可开启自动刷新。' : '当前 execution 已结束，自动刷新已关闭。'}</p>
    </section>

    <section class="panel">
      <h2>步骤列表</h2>
      <div id="execution-steps-table"></div>
    </section>

    <div class="split-layout">
      <section class="panel">
        <h2>事件流</h2>
        <div id="execution-events-table"></div>
      </section>
      <section class="panel">
        <h2>事件 / 步骤检查面板</h2>
        <pre id="execution-detail-inspector">点击“查看”后，这里会显示 step 或 event payload 的结构化内容。</pre>
      </section>
    </div>

    <div class="split-layout">
      <section class="panel">
        <h2>底层同步日志</h2>
        <div id="execution-logs-table"></div>
      </section>
      <section class="panel">
        <h2>日志检查面板</h2>
        <pre id="execution-log-inspector">点击“查看”后，这里会显示单条 sync_run_log 的详细内容。</pre>
      </section>
    </div>
  `);

  const stepsRoot = document.getElementById('execution-steps-table');
  const eventsRoot = document.getElementById('execution-events-table');
  const logsRoot = document.getElementById('execution-logs-table');
  const detailInspector = document.getElementById('execution-detail-inspector');
  const logInspector = document.getElementById('execution-log-inspector');
  const autoRefreshToggle = document.getElementById('execution-detail-auto-refresh');
  const refreshIntervalSelect = document.getElementById('execution-detail-refresh-interval');
  const eventLevelFilter = document.getElementById('execution-event-level-filter');
  const eventSearchInput = document.getElementById('execution-event-search');
  const logStatusFilter = document.getElementById('execution-log-status-filter');
  const logSearchInput = document.getElementById('execution-log-search');

  function renderSteps(items) {
    const rows = items
      .map(
        (item, index) => `
          <tr>
            <td>${item.sequence_no}</td>
            <td>${escapeHtml(item.display_name)}</td>
            <td>${badge(item.status)}</td>
            <td>${escapeHtml(item.unit_kind || '—')}</td>
            <td>${escapeHtml(item.unit_value || '—')}</td>
            <td>${formatNumber(item.rows_written)}</td>
            <td>${formatDateTime(item.started_at)}</td>
            <td>${formatDateTime(item.ended_at)}</td>
            <td><button class="secondary" data-action="inspect-step" data-index="${index}">查看</button></td>
          </tr>
        `,
      )
      .join('');
    stepsRoot.innerHTML = tableOrEmpty(['序号', '步骤', '状态', '单位类型', '单位值', 'rows_written', '开始时间', '结束时间', '检查'], rows, '当前 execution 还没有结构化步骤。');
  }

  function renderEvents() {
    const level = eventLevelFilter.value.trim();
    const search = eventSearchInput.value.trim().toLowerCase();
    const filtered = allEvents.filter((item) => {
      const matchesLevel = !level || item.level === level;
      const haystack = `${item.event_type || ''} ${item.message || ''}`.toLowerCase();
      const matchesSearch = !search || haystack.includes(search);
      return matchesLevel && matchesSearch;
    });
    const rows = filtered
      .map(
        (item) => `
          <tr>
            <td>${formatDateTime(item.occurred_at)}</td>
            <td>${badge(String(item.level || '').toLowerCase())}</td>
            <td>${escapeHtml(item.event_type)}</td>
            <td>${escapeHtml(item.message || '—')}</td>
            <td><code>${escapeHtml(item.step_id || '—')}</code></td>
            <td><button class="secondary" data-action="inspect-event" data-id="${item.id}">查看</button></td>
          </tr>
        `,
      )
      .join('');
    eventsRoot.innerHTML = tableOrEmpty(['发生时间', '级别', '事件类型', '消息', 'step_id', '检查'], rows, '当前 execution 还没有结构化事件。');
  }

  function renderLogs() {
    const status = logStatusFilter.value.trim();
    const search = logSearchInput.value.trim().toLowerCase();
    const filtered = allLogs.filter((item) => {
      const matchesStatus = !status || item.status === status;
      const haystack = `${item.job_name || ''} ${item.message || ''}`.toLowerCase();
      const matchesSearch = !search || haystack.includes(search);
      return matchesStatus && matchesSearch;
    });
    const rows = filtered
      .map(
        (item) => `
          <tr>
            <td>${formatDateTime(item.started_at)}</td>
            <td>${escapeHtml(item.job_name)}</td>
            <td>${escapeHtml(item.run_type)}</td>
            <td>${badge(String(item.status || '').toLowerCase())}</td>
            <td>${formatNumber(item.rows_fetched)}</td>
            <td>${formatNumber(item.rows_written)}</td>
            <td>${escapeHtml(item.message || '—')}</td>
            <td><button class="secondary" data-action="inspect-log" data-id="${item.id}">查看</button></td>
          </tr>
        `,
      )
      .join('');
    logsRoot.innerHTML = tableOrEmpty(['开始时间', 'job_name', 'run_type', '状态', 'rows_fetched', 'rows_written', 'message', '检查'], rows, '当前 execution 还没有挂载 sync_run_log。');
  }

  renderSteps(allSteps);
  renderEvents();
  renderLogs();

  function armAutoRefresh() {
    clearExecutionDetailAutoRefresh();
    if (!isActiveExecution || !autoRefreshToggle.checked) return;
    const seconds = Number(refreshIntervalSelect.value || '10') || 10;
    localStorage.setItem(EXECUTION_AUTO_REFRESH_ENABLED_KEY, 'true');
    localStorage.setItem(EXECUTION_AUTO_REFRESH_INTERVAL_KEY, String(seconds));
    executionDetailAutoRefreshTimer = window.setTimeout(async () => {
      await loadAndRenderCurrentRoute();
    }, seconds * 1000);
  }

  if (isActiveExecution && autoRefreshToggle.checked) {
    armAutoRefresh();
  } else {
    localStorage.setItem(EXECUTION_AUTO_REFRESH_ENABLED_KEY, String(autoRefreshToggle.checked));
  }

  autoRefreshToggle?.addEventListener('change', () => {
    localStorage.setItem(EXECUTION_AUTO_REFRESH_ENABLED_KEY, String(autoRefreshToggle.checked));
    armAutoRefresh();
  });
  refreshIntervalSelect?.addEventListener('change', () => {
    localStorage.setItem(EXECUTION_AUTO_REFRESH_INTERVAL_KEY, refreshIntervalSelect.value);
    armAutoRefresh();
  });
  eventLevelFilter.addEventListener('change', renderEvents);
  eventSearchInput.addEventListener('input', renderEvents);
  logStatusFilter.addEventListener('change', renderLogs);
  logSearchInput.addEventListener('input', renderLogs);

  document.getElementById('btn-retry-detail').addEventListener('click', async () => {
    try {
      const result = await confirmThenRun(
        {
          title: `确认重试 execution #${detail.id}`,
          copy: '这会基于当前 execution 的原始参数，再创建一条新的 retry execution。',
          detail: {
            execution_id: detail.id,
            spec_type: detail.spec_type,
            spec_key: detail.spec_key,
            params_json: detail.params_json || {},
          },
          confirmLabel: '确认重试',
          confirmClass: 'warn',
        },
        () => callApi(`/api/v1/ops/executions/${detail.id}/retry`, { method: 'POST' }),
      );
      if (!result) return;
      if (!result.ok) throw new Error(result.body.message || `重试失败 (${result.status})`);
      setActionSummary(`execution #${detail.id} 已重试`, result.body);
      window.location.assign(`/ops/executions/${result.body.id}`);
    } catch (error) {
      setNotice(error.message, 'error');
      setActionSummary('execution 重试失败', error.message || String(error), 'error');
    }
  });

  document.getElementById('btn-refresh-detail').addEventListener('click', async () => {
    await loadAndRenderCurrentRoute();
  });

  document.getElementById('btn-copy-params').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(formatJson(detail.params_json || {}));
      setNotice(`execution #${detail.id} 的 params_json 已复制。`);
    } catch (error) {
      setNotice(`复制失败：${error.message || error}`, 'error');
    }
  });

  document.getElementById('btn-clone-detail').addEventListener('click', async () => {
    saveExecutionPrefill({
      source_execution_id: detail.id,
      spec_type: detail.spec_type,
      spec_key: detail.spec_key,
      params_json: detail.params_json || {},
    });
    setActionSummary(`execution #${detail.id} 参数已复制`, detail.params_json || {});
    window.location.assign('/ops/executions');
  });

  const cancelButton = document.getElementById('btn-cancel-detail');
  if (cancelButton) {
    cancelButton.addEventListener('click', async () => {
      try {
        const result = await confirmThenRun(
          {
            title: `确认取消 execution #${detail.id}`,
            copy: '这会发出 cancel_requested。若当前 execution 正在运行，worker 会在可中断点协作式停止。',
            detail: {
              execution_id: detail.id,
              status: detail.status,
              spec_type: detail.spec_type,
              spec_key: detail.spec_key,
            },
            confirmLabel: '确认取消',
            confirmClass: 'danger',
          },
          () => callApi(`/api/v1/ops/executions/${detail.id}/cancel`, { method: 'POST' }),
        );
        if (!result) return;
        if (!result.ok) throw new Error(result.body.message || `取消失败 (${result.status})`);
        setNotice(`execution #${detail.id} 已请求取消。`);
        setActionSummary(`execution #${detail.id} 已请求取消`, result.body);
        await loadAndRenderCurrentRoute();
      } catch (error) {
        setNotice(error.message, 'error');
        setActionSummary('execution 取消失败', error.message || String(error), 'error');
      }
    });
  }

  document.getElementById('ops-view-root').onclick = (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    if (action === 'inspect-step') {
      const item = allSteps[Number(button.dataset.index)];
      if (item) detailInspector.textContent = formatJson(item);
    }
    if (action === 'inspect-event') {
      const item = allEvents.find((candidate) => String(candidate.id) === button.dataset.id);
      if (item) detailInspector.textContent = formatJson(item.payload_json && Object.keys(item.payload_json).length ? item.payload_json : item);
    }
    if (action === 'inspect-log') {
      const item = allLogs.find((candidate) => String(candidate.id) === button.dataset.id);
      if (item) logInspector.textContent = formatJson(item);
    }
  };
}

function renderCatalog(payload) {
  const jobRows = (payload.job_specs || [])
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.display_name)}</td>
          <td><code>${escapeHtml(item.key)}</code></td>
          <td>${escapeHtml(item.strategy_type)}</td>
          <td>${escapeHtml(item.executor_kind)}</td>
          <td>${item.supports_schedule ? '是' : '否'}</td>
          <td>${formatNumber(item.schedule_binding_count)}</td>
          <td>${formatNumber(item.active_schedule_count)}</td>
          <td>${escapeHtml((item.supported_params || []).map((param) => param.key).join(', ') || '—')}</td>
        </tr>
      `,
    )
    .join('');
  const workflowRows = (payload.workflow_specs || [])
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml(item.display_name)}</td>
          <td><code>${escapeHtml(item.key)}</code></td>
          <td>${item.supports_schedule ? '是' : '否'}</td>
          <td>${formatNumber(item.schedule_binding_count)}</td>
          <td>${formatNumber(item.active_schedule_count)}</td>
          <td>${escapeHtml((item.steps || []).map((step) => step.display_name).join(' → '))}</td>
        </tr>
      `,
    )
    .join('');

  setViewContent(`
    <section class="panel">
      <h2>Job Specs</h2>
      ${tableOrEmpty(['显示名', 'key', '策略', '执行器', '可调度', '绑定数', '启用中', '参数'], jobRows, '当前没有 job spec。')}
    </section>
    <section class="panel">
      <h2>Workflow Specs</h2>
      ${tableOrEmpty(['显示名', 'key', '可调度', '绑定数', '启用中', '步骤'], workflowRows, '当前没有 workflow spec。')}
    </section>
  `);
}

async function loadAndRenderExecutions(filters = {}) {
  const session = await ensureAdminSession();
  if (!session) return;
  const catalog = await getCatalog();
  const effectiveFilters =
    filters && Object.keys(filters).length
      ? normalizeExecutionFilters(filters)
      : (() => {
          const search = new URLSearchParams(window.location.search);
          if (search.toString()) {
            return normalizeExecutionFilters({
              status: search.get('status') || '',
              trigger_source: search.get('trigger_source') || '',
              spec_key: search.get('spec_key') || '',
            });
          }
          return loadExecutionFilters();
        })();
  const search = new URLSearchParams();
  if (effectiveFilters.status) search.set('status', effectiveFilters.status);
  if (effectiveFilters.trigger_source) search.set('trigger_source', effectiveFilters.trigger_source);
  if (effectiveFilters.spec_key) search.set('spec_key', effectiveFilters.spec_key);
  search.set('limit', '100');
  const result = await callApi(`/api/v1/ops/executions?${search.toString()}`);
  if (!result.ok) throw new Error(result.body.message || `执行列表加载失败 (${result.status})`);
  rememberExecutionListContext(effectiveFilters);
  renderExecutionsPage(catalog, result.body, effectiveFilters);
}

function parseJsonInput(id) {
  const raw = document.getElementById(id).value.trim();
  if (!raw) return {};
  return JSON.parse(raw);
}

async function loadAndRenderCurrentRoute() {
  syncRouteMeta();
  setNotice('');
  clearExecutionDetailAutoRefresh();
  const route = currentRoute();
  try {
    if (route.name === 'overview') {
      const session = await ensureAdminSession();
      if (!session) return;
      const result = await callApi('/api/v1/ops/overview');
      if (!result.ok) throw new Error(result.body.message || `总览加载失败 (${result.status})`);
      renderOverview(result.body);
      return;
    }

    if (route.name === 'freshness') {
      const session = await ensureAdminSession();
      if (!session) return;
      const result = await callApi('/api/v1/ops/freshness');
      if (!result.ok) throw new Error(result.body.message || `新鲜度加载失败 (${result.status})`);
      renderFreshness(result.body);
      return;
    }

    if (route.name === 'schedules') {
      const session = await ensureAdminSession();
      if (!session) return;
      const [catalog, schedules] = await Promise.all([
        getCatalog(),
        callApi('/api/v1/ops/schedules?limit=100'),
      ]);
      if (!schedules.ok) throw new Error(schedules.body.message || `调度列表加载失败 (${schedules.status})`);
      renderSchedulesPage(catalog, schedules.body);
      return;
    }

    if (route.name === 'executions') {
      await loadAndRenderExecutions();
      return;
    }

    if (route.name === 'executionDetail') {
      const session = await ensureAdminSession();
      if (!session) return;
      const [detail, steps, events, logs] = await Promise.all([
        callApi(`/api/v1/ops/executions/${route.executionId}`),
        callApi(`/api/v1/ops/executions/${route.executionId}/steps`),
        callApi(`/api/v1/ops/executions/${route.executionId}/events`),
        callApi(`/api/v1/ops/executions/${route.executionId}/logs`),
      ]);
      if (!detail.ok) throw new Error(detail.body.message || `execution 详情加载失败 (${detail.status})`);
      if (!steps.ok) throw new Error(steps.body.message || `execution steps 加载失败 (${steps.status})`);
      if (!events.ok) throw new Error(events.body.message || `execution events 加载失败 (${events.status})`);
      if (!logs.ok) throw new Error(logs.body.message || `execution logs 加载失败 (${logs.status})`);
      renderExecutionDetail(detail.body, steps.body, events.body, logs.body);
      return;
    }

    if (route.name === 'catalog') {
      const session = await ensureAdminSession();
      if (!session) return;
      const payload = await getCatalog();
      renderCatalog(payload);
      return;
    }
  } catch (error) {
    setNotice(error.message || String(error), 'error');
    setViewContent(`
      <section class="panel">
        <div class="empty">
          <h2>页面加载失败</h2>
          <p>${escapeHtml(error.message || String(error))}</p>
        </div>
      </section>
    `);
  }
}

function bindAuthActions() {
  document.getElementById('btn-login').addEventListener('click', async () => {
    try {
      const username = document.getElementById('login-username').value.trim();
      const password = document.getElementById('login-password').value;
      const result = await callApi('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!result.ok) throw new Error(result.body.message || `登录失败 (${result.status})`);
      currentToken = result.body.token;
      localStorage.setItem(TOKEN_KEY, currentToken);
      opsCatalogCache = null;
      setNotice(`登录成功，当前用户：${result.body.username}`);
      clearActionSummary();
      await loadAndRenderCurrentRoute();
    } catch (error) {
      setNotice(error.message, 'error');
    }
  });

  document.getElementById('btn-logout').addEventListener('click', async () => {
    currentToken = '';
    currentSession = null;
    opsCatalogCache = null;
    localStorage.removeItem(TOKEN_KEY);
    updateAuthChip();
    setNotice('已清理本地 token。');
    clearActionSummary();
    await loadAndRenderCurrentRoute();
  });

  document.getElementById('btn-refresh').addEventListener('click', async () => {
    await loadHealth();
    await loadAndRenderCurrentRoute();
  });
}

async function init() {
  bindAuthActions();
  syncRouteMeta();
  await loadHealth();
  await refreshSession();
  await loadAndRenderCurrentRoute();
}

window.addEventListener('DOMContentLoaded', init);
