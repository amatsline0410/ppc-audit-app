import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, money, pct, TemplateLink, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'
import { useToast } from './Toast.jsx'

const candKey = c => `${c.action}:${c.campaign_id}:${c.ad_group_id}:${c.search_term}`
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')

// SP BULK file (with its embedded "SP Search Term Report" sheet) -> promote /
// negate candidates carrying the report's REAL Campaign/Ad Group/Keyword/PT IDs
// -> downloadable bulk that acts by exact ID (Weekly engine). Dropping a
// standalone STR still works as a fallback — that path maps to the loaded
// account by campaign + ad-group NAME (the old flow).
// cands/onCands optional: when provided, candidates are lifted to the parent so
// they survive tab switches and are shared across panel instances.
export function HarvestPanel({ targetAcos, cands: candsProp, onCands, fromBulk, onNgram }) {
  const toast = useToast()
  const inputRef = useRef()
  const [drag, setDrag] = useState(false)
  const [name, setName] = useState(null)
  const [candsLocal, setCandsLocal] = useState(null)
  const cands = onCands ? candsProp : candsLocal
  const setCands = onCands || setCandsLocal
  const [mode, setMode] = useState('legacy')      // bulk (exact IDs) | legacy (name-mapped)
  const [selected, setSelected] = useState(new Set())
  const [filter, setFilter] = useState('ALL')     // ALL | promote | negate
  const [busy, setBusy] = useState(false)
  const [building, setBuilding] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState(null)

  // keep selection in sync with whatever candidates are present (default: all)
  useEffect(() => {
    if (cands && cands.length) setSelected(new Set(cands.map(candKey)))
  }, [cands])

  async function run(file) {
    if (!file) return
    setName(file.name); setErr(null); setNote(null); setBusy(true); setCands(null)
    // ONE upload powers both tools: the same file also runs the N-gram miner
    // below, scoped to the same keyword project's ASINs (fire-and-forget —
    // a failure there never blocks the harvest)
    onNgram?.(null)
    if (onNgram) {
      const pid0 = Number(api.kwProject.get()) || undefined
      api.ngrams(file, { targetAcos, projectId: pid0 }).then(onNgram).catch(() => {})
    }
    try {
      // preferred: the bulk file's embedded STR sheet (real entity IDs).
      // Scoped to the shared keyword project's ASIN(s) when one is picked.
      const pid = Number(api.kwProject.get()) || undefined
      const r = await api.harvestFromBulk(file, { targetAcos, projectId: pid })
      setMode('bulk')
      setCands([...(r.promotes || []), ...(r.negates || [])])
      const bits = [`Read the bulk's SP Search Term Report — ${r.summary?.terms ?? '?'} terms, real entity IDs (bulk acts by ID).`]
      if (r.asin_terms_hidden > 0) bits.push(`${r.asin_terms_hidden} ASIN search term${r.asin_terms_hidden === 1 ? '' : 's'} hidden (keywords only).`)
      if (r.scope) {
        bits.push(r.scope.note
          ? r.scope.note
          : `Scoped to project ASIN${r.scope.asins.length === 1 ? '' : 's'} ${r.scope.asins.join(', ')} — ${r.scope.hidden} term${r.scope.hidden === 1 ? '' : 's'} from other ASINs hidden.`)
      }
      setNote(bits.join(' '))
    } catch (e1) {
      // fallback: a standalone STR (no IDs) — old name-mapping flow
      try {
        const res = await api.harvest(file, { targetAcos })
        setMode('legacy')
        setCands(res)
        setNote('Standalone Search Term Report (no ID columns) — mapped to the loaded account by campaign + ad-group name. Upload the SP bulk file instead to act by exact ID.')
      } catch {
        setErr(cleanErr(e1))
      }
    } finally { setBusy(false) }
  }

  // merge the selected customer search terms into the shared Listing Optimizer
  // keyword project (picked in the Keywords tab) — SEO indexed % + listing
  // usage then cover them too.
  async function toProject() {
    const pid = Number(api.kwProject.get())
    if (!pid) { toast.error('Pick a keyword project in the Keywords tab first'); return }
    const terms = [...new Set(cands.filter(c => selected.has(candKey(c))).map(c => c.search_term))]
    try {
      const r = await api.trackerAddKeywords(pid, terms.map(t => ({ keyword: t })), 'harvest')
      const seo = (r.seo_before?.indexed != null && r.seo_after?.indexed != null)
        ? ` · indexed ${(r.seo_before.indexed * 100).toFixed(1)}% → ${(r.seo_after.indexed * 100).toFixed(1)}%` : ''
      toast.success(`+${r.added} search terms → “${r.project.name}” · ${r.duplicates} already tracked${seo}`)
    } catch (e) { toast.error(cleanErr(e)) }
  }

  async function download() {
    setBuilding(true); setErr(null)
    try {
      const chosen = cands.filter(c => selected.has(candKey(c)))
      // bulk-mode rows carry real IDs -> weekly-engine bulk; legacy -> name-mapped bulk
      const blob = mode === 'bulk'
        ? await api.harvestFromBulkFile({
            promotes: chosen.filter(c => c.action === 'promote'),
            negates: chosen.filter(c => c.action === 'negate'),
          })
        : await api.harvestBulk(chosen)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'ppc_harvest_bulk.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success(`Harvest bulk downloaded · ${chosen.length} row${chosen.length === 1 ? '' : 's'}`)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBuilding(false) }
  }

  const rows = useMemo(
    () => (cands || []).filter(c => filter === 'ALL' || c.action === filter),
    [cands, filter]
  )
  const ctl = useTableControls(rows, {
    searchKeys: ['search_term', 'ad_group_name', 'campaign_name', 'action'], deps: [filter, cands],
  })
  const counts = useMemo(() => ({
    promote: (cands || []).filter(c => c.action === 'promote').length,
    negate: (cands || []).filter(c => c.action === 'negate').length,
  }), [cands])

  const allSel = rows.length > 0 && rows.every(c => selected.has(candKey(c)))
  function toggle(c) {
    const k = candKey(c); const s = new Set(selected)
    s.has(k) ? s.delete(k) : s.add(k); setSelected(s)
  }
  function toggleAll() {
    const s = new Set(selected)
    if (allSel) rows.forEach(c => s.delete(candKey(c)))
    else rows.forEach(c => s.add(candKey(c)))
    setSelected(s)
  }

  return (
    <div className="card">
      <div className="p-4 border-b border-edge">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">search-term harvest <TemplateLink kind="str" /></div>
        <div className="text-xs text-mute font-mono">
          upload your Sponsored Products <span className="text-slate-200">bulk file</span> (with its SP Search Term Report sheet) →
          winners become Exact keywords, losers become Negative Exact — created/negated by the report's
          <span className="text-slate-200"> real Campaign / Ad Group / Keyword IDs</span>.
          A standalone STR still works (maps by name).
          <span className="text-slate-200"> One upload powers both tools — the same file also runs the N-gram miner below.</span>
        </div>
      </div>

      <div className="p-4">
        <div
          onDragOver={e => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={e => { e.preventDefault(); setDrag(false); run(e.dataTransfer.files[0]) }}
          onClick={() => inputRef.current?.click()}
          className={`card p-5 cursor-pointer text-center transition-colors ${drag ? 'border-lime bg-lime/5' : 'border-dashed'}`}
        >
          <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" hidden
            onChange={e => run(e.target.files[0])} />
          {busy ? <Spinner label="harvesting search terms…" /> : (
            <div className="font-mono text-sm">
              <span className="btn btn-primary text-xs inline-flex items-center gap-1 mb-2 pointer-events-none">
                <Icon name="upload" size={14} /> Upload Sponsored Products Bulk
              </span>
              <div className="text-mute text-xs">{name || `bulk with SP Search Term Report sheet — or drag & drop · goal ACoS ${pct(targetAcos)}`}</div>
            </div>
          )}
        </div>
      </div>

      {err && <div className="mx-4 mb-4 card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}
      {note && (
        <div className={`mx-4 mb-3 card p-2 font-mono text-xs ${mode === 'bulk' ? 'border-lime/30 text-lime' : 'border-amber/40 text-amber'}`}>
          {note}
        </div>
      )}

      {fromBulk && cands && !note && (
        <div className="mx-4 mb-3 card border-lime/30 p-2 font-mono text-xs text-lime">
          ▣ auto-loaded {cands.length} candidate(s) from the bulk file's <b>SP Search Term Report</b> sheet. Or upload a bulk above to replace.
        </div>
      )}

      {cands && (
        <>
          <div className="flex items-center justify-between px-4 pb-3 border-b border-edge">
            <div className="flex gap-1 flex-wrap">
              {[['ALL', cands.length], ['promote', counts.promote], ['negate', counts.negate]].map(([f, n]) => (
                <button key={f} onClick={() => setFilter(f)}
                  className={`tag ${filter === f ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>
                  {f.toUpperCase()} {n}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <button disabled={selected.size === 0} onClick={toProject}
                title="merge the selected search terms into the shared keyword project (pick it in the Keywords tab)"
                className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-50">
                <Icon name="playlist_add" size={14} /> to keyword project ({selected.size})
              </button>
              <button disabled={selected.size === 0 || building} onClick={download} aria-busy={building}
                className={`btn ${selected.size ? 'btn-primary' : 'btn-ghost opacity-50'}`}>
                {building ? 'building…' : <><Icon name="download" size={14} /> bulk file ({selected.size})</>}
              </button>
            </div>
          </div>

          <TableToolbar ctl={ctl} placeholder="search term / ad group…" />
          <div className="overflow-auto max-h-[420px]">
            <table className="w-full text-sm font-mono">
              <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
                <tr className="border-b border-edge">
                  <th className="p-2 text-left w-8"><input type="checkbox" checked={allSel} onChange={toggleAll} className="accent-lime" /></th>
                  <Th ctl={ctl} k="search_term">Search term</Th>
                  <Th ctl={ctl} k="campaign_name">Campaign · Ad group</Th>
                  <Th ctl={ctl} k="action">Action</Th>
                  <Th ctl={ctl} k="spend" align="right">Spend</Th>
                  <Th ctl={ctl} k="orders" align="right">Orders</Th>
                  <Th ctl={ctl} k="acos" align="right">ACoS</Th>
                  <Th ctl={ctl} k="break_even" align="right">BE ACoS</Th>
                  <Th ctl={ctl} k="suggested_bid" align="right">Bid →</Th>
                </tr>
              </thead>
              <tbody>
                {ctl.view.map((c, i) => (
                  <tr key={i} className="border-b border-edge/50 hover:bg-edge/30">
                    <td className="p-2"><input type="checkbox" checked={selected.has(candKey(c))} onChange={() => toggle(c)} className="accent-lime" /></td>
                    <td className="p-2 max-w-[240px] truncate text-slate-200" title={`${c.search_term} · ${c.ad_group_name}`}>{c.search_term}</td>
                    <td className="p-2 max-w-[220px] text-mute" title={`campaign ${c.campaign_id} · ad group ${c.ad_group_id}`}>
                      <div className="truncate">{c.campaign_name || c.campaign_id || '—'}</div>
                      <div className="truncate text-[10px]">{c.ad_group_name || c.ad_group_id || ''}</div>
                    </td>
                    <td className="p-2">
                      <span className={`tag ${c.action === 'promote' ? 'bg-lime/15 text-lime border border-lime/30' : 'bg-red/15 text-red border border-red/30'}`}>
                        {c.action === 'promote' ? 'PROMOTE' : 'NEGATE'}
                      </span>
                    </td>
                    <td className="p-2 text-right text-slate-300">{money(c.spend)}</td>
                    <td className="p-2 text-right text-slate-300">{c.orders}</td>
                    <td className={`p-2 text-right ${c.break_even != null && c.acos != null ? (c.acos > c.break_even ? 'text-down' : 'text-up') : 'text-slate-300'}`}
                      title={c.break_even != null ? `break-even ${(c.break_even * 100).toFixed(1)}% — red = this term converts above the product's break-even` : ''}>{pct(c.acos)}</td>
                    <td className="p-2 text-right text-mute"
                      title="the ad group's product break-even ACoS (benchmark upload wins, else catalog price + per-SKU COGS + real Transactions-ledger fees)">
                      {c.break_even != null ? pct(c.break_even) : '—'}</td>
                    <td className="p-2 text-right text-lime">{c.suggested_bid != null ? `$${c.suggested_bid}` : '—'}</td>
                  </tr>
                ))}
                {ctl.view.length === 0 && <tr><td colSpan="9" className="p-6 text-center text-mute">{ctl.query ? 'no matches' : 'no candidates — try a looser goal ACoS or a fuller report'}</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination ctl={ctl} />
        </>
      )}
    </div>
  )
}
