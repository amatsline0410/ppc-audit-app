import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Stat, StatsSkeleton, TableSkeleton, Icon } from './ui.jsx'
import { DataTable } from './table.jsx'
import { Modal, useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

// Product Benchmark — the store's product base, built from Amazon Category
// Listings Reports (Seller Central > Reports). STORE-scoped: one catalog per
// store, shared by every audit in it, never visible from another store.
// Amazon exports one file per category, so uploads MERGE by SKU.

const money2 = (x) => x == null ? '—' : `$${Number(x).toFixed(2)}`

function Thumb({ src, size = 38 }) {
  if (!src) return (
    <span className="inline-flex items-center justify-center rounded bg-edge/40 text-mute"
      style={{ width: size, height: size }}><Icon name="image" size={size * 0.5} /></span>
  )
  return <img src={src} alt="" loading="lazy" className="rounded object-contain bg-white"
    style={{ width: size, height: size }} />
}

function VariationBadge({ p }) {
  if (p.parentage === 'parent')
    return <span className="tag border border-lime/30 text-lime">parent{p.variation_theme ? ` · ${p.variation_theme.toLowerCase().replace(/_/g, ' ')}` : ''}</span>
  if (p.parentage === 'child')
    return <span className="tag border border-cyan/30 text-cyan" title={`parent SKU: ${p.parent_sku}`}>child</span>
  return <span className="text-mute">—</span>
}

function PriceCell({ p }) {
  if (p.price == null) return <span className="text-mute">—</span>
  return (
    <span>
      {p.sale_price != null && p.sale_price < p.price
        ? <><span className="text-up">{money2(p.sale_price)}</span> <s className="text-mute text-[11px]">{money2(p.price)}</s></>
        : money2(p.price)}
    </span>
  )
}

const pct1 = (x) => x == null ? '—' : `${(x * 100).toFixed(1)}%`

// campaigns per ASIN, joined from the audit's Product Ads upload:
// total + distinct-campaign breakdown by targeting kind (Auto/Keyword/Product/Manual)
function CampaignsCell({ a }) {
  if (!a) return <span className="text-mute">—</span>
  const bits = [['A', a.auto_campaigns], ['K', a.keyword_campaigns], ['P', a.product_campaigns], ['M', a.manual_campaigns]]
    .filter(([, n]) => n > 0).map(([t, n]) => `${n}${t}`).join(' ')
  return (
    <span title={`${a.ads} product ad${a.ads === 1 ? '' : 's'} · ${bits || 'no campaigns'} (A=auto K=keyword P=product M=manual)`}>
      {a.campaigns}{bits && <span className="text-mute text-[10px]"> {bits}</span>}
    </span>
  )
}

// PPC ACoS vs the product's break-even ACoS (uploaded benchmark wins, else
// derived from the catalog selling price + econ defaults)
function AcosBECell({ p }) {
  const be = p.be?.break_even_acos
  const a = p.ads
  if (!a || !a.spend) {
    return be != null
      ? <span className="text-mute" title="break-even ACoS (no ad spend yet)">BE {pct1(be)}</span>
      : <span className="text-mute">—</span>
  }
  if (!a.sales) return (
    <span className="text-down" title={`${money2(a.spend)} spend, $0 PPC sales — bleeding`}>
      ∞{be != null && <span className="text-mute font-normal"> / {pct1(be)}</span>}
    </span>
  )
  const cls = p.be_status === 'bleeding' ? 'text-down' : p.be_status === 'profitable' ? 'text-up' : ''
  return (
    <span title={be != null ? `PPC ACoS vs break-even ACoS ${pct1(be)}` : 'PPC ACoS (no break-even — no price)'}>
      <span className={cls}>{pct1(a.acos)}</span>
      {be != null && <span className="text-mute"> / {pct1(be)}</span>}
    </span>
  )
}

const trunc = (txt, w, cls = '') =>
  <span className={`truncate inline-block align-bottom ${cls}`} style={{ maxWidth: w }} title={txt}>{txt || '—'}</span>

// TOTAL FEES per unit = base fulfillment fee + referral fee, both straight from
// the Selling economics / FBA Fee Preview upload (bright). Muted = derived from
// the Transactions ledger / referral %. A dash means no fee data for that SKU,
// so its break-even is optimistic.
function TotalFeesCell({ be }) {
  if (!be || (!be.fba_fee && !be.amazon_fee)) return (
    <span className="text-mute" title="No fee data for this SKU — upload the Selling economics report (break-even currently prices fulfillment at $0)">—</span>
  )
  const src = be.total_source
  const total = be.total_fee ?? be.amazon_fee
  const note = src === 'report' ? 'from the fee report'
    : src === 'scaled' ? "report fees, referral re-priced to this listing's price"
    : 'derived from the referral % (no fee report for this item)'
  return (
    <span className={src === 'derived' ? 'text-mute' : ''}
      title={`total fees per unit — ${note}: `
        + `fulfillment ${money2(be.fba_fee)} + referral ${money2(be.referral_fee)}`
        + `${be.referral_pct != null ? ` (${(be.referral_pct * 100).toFixed(1)}%)` : ''}`
        + `${be.size_tier ? ` · ${be.size_tier}` : ''}`}>
      {money2(total)}
      <span className="text-mute text-[10px]"> {money2(be.fba_fee)}+{money2(be.referral_fee)}</span>
    </span>
  )
}

// stat card that filters the product table on click (click again to clear).
// Active card gets the yellow hairline; cards with no predicate stay static.
function FilterStat({ label, value, accent, active, onClick }) {
  if (!onClick) return <Stat label={label} value={value} accent={accent} />
  return (
    <button onClick={onClick}
      className={`card p-4 text-left transition-colors hover:border-primary/60 ${active ? 'border-primary' : ''}`}
      title={active ? 'click to clear this filter' : `click to show only: ${label.toLowerCase()}`}>
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider flex items-center justify-between gap-1">
        {label}{active && <Icon name="filter_alt" size={12} className="text-lime" />}
      </div>
      <div className={`mt-1 text-2xl font-mono font-bold ${accent || 'text-slate-100'}`}>{value}</div>
    </button>
  )
}

// stat key -> row predicate (mirrors how overview()/enrich() count each stat).
// Aggregate stats (Avg ACoS, Campaigns) have no row set — not clickable.
const STAT_FILTERS = {
  parents: p => p.parentage === 'parent',
  children: p => p.parentage === 'child',
  standalone: p => p.parentage !== 'parent' && p.parentage !== 'child',
  priced: p => p.price != null,
  missing_image: p => p.parentage !== 'parent' && !p.main_image,
  missing_desc: p => p.parentage !== 'parent' && !p.desc_chars,
  listing_issues: p => (p.seo_issues || 0) > 0,
  advertised: p => !!p.ads,
  over_be: p => p.be_status === 'bleeding',
  under_be: p => p.be_status === 'profitable',
}
const STAT_LABELS = {
  parents: 'variation families', children: 'child variations', standalone: 'standalone',
  priced: 'priced', missing_image: 'missing image',
  missing_desc: 'missing description', listing_issues: 'listing issues',
  advertised: 'advertised', over_be: 'over break-even', under_be: 'under break-even',
}

// editable per-SKU COGS (% of selling price, default 40%). Accepts a decimal
// (0.35) or a percent (35 / 35%); empty clears back to the default.
function CogsCell({ p, onSave }) {
  const [edit, setEdit] = useState(false)
  const [val, setVal] = useState('')
  const be = p.be
  if (p.parentage === 'parent') return <span className="text-mute">—</span>
  if (edit) return (
    <input autoFocus value={val} onChange={e => setVal(e.target.value)}
      onKeyDown={async e => {
        if (e.key === 'Enter') { setEdit(false); await onSave(p.sku, val) }
        if (e.key === 'Escape') setEdit(false)
      }}
      onBlur={() => setEdit(false)}
      placeholder="35% / 0.35 / empty = 40%"
      className="w-24 bg-ink border border-primary rounded px-1.5 py-0.5 font-mono text-xs text-slate-100 focus:outline-none" />
  )
  const pct = be?.cogs_pct
  return (
    <button onClick={() => { setVal(pct != null ? String(Math.round(pct * 1000) / 10) : ''); setEdit(true) }}
      className="hover:text-lime text-right"
      title={`COGS ${pct != null ? `${(pct * 100).toFixed(1)}% of selling price` : ''}${be?.cogs_custom ? ' (custom)' : ' (default 40%)'} — click to edit (decimal 0.35 or percent 35%; empty = back to 40% default)`}>
      {pct == null ? <span className="text-mute">40%</span> : (
        <span className={be.cogs_custom ? '' : 'text-mute'}>
          {(pct * 100).toFixed(0)}%{be.cogs != null && <span className="text-mute text-[10px]"> {money2(be.cogs)}</span>}
        </span>
      )}
    </button>
  )
}

export function ProductCatalogPanel({ scope, onAudit }) {
  const toast = useToast()
  const { confirm } = useModals()
  const inputRef = useRef()
  const feeRef = useRef()
  const [data, setData] = useState(null)
  const [fees, setFees] = useState(null)      // per-unit fee report coverage
  const [busyFee, setBusyFee] = useState(false)
  const [err, setErr] = useState(null)
  const [busyUp, setBusyUp] = useState(false)
  const [upNote, setUpNote] = useState(null)
  const [detail, setDetail] = useState(null)   // full item payload for the modal
  const [detBusy, setDetBusy] = useState(false)
  const [auditFor, setAuditFor] = useState(null)  // {sku, title} -> project picker open
  const [repBusy, setRepBusy] = useState(false)
  const [statFilter, setStatFilter] = useState(null)  // active stat-card filter key

  function load() {
    api.catalog().then(setData).catch(e => setErr(String(e)))
    api.catalogFbaFees().then(setFees).catch(() => setFees(null))
  }
  useEffect(() => {
    setData(null); setErr(null); setUpNote(null); setDetail(null); setFees(null)
    setStatFilter(null)
    load()
  }, [scope])  // eslint-disable-line

  // Amazon splits the report per category — allow picking several files at once;
  // each upserts by SKU into the same store catalog.
  async function upload(files) {
    const list = [...(files || [])]
    if (!list.length) return
    setBusyUp(true); setErr(null)
    let added = 0, updated = 0, last = null
    try {
      for (const f of list) {
        const r = await api.catalogUpload(f)
        added += r.added; updated += r.replaced; last = r
      }
      setData(last)
      const note = `${list.length} file${list.length > 1 ? 's' : ''} · ${added} products added${updated ? ` · ${updated} updated` : ''}`
      setUpNote(note); toast.success(note)
    } catch (e) {
      const msg = String(e?.message || e).replace(/^Error:\s*/, '')
      setErr(msg); toast.error(msg); load()
    } finally { setBusyUp(false); if (inputRef.current) inputRef.current.value = '' }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear product catalog?', danger: true, confirmLabel: 'Clear catalog',
      message: 'Removes every product uploaded from Category Listings Reports for THIS store only.\n\nThis cannot be undone (re-upload the reports to rebuild).',
    })
    if (!ok) return
    await api.catalogClear().catch(e => toast.error(String(e)))
    setUpNote(null); load()
  }

  // exec report — xlsx with native Excel charts mirroring this tab
  async function exportReport() {
    setRepBusy(true)
    try {
      const blob = await api.catalogExport()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'product_benchmark_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Product Benchmark report downloaded — Overview · Products')
    } catch (e) { const msg = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(msg); toast.error(msg) }
    finally { setRepBusy(false) }
  }

  async function openDetail(sku) {
    setDetBusy(true)
    try { setDetail(await api.catalogItem(sku)) }
    catch (e) { toast.error(String(e?.message || e)) }
    finally { setDetBusy(false) }
  }

  // per-SKU COGS override -> recompute break-even/profit account-wide
  async function saveCogs(sku, value) {
    try {
      const r = await api.catalogSetCogs(sku, value.trim())
      toast.success(`${sku}: COGS ${r.cogs_pct != null ? `${(r.cogs_pct * 100).toFixed(1)}%` : 'back to 40% default'}`
        + (r.be?.break_even_acos != null ? ` · BE ${(r.be.break_even_acos * 100).toFixed(1)}%` : ''))
      load()
    } catch (e) { toast.error(String(e?.message || e).replace(/^Error:\s*/, '')) }
  }

  // Selling economics / FBA Fee Preview -> base fulfillment fee + referral fee
  // per unit (store-level). Matched onto CHILD/standalone ASINs only — a parent
  // ASIN is not a purchasable unit and has no fee.
  async function uploadFees(files) {
    const list = [...(files || [])]
    if (!list.length) return
    setBusyFee(true); setErr(null)
    try {
      let last = null
      for (const f of list) last = await api.catalogFbaUpload(f)
      setFees(await api.catalogFbaFees())
      toast.success(`fulfillment fees · ${last.added} SKUs added${last.replaced ? ` · ${last.replaced} updated` : ''}`
        + ` · ${last.matched_asins} ASINs matched`)
      load()
    } catch (e) {
      const msg = String(e?.message || e).replace(/^Error:\s*/, '')
      setErr(msg); toast.error(msg)
    } finally { setBusyFee(false); if (feeRef.current) feeRef.current.value = '' }
  }

  async function clearFees() {
    const ok = await confirm({
      title: 'Clear fulfillment fees?', danger: true, confirmLabel: 'Clear fees',
      message: 'Removes the uploaded per-unit fulfillment / referral fees for THIS store.\n\nBreak-even ACoS falls back to the Transactions-ledger FBA fee (or $0 when there is none).',
    })
    if (!ok) return
    await api.catalogFbaClear().catch(e => toast.error(String(e)))
    setFees(null); load()
  }

  const FeeBtn = (
    <>
      <button onClick={() => feeRef.current?.click()} disabled={busyFee} aria-busy={busyFee}
        title="Seller Central > Reports > Business > Selling economics (or Fulfilment > Fee Preview) — base fulfillment fee + referral fee per unit. Feeds break-even ACoS and profit/unit."
        className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-50">
        <Icon name={busyFee ? 'sync' : 'local_shipping'} size={14} />
        {busyFee ? 'Reading…' : 'Upload Selling Economics'}
      </button>
      <input ref={feeRef} type="file" accept=".csv,.txt,.tsv,.xlsx,.xlsm" multiple className="hidden"
        onChange={e => uploadFees(e.target.files)} />
    </>
  )

  const UploadBtn = (
    <>
      <button onClick={() => inputRef.current?.click()} disabled={busyUp} aria-busy={busyUp}
        className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
        <Icon name={busyUp ? 'sync' : 'upload'} size={14} />
        {busyUp ? 'Reading…' : 'Upload Category Listings Report'}
      </button>
      <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" multiple className="hidden"
        onChange={e => upload(e.target.files)} />
    </>
  )

  if (!data && !err) return (
    <div className="space-y-6">
      <div className="card p-4"><StatsSkeleton count={5} /></div>
      <div className="card"><TableSkeleton rows={8} cols={7} /></div>
    </div>
  )

  const stats = data?.stats
  if (err || !stats || stats.total === 0) return (
    <div className="space-y-4">
      {err && <div className="card border-down/40 p-3 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
      <div className="card p-8 text-center space-y-3">
        <div className="font-mono text-sm text-slate-200">No products in this store's catalog yet</div>
        <div className="font-mono text-xs text-mute max-w-lg mx-auto">
          Product Benchmark is the <span className="text-slate-200">store-level product base</span>: titles,
          descriptions, bullet points, selling prices, images and variation families — mapped from your{' '}
          <span className="text-slate-200">Amazon Category Listings Report</span> (Seller Central → Reports).
          Amazon exports one file per category; upload each one and they merge by SKU.
        </div>
        <div className="flex justify-center gap-2">{UploadBtn}{FeeBtn}</div>
      </div>
    </div>
  )

  const filtered = statFilter && STAT_FILTERS[statFilter]
    ? data.products.filter(STAT_FILTERS[statFilter]) : data.products

  const COLS = [
    { key: 'main_image', label: '', render: p => <Thumb src={p.main_image} />, value: p => (p.main_image ? 1 : 0) },
    { key: 'title', label: 'Product', render: p => (
        <button onClick={() => openDetail(p.sku)} className="text-left hover:text-lime" title={p.title}>
          <span className="truncate inline-block align-bottom" style={{ maxWidth: 340 }}>{p.title || '—'}</span>
        </button>) },
    { key: 'sku', label: 'SKU', cellClass: 'text-mute', render: p => trunc(p.sku, 130, 'text-mute') },
    { key: 'asin', label: 'ASIN', render: p => p.asin
        ? <a href={`https://www.amazon.com/dp/${p.asin}`} target="_blank" rel="noreferrer" className="hover:text-lime">{p.asin}</a>
        : <span className="text-mute">—</span> },
    { key: 'product_type', label: 'Type', cellClass: 'text-mute', render: p => trunc(p.product_type, 120, 'text-mute') },
    { key: 'parentage', label: 'Variation', render: p => <VariationBadge p={p} /> },
    { key: 'variant', label: 'Color / Size', cellClass: 'text-mute',
      value: p => [p.color, p.size].filter(Boolean).join(' / '),
      render: p => trunc([p.color, p.size].filter(Boolean).join(' / ') || '', 120, 'text-mute') },
    { key: 'price', label: 'Price', align: 'right', value: p => p.price, render: p => <PriceCell p={p} /> },
    { key: 'cogs', label: 'COGS', align: 'right', value: p => p.be?.cogs_pct ?? -1,
      render: p => <CogsCell p={p} onSave={saveCogs} /> },
    { key: 'total_fee', label: 'Total Fees', align: 'right',
      value: p => p.be?.total_fee ?? p.be?.amazon_fee ?? -1,
      render: p => <TotalFeesCell be={p.be} /> },
    { key: 'profit_unit', label: 'Profit / Unit', align: 'right', value: p => p.be?.profit_per_unit ?? -999,
      render: p => p.be?.profit_per_unit != null
        ? <span className={p.be.profit_per_unit > 0 ? 'text-up' : 'text-down'}
            title={`price ${money2(p.be.price)} − COGS ${money2(p.be.cogs)} − total fees ${money2(p.be.amazon_fee)} (fulfillment ${money2(p.be.fba_fee)} + referral ${money2(p.be.referral_fee)})`}>{money2(p.be.profit_per_unit)}</span>
        : <span className="text-mute">—</span> },
    { key: 'campaigns', label: 'Campaigns', align: 'right',
      value: p => p.ads?.campaigns ?? -1, render: p => <CampaignsCell a={p.ads} /> },
    { key: 'ad_spend', label: 'Ad Spend', align: 'right', value: p => p.ads?.spend ?? -1,
      render: p => p.ads?.spend ? money2(p.ads.spend) : <span className="text-mute">—</span> },
    { key: 'acos_be', label: 'ACoS / BE', align: 'right',
      // sort: bleeding-no-sales worst (9), then ACoS desc; unadvertised last
      value: p => p.ads?.spend ? (p.ads.sales ? p.ads.acos : 9) : -1,
      render: p => <AcosBECell p={p} /> },
    { key: 'status', label: 'Status', render: p => p.status
        ? <span className={p.status.toLowerCase() === 'active' ? 'text-up' : 'text-mute'}>{p.status.toLowerCase()}</span>
        : <span className="text-mute">—</span> },
    { key: 'image_count', label: 'Imgs', align: 'right',
      render: p => p.image_count ? p.image_count : <span className="text-down">0</span> },
    { key: 'bullet_count', label: 'Bullets', align: 'right',
      render: p => p.bullet_count ? p.bullet_count : <span className="text-down">0</span> },
    { key: 'desc_chars', label: 'Desc', align: 'right',
      render: p => p.desc_chars ? p.desc_chars.toLocaleString() : <span className="text-down">0</span> },
    { key: 'seo_issues', label: 'SEO', align: 'right', value: p => p.seo_issues ?? -1,
      render: p => p.seo_issues == null ? <span className="text-mute">—</span>
        : p.seo_issues === 0 ? <span className="text-up">✓</span>
        : <span className={p.seo_issues >= 3 ? 'text-down' : 'text-amber'} title="high + medium SEO issues — open the product for the full list">{p.seo_issues}</span> },
    { key: 'audit', label: '', render: p => (
        <button onClick={() => setAuditFor({ sku: p.sku, title: p.title, asin: p.asin })}
          className="btn btn-ghost text-[11px] whitespace-nowrap flex items-center gap-1"
          title="Import this product's copy into Product Optimization and open Listing Audit">
          <Icon name="fact_check" size={13} /> Listing Audit
        </button>) },
  ]

  return (
    <div className="space-y-6">
      {upNote && <div className="card border-up/40 p-2 font-mono text-xs text-up inline-flex items-center gap-1"><Icon name="check_circle" size={12} /> {upNote}</div>}

      <div className="card">
        <div className="p-4 border-b border-edge flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">product benchmark · category listings catalog (store-level)</div>
            <div className="text-xs text-mute font-mono flex gap-3 flex-wrap">
              {(data.files || []).map(f => (
                <span key={f.name} title={`uploaded ${f.uploaded || ''}`}>
                  <Icon name="description" size={11} className="align-[-1px]" /> {f.name} · {f.rows}
                </span>
              ))}
              {data.updated && <span>updated {data.updated.slice(0, 10)}</span>}
              {fees?.skus > 0
                ? <span className="text-slate-200" title={`base fulfillment fee per unit · avg ${money2(fees.avg_fee)} · range ${money2(fees.min_fee)}–${money2(fees.max_fee)}`}>
                    <Icon name="local_shipping" size={11} className="align-[-1px]" /> {fees.skus} SKU fees · {fees.matched_asins} ASINs
                    <button onClick={clearFees} className="ml-1 hover:text-down" title="Clear uploaded fulfillment fees">✕</button>
                  </span>
                : <span title="Break-even ACoS currently prices fulfillment at $0 for SKUs with no transaction history">
                    <Icon name="local_shipping" size={11} className="align-[-1px]" /> no fulfillment fees uploaded
                  </span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {UploadBtn}
            {FeeBtn}
            <button onClick={exportReport} disabled={repBusy} aria-busy={repBusy}
              title="one workbook with charts: Overview (composition pie, issues-by-area bar) · Products (per-product SEO + PPC/break-even join)"
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="monitoring" size={14} />{repBusy ? 'Building…' : 'Export Report'}
            </button>
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          </div>
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
          {(() => {
            const S = (key) => key && ({
              active: statFilter === key,
              onClick: () => setStatFilter(f => f === key ? null : key),
            })
            return <>
              <FilterStat label="Products" value={stats.total.toLocaleString()} accent
                active={statFilter == null} onClick={() => setStatFilter(null)} />
              <FilterStat label="Variation Families" value={stats.parents.toLocaleString()} {...S('parents')} />
              <FilterStat label="Child Variations" value={stats.children.toLocaleString()} {...S('children')} />
              <FilterStat label="Standalone" value={stats.standalone.toLocaleString()} {...S('standalone')} />
              <FilterStat label="Priced" value={stats.priced.toLocaleString()} {...S('priced')} />
              <FilterStat label="Brands" value={stats.brands.toLocaleString()} />
              <FilterStat label="Missing Image" value={stats.missing_image.toLocaleString()} {...S('missing_image')} />
              <FilterStat label="Missing Description" value={stats.missing_desc.toLocaleString()} {...S('missing_desc')} />
              <FilterStat label="Listing Issues" value={(stats.listing_issues ?? 0).toLocaleString()}
                accent={stats.listing_issues ? 'text-amber' : undefined} {...S('listing_issues')} />
              <FilterStat label="Advertised" value={(stats.advertised ?? 0).toLocaleString()} {...S('advertised')} />
              <FilterStat label="Avg ACoS" value={stats.avg_acos != null ? pct1(stats.avg_acos) : '—'} />
              <FilterStat label="Campaigns" value={(stats.campaigns ?? 0).toLocaleString()} />
              <FilterStat label="Over Break-Even" value={(stats.over_be ?? 0).toLocaleString()}
                accent={stats.over_be ? 'text-down' : undefined} {...S('over_be')} />
              <FilterStat label="Under Break-Even" value={(stats.under_be ?? 0).toLocaleString()}
                accent={stats.under_be ? 'text-up' : undefined} {...S('under_be')} />
            </>
          })()}
        </div>
        {!data.ads_connected && (
          <div className="px-4 pb-3 -mt-1 font-mono text-[11px] text-mute flex items-center gap-1">
            <Icon name="info" size={12} /> No Product Ads data in the selected audit — upload a Sponsored
            Products bulk in the <span className="text-slate-200">Product Ads</span> tab to see campaigns,
            ad spend and ACoS vs break-even per ASIN here.
          </div>
        )}
      </div>

      <div className="card">
        {statFilter && (
          <div className="px-4 pt-3 font-mono text-[11px] flex items-center gap-2">
            <Icon name="filter_alt" size={12} className="text-lime" />
            <span className="text-slate-200">{STAT_LABELS[statFilter]}</span>
            <span className="text-mute">· {filtered.length} of {data.products.length} products</span>
            <button onClick={() => setStatFilter(null)} className="text-mute hover:text-down" title="clear filter">✕</button>
          </div>
        )}
        <DataTable columns={COLS} rows={filtered} scope={`${scope}:${statFilter || 'all'}`}
          rowKey={(p) => p.sku || p.asin}
          searchKeys={['title', 'sku', 'asin', 'brand', 'product_type', 'color', 'size', 'parent_sku']}
          placeholder="search title / SKU / ASIN / type / color…"
          empty={statFilter ? `no ${STAT_LABELS[statFilter]} products` : 'no products'} />
      </div>


      <Modal open={!!(detail || detBusy)} onClose={() => setDetail(null)} size="2xl"
        title={detail ? (detail.title || detail.sku) : 'Loading…'}
        subtitle={detail ? `SKU ${detail.sku}${detail.asin ? ` · ASIN ${detail.asin}` : ''}` : ''}>
        {detBusy && <TableSkeleton rows={4} cols={3} toolbar={false} />}
        {detail && !detBusy && (
          <ItemDetail p={detail} onOpen={openDetail}
            onAudit={() => setAuditFor({ sku: detail.sku, title: detail.title, asin: detail.asin })} />
        )}
      </Modal>

      <AuditPicker target={auditFor} onClose={() => setAuditFor(null)}
        onDone={(pid) => { setAuditFor(null); setDetail(null); onAudit?.(pid, auditFor?.asin || '') }} />
    </div>
  )
}

// "Perform Listing Audit" hand-off: pick (or create) the Product Optimization
// project, import the catalog product's copy into it, then jump to Listing Audit.
function AuditPicker({ target, onClose, onDone }) {
  const toast = useToast()
  const [projects, setProjects] = useState(null)
  const [pid, setPid] = useState(null)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!target) return
    setProjects(null); setPid(null); setNewName('')
    api.trackerProjects()
      .then(d => { setProjects(d.projects || []); setPid(d.projects?.[0]?.id ?? 'new') })
      .catch(e => { toast.error(String(e?.message || e)); setProjects([]) ; setPid('new') })
  }, [target])  // eslint-disable-line

  async function run() {
    setBusy(true)
    try {
      let id = pid
      if (id === 'new') {
        const name = newName.trim() || (target.title || target.sku).slice(0, 80)
        // new projects inherit the product's ASIN as primary ASIN automatically
        id = (await api.trackerCreateProject(name, target.asin || undefined)).project_id
      }
      const r = await api.trackerFromCatalog(id, target.sku)
      const kw = r.keywords_added ? ` + ${r.keywords_added} search-term keywords tracked (SEO)` : ''
      toast.success(`Imported ${r.imported.length ? r.imported.join(', ').replace(/_/g, ' ') : 'nothing'}${kw} — opening Listing Audit`)
      onDone(id)
    } catch (e) { toast.error(String(e?.message || e).replace(/^Error:\s*/, '')) }
    finally { setBusy(false) }
  }

  return (
    <Modal open={!!target} onClose={onClose} size="md" title="Perform Listing Audit"
      subtitle={target ? `SKU ${target.sku}${target.asin ? ` · ASIN ${target.asin}` : ''}` : ''}
      footer={
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn btn-ghost text-xs">Cancel</button>
          <button onClick={run} disabled={busy || pid == null || (pid === 'new' && !projects)}
            aria-busy={busy} className="btn btn-primary text-xs disabled:opacity-50">
            {busy ? 'Importing…' : 'Import copy & open Listing Audit'}
          </button>
        </div>
      }>
      <div className="space-y-3 font-mono text-xs">
        <div className="text-mute">
          Pulls this product's <span className="text-slate-200">title, bullet points, description and
          search terms</span> from the catalog into a Product Optimization project's own listing copy
          (existing pastes for those elements are replaced), adds its search terms as
          <span className="text-slate-200"> tracked keywords</span> for the <span className="text-slate-200">SEO</span> tab
          (deduped against the project's list), then opens the <span className="text-slate-200">Listing
          Audit</span> view.
        </div>
        {!projects && <div className="text-mute">loading projects…</div>}
        {projects && (
          <div className="space-y-1.5">
            {projects.map(p => (
              <label key={p.id} className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="audit-proj" className="accent-lime"
                  checked={pid === p.id} onChange={() => setPid(p.id)} />
                <span className={pid === p.id ? 'text-slate-100' : 'text-mute'}>{p.name}</span>
              </label>
            ))}
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="audit-proj" className="accent-lime"
                checked={pid === 'new'} onChange={() => setPid('new')} />
              <span className={pid === 'new' ? 'text-slate-100' : 'text-mute'}>new project:</span>
              <input value={newName} onFocus={() => setPid('new')} onChange={e => { setPid('new'); setNewName(e.target.value) }}
                placeholder={(target?.title || '').slice(0, 40) || 'project name'}
                className="flex-1 bg-ink border border-edge rounded px-2 py-1 text-slate-100 focus:outline-none focus:border-primary" />
            </label>
          </div>
        )}
      </div>
    </Modal>
  )
}

