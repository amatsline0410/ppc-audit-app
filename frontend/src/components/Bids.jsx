import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { money, pct, Spinner, TableSkeleton, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'
import { useToast } from './Toast.jsx'

function download(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = name; a.click()
  URL.revokeObjectURL(url)
}

// ---- Bid Optimizer: optimal bid for every eligible target (target-CPC) ----
export function BidOptimizerPanel({ scope, targetAcos }) {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(new Set())
  const [filter, setFilter] = useState('ALL')   // ALL | raise | cut
  const [busy, setBusy] = useState(false)
  const [dl, setDl] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (targetAcos == null) return   // wait for the per-audit Goal ACoS to load
    let live = true
    setBusy(true); setErr(null)
    api.bidsOptimize(targetAcos).then(d => {
      if (!live) return
      setData(d); setSel(new Set(d.rows.map(r => r.target_id)))
    }).catch(e => live && setErr(String(e))).finally(() => live && setBusy(false))
    return () => { live = false }
  }, [scope, targetAcos])

  const base = useMemo(() => (data?.rows || []).filter(r => filter === 'ALL' || r.direction === filter), [data, filter])
  const ctl = useTableControls(base, {
    searchKeys: ['label', 'reason', 'direction'], deps: [filter, scope],
  })
  function toggle(id) { const s = new Set(sel); s.has(id) ? s.delete(id) : s.add(id); setSel(s) }

  async function downloadBulk() {
    setDl(true); setErr(null)
    try { download(await api.bidsOptimizeBulk((data.rows).filter(r => sel.has(r.target_id))), 'ppc_bid_optimizer.xlsx'); toast.success(`Bid optimizer bulk downloaded · ${sel.size} target${sel.size === 1 ? '' : 's'}`) }
    catch (e) { setErr(String(e)); toast.error(String(e)) } finally { setDl(false) }
  }

  return (
    <div className="card">
      <div className="p-4 border-b border-edge">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">bid optimizer · target-CPC</div>
        <div className="text-xs text-mute font-mono">
          optimal bid for every eligible target = goal ACoS × revenue-per-click, capped by break-even. select → download Amazon bulk.
        </div>
      </div>

      {busy && <TableSkeleton rows={6} cols={5} toolbar={false} />}
      {err && <div className="m-4 card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      {data && !busy && (
        <>
          <div className="flex items-center justify-between px-4 py-3 border-b border-edge gap-2 flex-wrap">
            <div className="flex gap-1">
              {[['ALL', data.count], ['raise', data.raises], ['cut', data.cuts]].map(([f, n]) => (
                <button key={f} onClick={() => setFilter(f)}
                  className={`tag ${filter === f ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>
                  {f.toUpperCase()} {n}
                </button>
              ))}
            </div>
            <button disabled={sel.size === 0 || dl} onClick={downloadBulk} aria-busy={dl}
              className={`btn ${sel.size ? 'btn-primary' : 'btn-ghost opacity-50'}`}>
              {dl ? 'building…' : <><Icon name="download" size={14} /> bulk file ({sel.size})</>}
            </button>
          </div>
          <TableToolbar ctl={ctl} placeholder="search target / why…" />
          <div className="overflow-auto max-h-[440px]">
            <table className="w-full text-sm font-mono">
              <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
                <tr className="border-b border-edge">
                  <th className="p-2 w-8"></th><Th ctl={ctl} k="label">Target</Th>
                  <Th ctl={ctl} k="clicks" align="right">Clicks</Th><Th ctl={ctl} k="acos" align="right">ACoS</Th>
                  <Th ctl={ctl} k="break_even_acos" align="right">BE ACoS</Th>
                  <Th ctl={ctl} k="current_bid" align="right">Bid</Th><Th ctl={ctl} k="suggested_bid" align="right">→ New</Th>
                  <Th ctl={ctl} k="delta" align="right">Δ</Th><Th ctl={ctl} k="reason">Why</Th>
                </tr>
              </thead>
              <tbody>
                {ctl.view.map((r, i) => (
                  <tr key={i} className="border-b border-edge/50 hover:bg-edge/30">
                    <td className="p-2"><input type="checkbox" checked={sel.has(r.target_id)} onChange={() => toggle(r.target_id)} className="accent-lime" /></td>
                    <td className="p-2 max-w-[200px] truncate text-slate-200" title={r.label}>{r.label}</td>
                    <td className="p-2 text-right text-mute">{r.clicks}</td>
                    <td className={`p-2 text-right ${r.break_even_acos != null && r.acos != null ? (r.acos > r.break_even_acos ? 'text-down' : 'text-up') : 'text-slate-300'}`}
                      title={r.break_even_acos != null ? `break-even ${(r.break_even_acos * 100).toFixed(1)}% — red = losing money per ad sale` : ''}>{pct(r.acos)}</td>
                    <td className="p-2 text-right text-mute"
                      title="the product's break-even ACoS (benchmark upload wins, else catalog price + per-SKU COGS + real Transactions-ledger fees) — the suggested bid is capped so the implied ACoS never exceeds it">
                      {r.break_even_acos != null ? pct(r.break_even_acos) : '—'}</td>
                    <td className="p-2 text-right text-mute">${r.current_bid}</td>
                    <td className={`p-2 text-right font-bold ${r.direction === 'raise' ? 'text-lime' : 'text-cyan'}`}>${r.suggested_bid}</td>
                    <td className={`p-2 text-right ${r.delta >= 0 ? 'text-lime' : 'text-red'}`}>{r.delta >= 0 ? '+' : ''}{r.delta}</td>
                    <td className="p-2 text-mute text-xs max-w-[220px] truncate" title={r.reason}>{r.reason}</td>
                  </tr>
                ))}
                {ctl.view.length === 0 && <tr><td colSpan="9" className="p-6 text-center text-mute">{ctl.query ? 'no matches' : 'no bid changes — upload a bulk file or loosen the goal'}</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination ctl={ctl} />
        </>
      )}
    </div>
  )
}

// ---- Placement optimizer (Top of Search / Product pages / Rest) ----
const FLAG_TAG = {
  FLAT_MODIFIER: ['flat %', 'text-amber border-amber/40'],
  PLACEMENT_BLEED: ['bleed', 'text-red border-red/40'],
  TOS_STARVED: ['tos starved', 'text-cyan border-cyan/40'],
  BASE_BID_FIX: ['base bids', 'text-red border-red/40'],
  OVER_BREAK_EVEN: ['over BE', 'text-red border-red/40'],
}

export function PlacementPanel({ scope, targetAcos }) {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(new Set())
  const [selComp, setSelComp] = useState(new Set())
  const [busy, setBusy] = useState(false)
  const [dl, setDl] = useState(false)
  const [err, setErr] = useState(null)

  const pkey = (r) => `${r.campaign_id}|${r.placement}`

  useEffect(() => {
    if (targetAcos == null) return   // wait for the per-audit Goal ACoS to load
    let live = true
    setBusy(true); setErr(null)
    api.placements(targetAcos).then(d => {
      if (!live) return
      setData(d)
      setSel(new Set(d.rows.filter(r => Math.abs(r.delta) >= 1).map(pkey)))
      setSelComp(new Set())    // companions are opt-in (they change base bids)
    }).catch(e => live && setErr(String(e))).finally(() => live && setBusy(false))
    return () => { live = false }
  }, [scope, targetAcos])

  const ctl = useTableControls(data?.rows || [], {
    searchKeys: ['campaign_name', 'campaign_id', 'placement', 'reason'],
    accessors: { campaign: r => r.campaign_name || r.campaign_id }, deps: [scope, targetAcos],
  })
  function toggle(k) { const s = new Set(sel); s.has(k) ? s.delete(k) : s.add(k); setSel(s) }
  function toggleComp(k) { const s = new Set(selComp); s.has(k) ? s.delete(k) : s.add(k); setSelComp(s) }
  async function downloadBulk() {
    setDl(true); setErr(null)
    try {
      const rows = (data.rows).filter(r => sel.has(pkey(r)) && Math.abs(r.delta) >= 1)
      const comps = (data.companions || []).filter(c => selComp.has(c.target_id))
      download(await api.placementsBulk(rows, comps), 'ppc_placements.xlsx')
      toast.success(`Placement bulk downloaded · ${rows.length + comps.length} row${rows.length + comps.length === 1 ? '' : 's'}`)
    }
    catch (e) { setErr(String(e)); toast.error(String(e)) } finally { setDl(false) }
  }

  return (
    <div className="card">
      <div className="p-4 border-b border-edge">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">placement optimizer</div>
        <div className="text-xs text-mute font-mono">where your spend converts — Top of Search vs Product pages vs Rest. recommends bid % per placement.</div>
      </div>

      {busy && <TableSkeleton rows={5} cols={4} toolbar={false} />}
      {err && <div className="m-4 card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      {data && !busy && !data.has_data && (
        <div className="p-5 font-mono text-sm text-mute">no placement data in this bulk file.</div>
      )}

      {data && data.has_data && (
        <>
          <div className="px-4 py-3 grid grid-cols-2 md:grid-cols-4 gap-3 border-b border-edge">
            {data.summary.map((p, i) => (
              <div key={i} className="card p-2">
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{p.placement}</div>
                <div className={`font-mono font-bold ${p.acos != null && p.acos > targetAcos ? 'text-red' : 'text-lime'}`}>{pct(p.acos)}</div>
                <div className="text-[10px] font-mono text-mute">
                  {money(p.spend)} · {p.orders} ord{p.share_of_spend != null && <> · {Math.round(p.share_of_spend * 100)}% of spend</>}
                </div>
                <div className="text-[10px] font-mono text-mute">
                  cvr {p.cvr != null ? `${(p.cvr * 100).toFixed(1)}%` : '—'} · cpc {p.cpc != null ? `$${p.cpc.toFixed(2)}` : '—'}
                </div>
              </div>
            ))}
          </div>

          {data.campaign_flags?.length > 0 && (
            <div className="px-4 py-2 border-b border-edge font-mono text-[11px] text-mute flex flex-wrap gap-2 items-center">
              <span className="uppercase tracking-wider text-[10px]">placement diseases:</span>
              {['FLAT_MODIFIER', 'PLACEMENT_BLEED', 'TOS_STARVED'].map(fl => {
                const n = data.campaign_flags.filter(c => c.flags.includes(fl)).length
                if (!n) return null
                const [label, cls] = FLAG_TAG[fl]
                return <span key={fl} className={`tag border ${cls}`}>{label} × {n}</span>
              })}
            </div>
          )}

          <div className="flex items-center justify-between px-4 py-2 border-b border-edge">
            <span className="font-mono text-xs text-mute">{data.count} row(s)</span>
            <button disabled={(sel.size === 0 && selComp.size === 0) || dl} onClick={downloadBulk} aria-busy={dl}
              className={`btn ${(sel.size || selComp.size) ? 'btn-primary' : 'btn-ghost opacity-50'}`}>{dl ? 'building…' : <><Icon name="download" size={14} /> bulk file ({sel.size + selComp.size})</>}</button>
          </div>
          <TableToolbar ctl={ctl} placeholder="search campaign / placement / why…" />
          <div className="overflow-auto max-h-[360px]">
            <table className="w-full text-sm font-mono">
              <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
                <tr className="border-b border-edge">
                  <th className="p-2 w-8"></th><Th ctl={ctl} k="campaign">Campaign</Th>
                  <Th ctl={ctl} k="placement">Placement</Th><Th ctl={ctl} k="spend" align="right">Spend</Th>
                  <Th ctl={ctl} k="acos" align="right">ACoS</Th>
                  <Th ctl={ctl} k="break_even_acos" align="right">BE ACoS</Th>
                  <Th ctl={ctl} k="current_pct" align="right">%</Th><Th ctl={ctl} k="suggested_pct" align="right">→ New %</Th>
                  <th className="p-2 text-left">Flags</th><Th ctl={ctl} k="reason">Why</Th>
                </tr>
              </thead>
              <tbody>
                {ctl.view.map((r) => {
                  const changed = Math.abs(r.delta) >= 1
                  return (
                    <tr key={pkey(r)} className="border-b border-edge/50 hover:bg-edge/30">
                      <td className="p-2">{changed && <input type="checkbox" checked={sel.has(pkey(r))} onChange={() => toggle(pkey(r))} className="accent-lime" />}</td>
                      <td className="p-2 max-w-[180px] truncate text-slate-200" title={r.campaign_name}>{r.campaign_name || r.campaign_id}</td>
                      <td className="p-2 text-slate-300">{r.placement}</td>
                      <td className="p-2 text-right text-mute">{money(r.spend)}</td>
                      <td className={`p-2 text-right ${r.break_even_acos != null && r.acos != null ? (r.acos > r.break_even_acos ? 'text-down' : 'text-up') : 'text-slate-300'}`}
                        title={r.break_even_acos != null ? `break-even ${(r.break_even_acos * 100).toFixed(1)}% — red = this placement loses money per ad sale` : ''}>{pct(r.acos)}</td>
                      <td className="p-2 text-right text-mute"
                        title="the campaign's product break-even ACoS (benchmark upload wins, else catalog price + per-SKU COGS + real Transactions-ledger fees)">
                        {r.break_even_acos != null ? pct(r.break_even_acos) : '—'}</td>
                      <td className="p-2 text-right text-mute">{r.current_pct}%</td>
                      <td className={`p-2 text-right font-bold ${!changed ? 'text-mute' : r.delta >= 0 ? 'text-lime' : 'text-cyan'}`}>{changed ? `${r.suggested_pct}%` : '—'}</td>
                      <td className="p-2">
                        {(r.flags || []).map(fl => {
                          const [label, cls] = FLAG_TAG[fl] || [fl, 'text-mute border-edge']
                          return <span key={fl} className={`tag border ${cls} mr-1`}>{label}</span>
                        })}
                      </td>
                      <td className="p-2 text-mute text-xs max-w-[200px] truncate" title={r.reason}>{r.reason}</td>
                    </tr>
                  )
                })}
                {ctl.view.length === 0 && <tr><td colSpan="10" className="p-6 text-center text-mute">no matches</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination ctl={ctl} />

          {data.companions?.length > 0 && (
            <div className="border-t border-edge">
              <div className="px-4 py-2 font-mono text-[11px] text-mute">
                <span className="tag border text-red border-red/40 mr-2">base bids</span>
                product page bleeds at +0% — the modifier can't go lower, so cut the campaign's BASE bids
                (safe cut, never raises). Opt-in: tick the ones to include in the bulk.
              </div>
              <div className="overflow-auto max-h-[260px]">
                <table className="w-full text-sm font-mono">
                  <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
                    <tr className="border-b border-edge">
                      <th className="p-2 w-8"></th><th className="p-2 text-left">Target</th>
                      <th className="p-2 text-left">Campaign</th><th className="p-2 text-right">ACoS</th>
                      <th className="p-2 text-right">Bid</th><th className="p-2 text-right">→ New</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.companions.map(c => (
                      <tr key={c.target_id} className="border-b border-edge/50 hover:bg-edge/30">
                        <td className="p-2"><input type="checkbox" checked={selComp.has(c.target_id)} onChange={() => toggleComp(c.target_id)} className="accent-lime" /></td>
                        <td className="p-2 max-w-[200px] truncate text-slate-200" title={c.label}>{c.label}</td>
                        <td className="p-2 max-w-[160px] truncate text-mute" title={c.campaign_name}>{c.campaign_name || c.campaign_id}</td>
                        <td className="p-2 text-right text-slate-300">{pct(c.acos)}</td>
                        <td className="p-2 text-right text-mute">${c.current_bid}</td>
                        <td className="p-2 text-right font-bold text-cyan">${c.suggested_bid}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
