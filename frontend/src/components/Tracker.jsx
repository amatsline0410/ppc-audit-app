import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Line } from 'react-chartjs-2'
import { Doughnut } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler, ArcElement,
} from 'chart.js'
import { api } from '../api/client.js'
import { Icon, CardSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { Modal, useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler, ArcElement)

// Product Optimization — competitor research / indexed keywords / SEO tracker.
// Replaces the "Project Snore x Competitor Research" Google Sheet. RAW-data
// flow: create a project, upload raw Cerebro / X-ray exports, paste raw listing
// copy — the app computes the analysis (listing-audit match markers, coverage
// matrix, scorecards, movers, PPC rank-support, xlsx export). Legacy one-time
// sheet migration still supported.
// One panel, three nav views (`view` prop): 'seo' = scorecards + movers +
// keyword grid + PPC suggestions, 'listing' = listing audit copy engine,
// 'products' = competitor product matrix. No view (standalone) shows all.
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')

const VIEW_SUB = {
  seo: 'seo · search visibility, rank coverage & movers',
  listing: 'listing audit · copy coverage & health checks',
  products: 'product overview · competitor catalog & attributes',
}

const pageCls = (rank) => rank == null ? 'text-mute/50'
  : rank <= 48 ? 'text-up' : rank <= 144 ? 'text-amber' : 'text-mute'

export function TrackerPanel({ scope, view, focus }) {
  const show = (v) => !view || view === v
  const toast = useToast()
  const { confirm, prompt } = useModals()
  const migRef = useRef()
  const impRef = useRef()
  const xrayRef = useRef()
  const [projects, setProjects] = useState([])
  const [pid, setPid] = useState(null)
  const [matrix, setMatrix] = useState(null)
  const [comps, setComps] = useState(null)
  const [score, setScore] = useState(null)
  const [movers, setMovers] = useState(null)
  const [suggest, setSuggest] = useState(null)
  const [seoRec, setSeoRec] = useState(null)
  const [listing, setListing] = useState(null)
  const [variant, setVariant] = useState('current')   // listing copy variant: current | proposed
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [impAsin, setImpAsin] = useState('')
  const [impDate, setImpDate] = useState('')
  const [repBusy, setRepBusy] = useState(false)

  function loadProjects(pick) {
    api.trackerProjects().then(d => {
      setProjects(d.projects)
      setPid(cur => pick || (d.projects.some(p => p.id === cur) ? cur : (d.projects[0]?.id ?? null)))
    }).catch(() => {})
  }
  useEffect(() => { setPid(null); setVariant('current'); setMatrix(null); setComps(null); setScore(null); setMovers(null); setSuggest(null); setSeoRec(null); setListing(null); loadProjects() }, [scope])  // eslint-disable-line

  function loadViews(id, v = variant) {
    if (!id) { setMatrix(null); setComps(null); setScore(null); setMovers(null); setSuggest(null); setSeoRec(null); setListing(null); return }
    setBusy(true); setErr(null)
    Promise.all([api.trackerMatrix(id), api.trackerCompetitors(id), api.trackerScorecard(id),
      api.trackerMovers(id), api.trackerSuggest(id), api.trackerListing(id, v), api.trackerSeoRecommend(id, v)])
      .then(([m, c, s, mv, sg, li, sr]) => { setMatrix(m); setComps(c); setScore(s); setMovers(mv); setSuggest(sg); setListing(li); setSeoRec(sr) })
      .catch(e => setErr(cleanErr(e)))
      .finally(() => setBusy(false))
  }
  useEffect(() => { loadViews(pid) }, [pid])  // eslint-disable-line
  // variant switch (Current <-> Proposed) refetches just the copy-dependent views
  function switchVariant(v) {
    if (v === variant || !pid) { setVariant(v); return }
    setVariant(v); setErr(null)
    Promise.all([api.trackerListing(pid, v), api.trackerSeoRecommend(pid, v)])
      .then(([li, sr]) => { setListing(li); setSeoRec(sr) })
      .catch(e => setErr(cleanErr(e)))
  }
  // proposed drafting helper: seed the proposed variant from the current copy
  async function seedProposed() {
    if (!pid) return
    try {
      const cur = await api.trackerListing(pid, 'current')
      const elems = ['title', 'bullet_points', 'aplus', 'description', 'search_terms', 'alt_text']
      let n = 0
      for (const e of elems) {
        if ((cur.copy?.[e] || '').trim()) { await api.trackerSetListing(pid, e, cur.copy[e], 'proposed'); n++ }
      }
      toast.success(n ? `Copied ${n} element${n === 1 ? '' : 's'} from current → proposed` : 'Current copy is empty — nothing to seed')
      loadViews(pid, 'proposed')
    } catch (e) { toast.error(cleanErr(e)) }
  }
  // "Perform Listing Audit" hand-off from the Product Benchmark catalog: select
  // the target project (fresh ts re-fires even for the same pid -> views refetch)
  useEffect(() => {
    if (focus?.pid) { loadProjects(focus.pid); loadViews(focus.pid) }
    if (focus?.asin) setImpAsin(focus.asin)   // product ASIN prefills the single-ASIN input
  }, [focus?.ts])  // eslint-disable-line

  async function migrate(file) {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      const name = await prompt({ title: 'Project name', placeholder: 'e.g. Project Snore', required: true })
      if (!name) { setBusy(false); return }
      const r = await api.trackerMigrate(file, name)
      toast.success(`Imported "${r.name}" · ${r.keywords} keywords · ${r.competitors} ASINs · ${r.rank_cells} ranks`)
      loadProjects(r.project_id)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (migRef.current) migRef.current.value = '' }
  }

  async function newProject() {
    const name = await prompt({ title: 'New project', subtitle: 'Raw-data flow: create the project, then upload raw Cerebro / X-ray exports and paste your listing copy.', placeholder: 'Project name, e.g. Project Snore', required: true })
    if (!name) return
    const asin = await prompt({ title: 'Your ASIN', subtitle: 'Primary (your) ASIN — used to compute scorecards and movers. Optional but recommended.', placeholder: 'B0…' })
    if (asin === null) return
    try {
      const r = await api.trackerCreateProject(name, asin?.trim() || undefined)
      toast.success(`Project "${r.name}" created — upload a Cerebro export to add keywords & ranks`)
      loadProjects(r.project_id)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  async function importXray(file) {
    if (!file || !pid) return
    setBusy(true); setErr(null)
    try {
      const r = await api.trackerXray(file, pid)
      toast.success(`X-ray matched ${r.matched} Cerebro ASIN${r.matched === 1 ? '' : 's'} (${r.added} new, ${r.updated} updated) · ${r.skipped} not tracked, skipped`)
      loadViews(pid)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (xrayRef.current) xrayRef.current.value = '' }
  }

  async function importSnap(file) {
    if (!file || !pid) return
    setBusy(true); setErr(null)
    try {
      const r = await api.trackerImport(file, pid, impDate || undefined, impAsin || undefined)
      toast.success(`Snapshot ${r.snapshot_date} · ${r.rank_rows} ranks · ${r.keywords_added} new keywords`)
      loadViews(pid)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (impRef.current) impRef.current.value = '' }
  }

  async function delProject() {
    const p = projects.find(x => x.id === pid)
    if (!p) return
    const ok = await confirm({
      title: `Delete "${p.name}"?`,
      message: `Removes the project, its ${p.keywords} keywords, competitors and every snapshot. This cannot be undone.`,
      danger: true, confirmLabel: 'Delete project',
    })
    if (!ok) return
    try { await api.trackerDeleteProject(pid); toast.success(`Deleted "${p.name}"`); loadProjects() }
    catch (e) { toast.error(cleanErr(e)) }
  }

  async function editCell(row, asin) {
    const cur = row.ranks[matrix.asins.indexOf(asin)]
    const v = await prompt({
      title: `Rank · ${row.keyword}`,
      subtitle: `${asin} — enter organic rank (blank = not ranked)`,
      placeholder: cur == null ? 'e.g. 12' : String(cur),
    })
    if (v === null) return
    const rank = v.trim() === '' ? null : Number(v)
    if (rank !== null && (!Number.isFinite(rank) || rank < 0)) { toast.error('Rank must be a number'); return }
    try {
      await api.trackerCell(row.keyword_id, asin, rank)
      toast.success('Rank saved (today\'s snapshot)')
      loadViews(pid)
    } catch (e) { toast.error(cleanErr(e)) }
  }

  async function download() {
    try {
      const blob = await api.trackerExport(pid)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'listing_optimizer_matrix.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Coverage matrix downloaded')
    } catch (e) { toast.error(cleanErr(e)) }
  }

  // full exec report — xlsx with native Excel charts, one sheet per view
  async function downloadReport() {
    setRepBusy(true)
    try {
      const blob = await api.trackerReport(pid)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'product_optimization_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Product Optimization report downloaded — Overview · SEO · Listing Audit · Product Overview')
    } catch (e) { toast.error(cleanErr(e)) }
    finally { setRepBusy(false) }
  }

  // the sheet's Main-tab grid: keyword + SV + computed REL, the six listing-
  // element usage markers (computed from pasted copy / sheet import), then one
  // column per ASIN with product image + brand + ASIN header and rank cells.
  const cols = useMemo(() => {
    if (!matrix) return []
    const marksBy = Object.fromEntries((listing?.rows || []).map(r => [r.keyword_id, r.marks]))
    const imgBy = Object.fromEntries((comps?.competitors || []).map(c => [c.asin, c.image_url]))
    const mv = m => m === 'exact' ? 2 : m === 'broad' ? 1 : 0
    const base = [
      { key: 'keyword', label: 'Keyword', render: r => <span className="text-slate-200">{r.keyword}</span> },
      { key: 'sv', label: 'SV', align: 'right', render: r => r.sv?.toLocaleString() ?? '—' },
      { key: 'relevancy', label: 'Rel', align: 'right',
        render: r => <span title="computed: ASINs using this keyword in their listing (Title / Bullets / Description)"
          className={r.relevancy > 0 ? 'text-primary font-semibold' : 'text-mute/50'}>{r.relevancy ?? 0}</span> },
    ]
    const markerCols = COPY_ELEMS.map(([e, label]) => ({
      key: `m_${e}`, label, align: 'center',
      value: r => mv(marksBy[r.keyword_id]?.[e]),
      render: r => {
        const m = marksBy[r.keyword_id]?.[e]
        return m
          ? <span className={`tag ${m === 'exact' ? 'bg-up/15 text-up border border-up/30' : 'bg-amber/15 text-amber border border-amber/30'}`}>{m}</span>
          : <span className="text-mute/30">—</span>
      },
    }))
    const asinCols = matrix.columns.map((c, i) => ({
      key: `a${i}`, align: 'center',
      label: (
        <span className="inline-flex flex-col items-center gap-1 align-middle py-1">
          {imgBy[c.asin]
            ? <img src={imgBy[c.asin]} alt={c.brand || c.asin} loading="lazy"
                className="h-14 w-14 object-contain rounded bg-white/5" />
            : <span className="h-14 w-14 rounded bg-edge/40 grid place-items-center text-mute"><Icon name="image" size={16} /></span>}
          <span className={`text-[10px] leading-none ${c.is_primary ? 'text-primary font-bold' : 'text-slate-300'}`}>
            {c.is_primary ? '★ ' : ''}{c.brand || '—'}
          </span>
          <a href={`https://www.amazon.com/dp/${c.asin}`} target="_blank" rel="noreferrer"
            onClick={e => e.stopPropagation()} className="text-cyan text-[9px] leading-none hover:underline">{c.asin}</a>
        </span>
      ),
      value: r => r.ranks[i] ?? 10 ** 6,
      render: r => (
        <button onClick={() => editCell(r, c.asin)} title={`${c.asin} — click to edit rank`}
          className={`font-mono ${pageCls(r.ranks[i])} ${c.is_primary ? 'font-bold' : ''} hover:underline`}>
          {r.ranks[i] ?? '—'}
        </button>
      ),
    }))
    return [...base, ...markerCols, ...asinCols]
  }, [matrix, listing, comps])  // eslint-disable-line

  const mvCols = (withDelta) => [
    { key: 'keyword', label: 'Keyword' },
    { key: 'sv', label: 'SV', align: 'right', render: r => r.sv?.toLocaleString() ?? '—' },
    { key: 'prev', label: 'Prev', align: 'right', render: r => r.prev ?? '—' },
    { key: 'cur', label: 'Now', align: 'right', render: r => r.cur ?? '—' },
    ...(withDelta ? [{ key: 'delta', label: 'Δ', align: 'right',
      render: r => <span className={r.delta < 0 ? 'text-up' : 'text-down'}>{r.delta > 0 ? `+${r.delta}` : r.delta}</span> }] : []),
  ]

  const proj = projects.find(p => p.id === pid)

  return (
    <div className="space-y-6">
      {/* header: project switcher + imports */}
      <div className="card">
        <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">product optimization · {VIEW_SUB[view] || 'competitor research · indexed keywords'}</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload RAW exports (Cerebro, X-ray) + paste your listing copy — the app computes the analysis. Ranks accumulate into trends.
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {projects.length > 0 && (
              <select value={pid ?? ''} onChange={e => setPid(Number(e.target.value))}
                className="bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary">
                {projects.map(p => <option key={p.id} value={p.id}>{p.name} · {p.keywords} kw</option>)}
              </select>
            )}
            <button onClick={newProject} disabled={busy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="add" size={14} />New project
            </button>
            <button onClick={() => migRef.current?.click()} disabled={busy} aria-busy={busy}
              title="legacy: one-time import of the pre-computed Google Sheet"
              className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="upload_file" size={14} />Migrate sheet
            </button>
            {pid && (
              <>
                <button onClick={downloadReport} disabled={repBusy} aria-busy={repBusy}
                  title="one workbook with charts: Overview · SEO · Listing Audit · Product Overview"
                  className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
                  <Icon name="monitoring" size={14} />{repBusy ? 'Building…' : 'Export Report'}
                </button>
                <button onClick={download} className="btn btn-ghost text-xs flex items-center gap-1">
                  <Icon name="download" size={14} />Export matrix
                </button>
                <button onClick={delProject} title="delete project"
                  className="btn btn-ghost text-xs text-down flex items-center gap-1">
                  <Icon name="delete" size={14} />
                </button>
              </>
            )}
            <input ref={migRef} type="file" accept=".xlsx,.xlsm" className="hidden"
              onChange={e => migrate(e.target.files?.[0])} />
          </div>
        </div>

        {pid && (
          <div className="p-4 flex items-end gap-2 flex-wrap">
            <label className="font-mono text-[10px] text-mute uppercase tracking-wider">Snapshot date
              <input type="date" value={impDate} onChange={e => setImpDate(e.target.value)}
                className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary" />
            </label>
            <label className="font-mono text-[10px] text-mute uppercase tracking-wider">ASIN (single-ASIN Cerebro)
              <input value={impAsin} onChange={e => setImpAsin(e.target.value.trim())} placeholder={proj?.primary_asin || 'B0…'}
                className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 w-36 focus:outline-none focus:border-primary" />
            </label>
            <button onClick={() => impRef.current?.click()} disabled={busy} aria-busy={busy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="upload" size={14} />Upload Cerebro (raw)
            </button>
            <button onClick={() => xrayRef.current?.click()} disabled={busy} aria-busy={busy}
              title="raw Helium10 X-ray export — rows matched against your Cerebro ASINs (any upload order); top 10 by revenue kept active"
              className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="groups" size={14} />Upload X-ray (raw)
            </button>
            <span className="font-mono text-[10px] text-mute">multi-ASIN Cerebro → leave ASIN blank · single-ASIN defaults to your primary ASIN</span>
            <input ref={impRef} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
              onChange={e => importSnap(e.target.files?.[0])} />
            <input ref={xrayRef} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
              onChange={e => importXray(e.target.files?.[0])} />
          </div>
        )}

        {err && <div className="mx-4 mb-4 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
        {!pid && !busy && (
          <div className="p-8 text-center">
            <div className="font-mono text-sm text-slate-200">No projects yet</div>
            <div className="font-mono text-xs text-mute mt-1">
              Hit <b>New project</b>, then upload RAW exports — a Cerebro export (keywords + ranks) and an
              X-ray export (competitors) — and paste your listing copy. The app computes the whole analysis:
              listing-audit markers, coverage matrix, scorecards, movers.
              <br />Have the old Google Sheet? <b>Migrate sheet</b> imports it in one go (legacy).
            </div>
          </div>
        )}
        {busy && !matrix && <div className="p-4"><CardSkeleton lines={5} /></div>}
      </div>

      {/* listing sanitizer — banned-keyword check over OUR copy (Product Overview view) */}
      {show('products') && pid && <SanitizerCard pid={pid} scope={scope} />}

      {/* competitor matrix — the sheet's Main-tab layout (Product List view) */}
      {show('products') && comps && comps.competitors.length > 0 && (
        <CompetitorMatrix data={comps}
          onToggle={async (c, field) => {
            // cycle Yes -> None -> Yes (sheet dropdown habit); unchecked starts at Yes
            const next = c[field] === true ? false : true
            try { await api.trackerSetCompetitor(c.id, field, next); loadViews(pid) }
            catch (e) { toast.error(cleanErr(e)) }
          }} />
      )}

      {/* listing copy + computed audit — the raw-data analysis engine (Listing Audit view) */}
      {show('listing') && listing && (
        <ListingAudit data={listing} scope={scope} variant={variant} onVariant={switchVariant} onSeed={seedProposed}
          onSave={async (element, text, asin) => {
            // competitor pastes are reference data — always stored on 'current'
            try { await api.trackerSetListing(pid, element, text, asin ? 'current' : variant, asin); loadViews(pid) }
            catch (e) { toast.error(cleanErr(e)) }
          }} />
      )}

      {/* SEO recommendations directly under the copy editor (Listing Audit view).
          `view &&` guards standalone mode, where the SEO-view block below renders it. */}
      {show('listing') && view && seoRec && (
        <SeoRecommendations data={seoRec} toast={toast} variant={variant} onVariant={switchVariant} />
      )}

      {/* scorecards (SEO view) */}
      {show('seo') && score && (
        <div className="card p-4">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">seo scorecards · {score.dates.length} snapshot{score.dates.length === 1 ? '' : 's'}</div>
            <div className="font-mono text-[10px] text-mute">
              top-10 revenue ${Math.round(score.kpis.total_revenue_top10).toLocaleString()} ·
              market share {score.kpis.market_share == null ? '—' : `${(score.kpis.market_share * 100).toFixed(2)}%`} ·
              avg reviews {score.kpis.avg_reviews_top10 ?? '—'}
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-2">
            {score.cards.map(c => (
              <div key={c.asin} className={`rounded-lg border p-3 ${c.is_primary ? 'border-primary bg-primary/10' : 'border-edge'}`}>
                <div className="flex items-center justify-between gap-1">
                  <span className={`font-mono text-xs font-semibold truncate ${c.is_primary ? 'text-primary' : 'text-slate-200'}`}>
                    {c.is_primary ? '★ ' : ''}{c.brand || c.asin}
                  </span>
                  <span className="font-mono text-[9px] text-mute">{c.asin}</span>
                </div>
                <div className="grid grid-cols-3 gap-1 mt-2 font-mono text-center">
                  <div><div className="text-[9px] text-mute uppercase">indexed</div>
                    <div className="text-sm font-bold text-slate-100">{c.index_rate == null ? '—' : `${(c.index_rate * 100).toFixed(1)}%`}</div></div>
                  <div><div className="text-[9px] text-mute uppercase">page 1</div>
                    <div className="text-sm font-bold text-up">{c.page1_count}</div></div>
                  <div><div className="text-[9px] text-mute uppercase">avg rank</div>
                    <div className="text-sm font-bold text-slate-100">{c.avg_rank ?? '—'}</div></div>
                </div>
                {c.series.length > 1 && (
                  <div className="h-10 mt-2">
                    <Line data={{
                      labels: c.series.map(s => s.date),
                      datasets: [{ data: c.series.map(s => s.page1), borderColor: '#FCD535',
                        backgroundColor: 'rgba(252,213,53,.12)', fill: true, tension: .3,
                        pointRadius: 0, borderWidth: 1.5 }],
                    }} options={{ plugins: { legend: { display: false }, tooltip: { enabled: false } },
                      scales: { x: { display: false }, y: { display: false } },
                      responsive: true, maintainAspectRatio: false }} />
                  </div>
                )}
                {c.is_primary && c.coverage_vs_best != null && (
                  <div className="font-mono text-[10px] text-mute mt-1">coverage vs best comp: {(c.coverage_vs_best * 100).toFixed(1)}%</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SEO + backend search-term recommendations (SEO view) */}
      {show('seo') && seoRec && (
        <SeoRecommendations data={seoRec} toast={toast} variant={variant} onVariant={switchVariant} />
      )}

      {/* movers (SEO view) */}
      {show('seo') && movers && (movers.climbers.length + movers.decliners.length + movers.new.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <DataTable title={`Climbers · ${movers.prev_date} → ${movers.cur_date}`} lean
            columns={mvCols(true)} rows={movers.climbers} rowKey={r => r.keyword}
            scope={scope} empty="No improved keywords." />
          <DataTable title={`Decliners · ${movers.prev_date} → ${movers.cur_date}`} lean
            columns={mvCols(true)} rows={movers.decliners} rowKey={r => r.keyword}
            scope={scope} empty="No declined keywords." />
          {movers.new.length > 0 && (
            <DataTable title="Newly ranked" lean columns={mvCols(false)} rows={movers.new}
              rowKey={r => r.keyword} scope={scope} empty="" />
          )}
          {movers.lost.length > 0 && (
            <DataTable title="Lost rank" lean columns={mvCols(false)} rows={movers.lost}
              rowKey={r => r.keyword} scope={scope} empty="" />
          )}
        </div>
      )}

      {/* coverage matrix (SEO view) */}
      {show('seo') && matrix && (
        <div className="card p-4">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
              keyword grid · {matrix.rows.length.toLocaleString()} keywords · as of {matrix.date}
            </div>
            <div className="font-mono text-[10px] text-mute inline-flex items-center gap-2 flex-wrap">
              <span className="text-up">exact</span>/<span className="text-amber">broad</span> = keyword in that listing element
              · ranks: <span className="text-up">page 1</span><span className="text-amber">page 2–3</span>
              <span className="text-mute">deeper</span><span className="text-mute/50">— unranked</span>
              · click a rank to edit
            </div>
          </div>
          <DataTable columns={cols} rows={matrix.rows} rowKey={r => r.keyword_id}
            scope={`${scope}:${matrix.date}`} empty="No keywords — migrate the sheet or import a Cerebro snapshot."
            placeholder="search keyword…" />
        </div>
      )}

      {/* ppc suggestions — kept last (SEO view) */}
      {show('seo') && suggest && (suggest.rank_support?.length > 0 || suggest.product_targets?.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <DataTable title={`Rank support → exact-target these · ${suggest.rank_support.length}`} lean
            columns={[
              { key: 'keyword', label: 'Keyword' },
              { key: 'sv', label: 'SV', align: 'right', render: r => r.sv?.toLocaleString() ?? '—' },
              { key: 'rank', label: 'Rank', align: 'right', cellClass: 'text-amber' },
              { key: 'page', label: 'Page', align: 'right' },
            ]}
            rows={suggest.rank_support} rowKey={r => r.keyword} scope={scope}
            empty="Nothing on page 2-3 worth pushing yet." />
          <DataTable title={`Competitor ASINs → product-target · ${suggest.product_targets.length}`} lean
            columns={[
              { key: 'brand', label: 'Brand' },
              { key: 'asin', label: 'ASIN', cellClass: 'text-cyan' },
              { key: 'review_count', label: 'Reviews', align: 'right', render: r => r.review_count?.toLocaleString() ?? '—' },
              { key: 'rating', label: 'Rating', align: 'right', render: r => r.rating ?? '—' },
              { key: 'price', label: 'Price', align: 'right', render: r => r.price == null ? '—' : `$${r.price}` },
            ]}
            rows={suggest.product_targets} rowKey={r => r.asin} scope={scope}
            empty="No active competitors." />
        </div>
      )}
    </div>
  )
}

// ---- SEO recommendations + backend search-term recommendation ----------------
// Computed from the Listing Audit copy vs the tracked keywords: prioritized
// actions (left) + a ready-to-paste 249-byte generic-keywords line (right).
const SEV_CLS = { high: 'text-down border-down/40', medium: 'text-amber border-amber/40', low: 'text-mute border-edge' }

// Current | Proposed copy-variant switch (shared by Listing Audit + SEO recs)
function VariantToggle({ variant, onVariant }) {
  return (
    <div className="flex gap-1">
      {[['current', 'Current'], ['proposed', 'Proposed']].map(([v, l]) => (
        <button key={v} onClick={() => onVariant?.(v)}
          className={`tag ${variant === v ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>{l}</button>
      ))}
    </div>
  )
}

function SeoRecommendations({ data, toast, variant, onVariant }) {
  const st = data.search_terms || {}
  const c = data.counts || {}
  async function copyLine() {
    try { await navigator.clipboard.writeText(st.suggested); toast.success('Search-term line copied — paste into Seller Central > Edit Listing > Keywords') }
    catch { toast.error('Copy failed — select the text manually') }
  }
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* prioritized SEO actions */}
      <div className="card">
        <div className="p-3 border-b border-edge flex items-center justify-between gap-2 flex-wrap">
          <span className="text-mute text-[11px] font-mono uppercase tracking-wider">seo recommendations · {data.recommendations.length} · {variant} copy</span>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px]">
              {c.high > 0 && <span className="text-down">{c.high} high</span>}
              {c.medium > 0 && <span className="text-amber"> · {c.medium} med</span>}
              {c.low > 0 && <span className="text-mute"> · {c.low} low</span>}
            </span>
            <VariantToggle variant={variant} onVariant={onVariant} />
          </div>
        </div>
        <div className="divide-y divide-edge/40 max-h-96 overflow-auto">
          {data.recommendations.map((r, i) => (
            <div key={i} className={`p-3 font-mono text-xs border-l-2 ${SEV_CLS[r.severity] || SEV_CLS.low}`}>
              <div className="flex items-center gap-2">
                <span className="uppercase text-[9px]">{r.severity}</span>
                <span className="text-slate-200">{r.title}</span>
                <span className="tag border border-edge text-mute ml-auto">{r.area.replace('_', ' ')}</span>
              </div>
              <div className="text-mute mt-1">{r.action}</div>
              {r.keywords?.length > 0 && (
                <div className="flex gap-1.5 flex-wrap mt-1.5">
                  {r.keywords.map((k, j) => (
                    <span key={j} className="tag border border-edge text-slate-300">
                      {k.keyword}{k.sv != null && <span className="text-mute"> · {Number(k.sv).toLocaleString()}</span>}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {data.recommendations.length === 0 && (
            <div className="p-4 text-center text-up font-mono text-xs">✓ nothing to fix — copy covers your tracked keywords</div>
          )}
        </div>
      </div>

      {/* backend search-term recommendation */}
      <div className="card">
        <div className="p-3 border-b border-edge flex items-center justify-between gap-2">
          <span className="text-mute text-[11px] font-mono uppercase tracking-wider">backend search terms · recommended line</span>
          <span className={`font-mono text-[10px] ${st.bytes > st.max_bytes ? 'text-down' : 'text-mute'}`}>{st.bytes || 0}/{st.max_bytes || 249} bytes</span>
        </div>
        <div className="p-3 space-y-2">
          {st.suggested ? (
            <>
              <div className="font-mono text-xs text-slate-200 bg-ink border border-edge rounded p-2 break-words">{st.suggested}</div>
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={copyLine} className="btn btn-primary text-xs flex items-center gap-1">
                  <Icon name="content_copy" size={13} /> Copy line
                </button>
                <span className="font-mono text-[10px] text-mute">
                  {st.words?.length || 0} of {st.candidates || 0} uncovered words packed by search volume
                  {st.current_bytes != null && ` · current field: ${st.current_bytes} bytes`}
                </span>
              </div>
              <div className="font-mono text-[10px] text-mute">
                Words already indexed by your title/bullets/description are excluded — the field's 249 bytes go to what the copy doesn't say.
              </div>
              {st.wasted_words?.length > 0 && (
                <div className="font-mono text-[10px] text-amber">
                  wasted in current field (already in visible copy): {st.wasted_words.join(', ')}
                </div>
              )}
            </>
          ) : (
            <div className="font-mono text-xs text-mute p-2">
              No uncovered words to suggest — track keywords (Cerebro import / catalog search terms) and paste your listing copy first.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ---- Listing Audit — the raw-data analysis. Paste raw copy per element; the
// backend computes exact/broad match markers live from the tracked keywords
// (replaces the sheet's hand-marked Listing Audit tab). Elements without pasted
// copy fall back to sheet-imported markers (e.g. SP/SB targeting columns).
const COPY_ELEMS = [
  ['title', 'Title'], ['bullet_points', 'Bullet Points'], ['aplus', 'A+ / Brand Story'],
  ['description', 'Description'], ['search_terms', 'Search Terms'], ['alt_text', 'Alt Text'],
]
const TGT_ELEMS = [
  ['sp_broad', 'SP Broad'], ['sp_phrase', 'SP Phrase'], ['sp_exact', 'SP Exact'],
  ['sb_broad', 'SB Broad'], ['sb_phrase', 'SB Phrase'], ['sb_exact', 'SB Exact'],
]
const ELEM_LABEL = Object.fromEntries([...COPY_ELEMS, ...TGT_ELEMS])

// competitor-comparable elements — search_terms excluded (no competitor data)
const COMP_ELEMS = COPY_ELEMS.filter(([e]) => e !== 'search_terms')

// one comparison cell: pasted -> chars + exact/broad + SV; empty -> paste target
function CopyCell({ stat, onClick }) {
  const has = !!stat?.has_copy
  return (
    <button onClick={onClick} title="click to paste/edit raw copy"
      className={`w-full rounded border px-2 py-1.5 text-[10px] leading-tight transition-colors hover:border-primary ${has ? 'border-edge' : 'border-dashed border-edge/70 text-mute/60'}`}>
      {has ? (
        <>
          <div className="text-slate-300">{stat.chars.toLocaleString()} chars</div>
          <div><span className="text-up">{stat.exact} exact</span> · <span className="text-amber">{stat.broad} broad</span></div>
          <div className="text-mute">SV {(stat.total_exact_sv ?? 0).toLocaleString()}</div>
        </>
      ) : 'paste'}
    </button>
  )
}

function ListingAudit({ data, scope, onSave, variant = 'current', onVariant, onSeed }) {
  const [edit, setEdit] = useState(null)   // { element, text, asin?, brand? }
  const [saving, setSaving] = useState(false)
  const byElem = Object.fromEntries(data.elements.map(e => [e.element, e]))
  const cov = data.coverage
  const proposed = variant === 'proposed'
  // proposed = your draft rewrite; competitor pastes stay on Current only
  const comps = proposed ? [] : (data.competitors || [])
  const hasAnyCopy = data.elements.some(e => e.has_copy)
  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">listing audit · computed from your raw copy · {variant}</div>
          <div className="font-mono text-xs text-mute mt-1">
            {proposed
              ? 'Draft your rewrite here — same exact/broad markers + SEO recommendations, without touching the live (current) copy.'
              : 'Paste raw listing copy per element — exact/broad keyword markers are computed automatically.'}
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {proposed && onSeed && (
            <button onClick={onSeed} className="btn btn-ghost text-xs flex items-center gap-1"
              title="Copy every current element into the proposed draft as a starting point">
              <Icon name="content_copy" size={13} /> Seed from current
            </button>
          )}
          {onVariant && <VariantToggle variant={variant} onVariant={onVariant} />}
          <div className="font-mono text-[10px] text-mute">
            coverage <span className={cov.covered === cov.keywords && cov.keywords > 0 ? 'text-up' : 'text-slate-200'}>
              {cov.covered}/{cov.keywords}</span> keywords used somewhere
          </div>
        </div>
      </div>
      {proposed && !hasAnyCopy && (
        <div className="mx-4 mt-3 card border-edge p-2 font-mono text-xs text-mute inline-flex items-center gap-1">
          <Icon name="info" size={12} /> The proposed draft is empty — hit <span className="text-slate-200">Seed from current</span> or paste elements below, then check its SEO recommendations on the SEO tab.
        </div>
      )}

      {/* copy editor cards */}
      <div className="p-4 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2 border-b border-edge">
        {COPY_ELEMS.map(([e, label]) => {
          const s = byElem[e] || {}
          return (
            <button key={e} onClick={() => setEdit({ element: e, text: data.copy[e] || '' })}
              className={`rounded-lg border p-3 text-left hover:border-primary transition-colors ${s.has_copy ? 'border-edge' : 'border-dashed border-edge/70'}`}>
              <div className="flex items-center justify-between gap-1">
                <span className="font-mono text-[10px] text-mute uppercase tracking-wider truncate">{label}</span>
                <Icon name="edit" size={12} className="text-mute shrink-0" />
              </div>
              {s.has_copy ? (
                <div className="mt-1.5 font-mono text-[10px] space-y-0.5">
                  <div className="text-slate-300">{s.chars.toLocaleString()} chars</div>
                  <div><span className="text-up">{s.exact} exact</span> · <span className="text-amber">{s.broad} broad</span></div>
                  <div className="text-mute">SV {(s.total_exact_sv ?? 0).toLocaleString()}</div>
                </div>
              ) : (
                <div className="mt-1.5 font-mono text-[10px] text-mute/60">no copy — click to paste</div>
              )}
            </button>
          )
        })}
      </div>

      {/* competitor copy comparison — paste each competitor's copy manually;
          markers computed against the same tracked keywords. search terms
          skipped for competitors (no data source). */}
      {comps.length > 0 && (
        <div className="px-4 py-3 border-b border-edge">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
            <div className="font-mono text-[10px] text-mute uppercase tracking-wider">competitor copy comparison · paste their live copy per element</div>
            <div className="font-mono text-[10px] text-mute">search terms not compared (no competitor data) · click a cell to paste/edit</div>
          </div>
          <div className="overflow-x-auto">
            <table className="text-xs font-mono min-w-full">
              <tbody>
                <tr className="border-b border-edge">
                  <td className="p-2 sticky left-0 bg-panel z-10" />
                  <td className="p-2 text-center bg-primary/10">
                    <span className="text-primary font-semibold">★ You</span>
                    <div className="text-[9px] text-mute">{data.project.primary_asin || '—'}</div>
                  </td>
                  {comps.map(c => (
                    <td key={c.asin} className="p-2 text-center">
                      {c.image_url && <img src={c.image_url} alt={c.brand || c.asin} loading="lazy"
                        className="h-10 w-10 object-contain mx-auto rounded bg-white/5 mb-1" />}
                      <span className="text-slate-200 font-semibold">{c.brand || '—'}</span>
                      <div><a href={`https://www.amazon.com/dp/${c.asin}`} target="_blank" rel="noreferrer"
                        className="text-cyan text-[9px] hover:underline">{c.asin}</a></div>
                    </td>
                  ))}
                </tr>
                {COMP_ELEMS.map(([e, label]) => {
                  const mine = byElem[e] || {}
                  return (
                    <tr key={e} className="border-b border-edge/50 hover:bg-edge/20 align-top">
                      <td className="p-2 sticky left-0 bg-panel z-10 text-mute text-[10px] uppercase tracking-wider whitespace-nowrap">{label}</td>
                      <td className="p-1.5 text-center bg-primary/5">
                        <CopyCell stat={mine} onClick={() => setEdit({ element: e, text: data.copy[e] || '' })} />
                      </td>
                      {comps.map(c => {
                        const s = c.elements.find(x => x.element === e)
                        return (
                          <td key={c.asin} className="p-1.5 text-center">
                            <CopyCell stat={s} onClick={() => setEdit({
                              element: e, asin: c.asin, brand: c.brand,
                              text: data.comp_copy?.[c.asin]?.[e] || '' })} />
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
                <tr className="bg-primary/5">
                  <td className="p-2 sticky left-0 bg-panel z-10 text-primary text-[10px] uppercase tracking-wider whitespace-nowrap"
                    title="tracked keywords matched anywhere in that listing's pasted copy">Keywords covered</td>
                  <td className="p-2 text-center bg-primary/10">
                    <span className="font-bold text-slate-100">{cov.covered.toLocaleString()}</span>
                    <span className="text-mute text-[10px]"> /{cov.keywords.toLocaleString()}</span>
                  </td>
                  {comps.map(c => (
                    <td key={c.asin} className="p-2 text-center">
                      <span className={`font-bold ${c.covered > cov.covered ? 'text-down' : 'text-slate-100'}`}>
                        {c.covered.toLocaleString()}</span>
                      <span className="text-mute text-[10px]"> /{cov.keywords.toLocaleString()}</span>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* uncovered keywords worth working into the copy */}
      {cov.uncovered_top.length > 0 && (
        <div className="px-4 py-3 border-b border-edge">
          <div className="font-mono text-[10px] text-mute uppercase tracking-wider mb-1.5">not used anywhere · top by search volume</div>
          <div className="flex flex-wrap gap-1">
            {cov.uncovered_top.map(u => (
              <span key={u.keyword} className="tag border border-down/30 bg-down/10 text-down font-mono text-[10px]">
                {u.keyword}{u.sv ? ` · ${u.sv.toLocaleString()}` : ''}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* raw copy editor modal (yours + competitor cells share it) */}
      <Modal open={!!edit} onClose={() => !saving && setEdit(null)} size="lg"
        title={edit ? `${ELEM_LABEL[edit.element]} — ${edit.asin ? `${edit.brand || edit.asin} (competitor)` : 'raw copy'}` : ''}
        subtitle="Paste the raw text; markers recompute on save. Empty text clears the block."
        footer={edit && (
          <>
            <button onClick={() => setEdit(null)} disabled={saving} className="btn btn-ghost text-xs">Cancel</button>
            <button onClick={async () => { setSaving(true); await onSave(edit.element, edit.text, edit.asin); setSaving(false); setEdit(null) }}
              disabled={saving} aria-busy={saving} className="btn btn-primary text-xs disabled:opacity-50">
              {saving ? 'Saving…' : 'Save & recompute'}
            </button>
          </>
        )}>
        {edit && (
          <div>
            <textarea value={edit.text} onChange={e => setEdit({ ...edit, text: e.target.value })}
              rows={10} autoFocus
              className="w-full bg-ink border border-edge rounded p-2 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary resize-y" />
            <div className="font-mono text-[10px] text-mute mt-1 text-right">{edit.text.length.toLocaleString()} chars</div>
          </div>
        )}
      </Modal>
    </div>
  )
}

// ---- Listing Sanitizer — Amazon banned-keyword checker. Scans OUR OWN listing
// copy only (title / bullets / A+ / description / search terms / alt text) —
// competitors are never scanned. User maintains the banned list (paste once,
// shared across projects); each element reports its flagged phrases.
function SanitizerCard({ pid, scope }) {
  const toast = useToast()
  const [report, setReport] = useState(null)
  const [banned, setBanned] = useState(null)
  const [edit, setEdit] = useState(null)     // string being edited
  const [saving, setSaving] = useState(false)

  function load() {
    Promise.all([api.trackerSanitize(pid), api.trackerBanned()])
      .then(([r, b]) => { setReport(r); setBanned(b.phrases) })
      .catch(e => toast.error(cleanErr(e)))
  }
  useEffect(() => { setReport(null); if (pid) load() }, [pid, scope])  // eslint-disable-line

  if (!report) return null
  const checked = report.elements.filter(e => e.checked)
  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">listing sanitizer · amazon banned keywords · your listing only</div>
          <div className="font-mono text-xs text-mute mt-1">
            Checks YOUR pasted copy (Listing Audit) against the banned list — competitors are never scanned.
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap font-mono text-xs">
          {report.banned_count > 0 && (
            report.total_flagged > 0
              ? <span className="tag bg-down/15 text-down border border-down/30">{report.total_flagged} flagged</span>
              : checked.length > 0 && <span className="tag bg-up/15 text-up border border-up/30">clean</span>
          )}
          <span className="text-mute">{report.banned_count.toLocaleString()} banned terms</span>
          <button onClick={() => setEdit((banned || []).join('\n'))}
            className="btn btn-ghost text-xs flex items-center gap-1"><Icon name="edit_note" size={14} />Edit banned list</button>
        </div>
      </div>

      {report.banned_count === 0 ? (
        <div className="p-4 font-mono text-xs text-mute">
          No banned keywords yet — hit <b className="text-slate-200">Edit banned list</b> and paste Amazon's banned/restricted terms (one per line or comma-separated).
        </div>
      ) : (
        <div className="p-4 space-y-2">
          {report.elements.map(e => (
            <div key={e.element} className="flex items-start gap-3 font-mono text-xs">
              <span className="text-mute text-[10px] uppercase tracking-wider w-32 shrink-0 pt-0.5">{ELEM_LABEL[e.element]}</span>
              {!e.checked ? (
                <span className="text-mute/50">no copy — nothing to check</span>
              ) : e.flagged === 0 ? (
                <span className="text-up inline-flex items-center gap-1"><Icon name="check_circle" size={13} />clean</span>
              ) : (
                <div className="min-w-0">
                  <span className="text-down font-semibold">{e.flagged} flagged</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {e.phrases.map(p => (
                      <span key={p} className="tag border border-down/30 bg-down/10 text-down text-[10px]">{p}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* banned-list editor */}
      <Modal open={edit !== null} onClose={() => !saving && setEdit(null)} size="lg"
        title="Amazon banned keywords" subtitle="One phrase per line (commas work too). Saving replaces the whole list — it's shared across projects. Empty = clear."
        footer={edit !== null && (
          <>
            <button onClick={() => setEdit(null)} disabled={saving} className="btn btn-ghost text-xs">Cancel</button>
            <button onClick={async () => {
              setSaving(true)
              try {
                const r = await api.trackerSetBanned(edit)
                toast.success(`Banned list saved · ${r.count} terms`)
                setEdit(null); load()
              } catch (e) { toast.error(cleanErr(e)) }
              finally { setSaving(false) }
            }} disabled={saving} aria-busy={saving} className="btn btn-primary text-xs disabled:opacity-50">
              {saving ? 'Saving…' : 'Save & re-check'}
            </button>
          </>
        )}>
        {edit !== null && (
          <textarea value={edit} onChange={e => setEdit(e.target.value)} rows={12} autoFocus
            placeholder={'cure\nFDA approved\nanti-bacterial\n…'}
            className="w-full bg-ink border border-edge rounded p-2 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary resize-y" />
        )}
      </Modal>
    </div>
  )
}

// ---- Competitor matrix — the sheet's Main-tab layout, transposed: attribute
// rows x one column per ASIN. Product images on top, KPI blocks + revenue donut,
// numeric attribute rows, then the manual Yes/None audit rows (click to toggle)
// and the computed Listing Health Score row (1.25 pts per Yes, 8 checks = 10).
const DONUT = ['#0ecb81', '#2fbf8f', '#4db39c', '#68a8a6', '#809cac', '#9691b0',
  '#aa86b2', '#bd7bb1', '#cf71ad', '#e067a6', '#f6465d']

const NUM_ROWS = [
  ['price', 'Price', v => v == null ? '—' : `$${v}`],
  ['sales', 'Sales', v => v == null ? '—' : v.toLocaleString()],
  ['revenue', 'Revenue', v => v == null ? '—' : `$${Math.round(v).toLocaleString()}`],
  ['bsr', 'BSR', v => v == null ? '—' : v.toLocaleString()],
  ['review_count', 'Review Count', v => v == null ? '—' : v.toLocaleString()],
  ['rating', 'Star Ratings', v => v ?? '—'],
  ['review_velocity', 'Review Velocity', v => v == null ? '—' : v.toLocaleString()],
  ['fba_fees', 'FBA Fees', v => v == null ? '—' : `$${v}`],
  ['active_sellers', 'Active Sellers', v => v ?? '—'],
  ['buy_box', 'Buy Box', v => v || '—'],
  ['fulfillment', 'Fulfillment', v => v || '—'],
  ['size_tier', 'Size Tier', v => v || '—'],
  ['seller_country', 'Seller Country', v => v || '—'],
  ['creation_date', 'Creation Date', v => v || '—'],
  ['listing_age', 'Listing Age (yrs)', v => v ?? '—'],
]
const YES_ROWS = [
  ['pdp_images', 'PDP Images'], ['pdp_videos', 'PDP Videos'],
  ['brand_story', 'Brand Story'], ['aplus', 'Generic/Premium A+'],
  ['crawlable_text', 'Crawlable Text'], ['alt_text', 'Alt Text'],
  ['comparison_table', 'Comparison Table'], ['amazon_badge', "Amazon's Badge/Highlight"],
]

// health score = computed: 1.25 pts per Yes over the 8 audit rows, perfect 10
const scoreCls = (v) => v >= 7.5 ? 'text-up' : v >= 5 ? 'text-primary' : v > 0 ? 'text-amber' : 'text-mute'

function CompetitorMatrix({ data, onToggle }) {
  const comps = data.competitors
  const k = data.kpis
  const donutRows = comps.filter(c => (c.revenue || 0) > 0)
  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider">competitor matrix · {comps.length} ASINs</div>
        <div className="font-mono text-[10px] text-mute">click a Yes/None cell to toggle · health score computed: 1.25 pts per Yes, 8 checks = 10</div>
      </div>

      {/* KPI header block (the sheet's colored cells) + revenue share donut */}
      <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-3 border-b border-edge">
        <div className="space-y-2">
          <div className="rounded-lg border border-up/40 bg-up/10 p-3">
            <div className="text-mute text-[9px] font-mono uppercase tracking-wider">Total Revenue (Top 10)</div>
            <div className="font-mono text-xl font-bold text-up mt-0.5">${Math.round(k.total_revenue_top10).toLocaleString()}</div>
          </div>
          <div className="rounded-lg border border-primary/40 bg-primary/10 p-3">
            <div className="text-mute text-[9px] font-mono uppercase tracking-wider">Our Market Share (vs top 10)</div>
            <div className="font-mono text-xl font-bold text-primary mt-0.5">{k.market_share == null ? '—' : `${(k.market_share * 100).toFixed(2)}%`}</div>
          </div>
          <div className="rounded-lg border border-edge p-3">
            <div className="text-mute text-[9px] font-mono uppercase tracking-wider">Average Reviews (Top 10)</div>
            <div className="font-mono text-xl font-bold text-slate-100 mt-0.5">{k.avg_reviews_top10?.toLocaleString() ?? '—'}</div>
          </div>
        </div>
        <div className="md:col-span-2 flex items-center gap-4">
          <div className="h-44 w-44 shrink-0">
            <Doughnut data={{
              labels: donutRows.map(c => c.brand || c.asin),
              datasets: [{ data: donutRows.map(c => Math.round(c.revenue)),
                backgroundColor: donutRows.map((_, i) => DONUT[i % DONUT.length]),
                borderColor: '#1e2329', borderWidth: 2 }],
            }} options={{ plugins: { legend: { display: false } }, cutout: '62%',
              responsive: true, maintainAspectRatio: false }} />
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            {donutRows.map((c, i) => (
              <div key={c.asin} className="font-mono text-[10px] flex items-center gap-1.5 min-w-0">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: DONUT[i % DONUT.length] }} />
                <span className={`truncate ${c.is_primary ? 'text-primary' : 'text-mute'}`}>{c.brand || c.asin}</span>
                <span className="text-slate-300 ml-auto">${Math.round(c.revenue).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* transposed attribute table */}
      <div className="overflow-x-auto">
        <table className="text-xs font-mono min-w-full">
          <tbody>
            <tr className="border-b border-edge">
              <td className="p-2 sticky left-0 bg-panel z-10" />
              {comps.map(c => (
                <td key={c.asin} className={`p-2 text-center ${c.is_primary ? 'bg-primary/10' : ''}`}>
                  {c.image_url
                    ? <img src={c.image_url} alt={c.brand || c.asin} title={c.title || ''}
                        className="h-20 w-20 object-contain mx-auto rounded bg-white/5" loading="lazy" />
                    : <div className="h-20 w-20 mx-auto rounded bg-edge/40 grid place-items-center text-mute"><Icon name="image" size={20} /></div>}
                </td>
              ))}
            </tr>
            <tr className="border-b border-edge">
              <td className="p-2 sticky left-0 bg-panel z-10 text-mute text-[10px] uppercase tracking-wider">Brand</td>
              {comps.map(c => (
                <td key={c.asin} className={`p-2 text-center font-semibold ${c.is_primary ? 'text-primary bg-primary/10' : 'text-slate-200'}`}
                  title={c.title || ''}>
                  {c.is_primary ? '★ ' : ''}{c.brand || '—'}
                </td>
              ))}
            </tr>
            <tr className="border-b border-edge">
              <td className="p-2 sticky left-0 bg-panel z-10 text-mute text-[10px] uppercase tracking-wider">ASIN</td>
              {comps.map(c => (
                <td key={c.asin} className={`p-2 text-center ${c.is_primary ? 'bg-primary/10' : ''}`}>
                  <a href={`https://www.amazon.com/dp/${c.asin}`} target="_blank" rel="noreferrer"
                    className="text-cyan hover:underline">{c.asin}</a>
                </td>
              ))}
            </tr>
            {NUM_ROWS.map(([f, label, fmt]) => (
              <tr key={f} className="border-b border-edge/50 hover:bg-edge/20">
                <td className="p-2 sticky left-0 bg-panel z-10 text-mute text-[10px] uppercase tracking-wider whitespace-nowrap">{label}</td>
                {comps.map(c => (
                  <td key={c.asin} className={`p-2 text-center text-slate-300 whitespace-nowrap ${c.is_primary ? 'bg-primary/10' : ''}`}>
                    {fmt(c[f])}
                  </td>
                ))}
              </tr>
            ))}
            <tr className="border-b border-edge bg-primary/5">
              <td className="p-2 sticky left-0 bg-panel z-10 text-primary text-[10px] uppercase tracking-wider whitespace-nowrap"
                title="computed: each Yes below = 1.25 pts, 8 checks = perfect 10">Listing Health Score</td>
              {comps.map(c => (
                <td key={c.asin} className={`p-2 text-center ${c.is_primary ? 'bg-primary/10' : ''}`}>
                  <span className={`font-bold ${scoreCls(c.listing_health_score)}`}>
                    {c.listing_health_score.toFixed(2)}
                  </span>
                  <span className="text-mute text-[10px]"> /10</span>
                </td>
              ))}
            </tr>
            {YES_ROWS.map(([f, label]) => (
              <tr key={f} className="border-b border-edge/50 hover:bg-edge/20">
                <td className="p-2 sticky left-0 bg-panel z-10 text-mute text-[10px] uppercase tracking-wider whitespace-nowrap">{label}</td>
                {comps.map(c => (
                  <td key={c.asin} className={`p-1 text-center ${c.is_primary ? 'bg-primary/10' : ''}`}>
                    <button onClick={() => onToggle(c, f)} title="click to toggle"
                      className={`tag ${c[f] === true ? 'bg-up/15 text-up border border-up/30'
                        : c[f] === false ? 'bg-red/15 text-red border border-red/30'
                        : 'border border-edge text-mute/60'}`}>
                      {c[f] === true ? 'Yes' : c[f] === false ? 'None' : '—'}
                    </button>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
