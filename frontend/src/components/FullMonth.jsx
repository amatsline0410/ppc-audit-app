import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Icon, money, CardSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { CompareResult } from './compareView.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { pp, bidKey, hKey, bidCols, harvestCols, withML } from './cadenceCols.jsx'
import { MLInsights } from './MLInsights.jsx'

// Full Month Audit — the Full Month cadence's focus: the FULL optimization pass
// from one SP Search Term Report (single panel). Superset of the focused cadences:
// bid adjustments + harvest promote (winners) + negatives (wasted 0-order) +
// bleeders (converted but ACoS ≥ 2× goal). Tick rows → download one Amazon bulk
// pointing at the exact entity IDs the report carried.
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')

export function FullMonth({ scope, targetAcos, onStage, onUploaded }) {
  const toast = useToast()
  const { confirm } = useModals()
  const ref = useRef()
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dl, setDl] = useState(false)
  const [dlDone, setDlDone] = useState(false)   // funnel: bulk downloaded this scope
  const [err, setErr] = useState(null)
  const [info, setInfo] = useState(null)
  const [sel, setSel] = useState(() => new Set())
  const [cmp, setCmp] = useState(null)
  const [cmpBusy, setCmpBusy] = useState(false)

  function load() {
    api.fullMonthPlan(targetAcos).then(p => {
      setPlan(p)
      // default: bid + promotes + wasted negatives ON; bleeders OFF (they converted)
      setSel(new Set([...p.bid_tweaks.map(bidKey), ...p.promotes.map(hKey), ...p.negates.map(hKey)]))
    }).catch(() => setPlan(null))
  }
  // targetAcos in deps: bid tweaks / promotes / negates / bleeders are all
  // computed against the Goal ACoS — changing it must recompute the plan.
  useEffect(() => { setPlan(null); setCmp(null); setErr(null); setInfo(null); setDlDone(false); load() }, [scope, targetAcos])  // eslint-disable-line

  async function doCompare() {
    setErr(null); setCmp(null); setCmpBusy(true)
    try { setCmp(await api.fullMonthCompare(targetAcos)) }
    catch (e) { setErr(cleanErr(e)) }
    finally { setCmpBusy(false) }
  }

  async function upload(file) {
    if (!file) return
    setBusy(true); setErr(null); setInfo(null); setCmp(null)
    try {
      const s = await api.fullMonthUpload(file)
      setInfo(`Ingested ${s.terms} search terms · ${s.campaigns} campaigns · ${s.ad_groups} ad groups`)
      toast.success(`Uploaded ${s.terms} search terms`)
      load()
      onUploaded?.()   // bump app dataVer so Placement/BidOpt/AsinTree/Harvest/Ngram refetch
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear Full Month data?', danger: true, confirmLabel: 'Clear data',
      message: 'Removes the uploaded Full Month search-term data (current + previous snapshot) AND the '
        + 'bulk-derived audit data behind this cadence — the flag table, Dashboard KPIs and the optimizer '
        + 'panels below (Bid Optimizer, Placement, ASIN tree, Harvest, N-gram). Monitoring, Product Ads, '
        + 'Keywords and the Benchmark are NOT touched.\n\nThis cannot be undone — re-upload the bulk to rebuild.',
    })
    if (!ok) return
    try {
      await api.fullMonthClear()
      setPlan(null); setCmp(null); setSel(new Set()); setErr(null)
      setInfo('Cleared Full Month data.'); toast.success('Cleared Full Month data')
      onUploaded?.()   // bump dataVer so the flag table + optimizer sub-panels refetch (now empty)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  function toggle(key) {
    setSel(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })
  }
  function setMany(keys, on) {
    setSel(s => { const n = new Set(s); keys.forEach(k => on ? n.add(k) : n.delete(k)); return n })
  }

  async function download() {
    if (!plan) return
    const payload = {
      bid_tweaks: plan.bid_tweaks.filter(b => sel.has(bidKey(b))),
      promotes: plan.promotes.filter(h => sel.has(hKey(h))),
      negates: plan.negates.filter(h => sel.has(hKey(h))),
      bleeders: plan.bleeders.filter(h => sel.has(hKey(h))),
    }
    const n = payload.bid_tweaks.length + payload.promotes.length + payload.negates.length + payload.bleeders.length
    if (!n) { setErr('Nothing selected — tick at least one row first.'); return }
    setDl(true); setErr(null)
    try {
      const blob = await api.fullMonthBulk(payload)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'full_month_bulk.xlsx'; a.click()
      URL.revokeObjectURL(url)
      setDlDone(true)
      setInfo(`Downloaded bulk · ${n} row${n === 1 ? '' : 's'}. Re-upload it to Amazon Ads.`)
      toast.success(`Full month bulk downloaded · ${n} row${n === 1 ? '' : 's'}`)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setDl(false) }
  }

  const s = plan?.summary
  const allKeys = plan ? [...plan.bid_tweaks.map(bidKey), ...plan.promotes.map(hKey),
    ...plan.negates.map(hKey), ...plan.bleeders.map(hKey)] : []
  const selCount = allKeys.filter(k => sel.has(k)).length
  const hasRows = plan && allKeys.length > 0
  useEffect(() => { onStage?.({ uploaded: !!plan, hasRows: !!hasRows, downloaded: dlDone }) }, [plan, hasRows, dlDone])  // eslint-disable-line

  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">full month audit · full optimization</div>
          <div className="font-mono text-xs text-mute mt-1">Upload one Sponsored Products bulk (with its SP Search Term Report). The complete pass — bids + harvest + negatives. Sponsored Products only.</div>
          {plan?.upload_meta && (
            <div className="font-mono text-xs text-mute mt-1 flex gap-3 flex-wrap">
              <span><Icon name="description" size={11} className="align-[-1px]" /> {plan.upload_meta.file} · {plan.upload_meta.rows}</span>
              <span>updated {plan.upload_meta.uploaded}</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => ref.current?.click()} disabled={busy} aria-busy={busy}
            className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
            <Icon name={busy ? 'sync' : 'upload'} size={14} />{busy ? 'Reading…' : 'Upload Sponsored Products Bulk'}
          </button>
          {plan?.has_previous && (
            <button onClick={doCompare} disabled={cmpBusy} aria-busy={cmpBusy}
              className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="compare_arrows" size={14} />{cmpBusy ? 'Comparing…' : 'Compare to previous'}
            </button>
          )}
          {hasRows && (
            <button onClick={download} disabled={dl || !selCount} aria-busy={dl}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="download" size={14} />{dl ? 'Building…' : `Download bulk (${selCount})`}
            </button>
          )}
          {plan && (
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          )}
          <input ref={ref} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
            onChange={e => upload(e.target.files?.[0])} />
        </div>
      </div>

      {err && <div className="mx-4 mt-4 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
      {info && <div className="mx-4 mt-4 card border-up/40 p-2 font-mono text-xs text-up inline-flex items-center gap-1"><Icon name="check_circle" size={12} /> {info}</div>}

      {busy && !plan && <div className="p-4"><CardSkeleton lines={6} /></div>}

      {!busy && !plan && (
        <div className="p-8 text-center">
          <div className="font-mono text-sm text-slate-200">No Full Month data yet</div>
          <div className="font-mono text-xs text-mute mt-1">
            Upload your Sponsored Products bulk export above — the SP Search Term Report inside it drives
            the complete optimization (bids + harvest + negatives). Data stays isolated to the Full Month cadence.
          </div>
        </div>
      )}

      {plan && (
        <div className="p-4 space-y-5">
          {s && (
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
              <Mini label="Search Terms" value={s.terms} />
              <Mini label="Campaigns" value={s.campaigns} />
              <Mini label="Ad Spend" value={money(s.spend)} />
              <Mini label="Ad Sales" value={money(s.sales)} />
              <Mini label="ACoS" value={s.acos == null ? '—' : `${s.acos}%`} />
              <Mini label="Goal ACoS" value={pp(plan.target_acos)} />
            </div>
          )}

          <MLInsights ml={plan.ml} />

          <DataTable title={`Bid adjustments · ${plan.bid_tweaks.length}`} columns={withML(bidCols)} rows={plan.bid_tweaks}
            rowKey={bidKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No bid changes — every target's bid is already near optimal." placeholder="search target / reason…" />

          <DataTable title={`Harvest · promote winners → Exact · ${plan.promotes.length}`} columns={withML(harvestCols('promote'))} rows={plan.promotes}
            rowKey={hKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No winning search terms to promote." placeholder="search term / ad group…" />

          <DataTable title={`Negative targeting · wasted spend (0 orders) · ${plan.negates.length}`} columns={withML(harvestCols('negate'))} rows={plan.negates}
            rowKey={hKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No wasted search terms to negate." placeholder="search term / ad group…" />

          <div>
            {plan.bleeders.length > 0 && (
              <div className="font-mono text-[10px] text-down/80 mb-1 inline-flex items-center gap-1"><Icon name="warning" size={12} /> Bleeders DID convert — bid-down first (re-upload), then negate only ones still above break-even. Review before ticking.</div>
            )}
            <DataTable title={`Negative targeting · bleeders (2+ orders, ACoS ≥ 2× goal) · ${plan.bleeders.length}`} columns={withML(harvestCols('bleeder'))} rows={plan.bleeders}
              rowKey={hKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
              scope={scope} empty="No bleeding search terms worth acting on." placeholder="search term / ad group…" />
          </div>
        </div>
      )}

      {cmp && <CompareResult cmp={cmp} heading="Previous upload → Current upload" />}
    </div>
  )
}

function Mini({ label, value }) {
  return (
    <div className="card p-2">
      <div className="text-mute text-[9px] font-mono uppercase tracking-wider">{label}</div>
      <div className="font-mono text-sm font-bold text-slate-100 mt-0.5">{value}</div>
    </div>
  )
}