// Catalog-level SEO recommendations inside the detail modal — computed from the
// Category Listings Report fields alone (lengths, 249-byte backend field, wasted
// words, images). "Perform Listing Audit" adds the keyword-based recs on top.
const SEO_SEV = { high: 'text-down border-down/40', medium: 'text-amber border-amber/40', low: 'text-mute border-edge' }

function SeoSection({ seo }) {
  if (!seo) return null
  const c = seo.counts || {}
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider">seo recommendations · from the listing report</div>
        <span className="font-mono text-[10px]">
          {c.high > 0 && <span className="text-down">{c.high} high</span>}
          {c.medium > 0 && <span className="text-amber"> · {c.medium} med</span>}
          {c.low > 0 && <span className="text-mute"> · {c.low} low</span>}
        </span>
      </div>
      {seo.recommendations.length === 0 ? (
        <div className="font-mono text-xs text-up">✓ no listing-level issues — run Perform Listing Audit for keyword coverage</div>
      ) : (
        <div className="space-y-1.5">
          {seo.recommendations.map((r, i) => (
            <div key={i} className={`font-mono text-xs border-l-2 pl-2 py-0.5 ${SEO_SEV[r.severity] || SEO_SEV.low}`}>
              <span className="uppercase text-[9px] mr-2">{r.severity}</span>
              <span className="text-slate-200">{r.title}</span>
              <span className="text-mute"> — {r.action}</span>
              {r.words?.length > 0 && <span className="text-mute"> ({r.words.join(', ')})</span>}
            </div>
          ))}
          <div className="font-mono text-[10px] text-mute">
            Keyword-based recommendations (title coverage, backend search-term line) come from
            <span className="text-slate-200"> Perform Listing Audit</span> — it tracks this product's search terms in Product Optimization.
          </div>
        </div>
      )}
    </div>
  )
}

