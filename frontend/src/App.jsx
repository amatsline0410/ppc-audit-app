import React, { useEffect, useState, useCallback, useRef } from 'react'
import { api } from './api/client.js'
import { pct, Spinner, TableSkeleton, Icon, FlagLegend } from './components/ui.jsx'
import { TargetAcosControl } from './components/Upload.jsx'
import { AuditTable, flagKey } from './components/AuditTable.jsx'
import { AsinTree, NarratePanel } from './components/Panels.jsx'
import { HarvestPanel } from './components/Harvest.jsx'
import { TrendsPanel, NgramPanel } from './components/Insights.jsx'
import { ProfitDashboard } from './components/ProfitDashboard.jsx'
import { ReportsPanel } from './components/Reports.jsx'
import { BidOptimizerPanel, PlacementPanel } from './components/Bids.jsx'
import { ChangeLogPanel } from './components/ChangeLog.jsx'
import { StrategyPanel } from './components/Strategy.jsx'
import { ChecklistCard } from './components/Checklist.jsx'
import { KeywordsPanel } from './components/Keywords.jsx'
import { TrackerPanel } from './components/Tracker.jsx'
import { ProductCatalogPanel } from './components/Catalog.jsx'
import { TransactionsPanel } from './components/Transactions.jsx'
import { ProductAdsPanel } from './components/ProductAds.jsx'
import { MonitoringPanel } from './components/Monitoring.jsx'
import { StoresOverview } from './components/StoresOverview.jsx'
import { SideDrawer } from './components/Drawer.jsx'
import { AuditCadence } from './components/AuditCadence.jsx'
import { WaterfallPanel } from './components/Waterfall.jsx'
import { ConsultationPanel } from './components/Consultation.jsx'
import { CannibalizationPanel } from './components/Cannibalization.jsx'
import { ChannelsPanel } from './components/Channels.jsx'
import { Login } from './components/Login.jsx'
import { UsersPanel } from './components/Users.jsx'
import { ModalProvider, useModals } from './components/Modal.jsx'
import { ToastProvider, useToast } from './components/Toast.jsx'

// Icons are Material Symbols ligature names (rendered via <Icon>, see ui.jsx).
const TABS = [
  ['dashboard', 'Dashboard', 'dashboard'],
  ['stores', 'Stores', 'storefront'],
  ['ppc', 'PPC Optimization', 'ads_click'],
  ['productads', 'Product Ads', 'shopping_bag'],
  ['consult', 'Tier Recommendations', 'support_agent'],
  ['waterfall', 'Waterfall', 'waterfall_chart'],
  ['cannibal', 'Cannibalization', 'call_split'],
  ['channels', 'Channels', 'hub'],
  ['monitoring', 'Monitoring', 'monitoring'],
  ['keywords', 'Keywords', 'key'],
  ['seo', 'SEO', 'travel_explore'],
  ['listing', 'Listing Audit', 'fact_check'],
  ['products', 'Product Overview', 'inventory_2'],
  ['catalog', 'Product Benchmark', 'menu_book'],
  ['transactions', 'Transactions', 'receipt_long'],
  ['strategy', 'Strategy', 'strategy'],
  ['reports', 'Reports', 'assessment'],
  ['log', 'Change Log', 'history'],
]
const TAB_TITLE = Object.fromEntries(TABS.map(([id, label]) => [id, label]))

// Sidebar nav: leaves render as before; a group renders a collapsible submenu.
// PPC-related features (PPC Optimization, Product Ads, Strategy…) grouped under "PPC Suite".
// Structure tools (Tier Recommendations advisor, Waterfall) get their own
// top-level "Consultation" group — same rank as PPC Suite.
const NAV = [
  ['dashboard', 'Dashboard', 'dashboard'],
  ['stores', 'Stores', 'storefront'],
  { group: 'PPC Suite', icon: 'apps', children: [
    ['ppc', 'PPC Optimization', 'ads_click'],
    ['productads', 'Product Ads', 'shopping_bag'],
    ['cannibal', 'Cannibalization', 'call_split'],
    ['channels', 'Channels', 'hub'],
    ['strategy', 'Strategy', 'strategy'],
  ] },
  { group: 'Consultation', icon: 'support_agent', children: [
    ['consult', 'Tier Recommendations', 'support_agent'],
    ['waterfall', 'Waterfall', 'waterfall_chart'],
  ] },
  { group: 'Product Optimization', icon: 'category', children: [
    ['keywords', 'Keywords', 'key'],
    ['seo', 'SEO', 'travel_explore'],
    ['listing', 'Listing Audit', 'fact_check'],
    ['products', 'Product Overview', 'inventory_2'],
  ] },
  { group: 'Product Base', icon: 'inventory', children: [
    ['catalog', 'Product Benchmark', 'menu_book'],
    ['transactions', 'Transactions', 'receipt_long'],
  ] },
  ['monitoring', 'Monitoring', 'monitoring'],
  ['reports', 'Reports', 'assessment'],
  ['log', 'Change Log', 'history'],
]

