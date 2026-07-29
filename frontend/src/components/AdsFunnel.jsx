import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { money, pct, Icon, TableSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { PerfTier } from './AdsStudio.jsx'

const num = (x) => (x ?? 0).toLocaleString()
const r2 = (x) => x == null ? '—' : Number(x).toFixed(2)

// funnel tiers in flow order — mirrors pipeline/funnel.py
const TIERS = ['AUTO', 'BROAD', 'PHRASE', 'EXACT', 'PT']
const TIER_UI = {
  AUTO: ['Auto discovery', 'text-cyan', 'border-cyan/40'],
  BROAD: ['Broad research', 'text-sky-400', 'border-sky-400/40'],
  PHRASE: ['Phrase research', 'text-lime', 'border-lime/40'],
  EXACT: ['Exact performance', 'text-primary', 'border-primary/40'],
  PT: ['Product targeting', 'text-amber-400', 'border-amber-400/40'],
}
// which tiers receive graduating winners
const RECEIVERS = ['EXACT', 'PT']

const trunc = (txt, w, cls = '') =>
  <span className={`truncate inline-block align-bottom ${cls}`} style={{ maxWidth: w }} title={txt}>{txt || '—'}</span>

function TierBadge({ tier }) {
  const [label, color, border] = TIER_UI[tier] || [tier, 'text-mute', 'border-edge']
  return <span className={`tag border ${color} ${border}`}>{label}</span>
}

/**
 * The segmented funnel view of Ads Studio.
 *
 * Phase 1 (Auto / Broad / Phrase) mines search terms; Phase 2 (Exact / PT) takes the
 * proven ones and carries the budget. This panel reports how the selected products'
 * campaigns map onto that shape, then routes every winner to where it belongs —
 * negative-exacting it upstream so the funnel only flows one way.
 */
export function AdsFunnel({ asins, scope, campaignTypes, targetAcos, onClose }) {
  const toast = useToast()
  const { confirm } = useModals()
  const [rep, setRep] = useState(null)
  const [err, setErr] = useState(null)
  const [bosses, setBosses] = useState({})
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [pick, setPick] = useState({ promotes: new Set(), migrates: new Set(), negatives: new Set(), pauses: new Set(), placements: new Set() })

  const list = asins || []
  useEffect(() => {
    setRep(null); setErr(null); setPlan(null)
    api.studioFunnel(list, targetAcos, campaignTypes)
      .then(r => {
        setRep(r)
        // default each receiving tier to its highest-spend campaign
        const seed = {}
        for (const t of RECEIVERS) {
          const tier = r.tiers.find(x => x.tier === t)
          const top = (tier?.campaigns || [])
            .slice().sort((a, b) => (b.metrics?.spend || 0) - (a.metrics?.spend || 0))[0]
          if (top) seed[t] = top.campaign_id
        }
        setBosses(seed)
      })
      .catch(e => setErr(String(e?.message || e).replace(/^Error:\s*/, '')))
  }, [scope, list.join(','), targetAcos, (campaignTypes || []).join(',')])  // eslint-disable-line

  const byTier = useMemo(() => {
    const m = {}
    for (const t of rep?.tiers || []) m[t.tier] = t
    return m
  }, [rep])

  async function draft() {
    setBusy(true)
    try {
      const p = await api.studioFunnelPlan(list, bosses, campaignTypes, targetAcos)
      setPlan(p)
      setPick({
        promotes: new Set(p.promotes.map(keyOf)),
        migrates: new Set(p.migrates.map(keyOf)),
        negatives: new Set(p.negatives.map(negKey)),
        pauses: new Set(p.pauses.map(pauseKey)),
        placements: new Set(),   // placement bids are a separate decision — opt in
      })
      toast.success(`${p.counts.promotes} promote · ${p.counts.negatives} negate · ${p.counts.pauses} pause`)
    } catch (e) {
      const m = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(m); toast.error(m)
    } finally { setBusy(false) }
  }

  async function exportBulk() {
    const promotes = plan.promotes.filter(r => pick.promotes.has(keyOf(r)))
    const migrates = plan.migrates.filter(r => pick.migrates.has(keyOf(r)))
    const negatives = plan.negatives.filter(r => pick.negatives.has(negKey(r)))
    const pauses = plan.pauses.filter(r => pick.pauses.has(pauseKey(r)))
    const placements = (plan.placements || []).filter(r => pick.placements.has(r.campaign_id))

    // A promotion without its upstream negative pays for the same term twice.
    const orphan = promotes.filter(p => !negatives.some(n =>
      n.campaign_id === p.from_campaign_id &&
      (n.keyword_text || n.expression) === (p.keyword_text || p.expression)))
    if (orphan.length) {
      const ok = await confirm({
        title: `${orphan.length} promotion(s) without their negative`, danger: true,
        confirmLabel: 'Export anyway',
        message: 'You are promoting terms into the money tier but leaving them live upstream. '
          + 'The discovery campaign will keep bidding on the same search term, so you pay '
          + 'twice and the funnel stops flowing one way.\n\nTick the matching rows in '
          + '"negate upstream" unless you meant this.',
      })
      if (!ok) return
    }
    setBulkBusy(true)
    try {
      const blob = await api.studioFunnelBulk({ promotes, migrates, negatives, pauses, placements })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'ads_studio_funnel.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success(`Funnel bulk downloaded — ${promotes.length + migrates.length} create · ${negatives.length} negative · ${pauses.length + placements.length} update`)
    } catch (e) {
      const m = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(m); toast.error(m)
    } finally { setBulkBusy(false) }
  }

  if (err && !rep) return (
    <div className="space-y-3">
      <button onClick={onClose} className="btn btn-ghost text-xs"><Icon name="arrow_back" size={14} /> Back</button>
      <div className="card border-down/40 p-3 font-mono text-xs text-down inline-flex items-center gap-1">
        <Icon name="warning" size={12} /> {err}
      </div>
    </div>
  )
  if (!rep) return <div className="card"><TableSkeleton rows={6} cols={5} /></div>

  const picked = Object.values(pick).reduce((n, s) => n + s.size, 0)
  const bandLo = Math.round((rep.auto_share_target?.[0] ?? 0.15) * 100)
  const bandHi = Math.round((rep.auto_share_target?.[1] ?? 0.20) * 100)
  const verdictColor = { ok: 'text-up', under: 'text-amber-400', over: 'text-amber-400', unknown: 'text-mute' }[rep.budget_verdict]

  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">
            ads studio · funnel strategy
          </div>
          <div className="text-xs text-mute font-mono flex gap-3 flex-wrap">
            <span>{rep.asins.length} product(s)</span>
            <span>goal ACoS {pct(rep.target_acos)}</span>
            <span className="text-up">{rep.counts.keep} keep</span>
            <span className="text-down">{rep.counts.drop} drop</span>
            <span>{rep.counts.review} review</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={draft} disabled={busy} aria-busy={busy}
            className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
            <Icon name={busy ? 'sync' : 'moving'} size={14} />{busy ? 'Routing…' : 'Route winners'}
          </button>
          <button onClick={onClose} className="btn btn-ghost text-xs flex items-center gap-1">
            <Icon name="close" size={14} /> Close
          </button>
        </div>
      </div>

      {/* Phase 1 budget rule */}
      <div className="card p-4 space-y-2">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
            phase 1 budget · auto discovery should hold {bandLo}–{bandHi}%
          </div>
          <div className={`font-mono text-sm ${verdictColor}`}>
            {rep.auto_share == null ? '—' : `${(rep.auto_share * 100).toFixed(1)}%`}
          </div>
        </div>
        {/* the band drawn to scale, with the actual share marked on it */}
        <div className="relative h-2 rounded bg-edge overflow-hidden">
          <div className="absolute inset-y-0 bg-up/30" style={{ left: `${bandLo}%`, width: `${bandHi - bandLo}%` }} />
          {rep.auto_share != null && (
            <div className="absolute inset-y-0 w-1 bg-primary"
              style={{ left: `${Math.min(100, rep.auto_share * 100)}%` }} />
          )}
        </div>
        <div className="font-mono text-[11px] text-mute">{rep.budget_note}</div>
      </div>

      {/* the funnel itself */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        {TIERS.map(t => {
          const tier = byTier[t] || {}
          const [label, color, border] = TIER_UI[t]
          const m = tier.metrics || {}
          return (
            <div key={t} className={`card p-3 space-y-2 ${tier.present ? border : 'border-dashed'}`}>
              <div>
                <div className={`font-mono text-[11px] uppercase tracking-wider ${tier.present ? color : 'text-mute'}`}>{label}</div>
                <div className="font-mono text-[10px] text-mute">phase {tier.phase || (t === 'EXACT' || t === 'PT' ? 2 : 1)}</div>
              </div>
              {tier.present ? (
                <>
                  <div className="font-mono text-lg text-slate-100">{num(tier.count)}<span className="text-mute text-xs ml-1">campaigns</span></div>
                  <div className="font-mono text-[11px] text-mute space-y-0.5">
                    <div>{money(m.spend)} spend{tier.spend_share != null && <span className="text-mute"> · {(tier.spend_share * 100).toFixed(0)}%</span>}</div>
                    <div>{money(m.sales)} sales</div>
                    <div>{pct(m.acos)} ACoS · {num(m.orders)} orders</div>
                  </div>
                  {RECEIVERS.includes(t) && (
                    <select value={bosses[t] || ''} onChange={e => { setPlan(null); setBosses(b => ({ ...b, [t]: e.target.value })) }}
                      className="w-full bg-ink border border-edge rounded px-1 py-1 font-mono text-[10px] text-slate-100 focus:border-primary outline-none">
                      <option value="">— no {label} boss —</option>
                      {(tier.campaigns || []).map(c => (
                        <option key={c.campaign_id} value={c.campaign_id}>
                          {c.tier ? `[${c.tier}] ` : ''}{c.campaign_name}
                        </option>
                      ))}
                    </select>
                  )}
                </>
              ) : (
                <div className="font-mono text-[11px] text-amber-400">missing tier</div>
              )}
            </div>
          )
        })}
      </div>

      {/* structural problems */}
      {(rep.gaps.length > 0 || rep.mix_violations.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {rep.gaps.length > 0 && (
            <DataTable title={`funnel gaps · ${rep.gaps.length}`} lean columns={GAP_COLS} rows={rep.gaps}
              rowKey={g => g.tier} empty="no gaps" />
          )}
          {rep.mix_violations.length > 0 && (
            <DataTable title={`mixed match types · ${rep.mix_violations.length} — never mix them in one campaign`}
              lean columns={MIX_COLS} rows={rep.mix_violations} rowKey={v => v.campaign_id} empty="none" />
          )}
        </div>
      )}

      {/* the routed plan */}
      {plan && (
        <div className="card p-4 space-y-4">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
              routed · {plan.counts.promotes} promote · {plan.counts.migrates} consolidate · {plan.counts.negatives} negate · {plan.counts.pauses} pause
            </div>
            <button onClick={exportBulk} disabled={!picked || bulkBusy} aria-busy={bulkBusy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name={bulkBusy ? 'sync' : 'download'} size={14} />{bulkBusy ? 'Building…' : `Export funnel bulk (${picked})`}
            </button>
          </div>

          {plan.promotes.length > 0 && (
            <DataTable title={`promote into the money tier · ${plan.promotes.length}`} lean columns={PROMOTE_COLS}
              rows={plan.promotes} rowKey={keyOf} selectable selected={pick.promotes}
              onToggle={k => toggle(setPick, 'promotes', k)}
              onToggleAll={(keys, on) => setAll(setPick, 'promotes', keys, on)} />
          )}
          {plan.negatives.length > 0 && (
            <DataTable title={`negate upstream · ${plan.negatives.length} — stops the discovery campaign paying twice`}
              lean columns={NEG_COLS} rows={plan.negatives} rowKey={negKey} selectable selected={pick.negatives}
              onToggle={k => toggle(setPick, 'negatives', k)}
              onToggleAll={(keys, on) => setAll(setPick, 'negatives', keys, on)} />
          )}
          {plan.migrates.length > 0 && (
            <DataTable title={`consolidate within the tier · ${plan.migrates.length}`} lean columns={PROMOTE_COLS}
              rows={plan.migrates} rowKey={keyOf} selectable selected={pick.migrates}
              onToggle={k => toggle(setPick, 'migrates', k)}
              onToggleAll={(keys, on) => setAll(setPick, 'migrates', keys, on)} />
          )}
          {plan.pauses.length > 0 && (
            <DataTable title={`pause — missed the goal ACoS · ${plan.pauses.length}`} lean columns={PAUSE_COLS}
              rows={plan.pauses} rowKey={pauseKey} selectable selected={pick.pauses}
              onToggle={k => toggle(setPick, 'pauses', k)}
              onToggleAll={(keys, on) => setAll(setPick, 'pauses', keys, on)} />
          )}
          {(plan.placements || []).length > 0 && (
            <DataTable title={`top of search uplift · ${plan.placements.length} — not pre-selected`}
              lean columns={TOS_COLS} rows={plan.placements} rowKey={p => p.campaign_id}
              selectable selected={pick.placements}
              onToggle={k => toggle(setPick, 'placements', k)}
              onToggleAll={(keys, on) => setAll(setPick, 'placements', keys, on)} />
          )}
          {plan.skipped.length > 0 && (
            <DataTable title={`can't move · ${plan.skipped.length}`} lean columns={SKIP_COLS}
              rows={plan.skipped} rowKey={(r, i) => `${r.from_campaign_id}|${r.label}|${i}`} empty="none" />
          )}
        </div>
      )}
    </div>
  )
}

// selection keys come from the row, never its index (DataTable sorts the view)
const keyOf = (r) => `${r.from_campaign_id}|${r.entity}|${r.keyword_text || r.expression || r.label}`
const negKey = (r) => `${r.campaign_id}|${r.entity}|${r.keyword_text || r.expression || r.label}`
const pauseKey = (r) => `${r.campaign_id}|${r.entity}|${r.id || r.label}`

function toggle(setPick, bucket, key) {
  setPick(p => {
    const n = new Set(p[bucket]); n.has(key) ? n.delete(key) : n.add(key)
    return { ...p, [bucket]: n }
  })
}
function setAll(setPick, bucket, keys, on) {
  setPick(p => {
    const n = new Set(p[bucket]); keys.forEach(k => on ? n.add(k) : n.delete(k))
    return { ...p, [bucket]: n }
  })
}

const PROMOTE_COLS = [
  { key: 'label', label: 'Term', render: r => trunc(r.label, 200) },
  { key: 'from_tier', label: 'From', value: r => r.from_tier, render: r => <TierBadge tier={r.from_tier} /> },
  { key: 'from_campaign_name', label: 'Source campaign', cellClass: 'text-mute', render: r => trunc(r.from_campaign_name, 170, 'text-mute') },
  { key: 'to_tier', label: 'To', value: r => r.to_tier, render: r => <TierBadge tier={r.to_tier} /> },
  { key: 'to_campaign_name', label: 'Into', cellClass: 'text-mute', render: r => trunc(r.to_campaign_name, 170, 'text-mute') },
  { key: 'new_bid', label: 'Bid', align: 'right', render: r => r.new_bid == null ? '—' : `$${r2(r.new_bid)}` },
  { key: 'orders', label: 'Orders', align: 'right', value: r => r.metrics?.orders, render: r => num(r.metrics?.orders) },
  { key: 'acos', label: 'ACOS', align: 'right', value: r => r.metrics?.acos, render: r => pct(r.metrics?.acos) },
]

const NEG_COLS = [
  { key: 'label', label: 'Term', render: r => trunc(r.label, 200) },
  { key: 'campaign_name', label: 'Negate in', cellClass: 'text-mute', render: r => trunc(r.campaign_name, 190, 'text-mute') },
  { key: 'ad_group_name', label: 'Ad group', cellClass: 'text-mute', render: r => trunc(r.ad_group_name || r.ad_group_id, 150, 'text-mute') },
  { key: 'reason', label: 'Why', cellClass: 'text-mute', render: r => trunc(r.reason, 280, 'text-mute') },
]

const PAUSE_COLS = [
  { key: 'label', label: 'Term', render: r => trunc(r.label, 200) },
  { key: 'from_tier', label: 'Tier', value: r => r.from_tier, render: r => <TierBadge tier={r.from_tier} /> },
  { key: 'campaign_name', label: 'In campaign', cellClass: 'text-mute', render: r => trunc(r.campaign_name || r.from_campaign_name, 180, 'text-mute') },
  { key: 'reason', label: 'Why', cellClass: 'text-mute', render: r => trunc(r.reason, 220, 'text-mute') },
  { key: 'spend', label: 'Spend', align: 'right', value: r => r.metrics?.spend, render: r => money(r.metrics?.spend) },
]

const TOS_COLS = [
  { key: 'campaign_name', label: 'Exact campaign', render: r => trunc(r.campaign_name, 220) },
  { key: 'current_pct', label: 'Current', align: 'right', render: r => r.current_pct == null ? '— none set' : `${r2(r.current_pct)}%` },
  { key: 'new_pct', label: 'New', align: 'right', cellClass: 'text-primary', render: r => `${r2(r.new_pct)}%` },
  { key: 'uplift', label: 'Uplift', align: 'right', render: r => `+${Math.round((r.uplift || 0) * 100)}%` },
  { key: 'orders', label: 'Orders', align: 'right', render: r => num(r.orders) },
  { key: 'acos', label: 'ACOS', align: 'right', render: r => pct(r.acos) },
]

const GAP_COLS = [
  { key: 'label', label: 'Missing', render: r => <span className="text-amber-400">{r.label}</span> },
  { key: 'phase', label: 'Phase', align: 'right', render: r => r.phase },
  { key: 'reason', label: 'Why it matters', cellClass: 'text-mute', render: r => trunc(r.reason, 420, 'text-mute') },
]

const MIX_COLS = [
  { key: 'campaign_name', label: 'Campaign', render: r => trunc(r.campaign_name, 220) },
  { key: 'tiers', label: 'Holds', render: r => Object.entries(r.tiers).map(([t, n]) => `${t}×${n}`).join(' · ') },
  { key: 'reason', label: 'Why it matters', cellClass: 'text-mute', render: r => trunc(r.reason, 340, 'text-mute') },
]

const SKIP_COLS = [
  { key: 'label', label: 'Term', render: r => trunc(r.label, 200) },
  { key: 'from_campaign_name', label: 'Stays in', cellClass: 'text-mute', render: r => trunc(r.from_campaign_name, 180, 'text-mute') },
  { key: 'skip_reason', label: 'Why it stays put', cellClass: 'text-mute', render: r => trunc(r.skip_reason, 340, 'text-mute') },
]
