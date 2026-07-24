import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { money, Spinner, CardSkeleton, Icon } from './ui.jsx'
import { StrategyFlow } from './StrategyFlow.jsx'
import { useTableControls, TableToolbar, Pagination, Th, DataTable } from './table.jsx'
import { useToast } from './Toast.jsx'

const STATUS = {
  active: 'bg-lime/15 text-lime border border-lime/30',
  available: 'bg-cyan/15 text-cyan border border-cyan/30',
  manual: 'border border-edge text-mute',
  'needs config': 'bg-amber/15 text-amber border border-amber/30',
  'n/a': 'border border-edge text-slate-600',
}
const PRIO = { high: 'text-red', med: 'text-amber', low: 'text-mute' }
const TOOL = { harvest: 'PPC → Harvest', bidopt: 'PPC → Bid Optimizer', placement: 'PPC → Placement',
  ngram: 'PPC → N-gram', manual: 'manual' }

// per-campaign state classifier (the methodology map's four states, live)
const STATE_META = {
  below_target: ['Below target', 'text-up border-up/40', 'grow'],
  at_target: ['At target', 'text-cyan border-cyan/40', 'balance'],
  above_target: ['Above target', 'text-amber border-amber/40', 'cut'],
  over_break_even: ['Over break-even', 'text-down border-down/40', 'cut hard'],
  no_data: ['No data', 'text-mute border-edge', 'rank'],
}

function AccountStates({ states, scope }) {
  if (!states?.campaigns?.length) return null
  const COLS = [
    { key: 'state', label: 'State', value: x => x.state,
      render: x => { const [label, cls] = STATE_META[x.state] || [x.state, 'text-mute border-edge']
        return <span className={`tag border whitespace-nowrap ${cls}`}>{label}</span> } },
    { key: 'campaign', label: 'Campaign', render: x => (
        <span className="inline-block max-w-[240px] truncate align-bottom text-slate-200" title={x.campaign}>{x.campaign || x.campaign_id}</span>) },
    { key: 'spend', label: 'Spend', align: 'right', render: x => money(x.spend) },
    { key: 'acos', label: 'ACoS / BE', align: 'right', value: x => x.acos ?? 9,
      render: x => (
        <span title={x.break_even != null ? `break-even ${(x.break_even * 100).toFixed(1)}%` : ''}>
          <span className={x.break_even != null && x.acos != null ? (x.acos > x.break_even ? 'text-down' : 'text-up') : 'text-mute'}>
            {x.acos != null ? `${(x.acos * 100).toFixed(0)}%` : x.spend ? '∞' : '—'}
          </span>
          <span className="text-mute"> / {x.break_even != null ? `${(x.break_even * 100).toFixed(0)}%` : '—'}</span>
        </span>) },
    { key: 'goal', label: 'Goal', align: 'right', cellClass: 'text-mute', render: x => `${(x.goal * 100).toFixed(0)}%` },
    { key: 'lever', label: 'Lever', render: x => <span className="text-cyan text-xs whitespace-nowrap">{x.lever}</span> },
    { key: 'why', label: 'Why', cellClass: 'text-mute text-xs',
      render: x => <span className="inline-block max-w-[260px] truncate align-bottom" title={x.why}>{x.why}</span> },
  ]
  return (
    <div className="card">
      <DataTable title={`account states · ${states.campaigns.length} campaigns classified`}
        columns={COLS} rows={states.campaigns} rowKey={x => x.campaign_id} scope={scope}
        searchKeys={['campaign', 'state', 'lever', 'why', 'asin']}
        placeholder="search campaign / state / lever…" empty="no campaigns"
        initial={{ sort: { key: 'spend', dir: 'desc' } }} />
    </div>
  )
}