// ---- URL routing (History API, no router dep) -------------------------------
// path shape: /<store>/<tab-slug>[/<cadence-slug>]  e.g. /zvalves/ppc-optimization/daily-watch
const TAB_SLUG = { dashboard: 'dashboard', stores: 'stores', ppc: 'ppc-optimization',
  productads: 'product-ads', consult: 'tier-recommendations', waterfall: 'waterfall',
  cannibal: 'cannibalization',
  channels: 'channels', monitoring: 'monitoring',
  keywords: 'keywords', seo: 'seo', listing: 'listing-audit', products: 'product-overview',
  catalog: 'product-benchmark', transactions: 'transactions',
  strategy: 'strategy', reports: 'reports', log: 'change-log',
  users: 'users' }
const SLUG_TAB = Object.fromEntries(Object.entries(TAB_SLUG).map(([k, v]) => [v, k]))
SLUG_TAB['listing-optimizer'] = 'seo'      // old URL slugs — keep bookmarks working
SLUG_TAB['product-list'] = 'products'
SLUG_TAB['ppc-audit'] = 'ppc'
SLUG_TAB['bulk-upload'] = 'ppc'    // removed Bulk Upload tab — old links land on PPC Optimization
SLUG_TAB['consultation'] = 'consult'          // tab renamed to Tier Recommendations
SLUG_TAB['structure-redesign'] = 'consult'    // removed Structure Redesign tab
const CAD_SLUG = { daily: 'daily-watch', weekly: 'weekly', mid_month: 'mid-month',
  full_month: 'full-month', pause_scale: 'pause-scale' }
const SLUG_CAD = Object.fromEntries(Object.entries(CAD_SLUG).map(([k, v]) => [v, k]))
// tabs whose URL carries the cadence as a second segment
const CADENCE_TABS = new Set(['ppc', 'strategy'])

function parsePath() {
  const [seg1, seg2, seg3] = window.location.pathname.replace(/^\/+/, '').split('/')
  return { store: seg1 ? decodeURIComponent(seg1) : null,
           tab: SLUG_TAB[seg2] || 'dashboard', cad: (seg3 && SLUG_CAD[seg3]) || null }
}
function pathFor(store, tab, auditType) {
  let p = '/' + encodeURIComponent(store || '') + '/' + (TAB_SLUG[tab] || tab)
  if (CADENCE_TABS.has(tab)) p += '/' + (CAD_SLUG[auditType] || 'full-month')
  return p
}

