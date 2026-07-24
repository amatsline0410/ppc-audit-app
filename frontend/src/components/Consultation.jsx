import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Icon, money, pct, CardSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useToast } from './Toast.jsx'
import { useModals } from './Modal.jsx'

// Consultation — the right campaign structure for the ASIN count. One SP bulk
// upload -> tier route (1-5 Waterfall … 1000+ Capital Allocation) -> that
// tier's problem scan with concrete resolutions.
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')

const PROBLEM_META = {
  WASTED_SPEND: ['Wasted spend', 'text-down', 'Spend accrued, zero orders'],
  HIGH_ACOS: ['High ACoS', 'text-amber', 'Over target+20% with enough clicks'],
  RAISE_WINNER: ['Underexposed winner', 'text-up', 'Under target−20%, starved of impressions'],
  OVERBID: ['Overbid', 'text-cyan', 'Bid far above the actual CPC'],
  MIXED_AD_GROUP: ['Mixed ad group', 'text-amber', 'More than one ASIN in an ad group'],
  HARVEST_CANDIDATE: ['Harvest candidate', 'text-lime', 'Search term earning promotion'],
}
const ORDER = ['WASTED_SPEND', 'HIGH_ACOS', 'OVERBID', 'MIXED_AD_GROUP', 'RAISE_WINNER', 'HARVEST_CANDIDATE']

const pcols = [
  { key: 'target', label: 'Target / term', cellClass: 'max-w-[280px] truncate' },
  { key: 'campaign_id', label: 'Campaign ID', cellClass: 'font-mono text-[10px] text-mute' },
  { key: 'clicks', label: 'Clicks', align: 'right' },
  { key: 'spend', label: 'Spend', align: 'right', render: r => r.spend != null ? money(r.spend) : '—' },
  { key: 'sales', label: 'Sales', align: 'right', render: r => r.sales != null ? money(r.sales) : '—' },
  { key: 'acos', label: 'ACoS', align: 'right', render: r => r.acos != null ? pct(r.acos) : '—' },
  { key: 'resolution', label: 'Resolution', cellClass: 'max-w-[360px] whitespace-normal' },
]

