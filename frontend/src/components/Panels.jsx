import React, { useMemo, useState } from 'react'
import { money, pct, StateBadge } from './ui.jsx'

const norm = s => (s || '').toLowerCase()
const dim = s => norm(s) === 'archived' ? 'opacity-50' : ''
const dot = s => norm(s) === 'enabled' ? 'bg-lime' : norm(s) === 'paused' ? 'bg-amber' : 'bg-slate-500'

// roll a list of campaign nodes up to one ASIN's spend / sales / acos
function rollup(campaigns) {
  let sp = 0, sa = 0
  campaigns.forEach(c => { sp += c.metrics.spend || 0; sa += c.metrics.sales || 0 })
  return { spend: sp, sales: sa, acos: sa ? sp / sa : null }
}

// ASIN-rooted forest: every ASIN -> its campaigns -> ad groups -> ads + targets.
export function AsinTree({ trees, tree }) {
  const forest = trees || (tree ? [tree] : [])
  const [open, setOpen] = useState({})        // id -> bool (asin/campaign/ad-group)
  const [filter, setFilter] = useState('active')
  const [q, setQ] = useState('')
  const toggle = id => setOpen(o => ({ ...o, [id]: !o[id] }))
  if (!forest.length) return null

  const matches = s => filter === 'all' || (filter === 'active' ? norm(s) !== 'archived' : norm(s) === filter)
  const FILTERS = [['active', 'Active'], ['enabled', 'Enabled'], ['paused', 'Paused'], ['archived', 'Archived'], ['all', 'All']]

  const ql = q.trim().toLowerCase()
  const shown = forest.filter(node => !ql
    || node.asin?.toLowerCase().includes(ql)
    || node.campaigns.some(c => (c.name || '').toLowerCase().includes(ql)))

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider">ASIN-rooted tree · {forest.length} ASIN{forest.length === 1 ? '' : 's'}</div>
        <div className="flex gap-1 items-center flex-wrap">
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="search ASIN / campaign…"
            className="bg-panel border border-edge rounded px-2 py-1 font-mono text-[11px] text-slate-100 focus:outline-none focus:border-primary" />
          {FILTERS.map(([v, label]) => (
            <button key={v} onClick={() => setFilter(v)}
              className={`tag ${filter === v ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>{label}</button>
          ))}
        </div>
      </div>

      <div className="space-y-0.5 font-mono text-sm">
        {shown.map(node => {
          const camps = node.campaigns.filter(c => matches(c.state))
          const r = rollup(node.campaigns)
          const aid = `asin:${node.asin}`
          const aOpen = open[aid]
          return (
            <div key={node.asin} className="border border-edge rounded">
              <button onClick={() => toggle(aid)}
                className="w-full flex items-center justify-between py-2 px-2 rounded hover:bg-edge/40 text-left">
                <span className="flex items-center gap-2 truncate">
                  <span className="text-primary">{aOpen ? '▾' : '▸'}</span>
                  <span className="text-slate-100 font-semibold">{node.asin}</span>
                  <span className="text-mute text-xs">· {camps.length} campaign{camps.length === 1 ? '' : 's'}</span>
                </span>
                <span className="flex gap-3 text-xs shrink-0">
                  <span className="text-mute">{money(r.spend)}</span>
                  <span className={r.acos > 0.35 ? 'text-red' : 'text-lime'}>{pct(r.acos)}</span>
                </span>
              </button>
              {aOpen && (
                <div className="px-2 pb-2 space-y-1">
                  {camps.map(c => (
                    <CampaignNode key={c.campaign_id} c={c} open={open} toggle={toggle} matches={matches} />
                  ))}
                  {camps.length === 0 && <div className="text-mute text-xs py-2 text-center">no campaigns in this state</div>}
                </div>
              )}
            </div>
          )
        })}
        {shown.length === 0 && <div className="text-mute text-xs py-4 text-center">no ASINs match</div>}
      </div>

      <div className="flex gap-4 mt-3 pt-3 border-t border-edge text-[10px] font-mono text-mute">
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-lime" />enabled</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber" />paused</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-slate-500" />archived</span>
      </div>
    </div>
  )
}

// campaign -> ad groups -> ads + targets
function CampaignNode({ c, open, toggle, matches }) {
  const m = c.metrics
  const cid = `camp:${c.campaign_id}`
  const isOpen = open[cid]
  const ags = c.ad_groups.filter(ag => matches(ag.state))
  return (
    <div className={dim(c.state)}>
      <button onClick={() => toggle(cid)}
        className="w-full flex items-center justify-between py-1.5 px-2 rounded hover:bg-edge/40 text-left">
        <span className="flex items-center gap-2 truncate">
          <span className="text-lime">{isOpen ? '▾' : '▸'}</span>
          <StateBadge state={c.state} />
          <span className={`truncate text-slate-200 ${norm(c.state) === 'archived' ? 'line-through' : ''}`}>{c.name}</span>
          <span className="text-mute text-[10px] shrink-0">{ags.length} ad group{ags.length === 1 ? '' : 's'}</span>
        </span>
        <span className="flex gap-3 text-xs shrink-0">
          <span className="text-mute">{money(m.spend)}</span>
          <span className={m.acos > 0.35 ? 'text-red' : 'text-lime'}>{pct(m.acos)}</span>
        </span>
      </button>
      {isOpen && ags.map(ag => {
        const ads = (ag.ads || []).filter(a => matches(a.state))
        const ts = ag.targets.filter(t => matches(t.state))
        return (
          <div key={ag.ad_group_id} className={`ml-6 border-l border-edge pl-3 py-1 ${dim(ag.state)}`}>
            <div className="flex items-center gap-2 text-xs mb-1">
              <StateBadge state={ag.state} />
              <span className="text-mute truncate">{ag.name} · {ads.length} ad{ads.length === 1 ? '' : 's'} · {ts.length} target{ts.length === 1 ? '' : 's'}</span>
            </div>

            {/* connected ads */}
            {ads.length > 0 && (
              <div className="mb-1">
                <div className="text-mute text-[10px] uppercase tracking-wider mb-0.5">ads</div>
                {ads.slice(0, 12).map(a => (
                  <div key={a.ad_id} className={`flex justify-between text-xs py-0.5 ${dim(a.state)}`}>
                    <span className="flex items-center gap-2 truncate max-w-[240px]">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot(a.state)}`} />
                      <span className="truncate text-slate-300">{a.asin || a.ad_id}{a.sku ? ` · ${a.sku}` : ''}</span>
                    </span>
                    <span className="flex gap-3 shrink-0">
                      <span className="text-mute">{money(a.metrics.spend)}</span>
                      <span className={a.metrics.acos > 0.35 ? 'text-red' : 'text-lime'}>{pct(a.metrics.acos)}</span>
                    </span>
                  </div>
                ))}
                {ads.length > 12 && <div className="text-mute text-xs">+{ads.length - 12} more ads…</div>}
              </div>
            )}

            {/* targets */}
            {ts.length > 0 && <div className="text-mute text-[10px] uppercase tracking-wider mb-0.5">targets</div>}
            {ts.slice(0, 12).map(t => (
              <div key={t.target_id} className={`flex justify-between text-xs py-0.5 ${dim(t.state)}`}>
                <span className="flex items-center gap-2 truncate max-w-[240px]">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot(t.state)}`} />
                  <span className="truncate text-slate-300">{t.label}</span>
                </span>
                <span className="flex gap-3 shrink-0">
                  <span className="text-mute">bid ${t.bid ?? '—'}</span>
                  <span className={t.metrics.acos > 0.35 ? 'text-red' : 'text-lime'}>{pct(t.metrics.acos)}</span>
                </span>
              </div>
            ))}
            {ts.length > 12 && <div className="text-mute text-xs">+{ts.length - 12} more…</div>}
            {ads.length === 0 && ts.length === 0 && <div className="text-mute text-xs italic">nothing in this state</div>}
          </div>
        )
      })}
    </div>
  )
}

export function NarratePanel({ enabled, provider, onNarrate, text, busy }) {
  const [mode, setMode] = useState('summary')
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-mute text-[11px] font-mono uppercase tracking-wider">AI narration</span>
        <span className={`tag ${enabled ? 'bg-lime/15 text-lime' : 'bg-edge text-mute'}`}>
          {provider}{enabled ? '' : ' · off'}
        </span>
      </div>
      <div className="flex gap-2 mb-3">
        {['summary', 'email'].map(m => (
          <button key={m} onClick={() => setMode(m)}
            className={`tag ${mode === m ? 'bg-lime text-ink' : 'border border-edge text-mute'}`}>{m}</button>
        ))}
        <button onClick={() => onNarrate(mode)} disabled={busy} aria-busy={busy} className="btn btn-ghost ml-auto">
          {busy ? 'thinking…' : 'generate'}
        </button>
      </div>
      <div className="bg-ink rounded p-3 font-mono text-sm text-slate-300 whitespace-pre-wrap min-h-[80px]">
        {text || (enabled ? 'click generate for an AI summary of the audit.'
          : 'LLM disabled. Set LLM_PROVIDER=ollama|lmstudio|openclaw in the backend to enable. The audit + bulk files work fully without it.')}
      </div>
    </div>
  )
}