function AppShell({ user, onLogout }) {
  const { confirm, prompt } = useModals()
  const toast = useToast()
  const [cfg, setCfg] = useState(null)
  const [targetAcos, setTargetAcos] = useState(null)   // per-audit Goal ACoS; null until loaded from meta (avoid fetching with the wrong default)
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  // no scoped fetch may fire before the user's real store list is in — the initial
  // `store` value is a guess (URL/localStorage/legacy 'zvalves' fallback) and
  // fetching with a store the user doesn't own would 404 or re-create it server-side
  const [storesLoaded, setStoresLoaded] = useState(false)
  const [stores, setStores] = useState([{ id: 'zvalves', title: 'ZValves' }])
  const [store, setStore] = useState(() => parsePath().store || localStorage.getItem('ppc_store') || 'zvalves')
  const [projects, setProjects] = useState([{ id: 'default', title: 'Default' }])
  const [project, setProject] = useState(() => localStorage.getItem('ppc_project') || 'default')
  const [flags, setFlags] = useState([])
  const [tree, setTree] = useState(null)        // full ASIN forest (all ASINs)
  const [report, setReport] = useState(null)
  // harvest + n-gram results lifted here so they survive tab switches / are shared
  const [harvestCands, setHarvestCands] = useState(null)
  const [harvestFromBulk, setHarvestFromBulk] = useState(false)
  const [ngramRes, setNgramRes] = useState(null)
  const setHarvestManual = useCallback((c) => { setHarvestCands(c); setHarvestFromBulk(false) }, [])
  const [selected, setSelected] = useState(new Set())
  const [narration, setNarration] = useState('')
  const [busy, setBusy] = useState({ load: false, up: false, auto: false, narr: false })
  const [err, setErr] = useState(null)
  const [tab, setTab] = useState(() => parsePath().tab)
  // Product Benchmark "Perform Listing Audit" -> select this tracker project when
  // the Product Optimization panel opens ({ pid, ts } so repeat clicks re-fire)
  const [trackerFocus, setTrackerFocus] = useState(null)
  const [auditType, setAuditType] = useState(() => parsePath().cad || 'full_month')   // PPC Optimization cadence preset
  const auditTypeRef = useRef(auditType)   // current cadence for callbacks resolving after async work
  useEffect(() => { auditTypeRef.current = auditType }, [auditType])
  const [cadenceMeta, setCadenceMeta] = useState(null)       // active preset: { focus, feature, table_title }
  const [sidebarOpen, setSidebarOpen] = useState(() => localStorage.getItem('ppc_sidebar') !== '0')
  useEffect(() => { localStorage.setItem('ppc_sidebar', sidebarOpen ? '1' : '0') }, [sidebarOpen])
  // PPC Audit setup drawer (cart-style overlay) — open state survives refresh
  const [drawerOpen, setDrawerOpen] = useState(() => localStorage.getItem('ppc_drawer') === '1')
  useEffect(() => { localStorage.setItem('ppc_drawer', drawerOpen ? '1' : '0') }, [drawerOpen])
  const [openGroups, setOpenGroups] = useState(() => ({ 'PPC Suite': true }))   // collapsible nav groups
  const [visited, setVisited] = useState({ dashboard: true })   // keep-alive: mount a tab once, then hide (don't unmount) so panel state survives
  const [dataVer, setDataVer] = useState(0)   // bump to refetch profit/sales after edits
  const bump = useCallback(() => setDataVer(v => v + 1), [])
  // per-cadence data versions: an upload/clear in ONE cadence only reloads that
  // cadence's panel (the others keep their state — no cross-cadence loading).
  const [cadVers, setCadVers] = useState({})
  const bumpCadence = useCallback((k) => setCadVers(v => ({ ...v, [k]: (v[k] || 0) + 1 })), [])
  // data landed (upload/clear) for cadence k: reload that cadence's panel, and only
  // touch the global active-cadence views (flags/tree/Bid Optimizer/Placement/
  // Dashboard/Reports) when k IS the active cadence — a background upload finishing
  // in another cadence must not reload what's on screen.
  const onCadenceData = useCallback((k) => { bumpCadence(k); if (k === auditTypeRef.current) bump() }, [bumpCadence, bump])
  // hard reset (audit flush) — forces every cadence panel to refetch
  const [resetVer, setResetVer] = useState(0)
  // set the active cadence on the api SYNCHRONOUSLY (before any child panel refetch)
  // so per-cadence calls hit the right db file the moment a cadence is picked.
  // Lifted per-cadence results (harvest / n-gram / narration) are cleared too —
  // they came from ONE cadence's data and must never show under another.
  const changeCadence = useCallback((c) => {
    api.setCadence(c); setAuditType(c); setSelected(new Set())
    setHarvestCands(null); setHarvestFromBulk(false); setNgramRes(null); setNarration('')
  }, [])
  useEffect(() => { setVisited(v => (v[tab] ? v : { ...v, [tab]: true })) }, [tab])
  // reflect the active tab (+ cadence, for cadence tabs) in the URL, and follow
  // browser back/forward. History API only — no router dependency.
  // Gated on storesLoaded: before validation `store` is a guess (stale
  // localStorage / legacy default) — a store the user may not own must never
  // appear in the address bar. Once the real list is in, the URL always names
  // the user's actual store: /<your-store>/<tab>[/<cadence>].
  useEffect(() => {
    if (!storesLoaded) return
    const path = pathFor(store, tab, auditType)
    if (window.location.pathname !== path) window.history.pushState({}, '', path)
  }, [store, tab, auditType, storesLoaded])
  useEffect(() => {
    const onPop = () => {
      const { store: s, tab: t, cad } = parsePath()
      if (s) setStore(s)
      setTab(t)
      if (cad) changeCadence(cad)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [changeCadence])
  // keep a nav group expanded whenever one of its children is the active tab
  useEffect(() => {
    const g = NAV.find(x => !Array.isArray(x) && x.children.some(([id]) => id === tab))
    if (g) setOpenGroups(o => (o[g.group] ? o : { ...o, [g.group]: true }))
  }, [tab])

  // load config + store list once
  useEffect(() => {
    // NOTE: don't seed targetAcos from the global default here — the per-audit Goal
    // ACoS (below) is the source of truth. Seeding the default first makes children
    // fetch with 0.25 before the saved 0.20 loads.
    api.config().then(c => setCfg(c)).catch(e => setErr(String(e)))
    api.stores().then(s => {
      setStores(s.stores)
      // URL/localStorage may name a store that doesn't exist for this user
      // (deleted store, or the legacy 'zvalves' default) — fall back to first
      setStore(cur => (s.stores.some(x => x.id === cur) ? cur : (s.stores[0]?.id || cur)))
      setStoresLoaded(true)
    }).catch(() => setStoresLoaded(true))   // still unblock the UI; 401 handling takes over
  }, [])

  // when the active store changes, load its projects + pick one.
  // Gated on storesLoaded: the pre-validation store value must never hit the API.
  useEffect(() => {
    if (!storesLoaded) return
    api.setStore(store); localStorage.setItem('ppc_store', store)
    setProjectsLoaded(false)
    api.projects(store).then(r => {
      setProjects(r.projects)
      setProject(p => (r.projects.some(x => x.id === p) ? p : (r.projects[0]?.id || 'default')))
      setProjectsLoaded(true)
    }).catch(() => {})
  }, [store, storesLoaded])

  // each audit carries its own Goal ACoS — load it once the real project list is in
  // (not the placeholder), so children never fetch with the global default first.
  useEffect(() => {
    if (!cfg || !projectsLoaded) return
    const meta = projects.find(p => p.id === project)
    setTargetAcos(meta?.acos_threshold ?? cfg.default_target_acos)
  }, [cfg, project, projects, projectsLoaded])

  // user moved the knob: update + persist to this audit only
  const changeAcos = useCallback((t) => {
    setTargetAcos(t)
    setProjects(ps => ps.map(p => (p.id === project ? { ...p, acos_threshold: t } : p)))
    api.updateProjectAcos(store, project, t).catch(e => setErr(String(e)))
  }, [store, project])

  // refresh audit whenever target ACoS changes (the headline knob).
  // seq guard: only the newest request may write state (kills stale responses
  // when the user flips audits faster than the network).
  const reqRef = useRef(0)
  const refresh = useCallback(async (t, at) => {
    const id = ++reqRef.current
    setBusy(b => ({ ...b, load: true })); setErr(null)
    try {
      const d = await api.dashboard(t, at)   // asins + flags + report + full ASIN forest in ONE call
      if (id !== reqRef.current) return
      setFlags(d.flags); setReport(d.report); setTree(d.trees || (d.tree ? [d.tree] : []))
    } catch (e) { if (id === reqRef.current) setErr(String(e)) }
    finally { if (id === reqRef.current) setBusy(b => ({ ...b, load: false })) }
  }, [])

  // re-audit on target ACoS / store / project change; store+project set before any call.
  // debounced so an audit switch (project change + its acos load) coalesces into ONE fetch.
  useEffect(() => {
    if (!cfg || targetAcos == null) return   // wait for the per-audit Goal ACoS to load
    api.setStore(store); api.setProject(project); api.setCadence(auditType)
    localStorage.setItem('ppc_project', project)
    setSelected(new Set())
    const id = setTimeout(() => refresh(targetAcos, auditType), 120)
    return () => clearTimeout(id)
  }, [cfg, targetAcos, store, project, auditType, refresh])

  // re-pull report after a sales/cost edit (dataVer bump), without re-running the debounce
  useEffect(() => {
    if (cfg && dataVer && targetAcos != null) refresh(targetAcos, auditType)
  }, [dataVer]) // eslint-disable-line react-hooks/exhaustive-deps

  async function addStore() {
    const title = await prompt({ title: 'New store', placeholder: 'Store name', confirmLabel: 'Create' })
    if (!title?.trim()) return
    try {
      const s = await api.createStore(title.trim())
      const list = await api.stores(); setStores(list.stores)
      setStore(s.id)   // store-change effect loads its default project
      toast.success(`Store “${title.trim()}” created`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
  }

  async function addProject() {
    const title = await prompt({ title: 'New audit', placeholder: 'Audit title', confirmLabel: 'Create' })
    if (!title?.trim()) return
    try {
      const p = await api.createProject(store, title.trim())
      const r = await api.projects(store); setProjects(r.projects)
      setProject(p.id)   // upload a bulk file next to populate it
      toast.success(`Audit “${title.trim()}” created`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
  }

  async function handleDeleteStore(targetId) {
    const target = typeof targetId === 'string' ? targetId : store
    const title = stores.find(s => s.id === target)?.title || target
    const remaining = stores.find(s => s.id !== target)?.id
    if (!remaining) { setErr('Cannot delete the only store.'); return }
    const ok = await confirm({
      title: `Delete store “${title}”?`, danger: true, confirmLabel: 'Delete store',
      message: `This removes EVERY audit in the store, its bulk data, and the store's benchmark.\n\nThis cannot be undone.` })
    if (!ok) return
    setErr(null)
    // switch away FIRST so no in-flight request re-creates the store (get_db auto-creates)
    if (target === store) { api.setStore(remaining); setStore(remaining) }
    try {
      await api.deleteStore(target)
      const list = await api.stores(); setStores(list.stores)
      toast.success(`Store “${title}” deleted`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
  }

  async function handleDeleteProject(targetId) {
    const target = typeof targetId === 'string' ? targetId : project
    const title = projects.find(p => p.id === target)?.title || target
    const remaining = projects.find(p => p.id !== target)?.id
    if (!remaining) { setErr('Cannot delete the only audit — flush it instead.'); return }
    const ok = await confirm({
      title: `Delete audit “${title}”?`, danger: true, confirmLabel: 'Delete audit',
      message: 'Removes this audit and all its data.\n\nThis cannot be undone.' })
    if (!ok) return
    setErr(null)
    // switch away FIRST so nothing re-queries (and re-creates) the deleted audit
    if (target === project) { api.setProject(remaining); setProject(remaining) }
    try {
      await api.deleteProject(store, target)
      const r = await api.projects(store); setProjects(r.projects)
      toast.success(`Audit “${title}” deleted`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
  }

  async function handleFlush(targetId) {
    const target = typeof targetId === 'string' ? targetId : project
    const title = projects.find(p => p.id === target)?.title || target
    const ok = await confirm({
      title: `Flush all data in “${title}”?`, danger: true, confirmLabel: 'Flush data',
      message: 'Wipes bulk, benchmark, placements, daily watch, and cadence runs for this audit only.\n\nThe audit and its Goal ACoS are kept. This cannot be undone.' })
    if (!ok) return
    setErr(null)
    try {
      await api.flush(store, target)
      bump()                 // refetch sales/profit/benchmark panels
      setResetVer(v => v + 1)   // flush wipes every cadence — reload all cadence panels
      await refresh(targetAcos)
      toast.success(`Flushed all data in “${title}”`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
  }

  async function handleAutomate() {
    setBusy(b => ({ ...b, auto: true }))
    try {
      const chosen = flags.filter(f => selected.has(flagKey(f)))
      const blob = await api.automate(chosen)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'ppc_automation_bulk.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success(`Automation bulk downloaded · ${chosen.length} flag${chosen.length === 1 ? '' : 's'}`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
    finally { setBusy(b => ({ ...b, auto: false })) }
  }

  async function handleNarrate(mode) {
    setBusy(b => ({ ...b, narr: true }))
    try {
      const res = await api.narrate({ target_acos: targetAcos, mode, flags })
      setNarration(res.text)
    } catch (e) { setErr(String(e)) }
    finally { setBusy(b => ({ ...b, narr: false })) }
  }

  // one nav leaf button (used at top level + inside a group submenu)
  const navLeaf = ([id, label, icon]) => (
    <button key={id} onClick={() => setTab(id)}
      className={`w-full flex items-center gap-3 px-3 py-2 rounded font-mono text-sm transition-colors ${tab === id ? 'bg-lime/10 text-lime border-l-2 border-lime' : 'text-mute hover:text-slate-200 hover:bg-edge/30 border-l-2 border-transparent'}`}>
      <Icon name={icon} size={18} className="w-5 text-center" />{label}
    </button>
  )

  // Sync the api's active scope DURING render — child effects fire before the parent
  // effect (bottom-up), so setting these in a useEffect would let a child refetch with
  // the PREVIOUS store/cadence and show stale data. Setting here (idempotent) guarantees
  // every child effect this commit reads the current scope.
  api.setStore(store); api.setProject(project); api.setCadence(auditType)

  return (
    <div className="min-h-screen bg-grid flex">
      {/* ---- sidebar (collapsible) ---- */}
      {sidebarOpen && (
      <aside className="w-60 shrink-0 border-r border-edge bg-ink/80 backdrop-blur sticky top-0 h-screen flex flex-col">
        <div className="px-5 py-5 border-b border-edge flex items-start justify-between gap-2">
          <div>
            <div className="font-mono font-bold text-lime text-xl">PPC<span className="text-slate-500">/</span>PROFIT</div>
            <div className="font-mono text-[11px] text-mute mt-1">target {pct(targetAcos)} · {targetAcos ? (1 / targetAcos).toFixed(1) : '—'}× ROAS</div>
          </div>
          <button onClick={() => setSidebarOpen(false)} title="hide sidebar"
            className="shrink-0 flex items-center text-mute hover:text-lime border border-edge rounded px-1.5 py-1"><Icon name="chevron_left" size={16} /></button>
        </div>

        <nav className="p-3 space-y-1">
          {NAV.map(item => {
            if (Array.isArray(item)) return navLeaf(item)
            const open = !!openGroups[item.group]
            const activeInside = item.children.some(([id]) => id === tab)
            return (
              <div key={item.group}>
                <button onClick={() => setOpenGroups(o => ({ ...o, [item.group]: !o[item.group] }))}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded font-mono text-sm transition-colors ${activeInside ? 'text-lime' : 'text-mute hover:text-slate-200 hover:bg-edge/30'}`}>
                  <Icon name={item.icon} size={18} className="w-5 text-center" />
                  <span className="flex-1 text-left uppercase tracking-wider text-xs">{item.group}</span>
                  <Icon name={open ? 'expand_more' : 'chevron_right'} size={18} />
                </button>
                {open && (
                  <div className="ml-3 mt-1 space-y-1 border-l border-edge pl-2">
                    {item.children.map(navLeaf)}
                  </div>
                )}
              </div>
            )
          })}
          {user?.is_superuser && navLeaf(['users', 'Users', 'group'])}
        </nav>

        {/* store + audit management moved to the Stores tab (table there); the
            active pair stays visible in the header breadcrumb */}
        <div className="mt-auto p-3 space-y-2 border-t border-edge">
          <button onClick={() => setTab('stores')}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded border border-edge font-mono text-xs text-mute hover:text-lime hover:border-lime transition-colors"
            title="manage stores & audits in the Stores tab">
            <Icon name="storefront" size={14} />
            <span className="truncate flex-1 text-left">{stores.find(s => s.id === store)?.title || store}
              <span className="text-edge"> › </span>{projects.find(p => p.id === project)?.title || project}</span>
            <Icon name="chevron_right" size={14} />
          </button>
          <div className="font-mono text-[11px] text-mute pt-1">
            {cfg ? `llm: ${cfg.llm.provider}${cfg.llm.available ? ' ●' : ' ○'}` : '…'}
          </div>
        </div>
      </aside>
      )}

      {/* ---- main column ---- */}
      <div className="flex-1 min-w-0">
        <header className="border-b border-edge sticky top-0 bg-ink/90 backdrop-blur z-10 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => setSidebarOpen(o => !o)} title={sidebarOpen ? 'hide sidebar' : 'show sidebar'}
              className="flex items-center text-mute hover:text-lime border border-edge rounded px-1.5 py-1"><Icon name="menu" size={16} /></button>
            <span className="font-mono text-sm text-slate-200 uppercase tracking-wider">{TAB_TITLE[tab] || (tab === 'users' ? 'Users' : tab)}</span>
          </div>
          <div className="flex items-center gap-3 font-mono text-xs text-mute">
            <span>{stores.find(s => s.id === store)?.title} › {projects.find(p => p.id === project)?.title}</span>
            <span className="text-edge">|</span>
            <span className="text-slate-300">{user?.username}{user?.is_superuser ? ' ◉' : ''}</span>
            <button onClick={onLogout} className="tag border border-edge text-mute hover:text-red">log out</button>
          </div>
        </header>

        <main className="px-6 py-6 space-y-6">
        {err && <div className="card border-red/40 p-3 font-mono text-sm text-red">⚠ {err}</div>}

        {/* panels mount only after the store list is validated — otherwise their
            first fetches would carry the pre-validation store guess */}
        {!storesLoaded && <div className="card p-8 flex justify-center"><Spinner label="loading stores…" /></div>}

        {storesLoaded && <>
        {tab === 'dashboard' && (
          <div className="space-y-6">
            <ProfitDashboard scope={`${store}:${project}:${auditType}:${dataVer}`} report={report} targetAcos={targetAcos} onNav={setTab} />
            <TrendsPanel scope={`${store}:${project}:${auditType}:${dataVer}`} />
          </div>
        )}

        {tab === 'stores' && (
          <StoresOverview scope={`${store}:${project}:${dataVer}`} targetAcos={targetAcos} current={store}
            onSelect={(id) => setStore(id)}
            onOpen={(id) => { setStore(id); setTab('ppc') }}
            onAddStore={addStore} onDeleteStore={handleDeleteStore}
            audits={projects} currentAudit={project}
            onOpenAudit={(id) => { setProject(id); setTab('ppc') }}
            onAddAudit={addProject} onFlushAudit={handleFlush} onDeleteAudit={handleDeleteProject} />
        )}

        {visited.ppc && (
          <div className={tab === 'ppc' ? '' : 'hidden'}>
              <div className="space-y-6">
                <AuditCadence scope={`${store}:${project}:${auditType}:${dataVer}`}
                  baseScope={`${store}:${project}`} resetVer={resetVer}
                  cadVers={cadVers} onCadenceData={onCadenceData}
                  storeTitle={stores.find(s => s.id === store)?.title || store}
                  targetAcos={targetAcos} auditType={auditType} setAuditType={changeCadence}
                  onActivePreset={setCadenceMeta} />
                {/* Every cadence now has its own dedicated panel in AuditCadence
                    (watch tracker / STR-driven optimization / cut-scale); the generic
                    flag table only shows as a fallback for an unknown/legacy feature */}
                {!['watch', 'weekly', 'mid_month', 'full_month', 'pause_scale'].includes(cadenceMeta?.feature) && (
                  busy.load && flags.length === 0
                    ? <div className="card"><TableSkeleton rows={8} cols={6} /></div>
                    : <div className="relative">
                        {busy.load && (
                          <div className="absolute inset-0 z-10 flex items-start justify-center pt-10 bg-ink/50 backdrop-blur-[1px] rounded-xl">
                            <Spinner label="auditing…" />
                          </div>
                        )}
                        <div className={busy.load ? 'opacity-50 transition-opacity' : 'transition-opacity'}>
                          <AuditTable flags={flags} selected={selected} setSelected={setSelected}
                            onAutomate={handleAutomate} automating={busy.auto}
                            focus={cadenceMeta?.focus} title={cadenceMeta?.table_title} />
                        </div>
                      </div>
                )}
                <BidOptimizerPanel scope={`${store}:${project}:${auditType}:${dataVer}`} targetAcos={targetAcos} />
                <PlacementPanel scope={`${store}:${project}:${auditType}:${dataVer}`} targetAcos={targetAcos} />
                <AsinTree trees={tree} />
              </div>
              {/* setup panels live in a cart-style slide-in drawer (overlay from the
                  right); open/closed persists in localStorage across refreshes */}
              <SideDrawer open={drawerOpen && tab === 'ppc'} onClose={() => setDrawerOpen(false)}
                title="audit setup">
                <ChecklistCard scope={`${store}:${project}:${auditType}:${dataVer}`} />
                {targetAcos != null && <TargetAcosControl value={targetAcos} onChange={changeAcos} />}
                <NarratePanel enabled={cfg?.llm?.available} provider={cfg?.llm?.provider || 'none'}
                  onNarrate={handleNarrate} text={narration} busy={busy.narr} />
                <FlagLegend className="card p-4" />
              </SideDrawer>
              {tab === 'ppc' && !drawerOpen && (
                <button onClick={() => setDrawerOpen(true)} title="open the audit setup drawer"
                  className="fixed bottom-6 right-6 z-30 btn btn-primary flex items-center gap-2 text-sm">
                  <Icon name="tune" size={16} /> Audit Setup
                </button>
              )}
            </div>
        )}

        {tab === 'reports' && (
          <ReportsPanel scope={`${store}:${project}:${auditType}:${dataVer}`} targetAcos={targetAcos} />
        )}

        {tab === 'productads' && (
          <ProductAdsPanel scope={`${store}:${project}:${auditType}:${dataVer}`} />
        )}

        {tab === 'waterfall' && (
          <WaterfallPanel scope={`${store}:${project}:${dataVer}`} targetAcos={targetAcos} />
        )}

        {tab === 'consult' && (
          <ConsultationPanel scope={`${store}:${project}:${dataVer}`} targetAcos={targetAcos} />
        )}

        {tab === 'cannibal' && (
          <CannibalizationPanel scope={`${store}:${project}:${dataVer}`} targetAcos={targetAcos} />
        )}

        {tab === 'channels' && (
          <ChannelsPanel scope={`${store}:${project}:${dataVer}`} targetAcos={targetAcos} />
        )}

        {tab === 'keywords' && (
          <div className="space-y-6">
            <KeywordsPanel scope={`${store}:${project}:${auditType}:${dataVer}`}
              harvestCands={harvestCands} ngramRes={ngramRes} />
            <HarvestPanel targetAcos={targetAcos} cands={harvestCands} onCands={setHarvestManual} fromBulk={harvestFromBulk}
              onNgram={setNgramRes} />
            <NgramPanel targetAcos={targetAcos} res={ngramRes} onRes={setNgramRes} noUpload />
          </div>
        )}

        {/* Product Optimization group — one shared TrackerPanel instance (same slot,
            so the active project + loaded views survive switching between the three) */}
        {['seo', 'listing', 'products'].includes(tab) && (
          <TrackerPanel scope={`${store}:${project}:${dataVer}`} view={tab} focus={trackerFocus} />
        )}

        {/* Product Benchmark — store-level catalog from Category Listings Reports.
            Scope includes project + cadence: the campaigns/ACoS join comes from the
            SELECTED audit's Product Ads upload, so it must refetch on audit switch. */}
        {tab === 'catalog' && (
          <ProductCatalogPanel scope={`${store}:${project}:${auditType}:${dataVer}`}
            onAudit={(pid, asin) => { setTrackerFocus({ pid, asin, ts: Date.now() }); setTab('listing') }} />
        )}

        {/* Transactions — store-level SKU ledger from the Payments Date Range report */}
        {tab === 'transactions' && (
          <TransactionsPanel scope={`${store}:${dataVer}`} />
        )}

        {tab === 'strategy' && (
          <StrategyPanel scope={`${store}:${project}:${auditType}:${dataVer}`} targetAcos={targetAcos} />
        )}

        {tab === 'log' && (
          <ChangeLogPanel scope={`${store}:${project}:${auditType}:${dataVer}`} />
        )}

        {tab === 'monitoring' && (
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-3">monitoring · daily sales &amp; ppc tracker</div>
            <MonitoringPanel scope={`${store}:${project}:${dataVer}`} />
          </div>
        )}

        {tab === 'users' && user?.is_superuser && (
          <UsersPanel me={user} />
        )}
        </>}
        </main>
      </div>
    </div>
  )
}

// Auth gate: validate any stored token, otherwise show Login. Wraps the whole app.
export default function App() {
  const [user, setUser] = useState(null)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    let live = true
    if (api.isAuthed()) {
      api.me().then(u => { if (live) setUser(u) }).catch(() => {}).finally(() => live && setChecked(true))
    } else {
      setChecked(true)
    }
    // any 401 from the client clears the token and drops us back to login
    const onUnauth = () => setUser(null)
    window.addEventListener('ppc-unauthorized', onUnauth)
    return () => { live = false; window.removeEventListener('ppc-unauthorized', onUnauth) }
  }, [])

  async function logout() { await api.logout(); setUser(null) }

  if (!checked) return <div className="min-h-screen bg-ink flex items-center justify-center"><Spinner label="loading…" /></div>
  if (!user) return <Login onLogin={setUser} />
  return (
    <ToastProvider>
      <ModalProvider>
        <AppShell user={user} onLogout={logout} />
      </ModalProvider>
    </ToastProvider>
  )
}
