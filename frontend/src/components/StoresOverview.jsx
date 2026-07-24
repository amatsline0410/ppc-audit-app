import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { money, pct, StatsSkeleton, Icon } from './ui.jsx'

// Stores tab, Google-Drive style: KPI rollup on top, then a tile grid.
// Level 1 = store tiles (like Drive folders). Clicking a store drills into
// level 2 = that store's audit tiles, each labeled with the month of its latest
// uploaded snapshot so you can tell at a glance which month an audit covers.
// A breadcrumb ("Stores › <store>") navigates back; each tile has a ⋮ menu for
// open / flush / delete, and clicking an audit tile opens it in PPC Optimization.
export function StoresOverview({ scope, targetAcos, current, onSelect, onOpen,
                                 onAddStore, onDeleteStore,
                                 audits, currentAudit, onOpenAudit,
                                 onAddAudit, onFlushAudit, onDeleteAudit }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [drill, setDrill] = useState(null)   // store id drilled into (null = store grid)
  const [menu, setMenu] = useState(null)     // key of the open ⋮ menu
  const [q, setQ] = useState('')

  useEffect(() => {
    let live = true
    setData(null); setErr(null)
    api.storesOverview(targetAcos).then(d => { if (live) setData(d) }).catch(e => { if (live) setErr(String(e)) })
    return () => { live = false }
  }, [scope, targetAcos])

  const rows = data?.stores || []

  // if the drilled store vanishes (deleted elsewhere), fall back to the store grid
  useEffect(() => {
    if (drill && data && !data.stores.some(r => r.id === drill)) setDrill(null)
  }, [data, drill])

  const needle = q.trim().toLowerCase()
  const storeRows = needle ? rows.filter(r => (r.title || '').toLowerCase().includes(needle) || r.id.includes(needle)) : rows
  const auditRows = needle ? (audits || []).filter(p => (p.title || '').toLowerCase().includes(needle) || p.id.includes(needle)) : (audits || [])
  const drillStore = drill && rows.find(r => r.id === drill)

  if (err) return <div className="card p-4 text-down font-mono text-sm">{err}</div>
  if (!data) return (
    <div className="space-y-5">
      <StatsSkeleton count={5} />
      <div className="card p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-16 rounded-lg bg-edge/30 animate-pulse" />)}
      </div>
    </div>
  )

  const tot = rows.reduce((a, r) => ({
    spend: a.spend + (r.ad_spend || 0), sales: a.sales + (r.ad_sales || 0),
    flags: a.flags + (r.flags || 0), asins: a.asins + (r.asins || 0),
  }), { spend: 0, sales: 0, flags: 0, asins: 0 })

  const openStore = (id) => { onSelect?.(id); setDrill(id); setQ(''); setMenu(null) }

  return (
    <div className="space-y-5" onClick={() => menu && setMenu(null)}>
      <div className="card p-4 grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Stores" value={rows.length} />
        <Stat label="Ad Spend" value={money(tot.spend)} />
        <Stat label="Ad Sales" value={money(tot.sales)} accent />
        <Stat label="Acct ACoS" value={tot.sales ? pct(tot.spend / tot.sales) : '—'} />
        <Stat label="Open Flags" value={tot.flags} />
      </div>

      <div className="card">
        {/* breadcrumb header (Drive-style) + actions */}
        <div className="p-3 border-b border-edge flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 font-mono text-sm min-w-0">
            <button onClick={() => { setDrill(null); setQ('') }}
              className={`flex items-center gap-1.5 ${drill ? 'text-mute hover:text-lime' : 'text-slate-100 font-bold'}`}>
              <Icon name="storefront" size={16} /> Stores
            </button>
            {drillStore && <>
              <Icon name="chevron_right" size={16} className="text-mute" />
              <span className="text-slate-100 font-bold truncate">{drillStore.title}</span>
              {drillStore.id === current && <span className="text-primary text-[10px] inline-flex items-center gap-1"><Icon name="circle" size={10} /> current</span>}
            </>}
          </div>
          <div className="flex items-center gap-2">
            <input value={q} onChange={e => setQ(e.target.value)}
              placeholder={drill ? 'search audits…' : 'search stores…'}
              className="bg-ink border border-edge rounded px-3 py-1.5 font-mono text-xs text-slate-200 placeholder:text-mute focus:outline-none focus:border-lime w-44" />
            {!drill && onAddStore && (
              <button onClick={onAddStore} className="btn btn-primary text-xs flex items-center gap-1">
                <Icon name="add" size={14} /> New Store
              </button>
            )}
            {drill && onAddAudit && (
              <button onClick={onAddAudit} className="btn btn-primary text-xs flex items-center gap-1">
                <Icon name="add" size={14} /> New Audit
              </button>
            )}
          </div>
        </div>

        {/* -------- level 1: store tiles -------- */}
        {!drill && (
          <div className="p-4">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-3">
              {storeRows.length} store{storeRows.length === 1 ? '' : 's'} · click a store to see its audits
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {storeRows.map(r => (
                <Tile key={r.id} active={r.id === current}
                  icon="storefront" title={r.title}
                  sub={<>
                    <span>{money(r.ad_spend)}</span>
                    <span className="text-edge"> · </span>
                    <span className={r.acos != null && targetAcos && r.acos > targetAcos ? 'text-down' : 'text-up'}>{r.acos == null ? '—' : pct(r.acos)}</span>
                    <span className="text-edge"> · </span>
                    <span className={r.flags ? 'text-amber' : ''}>{r.flags} flag{r.flags === 1 ? '' : 's'}</span>
                  </>}
                  onClick={() => openStore(r.id)}
                  menuOpen={menu === `s:${r.id}`}
                  onMenu={() => setMenu(m => m === `s:${r.id}` ? null : `s:${r.id}`)}
                  menuItems={[
                    { icon: 'folder_open', label: 'View audits', onClick: () => openStore(r.id) },
                    { icon: 'query_stats', label: 'Open PPC Optimization', onClick: () => onOpen?.(r.id) },
                    { icon: 'delete', label: 'Delete store', danger: true, onClick: () => onDeleteStore?.(r.id) },
                  ]} />
              ))}
              {storeRows.length === 0 && <div className="col-span-full p-6 text-center text-mute font-mono text-sm">no stores</div>}
            </div>
          </div>
        )}

        {/* -------- level 2: audit tiles of the drilled store -------- */}
        {drill && (
          <div className="p-4">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-3">
              {auditRows.length} audit{auditRows.length === 1 ? '' : 's'} · click an audit to open it in PPC Optimization
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {auditRows.map(p => (
                <Tile key={p.id} active={p.id === currentAudit} accent="cyan"
                  icon="query_stats" title={p.title}
                  badge={monthLabel(p.snapshot) || 'no data'}
                  badgeMuted={!monthLabel(p.snapshot)}
                  sub={p.snapshot ? `latest snapshot ${p.snapshot}` : 'upload a bulk to populate'}
                  onClick={() => onOpenAudit?.(p.id)}
                  menuOpen={menu === `p:${p.id}`}
                  onMenu={() => setMenu(m => m === `p:${p.id}` ? null : `p:${p.id}`)}
                  menuItems={[
                    { icon: 'query_stats', label: 'Open in PPC Optimization', onClick: () => onOpenAudit?.(p.id) },
                    { icon: 'delete_sweep', label: 'Flush data', danger: true, onClick: () => onFlushAudit?.(p.id) },
                    { icon: 'delete', label: 'Delete audit', danger: true, onClick: () => onDeleteAudit?.(p.id) },
                  ]} />
              ))}
              {auditRows.length === 0 && (
                <div className="col-span-full p-6 text-center text-mute font-mono text-sm">no audits — hit New Audit</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// one Drive-style tile: icon + title (+ optional month badge) + ⋮ menu
function Tile({ icon, title, sub, badge, badgeMuted, active, accent = 'primary',
                onClick, menuOpen, onMenu, menuItems }) {
  const ring = accent === 'cyan' ? 'border-cyan bg-cyan/10' : 'border-primary bg-primary/10'
  const dot = accent === 'cyan' ? 'text-cyan' : 'text-primary'
  return (
    <div className="relative">
      <div onClick={onClick}
        className={`flex items-center gap-3 rounded-lg border px-4 py-3 cursor-pointer transition-colors
          ${active ? ring : 'border-edge bg-ink/40 hover:bg-edge/30 hover:border-mute/60'}`}>
        <Icon name={icon} size={20} className={active ? dot : 'text-mute'} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 min-w-0">
            <span className="truncate font-mono text-sm text-slate-100">{title}</span>
            {active && <Icon name="circle" size={8} className={dot} />}
            {badge && (
              <span className={`tag shrink-0 ${badgeMuted ? 'border border-edge text-mute' : 'bg-primary text-onPrimary font-bold'}`}>{badge}</span>
            )}
          </div>
          {sub && <div className="mt-0.5 truncate font-mono text-[11px] text-mute">{sub}</div>}
        </div>
        <button onClick={(e) => { e.stopPropagation(); onMenu() }} title="actions"
          className="shrink-0 rounded p-1 text-mute hover:text-slate-100 hover:bg-edge/50">
          <Icon name="more_vert" size={18} />
        </button>
      </div>
      {menuOpen && (
        <div className="absolute right-2 top-11 z-20 card p-1 min-w-[190px] shadow-none border border-edge"
          onClick={(e) => e.stopPropagation()}>
          {menuItems.map((m, i) => (
            <button key={i} onClick={() => { onMenu(); m.onClick() }}
              className={`w-full flex items-center gap-2 rounded px-2.5 py-1.5 font-mono text-xs text-left
                ${m.danger ? 'text-down hover:bg-down/10' : 'text-slate-200 hover:bg-edge/40'}`}>
              <Icon name={m.icon} size={14} /> {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// 'YYYY-MM-DD' -> 'Jul 2026' (string split — Date() parsing would shift across timezones)
function monthLabel(snapshot) {
  if (!snapshot) return null
  const [y, m] = String(snapshot).split('-')
  const i = parseInt(m, 10) - 1
  return MONTHS[i] ? `${MONTHS[i]} ${y}` : null
}

function Stat({ label, value, accent }) {
  return (
    <div className="card p-2">
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`font-mono font-bold mt-0.5 ${accent ? 'text-primary' : 'text-slate-100'}`}>{value}</div>
    </div>
  )
}