export function ConsultationPanel({ scope, targetAcos }) {
  const toast = useToast()
  const { confirm } = useModals()
  const ref = useRef(null)
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    setLoading(true); setErr(null)
    api.consultRun().then(r => { setRun(r); setLoading(false) })
      .catch(() => { setRun(null); setLoading(false) })
  }, [scope])

  async function upload(file) {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      const r = await api.consultUpload(file, targetAcos)
      setRun(r)
      toast.success(`Consultation ready — Tier ${r.tier.tier} · ${r.total_problems} problems found`)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear consultation?', danger: true, confirmLabel: 'Clear data',
      message: 'Removes the stored consultation result. Nothing else is affected — re-upload the bulk to rebuild.',
    })
    if (!ok) return
    try { await api.consultClear(); setRun(null); toast.success('Consultation cleared') }
    catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  const t = run?.tier
  return (
    <div className="space-y-6">
      <div className="card">
        <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">tier recommendations · right structure for your asin count</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload your Sponsored Products bulk — it counts advertised ASINs, routes the account to its
              structure tier and scans the bulk with that tier's rules (problems + resolutions).
            </div>
            {run?.upload_meta && (
              <div className="font-mono text-[10px] text-mute mt-1 flex gap-3">
                <span><Icon name="description" size={11} className="align-[-1px]" /> {run.upload_meta.file} · {run.upload_meta.rows} campaigns</span>
                <span>updated {run.upload_meta.uploaded}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => ref.current?.click()} disabled={busy} aria-busy={busy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name={busy ? 'sync' : 'upload'} size={14} />{busy ? 'Analyzing…' : 'Upload Sponsored Products Bulk'}
            </button>
            {run && (
              <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
                <Icon name="delete" size={14} /> Clear
              </button>
            )}
            <input ref={ref} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
              onChange={e => upload(e.target.files?.[0])} />
          </div>
        </div>

        {err && <div className="m-4 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
        {loading && <div className="p-4"><CardSkeleton lines={4} /></div>}
        {!loading && !run && !busy && (
          <div className="p-8 text-center">
            <div className="font-mono text-sm text-slate-200 font-bold">No tier recommendation yet</div>
            <div className="font-mono text-xs text-mute mt-2 max-w-xl mx-auto">
              Goal: the right campaign structure, based on your number of ASINs. Upload one Sponsored
              Products bulk export above — the tool detects problems and gives resolutions, tuned to
              your account's size tier.
            </div>
          </div>
        )}

        {t && (
          <div className="p-4 space-y-4">
            {/* tier card */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div>
                <div className="font-mono text-lg font-bold text-primary">Tier {t.tier} · {t.name}</div>
                <div className="font-mono text-xs text-mute">{t.range} · you advertise <span className="text-slate-200 font-bold">{run.asin_count}</span> ASINs in {run.campaigns} campaigns
                  {run.tier_overridden && <span className="text-amber"> · tier manually overridden (auto: Tier {run.auto_tier})</span>}
                </div>
                <div className="font-mono text-xs text-slate-200 mt-2 max-w-2xl">{t.tldr}</div>
              </div>
              <div className="text-right">
                <div className="tag border border-edge text-mute">automation: <span className="text-primary ml-1">{t.automation_mode}</span></div>
                <div className="font-mono text-[10px] text-mute mt-2">
                  min spend ${t.min_spend} · min clicks {t.min_clicks} · min impr {t.min_impr} · bid step {Math.round(t.bid_step * 100)}%
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="card p-3">
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">campaign structure</div>
                <ul className="font-mono text-xs text-slate-200 space-y-1 list-disc pl-4">
                  {t.structure.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
              <div className="card p-3">
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">optimization loop</div>
                <div className="font-mono text-xs text-slate-200">{t.loop}</div>
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider mt-3 mb-1">problems found</div>
                <div className="space-y-0.5">
                  {ORDER.filter(k => run.counts[k]).map(k => (
                    <div key={k} className="font-mono text-xs flex justify-between">
                      <span className={PROBLEM_META[k]?.[1] || ''}>{PROBLEM_META[k]?.[0] || k}</span>
                      <span className="text-slate-200 font-bold">{run.counts[k]}</span>
                    </div>
                  ))}
                  {!run.total_problems && <div className="font-mono text-xs text-up">No problems at this tier's thresholds.</div>}
                  {run.mixed_suppressed > 0 && (
                    <div className="font-mono text-[10px] text-mute mt-1">
                      {run.mixed_suppressed} multi-ASIN ad group{run.mixed_suppressed === 1 ? '' : 's'} — intentional at this tier, not flagged.
                    </div>
                  )}
                </div>
              </div>
              <div className="card p-3">
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">cautions</div>
                <ul className="font-mono text-xs text-amber space-y-1 list-disc pl-4">
                  {t.cautions.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            </div>
            {!run.has_str && (
              <div className="font-mono text-[11px] text-mute">
                <Icon name="info" size={12} className="align-[-2px]" /> No SP Search Term Report sheet in that bulk —
                harvest candidates skipped. Export the bulk with the Search Term Report included to get them.
              </div>
            )}
          </div>
        )}
      </div>

      {/* problems, one table per type */}
      {t && ORDER.filter(k => run.problems[k]?.length).map(k => (
        <div key={k} className="card">
          <div className="p-4 border-b border-edge">
            <div className={`text-[11px] font-mono uppercase tracking-wider ${PROBLEM_META[k]?.[1] || 'text-mute'}`}>
              {PROBLEM_META[k]?.[0] || k} · {run.counts[k]}{run.counts[k] > run.problems[k].length ? ` (showing top ${run.problems[k].length} by spend)` : ''}
            </div>
            <div className="font-mono text-xs text-mute mt-0.5">{PROBLEM_META[k]?.[2]}</div>
          </div>
          <DataTable lean columns={pcols} rows={run.problems[k]}
            rowKey={(r, i) => `${k}:${r.campaign_id}:${r.ad_group_id}:${r.target}:${i}`} />
        </div>
      ))}
    </div>
  )
}
