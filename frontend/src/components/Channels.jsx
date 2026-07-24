import React, { useEffect, useRef, useState } from 'react'
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js'
import { Doughnut } from 'react-chartjs-2'
import { api } from '../api/client.js'
import { Icon, money, CardSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

ChartJS.register(ArcElement, Tooltip, Legend)

// Channels — SP vs SB vs SD side by side from one full bulk workbook upload.
// v1 = audit visibility (channel mix, SB keyword flags, brand-vs-non-brand
// defense ratio, SD dormancy, read-only SB harvest). No SB/SD bulk emission yet.
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')
const pctf = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

const FLAG_CLS = { HIGH_ACOS: 'text-red border-red/40', WASTED_SPEND: 'text-red border-red/40' }

const kwCols = [
  { key: 'keyword', label: 'Keyword', render: r => <span className="text-slate-200">{r.keyword}</span> },
  { key: 'match_type', label: 'Match' },
  { key: 'ad_format', label: 'Ad format', render: r => r.ad_format ? r.ad_format.replace('_', ' ') : '—' },
  { key: 'brand', label: 'Brand', value: r => (r.brand ? 1 : 0),
    render: r => r.brand ? <span className="tag border border-lime/40 text-lime">brand</span> : <span className="text-mute">—</span> },
  { key: 'spend', label: 'Spend', align: 'right', render: r => money(r.spend) },
  { key: 'sales', label: 'Sales', align: 'right', render: r => money(r.sales) },
  { key: 'orders', label: 'Orders', align: 'right' },
  { key: 'acos', label: 'ACoS', align: 'right', value: r => (r.acos == null ? null : r.acos * 100), render: r => pctf(r.acos) },
  { key: 'flag', label: 'Flag', render: r => r.flag
      ? <span className={`tag border ${FLAG_CLS[r.flag] || 'border-edge text-mute'}`}>{r.flag}</span>
      : <span className="text-mute">—</span> },
]

const sdCols = [
  { key: 'expression', label: 'Targeting', render: r => <span className="text-slate-200">{r.expression || '—'}</span> },
  { key: 'kind', label: 'Kind', render: r => (r.kind || '').replace(' targeting', '') },
  { key: 'tactic', label: 'Tactic' },
  { key: 'campaign', label: 'Campaign' },
  { key: 'spend', label: 'Spend', align: 'right', render: r => money(r.spend) },
  { key: 'sales', label: 'Sales', align: 'right', render: r => money(r.sales) },
  { key: 'orders', label: 'Orders', align: 'right' },
  { key: 'acos', label: 'ACoS', align: 'right', value: r => (r.acos == null ? null : r.acos * 100), render: r => pctf(r.acos) },
  { key: 'flag', label: 'Flag', render: r => r.flag
      ? <span className={`tag border ${FLAG_CLS[r.flag] || 'border-edge text-mute'}`}>{r.flag}</span>
      : <span className="text-mute">—</span> },
]

const harvestCols = (kind) => [
  { key: 'search_term', label: 'Search term', render: r => <span className="text-slate-200">{r.search_term}</span> },
  { key: 'campaign_name', label: 'Campaign' },
  { key: 'clicks', label: 'Clicks', align: 'right' },
  { key: 'orders', label: 'Orders', align: 'right' },
  { key: 'spend', label: 'Spend', align: 'right', render: r => money(r.spend) },
  { key: 'acos', label: 'ACoS', align: 'right', value: r => (r.acos == null ? null : r.acos * 100), render: r => pctf(r.acos) },
  { key: 'reason', label: kind === 'promote' ? 'Why promote' : 'Why negate', cellClass: 'text-mute' },
]

export function ChannelsPanel({ scope, targetAcos }) {
  const toast = useToast()
  const { confirm } = useModals()
  const ref = useRef()
  const [sum, setSum] = useState(null)
  const [kws, setKws] = useState([])
  const [sd, setSd] = useState([])
  const [harv, setHarv] = useState(null)
  const [terms, setTerms] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  function load() {
    api.channelsSummary(targetAcos).then(s => {
      setSum(s)
      if (s?.has_data) {
        api.channelsSbKeywords(targetAcos).then(d => setKws(d.rows)).catch(() => {})
        api.channelsSdTargets(targetAcos).then(d => setSd(d.rows)).catch(() => {})
        api.channelsSbHarvest(targetAcos).then(setHarv).catch(() => {})
      }
    }).catch(() => setSum(null))
    api.channelsBrandTerms().then(d => setTerms((d.terms || []).join(', '))).catch(() => {})
  }
  useEffect(() => { setSum(null); setErr(null); load() }, [scope, targetAcos])  // eslint-disable-line

  async function upload(file) {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      const r = await api.channelsUpload(file)
      toast.success(`Channels ingested · SB ${r.sb_rows} rows · SD ${r.sd_rows} rows`)
      load()
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear channel data?', danger: true, confirmLabel: 'Clear data',
      message: 'Removes the uploaded SB / SD / SP channel snapshots for this audit (their own tables — '
        + 'nothing else is affected; brand terms are kept).\n\nThis cannot be undone — re-upload the workbook to rebuild.',
    })
    if (!ok) return
    try {
      await api.channelsClear()
      setErr(null); toast.success('Cleared channel data')
      load()
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  async function saveTerms() {
    try {
      await api.channelsSaveBrandTerms(terms.split(',').map(x => x.trim()).filter(Boolean))
      toast.success('Brand terms saved')
      load()
    } catch (e) { toast.error(cleanErr(e)) }
  }

  const chans = sum?.mix?.channels
  const bs = sum?.brand_split

  return (
    <div className="space-y-6">
      <div className="card">
        <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">channels · sponsored products vs brands vs display</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload the FULL Amazon bulk workbook. SB reads the “SB Multi Ad Group Campaigns” sheet only
              (the legacy sheet duplicates it). v1 is read-only visibility — no SB/SD bulk output.
            </div>
            {sum?.upload_meta && (
              <div className="font-mono text-xs text-mute mt-1 flex gap-3 flex-wrap">
                <span><Icon name="description" size={11} className="align-[-1px]" /> {sum.upload_meta.file} · {sum.upload_meta.rows} SB/SD rows</span>
                <span>updated {sum.upload_meta.uploaded}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => ref.current?.click()} disabled={busy} aria-busy={busy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name={busy ? 'sync' : 'upload'} size={14} />{busy ? 'Reading…' : 'Upload Amazon Bulk Workbook'}
            </button>
            {sum?.has_data && (
              <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
                <Icon name="delete" size={14} /> Clear
              </button>
            )}
          </div>
          <input ref={ref} type="file" accept=".xlsx,.xlsm" className="hidden" onChange={e => upload(e.target.files?.[0])} />
        </div>

        {err && <div className="mx-4 mt-4 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
        {busy && !sum?.has_data && <div className="p-4"><CardSkeleton lines={6} /></div>}

        {!busy && sum && !sum.has_data && (
          <div className="p-8 text-center">
            <div className="font-mono text-sm text-slate-200">No channel data yet</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload the full bulk workbook above — the SB / SD sheets inside it drive the channel mix,
              brand split and keyword tables.
            </div>
          </div>
        )}

        {sum?.has_data && chans && (
          <div className="p-4 space-y-5">
            {sum.sd_dormant && (
              <div className="card border-amber/40 p-2 font-mono text-xs text-amber inline-flex items-center gap-1">
                <Icon name="bedtime" size={12} /> Sponsored Display exists but spent $0 — dormant channel.
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {['SP', 'SB', 'SD'].map(k => {
                const c = chans[k]
                return (
                  <div key={k} className="card p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-mute text-[10px] font-mono uppercase tracking-wider">{k === 'SP' ? 'Sponsored Products' : k === 'SB' ? 'Sponsored Brands' : 'Sponsored Display'}</span>
                      <span className="font-mono text-[10px] text-mute">{c.spend_share != null ? `${Math.round(c.spend_share * 100)}% of spend` : ''}</span>
                    </div>
                    <div className={`font-mono text-xl font-bold mt-1 ${c.acos == null ? 'text-mute' : c.acos > targetAcos ? 'text-down' : 'text-up'}`}>{pctf(c.acos)}</div>
                    <div className="font-mono text-[11px] text-mute mt-1">
                      {money(c.spend)} spend · {money(c.sales)} sales · {c.orders} ord{c.roas != null && <> · {c.roas}× ROAS</>}
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
              <div className="card p-3">
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">
                  brand vs non-brand (SB {bs?.source === 'search_terms' ? 'search terms' : 'keywords'})
                </div>
                {bs?.brand_spend_share != null ? (
                  <>
                    <div className="max-w-[180px] mx-auto">
                      <Doughnut data={{
                        labels: ['Brand (defense)', 'Non-brand (growth)'],
                        datasets: [{
                          data: [bs.brand.spend, bs.nonbrand.spend],
                          backgroundColor: ['#FCD535', '#2b3139'],
                          borderColor: '#1e2329', borderWidth: 2,
                        }],
                      }} options={{ plugins: { legend: { display: false } }, cutout: '65%' }} />
                    </div>
                    <div className="font-mono text-xs text-center mt-2">
                      <span className="text-lime font-bold">{Math.round(bs.brand_spend_share * 100)}%</span>
                      <span className="text-mute"> of SB spend is branded (defense)</span>
                    </div>
                    <div className="font-mono text-[11px] text-mute mt-2 space-y-0.5">
                      <div>brand: {money(bs.brand.spend)} → {money(bs.brand.sales)} ({pctf(bs.brand.acos)})</div>
                      <div>non-brand: {money(bs.nonbrand.spend)} → {money(bs.nonbrand.sales)} ({pctf(bs.nonbrand.acos)})</div>
                    </div>
                  </>
                ) : (
                  <div className="font-mono text-xs text-mute">No SB keyword/term spend to split yet.</div>
                )}
                <div className="mt-3 border-t border-edge pt-2">
                  <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">brand terms (store-wide, comma-separated)</div>
                  <div className="flex gap-1">
                    <input value={terms} onChange={e => setTerms(e.target.value)} placeholder="pro ice, proice"
                      className="bg-panel border border-edge rounded px-2 py-1 font-mono text-xs text-slate-200 flex-1 focus:outline-none focus:border-mute" />
                    <button onClick={saveTerms} className="tag border border-edge text-lime hover:bg-lime hover:text-ink">save</button>
                  </div>
                </div>
              </div>

              <div className="md:col-span-2 space-y-4">
                <DataTable title={`SB keywords · ${kws.length}`} columns={kwCols} rows={kws}
                  rowKey={(r, i) => r.keyword_id || i} scope={scope} lean leanRows={10}
                  initial={{ sort: { key: 'spend', dir: 'desc' } }}
                  empty="No SB keywords in the upload." placeholder="search keyword / campaign…" />
                <DataTable title={`SD targeting · ${sd.length}`} columns={sdCols} rows={sd}
                  rowKey={(r, i) => r.targeting_id || i} scope={scope} lean leanRows={10}
                  initial={{ sort: { key: 'spend', dir: 'desc' } }}
                  empty="No SD targeting rows in the upload." placeholder="search targeting / campaign…" />
              </div>
            </div>

            {harv && (harv.promotes.length > 0 || harv.negates.length > 0) && (
              <div className="space-y-4">
                <div className="font-mono text-[11px] text-mute">
                  SB search-term harvest (read-only — SB bulk output is v2; act on these inside Amazon's SB console)
                </div>
                <DataTable title={`SB harvest · promote candidates · ${harv.promotes.length}`}
                  columns={harvestCols('promote')} rows={harv.promotes}
                  rowKey={(r, i) => `p${i}`} scope={scope} lean leanRows={8}
                  empty="No promote candidates." placeholder="search term…" />
                <DataTable title={`SB harvest · negate candidates · ${harv.negates.length}`}
                  columns={harvestCols('negate')} rows={harv.negates}
                  rowKey={(r, i) => `n${i}`} scope={scope} lean leanRows={8}
                  empty="No negate candidates." placeholder="search term…" />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