// PPC block inside the detail modal: this ASIN's campaigns from the audit's
// Product Ads upload + its break-even economics (catalog price / benchmark).
function PpcSection({ p }) {
  const a = p.ads, be = p.be
  if (!a && !be) return null
  const statusCls = p.be_status === 'bleeding' ? 'text-down' : p.be_status === 'profitable' ? 'text-up' : undefined
  const CAMP_COLS = [
    { key: 'name', label: 'Campaign', render: c => trunc(c.name, 260) },
    { key: 'type', label: 'Type', cellClass: 'text-mute' },
    { key: 'state', label: 'State', cellClass: 'text-mute' },
    { key: 'spend', label: 'Spend', align: 'right', value: c => c.metrics?.spend, render: c => money2(c.metrics?.spend) },
    { key: 'sales', label: 'Sales', align: 'right', value: c => c.metrics?.sales, render: c => money2(c.metrics?.sales) },
    { key: 'acos', label: 'ACoS', align: 'right', value: c => c.metrics?.acos ?? 9,
      render: c => {
        const v = c.metrics?.acos
        if (v == null) return c.metrics?.spend ? <span className="text-down">∞</span> : <span className="text-mute">—</span>
        const b = be?.break_even_acos
        return <span className={b != null ? (v > b ? 'text-down' : 'text-up') : ''}>{pct1(v)}</span>
      } },
    { key: 'orders', label: 'Orders', align: 'right', value: c => c.metrics?.orders, render: c => c.metrics?.orders ?? 0 },
  ]
  return (
    <div className="space-y-3">
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
        ppc · product ads &amp; break-even{be?.source === 'uploaded' && ' (benchmark upload)'}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Campaigns" value={a ? a.campaigns : '—'} />
        <Stat label="Ad Spend" value={a ? money2(a.spend) : '—'} />
        <Stat label="PPC Sales" value={a ? money2(a.sales) : '—'} />
        <Stat label="ACoS" value={a ? (a.sales ? pct1(a.acos) : (a.spend ? '∞' : '—')) : '—'} accent={statusCls} />
        <Stat label="Break-Even ACoS" value={pct1(be?.break_even_acos)} />
        <Stat label="Break-Even ROAS" value={be?.break_even_roas ?? '—'} />
        <Stat label="Profit / Unit" value={money2(be?.profit_per_unit)} />
        <Stat label={`Total Fees / Unit${be?.total_source === 'derived' ? ' (derived)' : ''}`}
          value={money2(be?.amazon_fee)} />
        <Stat label={`Fulfillment / Unit${be?.fba_source === 'ledger' ? ' (ledger)' : ''}`}
          value={be?.fba_fee ? money2(be.fba_fee) : '—'} />
        <Stat label={`Referral / Unit${be?.referral_pct != null ? ` (${(be.referral_pct * 100).toFixed(0)}%)` : ''}`}
          value={money2(be?.referral_fee)} />
        <Stat label={`COGS / Unit${be?.cogs_pct != null ? ` (${(be.cogs_pct * 100).toFixed(0)}%${be.cogs_custom ? '' : ' default'})` : ''}`}
          value={money2(be?.cogs)} />
      </div>
      {p.be_status && (
        <div className={`font-mono text-[11px] ${statusCls}`}>
          {p.be_status === 'bleeding'
            ? 'PPC ACoS is above break-even — every ad-driven sale loses money on this product.'
            : 'PPC ACoS is below break-even — ad-driven sales are profitable on this product.'}
        </div>
      )}
      {!p.ads_connected && (
        <div className="font-mono text-[11px] text-mute">
          No Product Ads data in the selected audit — upload a Sponsored Products bulk in the Product Ads tab.
        </div>
      )}
      {(a?.campaign_rows || []).length > 0 && (
        <DataTable title={`campaigns · ${a.campaign_rows.length}`} columns={CAMP_COLS} rows={a.campaign_rows} lean
          rowKey={(c, i) => c.campaign_id || i} empty="no campaigns" placeholder="search…" />
      )}
    </div>
  )
}

