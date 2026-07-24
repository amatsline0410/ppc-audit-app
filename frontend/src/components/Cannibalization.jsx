import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Icon, money, CardSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { Modal, useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

// Cannibalization / Keyword Ownership Detector — two overlap kinds from one
// uploaded bulk: duplicate targets (same keyword+match in 2+ campaigns) and
// cross-product term overlap (same search term selling for 2+ SKUs). The owner
// wins by CVR (tiebreak ACoS); losers get paused + negativeExact — user selects,
// never auto. Coexist rows are informational (grey, unselectable) except
// tier-pair isolation repairs, which carry just the missing sculpting negative.
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')
const pctf = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

const VERDICT_TAG = {
  resolve: ['resolve', 'bg-lime text-ink'],
  coexist: ['coexist', 'border border-edge text-mute'],
  insufficient_data: ['low data', 'border border-edge text-mute'],
}

function candCols(lean = true) {
  return [
    { key: 'sku', label: 'SKU', render: r => r.sku || '—' },
    { key: 'campaign_name', label: 'Campaign', render: r => <span className="text-slate-200">{r.campaign_name}</span> },
    { key: 'slot', label: 'Slot', render: r => r.slot || '—' },
    { key: 'clicks', label: 'Clicks', align: 'right' },
    { key: 'orders', label: 'Orders', align: 'right' },
    { key: 'spend', label: 'Spend', align: 'right', render: r => money(r.spend) },
    { key: 'cvr', label: 'CVR', align: 'right', value: r => (r.cvr == null ? null : r.cvr * 100), render: r => pctf(r.cvr) },
    { key: 'acos', label: 'ACoS', align: 'right', value: r => (r.acos == null ? null : r.acos * 100), render: r => pctf(r.acos) },
  ]
}

export function CannibalizationPanel({ scope, targetAcos }) {
  const toast = useToast()
  const { confirm } = useModals()
  const ref = useRef()
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dl, setDl] = useState(false)
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState(() => new Set())
  const [drill, setDrill] = useState(null)     // finding being drilled into

  function seed(d) {
    setData(d)
    setSel(new Set((d?.findings || []).filter(f => f.selected && f.actions?.length).map(f => f.id)))
  }
  function load() { api.cannibalFindings().then(seed).catch(() => setData(null)) }
  useEffect(() => { setData(null); setErr(null); load() }, [scope])  // eslint-disable-line

  async function upload(file) {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      await api.cannibalRun(file, targetAcos)
      load()
      toast.success('Cannibalization scan complete')
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear cannibalization scan?', danger: true, confirmLabel: 'Clear scan',
      message: 'Removes the stored findings for this audit (its own table — nothing else is affected).'
        + '\n\nThis cannot be undone — re-upload the bulk to re-scan.',
    })
    if (!ok) return
    try {
      await api.cannibalClear()
      setSel(new Set()); setErr(null)
      toast.success('Cleared cannibalization scan')
      load()
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  function toggle(key) {
    setSel(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })
  }
  function setMany(keys, on) {
    const actionable = new Set((data?.findings || []).filter(f => f.actions?.length).map(f => f.id))
    setSel(s => { const n = new Set(s); keys.forEach(k => { if (actionable.has(k)) on ? n.add(k) : n.delete(k) }); return n })
  }

  async function download() {
    const chosen = (data?.findings || []).filter(f => sel.has(f.id) && f.actions?.length)
    if (!chosen.length) { setErr('Nothing selected — tick at least one resolvable finding.'); return }
    setDl(true); setErr(null)
    try {
      const blob = await api.cannibalBulk(chosen)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'cannibalization_bulk.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success(`Cannibalization bulk downloaded · ${chosen.length} findings`)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setDl(false) }
  }

  const s = data?.summary
  const rows = data?.findings || []
  const dup = rows.filter(f => f.kind === 'duplicate_target')
  const cross = rows.filter(f => f.kind === 'cross_product')

  const cols = [
    { key: 'term', label: 'Term / target', render: r => <span className="text-slate-200">{r.term}{r.match_type ? <span className="text-mute"> · {r.match_type}</span> : ''}</span> },
    { key: 'candidates_n', label: 'Candidates', align: 'right', value: r => r.candidates.length,
      render: r => (
        <button onClick={() => setDrill(r)} className="tag border border-edge text-lime hover:bg-lime hover:text-ink">
          {r.candidates.length} ▤
        </button>
      ) },
    { key: 'owner', label: 'Owner', value: r => r.owner_sku || '',
      render: r => r.owner_sku
        ? <span className="tag bg-up/10 text-up border border-up/40">{r.owner_sku}</span>
        : <span className="text-mute">—</span> },
    { key: 'verdict', label: 'Verdict', render: r => {
        const [label, cls] = VERDICT_TAG[r.verdict] || [r.verdict, 'border border-edge text-mute']
        return <span className={`tag ${cls}`}>{label}{r.tier_pair ? ' · tier' : ''}</span>
      } },
    { key: 'actions_n', label: 'Actions', align: 'right', value: r => r.actions.length,
      render: r => r.actions.length
        ? <span>{r.actions.length}</span>
        : <span className="text-mute">—</span> },
    { key: 'loser_spend', label: 'Overlap $', align: 'right',
      value: r => r.candidates.filter(c => c.campaign_id !== r.owner_campaign_id).reduce((a, c) => a + (c.spend || 0), 0),
      render: r => {
        const v = r.candidates.filter(c => c.campaign_id !== r.owner_campaign_id).reduce((a, c) => a + (c.spend || 0), 0)
        return r.verdict === 'resolve' ? <span className="text-down">{money(v)}</span> : <span className="text-mute">—</span>
      } },
  ]

  return (
    <div className="space-y-6">
      <div className="card">
        <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">cannibalization · keyword ownership detector</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload the FULL Sponsored Products bulk (with the SP Search Term Report). Duplicate targets + cross-product
              term overlap — the best converter owns the term, losers get paused/negated (you pick, nothing is automatic).
            </div>
            {data?.upload_meta && (
              <div className="font-mono text-xs text-mute mt-1 flex gap-3 flex-wrap">
                <span><Icon name="description" size={11} className="align-[-1px]" /> {data.upload_meta.file} · {data.upload_meta.rows} findings</span>
                <span>updated {data.upload_meta.uploaded}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => ref.current?.click()} disabled={busy} aria-busy={busy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name={busy ? 'sync' : 'upload'} size={14} />{busy ? 'Scanning…' : 'Upload Sponsored Products Bulk'}
            </button>
            {rows.length > 0 && (
              <button onClick={download} disabled={dl || sel.size === 0} aria-busy={dl}
                className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
                <Icon name="download" size={14} />{dl ? 'Building…' : `Download bulk (${sel.size})`}
              </button>
            )}
            {rows.length > 0 && (
              <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
                <Icon name="delete" size={14} /> Clear
              </button>
            )}
            <input ref={ref} type="file" accept=".xlsx,.xlsm" className="hidden" onChange={e => upload(e.target.files?.[0])} />
          </div>
        </div>

        {err && <div className="mx-4 mt-4 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}

        {busy && !data && <div className="p-4"><CardSkeleton lines={6} /></div>}

        {!busy && rows.length === 0 && (
          <div className="p-8 text-center">
            <div className="font-mono text-sm text-slate-200">No cannibalization scan yet</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload your Sponsored Products bulk above. The detector finds the same keyword duplicated across campaigns
              and the same customer search term selling for multiple SKUs, then picks the rightful owner by CVR.
            </div>
          </div>
        )}

        {rows.length > 0 && (
          <div className="p-4 space-y-5">
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
              <Mini label="Findings" value={s.findings} />
              <Mini label="Duplicates" value={s.duplicates} />
              <Mini label="Cross-product" value={s.cross_product} />
              <Mini label="Resolvable" value={s.resolvable} lime />
              <Mini label="Coexist" value={s.coexist} />
              <Mini label="Overlap spend" value={money(s.overlap_spend)} warn={s.overlap_spend > 0} />
            </div>

            <DataTable title={`Type 1 · duplicate targets · ${dup.length}`} columns={cols} rows={dup}
              rowKey={r => r.id} selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
              scope={scope} initial={{ sort: { key: 'loser_spend', dir: 'desc' } }}
              empty="No duplicate targets — every keyword/target lives in one campaign."
              placeholder="search term / owner…" />

            <DataTable title={`Type 2 · cross-product term overlap · ${cross.length}`} columns={cols} rows={cross}
              rowKey={r => r.id} selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
              scope={scope} initial={{ sort: { key: 'loser_spend', dir: 'desc' } }}
              empty="No cross-product overlap (needs the SP Search Term Report sheet in the upload)."
              placeholder="search term / owner…" />
          </div>
        )}
      </div>

      {drill && (
        <Modal open title={`“${drill.term}”`} subtitle={`${drill.kind === 'duplicate_target' ? 'duplicate target' : 'cross-product overlap'} · verdict: ${drill.verdict}${drill.owner_sku ? ` · owner ${drill.owner_sku}` : ''}`}
          size="2xl" onClose={() => setDrill(null)}>
          <div className="space-y-3">
            <DataTable title={`candidates · ${drill.candidates.length}`} columns={candCols()} rows={drill.candidates}
              rowKey={(r, i) => `${r.campaign_id}:${i}`} lean leanRows={20} empty="no candidates" />
            {drill.actions?.length > 0 && (
              <div className="font-mono text-xs text-mute">
                <div className="text-[10px] uppercase tracking-wider mb-1">planned actions</div>
                <ul className="space-y-0.5">
                  {drill.actions.map((a, i) => (
                    <li key={i}>
                      {a.type === 'pause_keyword' && <>pause keyword <span className="text-down">{a.keyword_id}</span> in campaign {a.campaign_id}</>}
                      {a.type === 'pause_pt' && <>pause product target <span className="text-down">{a.product_targeting_id}</span> in campaign {a.campaign_id}</>}
                      {a.type === 'campaign_negative' && <>negativeExact “<span className="text-slate-200">{a.term}</span>” in campaign {a.campaign_id}</>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}

function Mini({ label, value, warn, lime }) {
  return (
    <div className="card p-2">
      <div className="text-mute text-[9px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`font-mono text-sm font-bold mt-0.5 ${warn ? 'text-down' : lime ? 'text-lime' : 'text-slate-100'}`}>{value}</div>
    </div>
  )
}
