// Thin API client. Base is /api in dev (vite proxies to :8000) or VITE_API_BASE.
const BASE = import.meta.env.VITE_API_BASE || '/api'

// active store + project + cadence — every scoped call carries ?store=&project=&audit_type=
// (the cadence isolates the PPC-bulk data: each Audit Cadence hits its own db file)
let STORE = 'zvalves'
let PROJECT = 'default'
let CADENCE = 'full_month'

// ---- auth: bearer token in localStorage, attached to every request ----------
const TOKEN_KEY = 'ppc_token'
export const token = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY)),
}
function authHeaders(extra = {}) {
  const t = token.get()
  return t ? { ...extra, Authorization: `Bearer ${t}` } : extra
}
// every request goes through here: injects the token, and on 401 clears it and
// signals the app to drop back to the login screen.
async function authFetch(url, opts = {}) {
  // never serve a scoped GET from the browser cache — switching store/cadence must
  // always hit the server, or stale previous-scope data leaks through.
  const r = await fetch(url, { cache: 'no-store', ...opts, headers: authHeaders(opts.headers || {}) })
  if (r.status === 401) {
    token.set(null)
    window.dispatchEvent(new Event('ppc-unauthorized'))
  }
  return r
}

// Pull a human message out of a failed response: prefer the API's {detail},
// fall back to status text — never surface a raw "500 {...}" blob to the user.
async function errMessage(r) {
  try {
    const b = await r.clone().json()
    if (b && b.detail) return typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail)
  } catch { /* body not JSON */ }
  const t = await r.text().catch(() => '')
  if (t && !t.trim().startsWith('<')) return t   // plain-text error, but not an HTML page
  if (r.status >= 500) return 'Something went wrong on the server. Please try again.'
  return r.statusText || `Request failed (${r.status})`
}

async function j(path, opts = {}) {
  const r = await authFetch(BASE + path, opts)
  if (!r.ok) throw new Error(await errMessage(r))
  return r.json()
}

// build a query string that always includes the active store + project + cadence.
// audit_type drives the per-cadence db isolation server-side; callers that pass
// their own audit_type (the cadence-tuned audit/dashboard) override the default.
function q(params = {}) {
  const sp = new URLSearchParams({ store: STORE, project: PROJECT, audit_type: CADENCE })
  for (const [k, v] of Object.entries(params)) if (v != null && v !== '') sp.set(k, v)
  return sp.toString()
}

