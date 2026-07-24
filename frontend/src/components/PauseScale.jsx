import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Icon, money, CardSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { pp, bidKey as tKey, cKey, scaleCols, pauseCols, campaignCols, withML } from './cadenceCols.jsx'
import { MLInsights } from './MLInsights.jsx'

// Pause/Scale Audit — the Pause/Scale cadence's focus: last-60-day cut/scale
// decisions on the EXISTING entities in one SP Search Term Report (single panel).
// Scale proven winners (bid up), pause dead targets (30+ clicks, 0 orders) and
// dead campaigns ($50+ spend, 0 orders) → download an Amazon bulk by exact ID.
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')

export function PauseScale({ scope, targetAcos, onStage, onUploaded }) {
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

  function load() {
    api.pauseScalePlan(targetAcos).then(p => {
      setPlan(p)
      // default: scale winners + pause dead targets ON; pause-CAMPAIGN OFF (most destructive)
      setSel(new Set([...p.scales.map(tKey), ...p.pauses.map(tKey)]))
    }).catch(() => setPlan(null))
  }
  // targetAcos in deps: scale/pause verdicts hang off the Goal ACoS — recompute on change
  useEffect(() => { setPlan(null); setErr(null); setInfo(null); setDlDone(false); load() }, [scope, targetAcos])  // eslint-disable-line

  async function upload(file) {
    if (!file) return
    setBusy(true); setErr(null); setInfo(null)
    try {
      const s = await api.pauseScaleUpload(file)
      setInfo(`Ingested ${s.terms} search terms · ${s.campaigns} campaigns · ${s.ad_groups} ad groups`)
      toast.success(`Uploaded ${s.terms} search terms`)
      load()
      onUploaded?.()   // bump app dataVer so Placement/BidOpt/AsinTree/Harvest/Ngram refetch
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear Pause/Scale data?', danger: true, confirmLabel: 'Clear data',
      message: 'Removes the uploaded Pause/Scale search-term data AND the bulk-derived data behind this '
        + 'cadence\'s optimizer panels below (Bid Optimizer, Placement, ASIN tree, Harvest, N-gram).'
        + '\n\nThis cannot be undone — re-upload the bulk to rebuild.',
    })
    if (!ok) return
    try {
      await api.pauseScaleClear()
      setPlan(null); setSel(new Set()); setErr(null)
      setInfo('Cleared Pause/Scale data.'); toast.success('Cleared Pause/Scale data')
      onUploaded?.()   // bump dataVer so the optimizer sub-panels refetch (now empty)
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
      scales: plan.scales.filter(r => sel.has(tKey(r))),
      pauses: plan.pauses.filter(r => sel.has(tKey(r))),
      campaign_pauses: plan.campaign_pauses.filter(c => sel.has(cKey(c))),
    }
    const n = payload.scales.length + payload.pauses.length + payload.campaign_pauses.length
    if (!n) { setErr('Nothing selected — tick at least one scale or pause row first.'); return }
    setDl(true); setErr(null)
    try {
      const blob = await api.pauseScaleBulk(payload)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'pause_scale_bulk.xlsx'; a.click()
      URL.revokeObjectURL(url)
      setDlDone(true)
      setInfo(`Downloaded bulk · ${n} row${n === 1 ? '' : 's'}. Re-upload it to Amazon Ads.`)
      toast.success(`Pause/scale bulk downloaded · ${n} row${n === 1 ? '' : 's'}`)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setDl(false) }
  }

  const s = plan?.summary
  const allKeys = plan ? [...plan.scales.map(tKey), ...plan.pauses.map(tKey), ...plan.campaign_pauses.map(cKey)] : []
  const selCount = allKeys.filter(k => sel.has(k)).length
  const hasRows = plan && allKeys.length > 0
  useEffect(() => { onStage?.({ uploaded: !!plan, hasRows: !!hasRows, downloaded: dlDone }) }, [plan, hasRows, dlDone])  // eslint-disable-line

  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">pause / scale audit · last 60 days</div>
          <div className="font-mono text-xs text-mute mt-1">Upload one Sponsored Products bulk (with its SP Search Term Report). Cut bleeders, scale winners. Sponsored Products only.</div>
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
          <div className="font-mono text-sm text-slate-200">No Pause/Scale data yet</div>
          <div className="font-mono text-xs text-mute mt-1">
            Upload your Sponsored Products bulk export above — the SP Search Term Report inside it drives the
            cut/scale plan (pause dead targets & campaigns, scale winners). Data stays isolated to this cadence.
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

          <DataTable title={`Scale winners → bid up · ${plan.scales.length}`} columns={withML(scaleCols)} rows={plan.scales}
            rowKey={tKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No winners hit the scale bar (10+ orders at/under goal) yet." placeholder="search target…" />

          <DataTable title={`Pause dead targets (30+ clicks, 0 orders) · ${plan.pauses.length}`} columns={withML(pauseCols)} rows={plan.pauses}
            rowKey={tKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No dead targets — nothing burned 30+ clicks with 0 orders." placeholder="search target…" />

          <div>
            {plan.campaign_pauses.length > 0 && (
              <div className="font-mono text-[10px] text-down/80 mb-1 inline-flex items-center gap-1"><Icon name="warning" size={12} /> Pauses the WHOLE campaign — not pre-selected. Review before ticking.</div>
            )}
            <DataTable title={`Pause dead campaigns ($50+ spend, 0 orders) · ${plan.campaign_pauses.length}`} columns={campaignCols} rows={plan.campaign_pauses}
              rowKey={cKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
              scope={scope} empty="No dead campaigns — none spent $50+ with 0 orders." placeholder="search campaign…" />
          </div>
        </div>
      )}
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