// Full listing detail: image gallery + attributes + price + bullets +
// description + search terms + the variation family.
function ItemDetail({ p, onOpen, onAudit }) {
  const gallery = [p.main_image, ...(p.images || [])].filter(Boolean)
  const [img, setImg] = useState(0)
  useEffect(() => { setImg(0) }, [p.sku])

  const FAM_COLS = [
    { key: 'main_image', label: '', render: c => <Thumb src={c.main_image} size={30} /> },
    { key: 'title', label: 'Product', render: c => (
        <button onClick={() => onOpen(c.sku)} className="text-left hover:text-lime" title={c.title}>
          <span className="truncate inline-block align-bottom" style={{ maxWidth: 300 }}>{c.title || c.sku}</span>
        </button>) },
    { key: 'sku', label: 'SKU', cellClass: 'text-mute' },
    { key: 'asin', label: 'ASIN', render: c => c.asin || <span className="text-mute">—</span> },
    { key: 'parentage', label: '', render: c => <VariationBadge p={c} /> },
    { key: 'variant', label: 'Color / Size', cellClass: 'text-mute',
      value: c => [c.color, c.size].filter(Boolean).join(' / ') },
    { key: 'price', label: 'Price', align: 'right', value: c => c.price, render: c => <PriceCell p={c} /> },
  ]

  return (
    <div className="space-y-5">
      <div className="flex gap-5 flex-wrap">
        {/* gallery */}
        <div className="space-y-2">
          <div className="w-56 h-56 rounded bg-white flex items-center justify-center overflow-hidden">
            {gallery.length
              ? <img src={gallery[img]} alt="" className="max-w-full max-h-full object-contain" />
              : <Icon name="image" size={48} className="text-mute" />}
          </div>
          {gallery.length > 1 && (
            <div className="flex gap-1 flex-wrap" style={{ maxWidth: 224 }}>
              {gallery.map((u, i) => (
                <button key={u + i} onClick={() => setImg(i)}
                  className={`rounded overflow-hidden border ${i === img ? 'border-lime' : 'border-edge'}`}>
                  <img src={u} alt="" className="w-9 h-9 object-contain bg-white" />
                </button>
              ))}
            </div>
          )}
        </div>
        {/* attributes */}
        <div className="flex-1 min-w-[260px] space-y-3 font-mono text-xs">
          <div className="flex gap-2 flex-wrap items-center">
            <VariationBadge p={p} />
            {p.status && <span className={`tag border border-edge ${p.status.toLowerCase() === 'active' ? 'text-up' : 'text-mute'}`}>{p.status.toLowerCase()}</span>}
            {p.product_type && <span className="tag border border-edge text-mute">{p.product_type}</span>}
            {onAudit && (
              <button onClick={onAudit} className="btn btn-primary text-[11px] flex items-center gap-1"
                title="Import this product's copy into Product Optimization and open Listing Audit">
                <Icon name="fact_check" size={13} /> Perform Listing Audit
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            {p.brand && <><span className="text-mute">Brand</span><span>{p.brand}</span></>}
            {p.asin && <><span className="text-mute">ASIN</span>
              <a href={`https://www.amazon.com/dp/${p.asin}`} target="_blank" rel="noreferrer" className="hover:text-lime">{p.asin} ↗</a></>}
            {p.parent_sku && <><span className="text-mute">Parent SKU</span><span>{p.parent_sku}</span></>}
            {p.variation_theme && <><span className="text-mute">Variation theme</span><span>{p.variation_theme}</span></>}
            {p.color && <><span className="text-mute">Color</span><span>{p.color}</span></>}
            {p.size && <><span className="text-mute">Size</span><span>{p.size}</span></>}
          </div>
          <div className="card p-3 grid grid-cols-3 gap-3">
            <Stat label="Selling Price" value={money2(p.price)} accent />
            <Stat label="Sale Price" value={money2(p.sale_price)} />
            <Stat label="List Price" value={money2(p.list_price)} />
          </div>
        </div>
      </div>

      <SeoSection seo={p.seo} />

      <PpcSection p={p} />

      {(p.bullets || []).length > 0 && (
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1.5">bullet points · {p.bullets.length}</div>
          <ul className="space-y-1.5 text-xs font-sans text-body/90 list-disc pl-4">
            {p.bullets.map((b, i) => <li key={i}>{b}</li>)}
          </ul>
        </div>
      )}

      {p.description && (
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1.5">description · {p.description.length.toLocaleString()} chars</div>
          <p className="text-xs font-sans text-body/90 whitespace-pre-wrap">{p.description}</p>
        </div>
      )}

      {(p.search_terms || []).length > 0 && (
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1.5">search terms</div>
          <div className="flex gap-1.5 flex-wrap">
            {p.search_terms.map((s, i) => <span key={i} className="tag border border-edge text-mute">{s}</span>)}
          </div>
        </div>
      )}

      {(p.family || []).length > 0 && (
        <DataTable title={`variation family · ${p.family.length}`} columns={FAM_COLS} rows={p.family} lean
          rowKey={(c, i) => c.sku || i} empty="no variations" placeholder="search…" />
      )}
    </div>
  )
}