export const api = {
  setStore: (s) => { STORE = s || 'zvalves' },
  setProject: (p) => { PROJECT = p || 'default' },
  setCadence: (c) => { CADENCE = c || 'full_month' },
  getStore: () => STORE,
  getProject: () => PROJECT,
  getCadence: () => CADENCE,

  // ---- auth ----
  isAuthed: () => !!token.get(),
  login: async (username, password) => {
    const r = await authFetch(`${BASE}/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'login failed')
    const d = await r.json(); token.set(d.token); return d.user
  },
  // public self-signup -> auto signs in
  register: async (username, password) => {
    const r = await authFetch(`${BASE}/auth/register`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }) })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'sign up failed')
    const d = await r.json(); token.set(d.token); return d.user
  },
  logout: async () => {
    try { await j('/auth/logout', { method: 'POST' }) } catch { /* ignore */ }
    token.set(null)
  },
  me: () => j('/auth/me'),
  users: () => j('/auth/users'),
  createUser: (username, password, isSuperuser = false) => j('/auth/users',
    { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, is_superuser: isSuperuser }) }),
  deleteUser: (username) => j(`/auth/users/${encodeURIComponent(username)}`, { method: 'DELETE' }),
  setUserPassword: (username, password) => j(`/auth/users/${encodeURIComponent(username)}/password`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) }),

  config: () => j('/config'),
  stores: () => j('/stores'),
  createStore: (title) => j('/stores', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }),
  projects: (store) => j(`/projects?store=${encodeURIComponent(store)}`),
  createProject: (store, title) => j(`/projects?store=${encodeURIComponent(store)}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }),
  // wipe all data in one audit (keeps the audit + its title/goal)
  flush: (store, project) => j(`/flush?${new URLSearchParams({ store, project })}`, { method: 'POST' }),
  // store-level delete (cascades to all audits) + audit-level delete
  deleteStore: (store) => j(`/stores/${encodeURIComponent(store)}`, { method: 'DELETE' }),
  deleteProject: (store, project) => j(`/projects/${encodeURIComponent(project)}?store=${encodeURIComponent(store)}`, { method: 'DELETE' }),
  // audit trail of exported actions
  changelog: (source) => j(`/changelog?${q(source ? { source } : {})}`),
  // change log as a downloadable .xlsx client report
  changelogExport: async (source) => {
    const r = await authFetch(`${BASE}/changelog/export?${q(source ? { source } : {})}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },
  // change log as a copy-paste client report message
  changelogReport: (source) => j(`/changelog/report?${q(source ? { source } : {})}`),
  changelogClear: (source) => j(`/changelog?${q(source ? { source } : {})}`, { method: 'DELETE' }),

  // per-audit checklist (auto items + manual tasks)
  checklist: () => j(`/checklist?${q()}`),
  addTask: (text) => j(`/checklist?${q()}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }),
  toggleTask: (id, done) => j(`/checklist/${id}?${q()}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ done }) }),
  deleteTask: (id) => j(`/checklist/${id}?${q()}`, { method: 'DELETE' }),
  // persist a per-audit Goal ACoS on the project
  updateProjectAcos: (store, project, acos) =>
    j(`/projects/${encodeURIComponent(project)}?store=${encodeURIComponent(store)}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ acos_threshold: acos }) }),

  upload: (file, { targetAcos, snapshot } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    return j(`/upload?${q({ target_acos: targetAcos, snapshot_date: snapshot })}`, { method: 'POST', body: fd })
  },

  // Consultation — tier route + tier-tuned problem scan from one SP bulk
  consultUpload: (file, targetAcos) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/consult/upload?${q({ target_acos: targetAcos })}`, { method: 'POST', body: fd })
  },
  consultRun: () => j(`/consult/run?${q()}`),
  consultTiers: () => j('/consult/tiers'),
  consultClear: () => j(`/consult/data?${q()}`, { method: 'DELETE' }),

  asins: (targetAcos) => j(`/asins?${q({ target_acos: targetAcos })}`),
  audit: (targetAcos, { flag, severity } = {}) => j(`/audit?${q({ target_acos: targetAcos, flag, severity })}`),
  tree: (asin) => j(`/asins/${asin}/tree?${q()}`),
  // daily SALES & PPC tracker (Monitoring)
  monitoring: (start, end, target) => j(`/monitoring?${q({ start, end, target })}`),
  uploadMonitoring: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/monitoring/upload?${q()}`, { method: 'POST', body: fd })
  },
  monitoringClear: () => j(`/monitoring/data?${q()}`, { method: 'DELETE' }),
  // manual total-sales for a month (vs last-month / last-year), null clears it
  setMonthSales: (year, month, sales) => j(`/monitoring/month-sales?${q()}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ year, month, sales }) }),
  // daily tracker -> downloadable .xlsx blob
  monitoringExport: async (start, end, target) => {
    const r = await authFetch(`${BASE}/monitoring/export?${q({ start, end, target })}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // Product Ads — its own dedicated bulk upload + own table (separate from PPC Optimization)
  productAdsUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/product-ads/upload?${q()}`, { method: 'POST', body: fd })
  },
  // every Product Ad (ASIN + SKU) + total, from Product Ads' own uploaded data
  productAds: () => j(`/product-ads?${q()}`),
  productAdsClear: () => j(`/product-ads/data?${q()}`, { method: 'DELETE' }),
  productAdsExport: async () => {
    const r = await authFetch(`${BASE}/product-ads/export?${q()}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },
  // drill-down for selected ASINs: ads + per-campaign rollups
  productAdsDetail: (asins) =>
    j(`/product-ads/detail?${q({ asins: (asins || []).join(',') })}`),

  narrate: (payload) =>
    j('/narrate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),

  // automate returns a file blob, not JSON
  automate: async (flags) => {
    const r = await authFetch(`${BASE}/automate?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ flags })
    })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // search-term harvest: STR file -> promote/negate candidates
  harvest: (file, { targetAcos, minSpend, minOrders } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    return j(`/harvest?${q({ target_acos: targetAcos, min_spend: minSpend, min_orders: minOrders })}`,
      { method: 'POST', body: fd })
  },

  // chosen candidates -> bulk file blob
  harvestBulk: async (candidates) => {
    const r = await authFetch(`${BASE}/harvest/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidates })
    })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },
  // PREFERRED harvest path: the SP BULK file's embedded Search Term Report (real IDs)
  harvestFromBulk: (file, { targetAcos, minSpend, minOrders, projectId } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    return j(`/harvest/from-bulk?${q({ target_acos: targetAcos, min_spend: minSpend,
                                       min_orders: minOrders, project_id: projectId })}`,
      { method: 'POST', body: fd })
  },
  harvestFromBulkFile: async (payload) => {
    const r = await authFetch(`${BASE}/harvest/from-bulk/file?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // n-gram analysis of a Search Term Report
  // backend Search Terms recommendation for the listing (words not already indexed);
  // basis: 'volume' (research demand) | 'harvest' (STR-proven terms first)
  keywordsBackendTerms: (projectId, basis) => j(`/keywords/backend-terms?${q({ project_id: projectId, basis })}`),
  // everything on the Keywords tab -> one .xlsx report
  keywordsExport: async (payload) => {
    const r = await authFetch(`${BASE}/keywords/export?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) })
    if (!r.ok) throw new Error(await errMessage(r))
    return r.blob()
  },
  // grams (+ summary) -> downloadable .xlsx report
  ngramExport: async (grams, summary) => {
    const r = await authFetch(`${BASE}/ngrams/export?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grams, summary }) })
    if (!r.ok) throw new Error(await errMessage(r))
    return r.blob()
  },
  ngrams: (file, { targetAcos, minClicks, projectId } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    return j(`/ngrams?${q({ target_acos: targetAcos, min_clicks: minClicks, project_id: projectId })}`,
      { method: 'POST', body: fd })
  },

  // period-over-period trends from snapshot history
  trends: () => j(`/trends?${q()}`),

  // keyword mining — Brand Analytics SQP + Helium10 Cerebro, consolidated
  uploadKeywords: (file, source) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/keywords/upload?${q({ source })}`, { method: 'POST', body: fd })
  },
  keywords: (projectId) => j(`/keywords?${q({ project_id: projectId })}`),
  keywordRecommend: () => j(`/keywords/recommend?${q()}`),
  clearKeywords: () => j(`/keywords?${q()}`, { method: 'DELETE' }),
  // push mined keywords into a Listing Optimizer project — all, or a selection
  keywordsToProject: (projectId, keywords) => j(`/keywords/to-project?${q()}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, keywords }) }),
  // what-if SEO scorecard: current vs projected — selection (POST, [] = none ->
  // forecast equals current) or whole pool (GET, keywords omitted)
  keywordsProjectPreview: (projectId, keywords) => (keywords != null
    ? j(`/keywords/project-preview?${q()}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, keywords }) })
    : j(`/keywords/project-preview?${q({ project_id: projectId })}`)),
  // merge arbitrary keywords (harvest terms, n-gram winners, manual) into a project
  trackerAddKeywords: (projectId, keywords, source) => j(`/tracker/keywords/bulk?${q()}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, keywords, source }) }),
  // copyable AI prompt: keyword relevancy vs CURRENT + PROPOSED listing copy
  trackerRelevancyPrompt: (projectId) => j(`/tracker/relevancy-prompt?${q({ project_id: projectId })}`),
  // shared keyword-project selection (Keywords tab picks it; harvest/n-gram push to it)
  kwProject: {
    get: () => localStorage.getItem('ppc_kw_project') || '',
    set: (id) => (id ? localStorage.setItem('ppc_kw_project', String(id))
                    : localStorage.removeItem('ppc_kw_project')),
  },

  // strategy advisor — runs the PPC playbook over the account (per cadence via audit_type)
  strategy: (targetAcos, auditType) => j(`/strategy?${q({ target_acos: targetAcos, audit_type: auditType })}`),
  // tier router — campaign-architecture tier suggested from the catalog ASIN count
  strategyTier: () => j(`/strategy/tier?${q()}`),
  // one-click: strategy name -> Amazon bulk file (scoped to the same cadence)
  strategyBulk: async (name, targetAcos, auditType) => {
    const r = await authFetch(`${BASE}/strategy/bulk?${q({ name, target_acos: targetAcos, audit_type: auditType })}`, { method: 'POST' })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // dashboard reporting summary (KPIs + flag/ladder breakdown)
  report: (targetAcos) => j(`/report?${q({ target_acos: targetAcos })}`),
  // one-shot refresh: asins + flags + report + first-ASIN tree in a single call
  dashboard: (targetAcos, auditType) => j(`/dashboard?${q({ target_acos: targetAcos, audit_type: auditType })}`),
  dashboardAnalytics: (targetAcos, auditType) => j(`/dashboard/analytics?${q({ target_acos: targetAcos, audit_type: auditType })}`),
  dashboardExport: async (targetAcos, auditType) => {
    const r = await authFetch(`${BASE}/dashboard/export?${q({ target_acos: targetAcos, audit_type: auditType })}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // all-stores KPI overview (the redesigned store picker)
  storesOverview: (targetAcos) => j(`/stores/overview?${q({ target_acos: targetAcos })}`),
  // audit cadence: presets + saved monthly runs
  cadencePresets: () => j('/cadence/presets'),
  cadenceRuns: () => j(`/cadence/runs?${q()}`),
  // refresh=true (the tile's audit button) recomputes the captured numbers at the
  // current Goal ACoS; plain opens return the stored snapshot.
  createCadenceRun: (year, month, auditType, targetAcos, refresh = false) => j(`/cadence/runs?${q({ audit_type: auditType })}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ year, month, audit_type: auditType, target_acos: targetAcos, refresh }) }),
  toggleCadenceTask: (id, done) => j(`/cadence/tasks/${id}?${q()}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ done }) }),
  deleteCadenceRun: (id) => j(`/cadence/runs/${id}?${q()}`, { method: 'DELETE' }),

  // daily watch: dated bulk uploads + day-over-day anomaly compare + trend
  dailyWatchUpload: (file, day, targetAcos) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/daily-watch/upload?${q({ day, target_acos: targetAcos })}`, { method: 'POST', body: fd })
  },
  dailyWatchMonitors: (targetAcos) => j(`/daily-watch/monitors?${q({ target_acos: targetAcos })}`),
  dailyWatchMonitor: (campaignId, name) => j(`/daily-watch/monitor?${q()}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ campaign_id: campaignId, name }) }),
  dailyWatchUnmonitor: (campaignId) => j(`/daily-watch/monitor?${q({ campaign_id: campaignId })}`, { method: 'DELETE' }),
  dailyWatchDays: () => j(`/daily-watch/days?${q()}`),
  dailyWatchDelete: (day) => j(`/daily-watch/day?${q({ day })}`, { method: 'DELETE' }),
  dailyWatchCompare: (yesterday, today, targetAcos) =>
    j(`/daily-watch/compare?${q({ yesterday, today, target_acos: targetAcos })}`),
  dailyWatchSeries: (start, end) => j(`/daily-watch/series?${q({ start, end })}`),
  dailyWatchAnomalies: () => j(`/daily-watch/anomalies?${q()}`),
  dailyWatchClearAll: () => j(`/daily-watch/data?${q()}`, { method: 'DELETE' }),

  // clear ONE cadence's uploaded data from its tile (Audit Cadence grid) — the
  // explicit audit_type override targets that cadence's own db file even when a
  // different cadence is currently active.
  cadenceClear: (auditType) => {
    const path = { daily: '/daily-watch/data', weekly: '/weekly/data', mid_month: '/mid-month/data',
      full_month: '/full-month/data', pause_scale: '/pause-scale/data' }[auditType]
    if (!path) return Promise.reject(new Error(`unknown cadence: ${auditType}`))
    return j(`${path}?${q({ audit_type: auditType })}`, { method: 'DELETE' })
  },

  // weekly optimization: per-week SP Search Term Report -> bid tweaks + harvest -> bulk
  weeklyUpload: (file, week) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/weekly/upload?${q({ week })}`, { method: 'POST', body: fd })
  },
  weeklyWeeks: () => j(`/weekly/weeks?${q()}`),
  weeklyDelete: (week) => j(`/weekly/week?${q({ week })}`, { method: 'DELETE' }),
  weeklyClearAll: () => j(`/weekly/data?${q()}`, { method: 'DELETE' }),
  weeklySeries: () => j(`/weekly/series?${q()}`),
  weeklyCompare: (prev, cur, targetAcos) =>
    j(`/weekly/compare?${q({ prev, cur, target_acos: targetAcos })}`),
  weeklyPlan: (targetAcos, week) => j(`/weekly/plan?${q({ target_acos: targetAcos, week })}`),
  weeklyBulk: async (payload) => {
    const r = await authFetch(`${BASE}/weekly/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // mid-month: single SP Search Term Report -> bid adjustments + negatives -> bulk
  midMonthUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/mid-month/upload?${q()}`, { method: 'POST', body: fd })
  },
  midMonthPlan: (targetAcos) => j(`/mid-month/plan?${q({ target_acos: targetAcos })}`),
  midMonthCompare: (targetAcos) => j(`/mid-month/compare?${q({ target_acos: targetAcos })}`),
  midMonthClear: () => j(`/mid-month/data?${q()}`, { method: 'DELETE' }),
  midMonthBulk: async (payload) => {
    const r = await authFetch(`${BASE}/mid-month/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // full month: single SP Search Term Report -> full optimization (bid + harvest + negatives)
  fullMonthUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/full-month/upload?${q()}`, { method: 'POST', body: fd })
  },
  fullMonthPlan: (targetAcos) => j(`/full-month/plan?${q({ target_acos: targetAcos })}`),
  fullMonthCompare: (targetAcos) => j(`/full-month/compare?${q({ target_acos: targetAcos })}`),
  fullMonthClear: () => j(`/full-month/data?${q()}`, { method: 'DELETE' }),
  fullMonthBulk: async (payload) => {
    const r = await authFetch(`${BASE}/full-month/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // pause/scale: single SP Search Term Report -> scale winners + pause dead targets/campaigns
  pauseScaleUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/pause-scale/upload?${q()}`, { method: 'POST', body: fd })
  },
  pauseScalePlan: (targetAcos) => j(`/pause-scale/plan?${q({ target_acos: targetAcos })}`),
  pauseScaleClear: () => j(`/pause-scale/data?${q()}`, { method: 'DELETE' }),
  pauseScaleBulk: async (payload) => {
    const r = await authFetch(`${BASE}/pause-scale/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // waterfall restructure engine (account-level, base db — cadence-agnostic)
  waterfallSettings: () => j(`/waterfall/settings?${q()}`),
  waterfallSaveSettings: (s) => j(`/waterfall/settings?${q()}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(s) }),
  waterfallUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/waterfall/upload?${q()}`, { method: 'POST', body: fd })
  },
  waterfallRun: () => j(`/waterfall/run?${q()}`),
  waterfallClear: () => j(`/waterfall/data?${q()}`, { method: 'DELETE' }),
  waterfallBulk: async (phase, ids) => {
    const r = await authFetch(`${BASE}/waterfall/bulk?${q({ phase })}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }) })
    if (!r.ok) throw new Error(await errMessage(r))
    return r.blob()
  },
  waterfallApplied: (phase) => j(`/waterfall/applied?${q({ phase })}`, { method: 'POST' }),
  waterfallOverride: (overrides) => j(`/waterfall/override?${q()}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ overrides }) }),
  waterfallBenchmark: () => j(`/waterfall/benchmark?${q()}`),
  waterfallLedger: () => j(`/waterfall/ledger?${q()}`),
  waterfallLedgerApplied: (payload) => j(`/waterfall/ledger/applied?${q()}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}) }),
  waterfallLedgerDiscard: (payload) => j(`/waterfall/ledger/discard?${q()}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}) }),

  // cannibalization / keyword ownership detector (account-level, base db)
  cannibalRun: (file, targetAcos) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/cannibal/run?${q({ target_acos: targetAcos })}`, { method: 'POST', body: fd })
  },
  cannibalFindings: (kind) => j(`/cannibal/findings?${q(kind ? { kind } : {})}`),
  cannibalClear: () => j(`/cannibal/data?${q()}`, { method: 'DELETE' }),
  cannibalBulk: async (findings) => {
    const r = await authFetch(`${BASE}/cannibal/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ findings }) })
    if (!r.ok) throw new Error(await errMessage(r))
    return r.blob()
  },

  // reporting summary (exec report) + Excel export
  reportSummary: (targetAcos) => j(`/report/summary?${q({ target_acos: targetAcos })}`),
  reportExport: async (targetAcos) => {
    const r = await authFetch(`${BASE}/report/export?${q({ target_acos: targetAcos })}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // bid optimization: full-portfolio optimizer + placement
  bidsOptimize: (targetAcos) => j(`/bids/optimize?${q({ target_acos: targetAcos })}`),
  bidsOptimizeBulk: async (rows) => {
    const r = await authFetch(`${BASE}/bids/optimize/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows }) })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },
  placements: (targetAcos) => j(`/placements?${q({ target_acos: targetAcos })}`),
  placementsBulk: async (rows, companions) => {
    const r = await authFetch(`${BASE}/placements/bulk?${q()}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows, companions: companions || [] }) })
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // channels — SB/SD ingestion + channel mix (account-level, base db)
  channelsUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/channels/upload?${q()}`, { method: 'POST', body: fd })
  },
  channelsSummary: (targetAcos) => j(`/channels/summary?${q({ target_acos: targetAcos })}`),
  channelsClear: () => j(`/channels/data?${q()}`, { method: 'DELETE' }),
  channelsSbKeywords: (targetAcos) => j(`/channels/sb-keywords?${q({ target_acos: targetAcos })}`),
  channelsSdTargets: (targetAcos) => j(`/channels/sd-targets?${q({ target_acos: targetAcos })}`),
  channelsSbHarvest: (targetAcos) => j(`/channels/sb-harvest?${q({ target_acos: targetAcos })}`),
  channelsBrandTerms: () => j(`/channels/brand-terms?${q()}`),
  channelsSaveBrandTerms: (terms) => j(`/channels/brand-terms?${q()}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ terms }) }),

  // Listing Optimizer — competitor research / indexed keywords / SEO tracker (base db)
  trackerProjects: () => j(`/tracker/projects?${q()}`),
  trackerCreateProject: (name, primaryAsin) => j(`/tracker/projects?${q()}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, primary_asin: primaryAsin }),
  }),
  trackerDeleteProject: (id) => j(`/tracker/projects/${id}?${q()}`, { method: 'DELETE' }),
  trackerXray: (file, projectId) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/tracker/xray?${q({ project_id: projectId })}`, { method: 'POST', body: fd })
  },
  trackerListing: (projectId, variant) => j(`/tracker/listing?${q({ project_id: projectId, variant })}`),
  trackerSetListing: (projectId, element, text, variant, asin) => j(`/tracker/listing?${q()}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, element, text, variant, asin }),
  }),
  // Product Benchmark catalog — Category Listings Report, store-level (merges by SKU)
  catalog: () => j(`/catalog?${q()}`),
  catalogItem: (sku) => j(`/catalog/item?${q({ sku })}`),
  catalogUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/catalog/upload?${q()}`, { method: 'POST', body: fd })
  },
  catalogClear: () => j(`/catalog?${q()}`, { method: 'DELETE' }),
  // base fulfillment fee per unit (FBA Fee Preview report), store-level
  catalogFbaUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/catalog/fba-fees/upload?${q()}`, { method: 'POST', body: fd })
  },
  catalogFbaFees: () => j(`/catalog/fba-fees?${q()}`),
  catalogFbaClear: () => j(`/catalog/fba-fees?${q()}`, { method: 'DELETE' }),
  catalogSetCogs: (sku, value) => j(`/catalog/cogs?${q()}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sku, value }),
  }),
  catalogExport: async () => {
    const r = await authFetch(`${BASE}/catalog/export?${q()}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },
  // SKU-level transactions (Payments Date Range report) — store-level, merges/dedupes
  catalogTxn: (start, end, sku) => j(`/catalog/transactions?${q({ start, end, sku })}`),
  catalogTxnUpload: (file) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/catalog/transactions/upload?${q()}`, { method: 'POST', body: fd })
  },
  catalogTxnClear: () => j(`/catalog/transactions?${q()}`, { method: 'DELETE' }),
  catalogTxnExport: async (start, end) => {
    const r = await authFetch(`${BASE}/catalog/transactions/export?${q({ start, end })}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },
  trackerFromCatalog: (projectId, sku) => j(`/tracker/listing/from-catalog?${q()}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, sku }),
  }),
  trackerBanned: () => j(`/tracker/banned?${q()}`),
  trackerSetBanned: (text) => j(`/tracker/banned?${q()}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }),
  trackerSanitize: (projectId) => j(`/tracker/sanitize?${q({ project_id: projectId })}`),
  trackerMigrate: (file, name, snapshotDate) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/tracker/migrate?${q({ name, snapshot_date: snapshotDate })}`, { method: 'POST', body: fd })
  },
  trackerImport: (file, projectId, checkedAt, asin) => {
    const fd = new FormData(); fd.append('file', file)
    return j(`/tracker/import?${q({ project_id: projectId, checked_at: checkedAt, asin })}`, { method: 'POST', body: fd })
  },
  trackerCompetitors: (projectId) => j(`/tracker/competitors?${q({ project_id: projectId })}`),
  trackerSetCompetitor: (id, field, value) => j(`/tracker/competitor?${q()}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, field, value }),
  }),
  trackerMatrix: (projectId, date) => j(`/tracker/matrix?${q({ project_id: projectId, date })}`),
  trackerScorecard: (projectId) => j(`/tracker/scorecard?${q({ project_id: projectId })}`),
  trackerMovers: (projectId) => j(`/tracker/movers?${q({ project_id: projectId })}`),
  trackerCell: (keywordId, asin, rank) => j(`/tracker/cell?${q()}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword_id: keywordId, asin, rank }),
  }),
  trackerSuggest: (projectId) => j(`/tracker/ppc-suggest?${q({ project_id: projectId })}`, { method: 'POST' }),
  trackerSeoRecommend: (projectId, variant) => j(`/tracker/seo-recommend?${q({ project_id: projectId, variant })}`),
  trackerExport: async (projectId, date) => {
    const r = await authFetch(`${BASE}/tracker/export?${q({ project_id: projectId, date })}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },
  // full Product Optimization exec report (xlsx with native Excel charts)
  trackerReport: async (projectId) => {
    const r = await authFetch(`${BASE}/tracker/report/export?${q({ project_id: projectId })}`)
    if (!r.ok) throw new Error(await r.text())
    return r.blob()
  },

  // per-ASIN break-even benchmark
  benchmark: () => j(`/benchmark?${q()}`),
  uploadBenchmark: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return j(`/benchmark/upload?${q()}`, { method: 'POST', body: fd })
  },
}