// Tier Router: campaign-architecture tier auto-suggested from the store catalog's
// advertisable-unit count (parents + standalone SKUs; falls back to advertised
// ASINs from the loaded bulk when no catalog exists). Cadence pills jump straight
// to that cadence's strategy set below.
function TierRouter({ scope, presets, onCadence }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [ladder, setLadder] = useState(false)

  useEffect(() => {
    let live = true
    api.strategyTier().then(x => { if (live) { setD(x); setErr(null) } })
      .catch(e => { if (live) setErr(String(e)) })
    return () => { live = false }
  }, [scope])   // eslint-disable-line

  if (err) return null                       // router is decoration — never block the panel
  if (!d) return <CardSkeleton lines={3} />
  const t = d.tier
  const label = k => presets.find(p => p.key === k)?.label || k
  const src = d.source === 'catalog'
    ? `${d.counts.parents} parents + ${d.counts.standalone} standalone from the Product Catalog (${d.counts.children} children fold into parents)`
    : 'advertised ASINs in this audit’s bulk — upload the Category Listings Report for an exact catalog count'

  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-2 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">tier router · campaign architecture</div>
          {t ? (
            <div className="mt-1 flex items-baseline gap-2 flex-wrap">
              <span className="tag bg-lime text-ink font-bold">Tier {t.tier}</span>
              <span className="text-slate-200 font-semibold">{t.name}</span>
              <span className="font-mono text-xs text-mute">{t.range} · you have <span className="text-primary font-bold">{d.asin_count}</span></span>
            </div>
          ) : (
            <div className="mt-1 font-mono text-xs text-mute">no ASINs counted yet — upload a Product Catalog (Product Benchmark tab) or a PPC bulk</div>
          )}
        </div>
        <button onClick={() => setLadder(v => !v)} className="tag border border-edge text-mute hover:text-slate-300">
          {ladder ? 'hide' : 'show'} all 7 tiers
        </button>
      </div>

      {t && (
        <div className="p-4 space-y-3">
          <div className="font-mono text-[11px] text-mute">{src}</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {[['structure', t.structure], ['campaigns / asin', t.campaigns_per_asin],
              ['acos targets', t.acos], ['automation', t.automation]].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-edge p-2.5">
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{k}</div>
                <div className="text-xs text-slate-200 mt-0.5">{v}</div>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-mute text-[11px] font-mono uppercase tracking-wider mr-1">run cadences</span>
            {t.cadences.map(k => (
              <button key={k} onClick={() => onCadence?.(k)} title="open this cadence's strategy set"
                className="tag bg-lime/15 text-lime border border-lime/30 hover:bg-lime hover:text-ink">{label(k)}</button>
            ))}
          </div>
          <ul className="space-y-1">
            {t.techniques.map((x, i) => (
              <li key={i} className="text-xs text-slate-300 flex gap-2"><span className="text-primary">·</span>{x}</li>
            ))}
          </ul>
          {d.notes.length > 0 && (
            <div className="rounded-lg border border-edge bg-ink/40 p-3 space-y-1">
              {d.notes.map((n, i) => <div key={i} className="text-xs text-mute">{n}</div>)}
            </div>
          )}
          <div className="font-mono text-[11px] text-cyan">{t.app}</div>
        </div>
      )}

      {ladder && (
        <div className="border-t border-edge overflow-x-auto">
          <table className="w-full text-sm font-mono">
            <thead className="text-mute text-[11px] uppercase">
              <tr className="border-b border-edge">
                <th className="p-2 text-left">Tier</th><th className="p-2 text-left">ASINs</th>
                <th className="p-2 text-left">Strategy</th><th className="p-2 text-left">Structure</th>
                <th className="p-2 text-left">Automation</th>
              </tr>
            </thead>
            <tbody>
              {d.tiers.map(x => {
                const on = t && x.key === t.key
                return (
                  <tr key={x.key} className={`border-b border-edge/50 ${on ? 'bg-primary/10' : ''}`}>
                    <td className="p-2"><span className={`tag ${on ? 'bg-lime text-ink font-bold' : 'border border-edge text-mute'}`}>T{x.tier}</span></td>
                    <td className="p-2 whitespace-nowrap text-mute">{x.range}</td>
                    <td className={`p-2 whitespace-nowrap ${on ? 'text-primary' : 'text-slate-200'}`}>{x.name}</td>
                    <td className="p-2 text-xs text-mute max-w-[340px]">{x.structure}</td>
                    <td className="p-2 text-xs text-mute whitespace-nowrap">{x.automation}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// Strategy Advisor: the 16-strategy playbook, run PER AUDIT CADENCE. Pick a cadence
// tile → its own recommendations (each cadence is scoped to its own db + retuned
// thresholds server-side, so every cadence yields a distinct strategy set).
export function StrategyPanel({ scope, targetAcos }) {
  const toast = useToast()
  const [presets, setPresets] = useState([])
  const [sel, setSel] = useState(() => scope.split(':')[2] || 'full_month')   // active cadence
  const [byC, setByC] = useState({})        // cadence key -> strategy data (cache)
  const [busy, setBusy] = useState(false)
  const [prio, setPrio] = useState('ALL')
  const [dl, setDl] = useState(null)        // strategy name being generated
  const [err, setErr] = useState(null)

  useEffect(() => { api.cadencePresets().then(d => setPresets(d.presets)).catch(() => {}) }, [])

  // load one cadence's strategy (cached; force re-fetches)
  async function fetchC(cadence, force) {
    if (!force && byC[cadence]) return
    setBusy(true); setErr(null)
    try {
      const d = await api.strategy(targetAcos, cadence)
      setByC(m => ({ ...m, [cadence]: d }))
    } catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  // account/goal changed → drop the cache and reload the selected cadence
  useEffect(() => { setByC({}); fetchC(sel, true) }, [scope, targetAcos])   // eslint-disable-line

  function selectCadence(k) { setSel(k); setPrio('ALL'); fetchC(k) }

  const data = byC[sel]

  async function downloadBulk(name) {
    setDl(name); setErr(null)
    try {
      const blob = await api.strategyBulk(name, targetAcos, sel)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'ppc_' + sel + '_' + name.toLowerCase().replace(/[^a-z0-9]+/g, '_') + '.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success(`Strategy bulk downloaded · ${name}`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
    finally { setDl(null) }
  }

  const recs = useMemo(() => (data?.recommendations || []).filter(r => prio === 'ALL' || r.priority === prio), [data, prio])
  const ctl = useTableControls(recs, {
    searchKeys: ['strategy', 'campaign', 'criteria', 'action', 'priority'], deps: [prio, sel, scope],
  })

  const activeLabel = presets.find(p => p.key === sel)?.label || sel

  return (
    <div className="space-y-6">
      <TierRouter scope={scope} presets={presets} onCadence={selectCadence} />

      <StrategyFlow counts={data?.states?.counts} />

      {/* cadence selector — one strategy set per Audit Cadence */}
      <div className="card">
        <div className="p-4 border-b border-edge">
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">strategy by audit cadence</div>
          <div className="font-mono text-xs text-mute mt-1">Pick a cadence to see its recommendation strategies. Each cadence has its own set.</div>
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-5 gap-2">
          {presets.map(p => {
            const on = p.key === sel
            const d = byC[p.key]
            return (
              <button key={p.key} onClick={() => selectCadence(p.key)}
                className={`text-left rounded-lg border p-3 transition-colors ${on ? 'border-primary bg-primary/10' : 'border-edge hover:border-mute'}`}>
                <div className={`font-mono text-xs font-semibold ${on ? 'text-primary' : 'text-slate-200'}`}>{p.label}</div>
                <div className="font-mono text-[10px] text-mute mt-1">{p.range}</div>
                <div className="font-mono text-[10px] mt-1">
                  {d ? <span className="text-primary font-bold">{d.recommendations.length}<span className="text-mute font-normal"> recs</span></span>
                    : <span className="text-mute/60">tap to load</span>}
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {err && <div className="card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      {busy && !data && <CardSkeleton lines={6} />}

      {data && (() => {
        const c = data.counts
        return (
          <>
            {/* the methodology map's four states, classified live per campaign
                (generic advisor only — cadence-specific sets have no campaign rollup) */}
            <AccountStates states={data.states} scope={`${scope}:${sel}`} />

            {/* recommendations for the selected cadence */}
            <div className="card">
              <div className="p-4 border-b border-edge flex items-center justify-between gap-2 flex-wrap">
                <div className="text-mute text-[11px] font-mono uppercase tracking-wider">{activeLabel} · recommendations · {data.recommendations.length}</div>
                <div className="flex gap-1">
                  {[['ALL', data.recommendations.length], ['high', c.high], ['med', c.med], ['low', c.low]].map(([v, n]) => (
                    <button key={v} onClick={() => setPrio(v)}
                      className={`tag ${prio === v ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>{String(v).toUpperCase()} {n}</button>
                  ))}
                </div>
              </div>
              <TableToolbar ctl={ctl} placeholder="search strategy / campaign / why…" />
              <div className="overflow-auto max-h-[460px]">
                <table className="w-full text-sm font-mono">
                  <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
                    <tr className="border-b border-edge">
                      <Th ctl={ctl} k="priority">!</Th><Th ctl={ctl} k="strategy">Strategy</Th>
                      <Th ctl={ctl} k="campaign">Campaign</Th><Th ctl={ctl} k="criteria">Why (triggered)</Th>
                      <Th ctl={ctl} k="acos" align="right">ACoS / BE</Th>
                      <Th ctl={ctl} k="action">Action</Th><Th ctl={ctl} k="tool">Run in</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {ctl.view.map((r, i) => (
                      <tr key={i} className="border-b border-edge/50 hover:bg-edge/30">
                        <td className={`p-2 font-bold ${PRIO[r.priority]}`}><Icon name="circle" size={10} /></td>
                        <td className="p-2 text-slate-200 whitespace-nowrap">{r.strategy}</td>
                        <td className="p-2 max-w-[180px] truncate text-mute" title={r.campaign}>{r.campaign}</td>
                        <td className="p-2 text-slate-300 text-xs max-w-[240px] truncate" title={r.criteria}>{r.criteria}</td>
                        <td className="p-2 text-right text-xs whitespace-nowrap"
                          title={r.break_even != null ? 'campaign ACoS vs the product\'s break-even (catalog COGS + real Transactions-ledger fees) — red = losing money per ad sale' : ''}>
                          {r.acos != null && r.break_even != null
                            ? <><span className={r.acos > r.break_even ? 'text-down' : 'text-up'}>{(r.acos * 100).toFixed(0)}%</span><span className="text-mute"> / {(r.break_even * 100).toFixed(0)}%</span></>
                            : r.acos != null ? <span className="text-mute">{(r.acos * 100).toFixed(0)}%</span>
                            : <span className="text-mute">—</span>}
                        </td>
                        <td className="p-2 text-mute text-xs max-w-[240px] truncate" title={r.action}>{r.action}</td>
                        <td className="p-2 text-xs whitespace-nowrap">
                          {r.bulk ? (
                            <button onClick={() => downloadBulk(r.strategy)} disabled={dl === r.strategy} aria-busy={dl === r.strategy}
                              className="tag bg-lime/15 text-lime border border-lime/30 hover:bg-lime hover:text-ink">
                              {dl === r.strategy ? 'building…' : <><Icon name="download" size={12} /> bulk</>}
                            </button>
                          ) : <span className="text-cyan">{TOOL[r.tool] || r.tool}</span>}
                        </td>
                      </tr>
                    ))}
                    {ctl.view.length === 0 && <tr><td colSpan="7" className="p-6 text-center text-mute">{ctl.query ? 'no matches' : `no recommendations for ${activeLabel} — upload this cadence's data or lower priority filter`}</td></tr>}
                  </tbody>
                </table>
              </div>
              <Pagination ctl={ctl} />
            </div>

            {/* playbook reference for the selected cadence — table list (was a card grid) */}
            <div className="card">
              <DataTable title={`${activeLabel} · playbook · ${data.playbook.length} strategies`}
                columns={[
                  { key: 'strategy', label: 'Strategy', render: p => <span className="text-slate-200 whitespace-nowrap">{p.strategy}</span> },
                  { key: 'status', label: 'Status',
                    render: p => <span className={`tag ${STATUS[p.status] || 'border border-edge text-mute'}`}>{p.status}</span> },
                  { key: 'criteria', label: 'Criteria', cellClass: 'text-mute text-xs',
                    render: p => <span className="inline-block max-w-[280px] truncate align-bottom" title={p.criteria}>{p.criteria}</span> },
                  { key: 'action', label: 'Action', cellClass: 'text-slate-400 text-xs',
                    render: p => <span className="inline-block max-w-[280px] truncate align-bottom" title={p.action}>→ {p.action}</span> },
                  { key: 'tool', label: 'Run in', render: p => <span className="text-cyan text-xs whitespace-nowrap">{TOOL[p.tool] || p.tool}</span> },
                  { key: 'bulk', label: '', render: p => (p.bulk && p.status === 'active') ? (
                      <button onClick={() => downloadBulk(p.strategy)} disabled={dl === p.strategy} aria-busy={dl === p.strategy}
                        className="tag bg-lime/15 text-lime border border-lime/30 hover:bg-lime hover:text-ink text-[10px] whitespace-nowrap">
                        {dl === p.strategy ? 'building…' : <><Icon name="download" size={12} /> bulk</>}
                      </button>) : null },
                ]}
                rows={data.playbook} rowKey={(p, i) => p.strategy || i} scope={`${scope}:${sel}`}
                searchKeys={['strategy', 'status', 'criteria', 'action', 'tool']}
                placeholder="search strategy / criteria / action…" empty="no playbook strategies"
                initial={{ sort: { key: 'status', dir: 'asc' } }} />
            </div>
          </>
        )
      })()}
    </div>
  )
}
