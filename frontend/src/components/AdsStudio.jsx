import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { money, pct, Stat, StateBadge, Icon, TableSkeleton, StatsSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { Modal, useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { AdsFunnel } from './AdsFunnel.jsx'

const num = (x) => (x ?? 0).toLocaleString()
const r2 = (x) => x == null ? '—' : Number(x).toFixed(2)

// campaign targeting kind -> label + colour (mirrors the Product Ads table)
const CTYPE = {
  auto: ['Auto', 'text-cyan border-cyan/30'],
  keyword: ['KW tgt', 'text-lime border-lime/30'],
  product: ['PT tgt', 'text-amber-400 border-amber-400/30'],
  manual: ['Manual', 'text-mute border-edge'],
}
// the unassigned column is split into one box per targeting kind, in this order
const TYPE_ORDER = ['auto', 'keyword', 'product', 'manual']
const TYPE_TITLE = {
  auto: 'automatic', keyword: 'keyword target', product: 'product target', manual: 'manual',
}
// ML performance tiers (pipeline/perftier.py) — best first
export const PERF_TIERS = ['HERO', 'A', 'B', 'C', 'D']
export const PERF_UI = {
  HERO: ['HERO', 'text-primary border-primary/50'],
  A: ['A', 'text-up border-up/40'],
  B: ['B', 'text-lime border-lime/30'],
  C: ['C', 'text-amber-400 border-amber-400/30'],
  D: ['D', 'text-down border-down/40'],
}
export function PerfTier({ tier, title }) {
  if (!tier) return null
  const [label, cls] = PERF_UI[tier] || [tier, 'text-mute border-edge']
  return <span className={`tag border ${cls}`} title={title}>{label}</span>
}

const VERDICT = {
  keep: ['keep', 'text-up'],
  drop: ['drop', 'text-down'],
  review: ['review', 'text-mute'],
}

function CampType({ type }) {
  const [label, color] = CTYPE[type] || ['—', 'text-mute border-edge']
  return <span className={`tag border ${color}`}>{label}</span>
}
function Verdict({ v }) {
  const [label, color] = VERDICT[v] || [v, 'text-mute']
  return <span className={`${color} text-[11px] font-mono`}>{label}</span>
}

// Ad group names, falling back to the id when the bulk carried no name for one.
const agLabel = (ags) =>
  (ags || []).map(a => a.ad_group_name || `id ${a.ad_group_id}`).join(' · ')

// A campaign the user drags between the pool and the consolidation groups.
function CampaignCard({ c, onDragStart, right, dim }) {
  const m = c.metrics || {}
  return (
    <div draggable onDragStart={onDragStart}
      className={`card p-2 cursor-grab active:cursor-grabbing hover:border-primary/40 ${dim ? 'opacity-50' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className={`font-mono text-[12px] truncate ${c.has_name ? 'text-slate-100' : 'text-mute'}`}
            title={c.has_name ? c.campaign_name : `campaign ${c.campaign_id} — no name in the uploaded bulk`}>
            {c.has_name ? c.campaign_name : `campaign ${c.campaign_id}`}
          </div>
          {/* the ID stays visible but secondary — it's what the exported bulk keys on */}
          {c.has_name && (
            <div className="font-mono text-[10px] text-mute truncate" title={c.campaign_id}>
              id {c.campaign_id}
            </div>
          )}
          {c.ad_groups?.length > 0 && (
            <div className="font-mono text-[10px] text-mute truncate" title={agLabel(c.ad_groups)}>
              ad group{c.ad_groups.length > 1 ? `s (${c.ad_groups.length})` : ''}: {agLabel(c.ad_groups)}
            </div>
          )}
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <PerfTier tier={c.tier} title={c.tier_reason} />
            <CampType type={c.campaign_type} />
            {c.state && <StateBadge state={c.state} />}
            <span className="text-mute text-[10px] font-mono">{c.asins?.length || 0} ASIN</span>
          </div>
        </div>
        {right}
      </div>
      <div className="mt-2 flex items-center gap-3 text-[11px] font-mono text-mute flex-wrap">
        <span>{money(m.spend)} spend</span>
        <span>{money(m.sales)} sales</span>
        <span>{pct(m.acos)} ACoS</span>
        <span className="text-up">{c.counts?.keep || 0} keep</span>
        <span className="text-down">{c.counts?.drop || 0} drop</span>
        <span>{c.counts?.review || 0} review</span>
      </div>
    </div>
  )
}

// One unassigned box per targeting kind. Collapsible and internally scrolled — a real
// account can put 100+ campaigns in a single kind, which would otherwise push the
// consolidation groups off the page.
function PoolBox({ type, campaigns, onDragStart, onInspect, dropProps }) {
  const [open, setOpen] = useState(true)
  const [, color] = CTYPE[type] || ['', 'text-mute border-edge']
  const spend = campaigns.reduce((s, c) => s + (c.metrics?.spend || 0), 0)
  const keep = campaigns.reduce((s, c) => s + (c.counts?.keep || 0), 0)
  return (
    <div className="card p-3 space-y-2" {...dropProps}>
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between gap-2 text-left">
        <span className="flex items-center gap-2">
          <Icon name={open ? 'expand_more' : 'chevron_right'} size={14} className="text-mute" />
          <span className={`text-[11px] font-mono uppercase tracking-wider ${color.split(' ')[0]}`}>
            {TYPE_TITLE[type] || type}
          </span>
          <span className="text-mute text-[11px] font-mono">· {campaigns.length}</span>
        </span>
        <span className="text-mute text-[10px] font-mono">{money(spend)} · {keep} keep</span>
      </button>
      {open && (
        <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
          {campaigns.map(c => (
            <CampaignCard key={c.campaign_id} c={c} onDragStart={e => onDragStart(e, c.campaign_id)}
              right={<button onClick={() => onInspect(c)} className="tag border border-edge text-mute hover:text-primary shrink-0">targets</button>} />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Ads Studio panel — its OWN bulk upload, its OWN goal ACoS.
 *
 * Flow: upload a Sponsored Products bulk -> pick products from the same table the
 * Product Ads tab shows -> choose Automatic and/or Manual campaigns -> open the
 * consolidation board.
 */
export function AdsStudioPanel({ scope }) {
  const toast = useToast()
  const { confirm } = useModals()
  const inputRef = useRef()
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [busyUp, setBusyUp] = useState(false)
  const [sel, setSel] = useState(new Set())            // picked product rows (asin|sku)
  const [types, setTypes] = useState(['auto', 'manual'])
  const [tiers, setTiers] = useState([])          // [] = every performance tier
  const [acos, setAcos] = useState(25)                 // Studio's own goal ACoS, in %
  const [open, setOpen] = useState(null)               // ASINs handed to a view
  const [view, setView] = useState('board')            // 'board' | 'funnel'

  // distinct ASINs behind the ticked rows — one ASIN can appear under several SKUs
  const picked = useMemo(() => asinsOf(sel), [sel])
  // tier filter on the product table: applied client-side, but the tiers themselves
  // are always computed over the WHOLE upload so hiding rows can't re-rank them.
  const shown = useMemo(() => {
    const rows = data?.rows || []
    return tiers.length ? rows.filter(r => tiers.includes(r.tier)) : rows
  }, [data, tiers])

  function load() {
    api.studioProducts()
      .then(d => { setData(d); setAcos(Math.round((d.settings?.target_acos ?? 0.25) * 1000) / 10) })
      .catch(e => setErr(String(e?.message || e).replace(/^Error:\s*/, '')))
  }
  useEffect(() => {
    setData(null); setErr(null); setSel(new Set()); setOpen(null)
    load()
  }, [scope])  // eslint-disable-line

  async function upload(file) {
    if (!file) return
    setBusyUp(true); setErr(null)
    try {
      const s = await api.studioUpload(file)
      toast.success(`Uploaded ${s.product_ads} product ads · ${s.targets} targets · ${s.asins} ASINs`)
      if (!s.targets) toast.error('That bulk had no keyword / product-target rows — consolidation needs them.')
      setSel(new Set()); setOpen(null)
      load()
    } catch (e) { const m = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(m); toast.error(m) }
    finally { setBusyUp(false); if (inputRef.current) inputRef.current.value = '' }
  }

  async function saveAcos(v) {
    setAcos(v)
    try { await api.studioSetSettings(Number(v) / 100) }
    catch (e) { toast.error(String(e?.message || e).replace(/^Error:\s*/, '')) }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear Ads Studio data?', danger: true, confirmLabel: 'Clear data',
      message: "Removes Ads Studio's uploaded snapshot for this audit. Its own tables only — "
        + 'the Product Ads tab and the PPC Optimization data are untouched.\n\n'
        + 'This cannot be undone — re-upload the bulk to rebuild.',
    })
    if (!ok) return
    try {
      await api.studioClear()
      setSel(new Set()); setOpen(null); setErr(null)
      toast.success('Cleared Ads Studio data')
      load()
    } catch (e) { const m = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(m); toast.error(m) }
  }

  const UploadBtn = (
    <>
      <button onClick={() => inputRef.current?.click()} disabled={busyUp} aria-busy={busyUp}
        className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
        <Icon name={busyUp ? 'sync' : 'upload'} size={14} />{busyUp ? 'Reading…' : 'Upload Sponsored Products Bulk'}
      </button>
      <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
        onChange={e => upload(e.target.files?.[0])} />
    </>
  )

  if (!data && !err) return (
    <div className="space-y-6">
      <div className="card p-4"><StatsSkeleton count={5} /></div>
      <div className="card"><TableSkeleton rows={8} cols={6} /></div>
    </div>
  )

  if (err || (data && data.count === 0)) return (
    <div className="space-y-4">
      {err && <div className="card border-down/40 p-3 font-mono text-xs text-down inline-flex items-center gap-1">
        <Icon name="warning" size={12} /> {err}</div>}
      <div className="card p-8 text-center space-y-3">
        <div className="font-mono text-sm text-slate-200">No Ads Studio data yet</div>
        <div className="font-mono text-xs text-mute max-w-lg mx-auto">
          Ads Studio has its <span className="text-slate-200">own bulk upload</span> and its own data —
          separate from the Product Ads tab. Upload a Sponsored Products bulk export (with its
          Product Ad <span className="text-slate-200">and</span> Keyword / Product Targeting rows) to
          pick products and consolidate the campaigns behind them.
        </div>
        <div className="flex justify-center">{UploadBtn}</div>
      </div>
    </div>
  )

  // the chosen view takes the tab over — both need the full width
  if (open) return view === 'funnel' ? (
    <AdsFunnel asins={open} scope={scope} campaignTypes={types}
      targetAcos={Number(acos) / 100} tiers={tiers} onClose={() => setOpen(null)} />
  ) : (
    <AdsStudio asins={open} scope={scope} campaignTypes={types} tiers={tiers}
      targetAcos={Number(acos) / 100} onClose={() => setOpen(null)} />
  )

  const t = data.total || {}
  const ct = data.campaign_types || {}
  return (
    <div className="space-y-6">
      <div className="card">
        <div className="p-4 border-b border-edge flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">
              ads studio · own bulk upload (separate from product ads)
            </div>
            <div className="text-xs text-mute font-mono flex gap-3 flex-wrap">
              {data.upload_meta && <span><Icon name="description" size={11} className="align-[-1px]" /> {data.upload_meta.file} · {data.upload_meta.rows}</span>}
              {data.upload_meta && <span>updated {data.upload_meta.uploaded}</span>}
              <span>{data.count} products</span>
              <span><span className="text-cyan">{ct.auto || 0} auto</span> · <span className="text-lime">{ct.keyword || 0} kw</span> · <span className="text-amber-400">{ct.product || 0} pt</span> campaigns</span>
              {!data.has_targets && <span className="text-down">no keyword/target rows in this bulk</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {UploadBtn}
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          </div>
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-5 gap-3">
          <Stat label="Ad Spend" value={money(t.spend)} />
          <Stat label="Ad Sales" value={money(t.sales)} accent />
          <Stat label="Orders" value={num(t.orders)} />
          <Stat label="ACOS" value={pct(t.acos)} />
          <Stat label="ROAS" value={t.roas == null ? '—' : `${r2(t.roas)}×`} />
        </div>
      </div>

      {/* the three choices that drive the board */}
      <div className="card p-4 space-y-4">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider">consolidation settings</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-1">
            <div className="font-mono text-[11px] text-mute">Campaign type</div>
            <div className="flex gap-2">
              {[['auto', 'Automatic'], ['manual', 'Manual (KW + PT)']].map(([k, label]) => (
                <button key={k} onClick={() => setTypes(ts => ts.includes(k) ? ts.filter(x => x !== k) : [...ts, k])}
                  className={`tag ${types.includes(k) ? 'bg-primary text-onPrimary' : 'border border-edge text-mute'}`}>
                  {label}
                </button>
              ))}
            </div>
            <div className="font-mono text-[10px] text-mute">Which campaigns the board will load.</div>
          </div>
          <div className="space-y-1">
            <div className="font-mono text-[11px] text-mute">Target ACoS — Ads Studio only</div>
            <div className="flex items-center gap-2">
              <input type="number" min="1" max="200" step="0.5" value={acos}
                onChange={e => setAcos(e.target.value)} onBlur={e => saveAcos(e.target.value)}
                className="bg-ink border border-edge rounded px-2 py-1 w-24 font-mono text-sm text-slate-100 focus:border-primary outline-none" />
              <span className="font-mono text-sm text-mute">%</span>
            </div>
            <div className="font-mono text-[10px] text-mute">
              Decides which targets survive. Saved for this feature only — it does not touch the audit's goal ACoS.
            </div>
          </div>
          <div className="space-y-1">
            <div className="font-mono text-[11px] text-mute">
              Performance tier
              {data.tiering?.method === 'kmeans' && <span className="text-[10px] ml-1">· clustered</span>}
              {data.tiering?.method === 'quantile' && <span className="text-[10px] ml-1">· ranked (too few to cluster)</span>}
            </div>
            <div className="flex gap-1 flex-wrap">
              {PERF_TIERS.map(t => {
                const n = data.tiering?.counts?.[t] || 0
                const on = tiers.includes(t)
                const [label, cls] = PERF_UI[t]
                return (
                  <button key={t} disabled={!n}
                    onClick={() => setTiers(ts => ts.includes(t) ? ts.filter(x => x !== t) : [...ts, t])}
                    title={n ? `${n} product(s)` : 'no products in this tier'}
                    className={`tag border ${on ? 'bg-primary text-onPrimary border-primary' : cls} ${n ? '' : 'opacity-30'}`}>
                    {label} {n ? <span className="opacity-70">{n}</span> : null}
                  </button>
                )
              })}
              {tiers.length > 0 && (
                <button onClick={() => setTiers([])} className="tag border border-edge text-mute hover:text-primary">all</button>
              )}
            </div>
            <div className="font-mono text-[10px] text-mute">
              Ranked by sales volume, ACoS against your goal, and shrunk conversion rate.
              Filters the table below and the board.
            </div>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-1">
            <div className="font-mono text-[11px] text-mute">Products</div>
            <div className="font-mono text-sm text-slate-100">
              {picked.length} picked
              {tiers.length > 0 && <span className="text-mute text-xs ml-2">{shown.length} shown</span>}
            </div>
            <div className="font-mono text-[10px] text-mute">Tick one for a single-product consolidation, or several to merge across products.</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { setView('funnel'); setOpen(picked) }}
            disabled={!picked.length || !types.length || !data.has_targets}
            title="segmented funnel: Auto/Broad/Phrase discovery feeding Exact/PT performance"
            className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
            <Icon name="moving" size={14} /> Funnel strategy ({picked.length})
          </button>
          <button onClick={() => { setView('board'); setOpen(picked) }}
            disabled={!picked.length || !types.length || !data.has_targets}
            title="drag campaigns into groups and merge them into a boss campaign"
            className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-50">
            <Icon name="dashboard" size={14} /> Consolidation board ({picked.length})
          </button>
          {sel.size > 0 && (
            <button onClick={() => setSel(new Set())} className="btn btn-ghost text-xs">clear selection</button>
          )}
        </div>
      </div>

      {/* Selection is keyed by ROW (asin|sku) because one ASIN can run under several
          SKUs; the ASIN list handed to the board is derived from it. Storing bare
          ASINs here would never match DataTable's rowKey, leaving every box unchecked. */}
      <DataTable title={`products · ${data.count} — pick what to consolidate`} columns={PRODUCT_COLS}
        rows={shown} rowKey={rowKey} selectable selected={sel}
        onToggle={k => toggleSet(setSel, k)}
        onToggleAll={(keys, on) => setAll(setSel, keys, on)}
        searchKeys={['asin', 'sku', 'status', 'tier']} placeholder="search ASIN / SKU / status…"
        empty="no product ads in this bulk" scope={scope} />
    </div>
  )
}

// one product row = one (ASIN, SKU) pair, matching how the table consolidates ads
const rowKey = (r) => `${r.asin || ''}|${r.sku || ''}`
const asinsOf = (keys) =>
  [...new Set([...keys].map(k => String(k).split('|')[0]).filter(Boolean))]

const PRODUCT_COLS = [
  { key: 'tier', label: 'Tier', value: r => PERF_TIERS.indexOf(r.tier), render: r => <PerfTier tier={r.tier} title={r.tier_reason} /> },
  { key: 'asin', label: 'ASIN', render: r => r.asin || '—' },
  { key: 'sku', label: 'SKU', cellClass: 'text-mute', render: r => trunc(r.sku, 160, 'text-mute') },
  { key: 'auto_campaigns', label: 'Auto', align: 'right', cellClass: 'text-cyan', render: r => r.auto_campaigns || '—' },
  { key: 'keyword_campaigns', label: 'KW tgt', align: 'right', cellClass: 'text-lime', render: r => r.keyword_campaigns || '—' },
  { key: 'product_campaigns', label: 'PT tgt', align: 'right', cellClass: 'text-amber-400', render: r => r.product_campaigns || '—' },
  { key: 'spend', label: 'Spend', align: 'right', render: r => money(r.spend) },
  { key: 'sales', label: 'Sales', align: 'right', render: r => money(r.sales) },
  { key: 'orders', label: 'Orders', align: 'right', render: r => num(r.orders) },
  { key: 'acos', label: 'ACOS', align: 'right', render: r => pct(r.acos) },
]

/**
 * Ads Studio — consolidate the campaigns behind the picked ASINs.
 *
 * Board model: every campaign advertising the selection starts in the pool, and the
 * user drags it into a consolidation group. Each group has one destination campaign
 * (the keeper); everything else in the group is a source whose winning targets get
 * migrated in. "Winning" is the backend's call, on goal ACoS — the UI only shows it.
 */
export function AdsStudio({ asins, scope, onClose, campaignTypes, targetAcos, tiers }) {
  const toast = useToast()
  const { confirm } = useModals()
  const [board, setBoard] = useState(null)
  const [err, setErr] = useState(null)
  const [groups, setGroups] = useState([])       // [{ id, name, destId, memberIds: [] }]
  const [plan, setPlan] = useState(null)
  const [planBusy, setPlanBusy] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [inspect, setInspect] = useState(null)   // campaign whose targets are open
  const [pickMig, setPickMig] = useState(new Set())
  const [pickPause, setPickPause] = useState(new Set())
  const [pickCamp, setPickCamp] = useState(new Set())

  const list = (asins || [])
  useEffect(() => {
    setBoard(null); setErr(null); setPlan(null); setGroups([])
    if (!list.length) return
    api.studioBoard(list, targetAcos, campaignTypes, tiers)
      .then(b => {
        setBoard(b)
        // Seed one group per targeting kind present, with only its highest-spend
        // campaign as the destination. The rest stay in their type box so merging
        // is a deliberate drag — an account with 100+ campaigns should not have
        // every one of them swept into a single group before the user looks.
        const byType = {}
        for (const c of b.campaigns) (byType[c.campaign_type] ||= []).push(c)
        setGroups(TYPE_ORDER
          .filter(type => (byType[type] || []).length > 1)
          .map((type, i) => ({
            id: `g${i}`, name: `${(CTYPE[type] || ['Manual'])[0]} consolidation`,
            destId: byType[type][0].campaign_id, memberIds: [byType[type][0].campaign_id],
          })))
      })
      .catch(e => setErr(String(e?.message || e).replace(/^Error:\s*/, '')))
  }, [scope, list.join(','), targetAcos, (campaignTypes || []).join(','), (tiers || []).join(',')])  // eslint-disable-line

  const byId = useMemo(() => {
    const m = {}
    for (const c of board?.campaigns || []) m[c.campaign_id] = c
    return m
  }, [board])

  const assigned = useMemo(() => new Set(groups.flatMap(g => g.memberIds)), [groups])
  const pool = (board?.campaigns || []).filter(c => !assigned.has(c.campaign_id))
  const poolByType = useMemo(() => {
    const m = {}
    for (const c of pool) (m[c.campaign_type] ||= []).push(c)
    return m
  }, [pool])

  // ---- drag & drop -----------------------------------------------------------
  function onDragStart(e, campaignId) {
    e.dataTransfer.setData('text/plain', campaignId)
    e.dataTransfer.effectAllowed = 'move'
  }
  function moveTo(campaignId, groupId) {
    setPlan(null)
    setGroups(gs => {
      const stripped = gs.map(g => ({ ...g, memberIds: g.memberIds.filter(id => id !== campaignId) }))
      if (!groupId) return stripped.map(g => g.destId === campaignId ? { ...g, destId: g.memberIds.find(i => i !== campaignId) || null } : g)
      return stripped.map(g => g.id === groupId
        ? { ...g, memberIds: [...g.memberIds, campaignId], destId: g.destId || campaignId }
        : (g.destId === campaignId ? { ...g, destId: g.memberIds.find(i => i !== campaignId) || null } : g))
    })
  }
  const dropProps = (groupId) => ({
    onDragOver: (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' },
    onDrop: (e) => { e.preventDefault(); const id = e.dataTransfer.getData('text/plain'); if (id) moveTo(id, groupId) },
  })

  function addGroup() {
    setGroups(gs => [...gs, { id: `g${Date.now()}`, name: `Consolidation ${gs.length + 1}`, destId: null, memberIds: [] }])
  }
  async function removeGroup(id) {
    const g = groups.find(x => x.id === id)
    if (g?.memberIds.length) {
      const ok = await confirm({
        title: 'Remove this group?',
        message: `Its ${g.memberIds.length} campaign(s) go back to the pool. No changes to your account — nothing has been exported yet.`,
        confirmLabel: 'Remove group',
      })
      if (!ok) return
    }
    setPlan(null)
    setGroups(gs => gs.filter(x => x.id !== id))
  }

  // ---- plan / export ---------------------------------------------------------
  async function draft() {
    const payload = groups
      .filter(g => g.destId && g.memberIds.length > 1)
      .map(g => ({
        name: g.name,
        destination_campaign_id: g.destId,
        destination_ad_group_id: byId[g.destId]?.ad_groups?.[0]?.ad_group_id || null,
        source_campaign_ids: g.memberIds.filter(id => id !== g.destId),
      }))
    if (!payload.length) {
      toast.error('A group needs a boss campaign and at least one other campaign.')
      return
    }
    setPlanBusy(true)
    try {
      const p = await api.studioPlan(payload, targetAcos)
      setPlan(p)
      // migrations + target pauses pre-selected; campaign pauses never are —
      // pausing a campaign stops its sales the moment Amazon processes the file.
      setPickMig(new Set(p.groups.flatMap((g, gi) => g.migrate.map(r => migKey(gi, r)))))
      setPickPause(new Set(p.groups.flatMap((g, gi) => g.pause_targets.map(r => pauseKey(gi, r)))))
      setPickCamp(new Set())
      toast.success(`Plan drafted — ${p.counts.migrate} migrate · ${p.counts.pause_targets} pause`)
    } catch (e) {
      const msg = String(e?.message || e).replace(/^Error:\s*/, '')
      setErr(msg); toast.error(msg)
    } finally { setPlanBusy(false) }
  }

  async function exportBulk() {
    const migrate = [], pause_targets = [], campaign_pauses = []
    plan.groups.forEach((g, gi) => {
      g.migrate.forEach(r => pickMig.has(migKey(gi, r)) && migrate.push(r))
      g.pause_targets.forEach(r => pickPause.has(pauseKey(gi, r)) && pause_targets.push(r))
      g.campaign_pauses.forEach(r => pickCamp.has(campKey(gi, r)) && campaign_pauses.push(r))
    })
    if (campaign_pauses.length) {
      const ok = await confirm({
        title: `Pause ${campaign_pauses.length} campaign(s)?`, danger: true, confirmLabel: 'Include pauses',
        message: 'Pausing a source campaign stops its sales as soon as Amazon processes the file. '
          + 'Only include these once the migrated targets have had time to pick up delivery in the '
          + 'destination campaign.\n\nThe file downloads either way — this only decides whether the '
          + 'campaign pause rows are in it.',
      })
      if (!ok) return
    }
    setBulkBusy(true)
    try {
      const blob = await api.studioBulk({ migrate, pause_targets, campaign_pauses })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'ads_studio_consolidation.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success(`Bulk downloaded — ${migrate.length} create · ${pause_targets.length + campaign_pauses.length} pause`)
    } catch (e) {
      const msg = String(e?.message || e).replace(/^Error:\s*/, '')
      setErr(msg); toast.error(msg)
    } finally { setBulkBusy(false) }
  }

  const picked = pickMig.size + pickPause.size + pickCamp.size

  if (err && !board) return (
    <div className="space-y-3">
      <button onClick={onClose} className="btn btn-ghost text-xs"><Icon name="arrow_back" size={14} /> Back</button>
      <div className="card border-down/40 p-3 font-mono text-xs text-down inline-flex items-center gap-1">
        <Icon name="warning" size={12} /> {err}
      </div>
    </div>
  )
  if (!board) return <div className="card"><TableSkeleton rows={6} cols={5} /></div>

  const t = board.totals || {}
  const noNames = board.campaigns.filter(c => !c.has_name).length
  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">
            ads studio · consolidation board
          </div>
          <div className="text-xs text-mute font-mono flex gap-3 flex-wrap">
            <span>{board.asins.length} product(s): {board.asins.join(', ')}</span>
            <span>{board.campaigns.length} campaigns</span>
            <span>goal ACoS {pct(board.target_acos)}</span>
            <span className="text-up">{board.counts.keep} keep</span>
            <span className="text-down">{board.counts.drop} drop</span>
            <span>{board.counts.review} review</span>
            {board.tier_filter?.length > 0 && (
              <span className="text-primary">tier {board.tier_filter.join(' · ')} only</span>
            )}
          </div>
          {board.tiering?.counts && (
            <div className="flex items-center gap-1 mt-2 flex-wrap">
              {PERF_TIERS.filter(t => board.tiering.counts[t]).map(t => (
                <span key={t} className="inline-flex items-center gap-1">
                  <PerfTier tier={t} />
                  <span className="text-mute text-[10px] font-mono">{board.tiering.counts[t]}</span>
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={addGroup} className="btn btn-ghost text-xs flex items-center gap-1">
            <Icon name="add" size={14} /> Add group
          </button>
          <button onClick={draft} disabled={planBusy} aria-busy={planBusy}
            className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
            <Icon name={planBusy ? 'sync' : 'science'} size={14} />{planBusy ? 'Drafting…' : 'Draft plan'}
          </button>
          <button onClick={onClose} className="btn btn-ghost text-xs flex items-center gap-1">
            <Icon name="close" size={14} /> Close
          </button>
        </div>
      </div>

      {/* Names come from the bulk at parse time, so a snapshot ingested before the
          name fix (or an export without the name columns) shows IDs until re-uploaded. */}
      {noNames > 0 && (
        <div className="card border-amber-400/40 p-3 font-mono text-xs text-amber-400 flex items-start gap-2">
          <Icon name="warning" size={14} className="mt-0.5 shrink-0" />
          <span>
            {noNames} of {board.campaigns.length} campaigns have no name stored — showing IDs.
            Re-upload this audit's Sponsored Products bulk on the Product Ads tab to pull the
            campaign and ad group names in. Nothing else changes; the plan and the exported
            bulk key on IDs either way.
          </span>
        </div>
      )}

      <div className="card p-4 grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Ad Spend" value={money(t.spend)} />
        <Stat label="Ad Sales" value={money(t.sales)} accent />
        <Stat label="Orders" value={num(t.orders)} />
        <Stat label="ACOS" value={pct(t.acos)} />
        <Stat label="ROAS" value={t.roas == null ? '—' : `${r2(t.roas)}×`} />
      </div>

      {/* board: pool on the left, consolidation groups on the right */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        {/* unassigned pool — one box per targeting kind, each its own drop zone */}
        <div className="space-y-3">
          <div className="text-[11px] font-mono text-mute px-1">
            Drag a campaign into a group to merge it — or back here to pull it out.
          </div>
          {TYPE_ORDER.filter(type => poolByType[type]?.length).map(type => (
            <PoolBox key={type} type={type} campaigns={poolByType[type]}
              onDragStart={onDragStart} onInspect={setInspect} dropProps={dropProps(null)} />
          ))}
          {pool.length === 0 && (
            <div className="card p-4 text-mute font-mono text-xs text-center" {...dropProps(null)}>
              every campaign is assigned to a group
            </div>
          )}
        </div>

        <div className="lg:col-span-2 space-y-4">
          {groups.map(g => {
            const members = g.memberIds.map(id => byId[id]).filter(Boolean)
            return (
              <div key={g.id} className="card p-3 space-y-2 border-dashed" {...dropProps(g.id)}>
                <div className="flex items-center justify-between gap-2">
                  <input value={g.name} onChange={e => setGroups(gs => gs.map(x => x.id === g.id ? { ...x, name: e.target.value } : x))}
                    className="bg-transparent border-b border-edge focus:border-primary outline-none font-mono text-sm text-slate-100 px-1" />
                  <div className="flex items-center gap-2">
                    <span className="text-mute text-[11px] font-mono">{members.length} campaign(s)</span>
                    <button onClick={() => removeGroup(g.id)} className="tag border border-edge text-mute hover:text-down">remove</button>
                  </div>
                </div>
                {members.length === 0 && (
                  <div className="text-mute font-mono text-xs p-4 text-center border border-dashed border-edge rounded">
                    drop campaigns here
                  </div>
                )}
                <div className="space-y-2 max-h-[520px] overflow-y-auto pr-1">
                {members.map(c => {
                  const isDest = g.destId === c.campaign_id
                  return (
                    <div key={c.campaign_id} className={isDest ? 'ring-1 ring-primary/50 rounded' : ''}>
                      <CampaignCard c={c} dim={!isDest} onDragStart={e => onDragStart(e, c.campaign_id)}
                        right={
                          <div className="flex items-center gap-1 shrink-0">
                            <button onClick={() => setInspect(c)} className="tag border border-edge text-mute hover:text-primary">targets</button>
                            <button onClick={() => setGroups(gs => gs.map(x => x.id === g.id ? { ...x, destId: c.campaign_id } : x))}
                              title="boss campaign — everything in this group is consolidated INTO it"
                              className={`tag ${isDest ? 'bg-primary text-onPrimary' : 'border border-edge text-mute hover:text-primary'}`}>
                              {isDest ? 'destination' : 'set destination'}
                            </button>
                          </div>
                        } />
                    </div>
                  )
                })}
                </div>
              </div>
            )
          })}
          {groups.length === 0 && (
            <div className="card p-6 text-center font-mono text-xs text-mute">
              No consolidation groups. <button onClick={addGroup} className="text-primary underline">Add one</button> and drag campaigns in.
            </div>
          )}
        </div>
      </div>

      {/* per-campaign target inspector */}
      <Modal open={!!inspect} onClose={() => setInspect(null)} size="2xl"
        title={inspect?.campaign_name} subtitle="targets judged against the goal ACoS">
        {inspect && (
          <DataTable title={`targets · ${inspect.targets.length}`} columns={TARGET_COLS} rows={inspect.targets}
            rowKey={(r, i) => r.id || i} empty="no keyword / product-target rows in this campaign"
            placeholder="search target…" initial={{ sort: { key: 'spend', dir: 'desc' } }} />
        )}
      </Modal>

      {/* drafted plan */}
      {plan && (
        <div className="card p-4 space-y-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
              plan · {plan.counts.migrate} migrate · {plan.counts.pause_targets} pause · {plan.counts.skipped} can't move
            </div>
            <button onClick={exportBulk} disabled={!picked || bulkBusy} aria-busy={bulkBusy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name={bulkBusy ? 'sync' : 'download'} size={14} />{bulkBusy ? 'Building…' : `Export bulk (${picked})`}
            </button>
          </div>
          {plan.groups.map((g, gi) => (
            <div key={gi} className="space-y-3 border-t border-edge pt-3 first:border-0 first:pt-0">
              <div className="font-mono text-sm text-slate-100">
                {g.name}
                <span className="text-mute text-xs ml-2">
                  {g.sources.length} campaign(s) → boss: {g.destination.campaign_name}
                </span>
              </div>
              {g.migrate.length > 0 && (
                <DataTable title={`move into the boss campaign · ${g.migrate.length}`} lean columns={MIGRATE_COLS} rows={g.migrate}
                  rowKey={r => migKey(gi, r)} selectable selected={pickMig}
                  onToggle={k => toggleSet(setPickMig, k)}
                  onToggleAll={(keys, on) => setAll(setPickMig, keys, on)} />
              )}
              {g.pause_targets.length > 0 && (
                <DataTable title={`pause — missed the goal ACoS · ${g.pause_targets.length}`} lean columns={PAUSE_COLS} rows={g.pause_targets}
                  rowKey={r => pauseKey(gi, r)} selectable selected={pickPause}
                  onToggle={k => toggleSet(setPickPause, k)}
                  onToggleAll={(keys, on) => setAll(setPickPause, keys, on)} />
              )}
              {g.campaign_pauses.length > 0 && (
                <DataTable title={`pause source campaigns · ${g.campaign_pauses.length} — not pre-selected`} lean columns={CAMP_PAUSE_COLS}
                  rows={g.campaign_pauses} rowKey={r => campKey(gi, r)} selectable selected={pickCamp}
                  onToggle={k => toggleSet(setPickCamp, k)}
                  onToggleAll={(keys, on) => setAll(setPickCamp, keys, on)} />
              )}
              {g.skipped.length > 0 && (
                <DataTable title={`can't move · ${g.skipped.length}`} lean columns={SKIP_COLS} rows={g.skipped}
                  rowKey={(r, i) => `skip${gi}:${r.id || i}`} empty="none" />
              )}
            </div>
          ))}
        </div>
      )}

      {/* bottom: what each boss campaign looks like once the plan is applied */}
      {plan?.consolidated?.length > 0 && (
        <div className="card p-4 space-y-3">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
              consolidated campaigns · {plan.consolidated.length}
            </div>
            <div className="font-mono text-[10px] text-mute mt-1">
              The boss campaign after the plan is applied. Metrics are the trailing numbers of
              the targets that survive (its own keepers + everything moved in) — not a forecast.
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {plan.consolidated.map(c => (
              <div key={c.campaign_id} className="card p-3 space-y-2 border-primary/30">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-[12px] text-slate-100 truncate" title={c.campaign_name}>
                      {c.campaign_name}
                    </div>
                    <div className="font-mono text-[10px] text-mute truncate">id {c.campaign_id}</div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <CampType type={c.campaign_type} />
                    <span className={`tag border ${c.scope === 'multi' ? 'text-primary border-primary/40' : 'border-edge text-mute'}`}>
                      {c.scope === 'multi' ? `${c.asins.length} products` : 'single product'}
                    </span>
                  </div>
                </div>
                <div className="font-mono text-[10px] text-mute truncate" title={c.asins.join(', ')}>
                  {c.asins.join(' · ')}
                </div>
                <div className="grid grid-cols-3 gap-2 text-[11px] font-mono">
                  <div><div className="text-mute text-[10px]">absorbed</div>{num(c.campaigns_absorbed)} campaigns</div>
                  <div><div className="text-mute text-[10px]">targets</div>{num(c.targets_total)} <span className="text-mute">({num(c.targets_migrated)} moved in)</span></div>
                  <div><div className="text-mute text-[10px]">switched off</div><span className="text-down">{money(c.spend_switched_off)}</span></div>
                </div>
                <div className="flex items-center gap-3 text-[11px] font-mono text-mute flex-wrap border-t border-edge pt-2">
                  <span>{money(c.metrics?.spend)} spend</span>
                  <span>{money(c.metrics?.sales)} sales</span>
                  <span>{num(c.metrics?.orders)} orders</span>
                  <span className="text-up">{pct(c.metrics?.acos)} ACoS</span>
                  <span>{c.metrics?.roas == null ? '—' : `${r2(c.metrics.roas)}×`} ROAS</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// Selection keys must come from the ROW, not its index: DataTable computes rowKey
// against the sorted/paged view, so an index-based key would re-point at a different
// row the moment the user sorts a column.
const migKey = (gi, r) =>
  `${gi}|m|${r.entity}|${r.id || ''}|${r.keyword_text || r.expression || ''}|${r.match_type || ''}`
const pauseKey = (gi, r) => `${gi}|p|${r.entity}|${r.id || ''}`
const campKey = (gi, r) => `${gi}|c|${r.campaign_id}`

function toggleSet(setter, key) {
  setter(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })
}
function setAll(setter, keys, on) {
  setter(s => { const n = new Set(s); keys.forEach(k => on ? n.add(k) : n.delete(k)); return n })
}

const trunc = (txt, w, cls = '') =>
  <span className={`truncate inline-block align-bottom ${cls}`} style={{ maxWidth: w }} title={txt}>{txt || '—'}</span>

const TARGET_COLS = [
  { key: 'label', label: 'Target', render: r => trunc(r.label, 240) },
  { key: 'entity', label: 'Kind', render: r => r.entity === 'keyword' ? (r.match_type || 'keyword') : 'product' },
  { key: 'ad_group_name', label: 'Ad group', cellClass: 'text-mute', render: r => trunc(r.ad_group_name || r.ad_group_id, 160, 'text-mute') },
  { key: 'verdict', label: 'Verdict', value: r => r.verdict, render: r => <Verdict v={r.verdict} /> },
  { key: 'reason', label: 'Why', cellClass: 'text-mute', render: r => trunc(r.reason, 220, 'text-mute') },
  { key: 'bid', label: 'Bid', align: 'right', render: r => r.bid == null ? '—' : `$${r2(r.bid)}` },
  { key: 'spend', label: 'Spend', align: 'right', value: r => r.metrics?.spend, render: r => money(r.metrics?.spend) },
  { key: 'sales', label: 'Sales', align: 'right', value: r => r.metrics?.sales, render: r => money(r.metrics?.sales) },
  { key: 'orders', label: 'Orders', align: 'right', value: r => r.metrics?.orders, render: r => num(r.metrics?.orders) },
  { key: 'acos', label: 'ACOS', align: 'right', value: r => r.metrics?.acos, render: r => pct(r.metrics?.acos) },
]

const MIGRATE_COLS = [
  { key: 'label', label: 'Target', render: r => trunc(r.label, 220) },
  { key: 'entity', label: 'Kind', render: r => r.entity === 'keyword' ? (r.match_type || 'keyword') : 'product' },
  { key: 'from_campaign_name', label: 'From campaign', cellClass: 'text-mute', render: r => trunc(r.from_campaign_name, 180, 'text-mute') },
  { key: 'ad_group_name', label: 'From ad group', cellClass: 'text-mute', render: r => trunc(r.ad_group_name || r.ad_group_id, 150, 'text-mute') },
  { key: 'new_bid', label: 'New bid', align: 'right', render: r => r.new_bid == null ? '—' : `$${r2(r.new_bid)}` },
  { key: 'orders', label: 'Orders', align: 'right', value: r => r.metrics?.orders, render: r => num(r.metrics?.orders) },
  { key: 'acos', label: 'ACOS', align: 'right', value: r => r.metrics?.acos, render: r => pct(r.metrics?.acos) },
]

const PAUSE_COLS = [
  { key: 'label', label: 'Target', render: r => trunc(r.label, 220) },
  { key: 'campaign_name', label: 'In campaign', cellClass: 'text-mute', render: r => trunc(r.campaign_name, 180, 'text-mute') },
  { key: 'ad_group_name', label: 'Ad group', cellClass: 'text-mute', render: r => trunc(r.ad_group_name || r.ad_group_id, 150, 'text-mute') },
  { key: 'reason', label: 'Why', cellClass: 'text-mute', render: r => trunc(r.reason, 220, 'text-mute') },
  { key: 'spend', label: 'Spend', align: 'right', value: r => r.metrics?.spend, render: r => money(r.metrics?.spend) },
  { key: 'acos', label: 'ACOS', align: 'right', value: r => r.metrics?.acos, render: r => pct(r.metrics?.acos) },
]

const CAMP_PAUSE_COLS = [
  { key: 'campaign_name', label: 'Campaign', render: r => trunc(r.campaign_name, 240) },
  { key: 'campaign_type', label: 'Type', value: r => r.campaign_type, render: r => <CampType type={r.campaign_type} /> },
  { key: 'migrated', label: 'Migrated out', align: 'right', render: r => num(r.migrated) },
  { key: 'spend', label: 'Spend', align: 'right', value: r => r.metrics?.spend, render: r => money(r.metrics?.spend) },
  { key: 'sales', label: 'Sales at risk', align: 'right', value: r => r.metrics?.sales, render: r => money(r.metrics?.sales) },
]

const SKIP_COLS = [
  { key: 'label', label: 'Target', render: r => trunc(r.label, 220) },
  { key: 'campaign_name', label: 'In campaign', cellClass: 'text-mute', render: r => trunc(r.campaign_name, 180, 'text-mute') },
  { key: 'skip_reason', label: 'Why it stays put', cellClass: 'text-mute', render: r => trunc(r.skip_reason, 320, 'text-mute') },
]
