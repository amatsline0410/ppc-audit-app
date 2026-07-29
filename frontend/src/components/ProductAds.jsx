import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, money, pct, Stat, StateBadge, TableSkeleton, StatsSkeleton, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th, DataTable } from './table.jsx'
import { Modal, useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

const r2 = (x) => x == null ? '—' : Number(x).toFixed(2)
const num = (x) => (x ?? 0).toLocaleString()

// status -> label + tailwind color. Non-"ok" rows are action items.
const STATUS = {
  ok: ['converting', 'text-lime'],
  no_orders: ['no orders — fix/push', 'text-amber-400'],
  no_data: ['no traffic — push', 'text-orange-400'],
  no_campaign: ['no campaign — create', 'text-rose-400'],
}
function StatusBadge({ status }) {
  const [label, color] = STATUS[status] || [status, 'text-mute']
  return <span className={`${color} text-[11px] font-mono`}>{label}</span>
}

// campaign targeting kind -> label + color (Automatic / Keyword / Product target)
const CTYPE = {
  auto: ['Auto', 'text-cyan border-cyan/30'],
  keyword: ['KW tgt', 'text-lime border-lime/30'],
  product: ['PT tgt', 'text-amber-400 border-amber-400/30'],
  manual: ['Manual', 'text-mute border-edge'],
}
function CampType({ type }) {
  const [label, color] = CTYPE[type] || ['—', 'text-mute border-edge']
  return <span className={`tag border ${color}`}>{label}</span>
}

// Every Product Ad (ASIN + SKU) from Product Ads' OWN uploaded bulk (its own table,
// separate from the PPC Optimization data), with that bulk's metrics + one account total.
export function ProductAdsPanel({ scope }) {
  const toast = useToast()
  const { confirm } = useModals()
  const inputRef = useRef()
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [busyUp, setBusyUp] = useState(false)
  const [upInfo, setUpInfo] = useState(null)
  const [sel, setSel] = useState(new Set())   // selected ASINs
  const [repBusy, setRepBusy] = useState(false)
  const [detail, setDetail] = useState(null)  // drill-down result
  const [detBusy, setDetBusy] = useState(false)
  const [detErr, setDetErr] = useState(null)

  function load() {
    api.productAds().then(setData).catch(e => setErr(String(e)))
  }
  useEffect(() => {
    setData(null); setErr(null); setUpInfo(null); setSel(new Set()); setDetail(null); setDetErr(null)
    load()
  }, [scope])  // eslint-disable-line

  async function upload(file) {
    if (!file) return
    setBusyUp(true); setErr(null); setUpInfo(null)
    try {
      const s = await api.productAdsUpload(file)
      setUpInfo(`Ingested ${s.product_ads} product ads · ${s.asins} ASINs`)
      toast.success(`Uploaded ${s.product_ads} product ads · ${s.asins} ASINs`)
      load()
    } catch (e) { const msg = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(msg); toast.error(msg) }
    finally { setBusyUp(false); if (inputRef.current) inputRef.current.value = '' }
  }

  const ctl = useTableControls(data?.rows || [], {
    searchKeys: ['asin', 'sku', 'status'], deps: [scope],
  })

  function toggle(asin) {
    setSel(s => { const n = new Set(s); n.has(asin) ? n.delete(asin) : n.add(asin); return n })
  }
  async function viewSelected() {
    if (!sel.size) return
    setDetBusy(true); setDetErr(null)
    try { setDetail(await api.productAdsDetail([...sel])) }
    catch (e) { setDetErr(String(e)) }
    finally { setDetBusy(false) }
  }

  // exec report — xlsx with native Excel charts (status pie, campaign-kind +
  // top-spend bars) mirroring this tab
  async function exportReport() {
    setRepBusy(true)
    try {
      const blob = await api.productAdsExport()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'product_ads_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Product Ads report downloaded — Overview · Products')
    } catch (e) { const msg = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(msg); toast.error(msg) }
    finally { setRepBusy(false) }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear Product Ads data?', danger: true, confirmLabel: 'Clear data',
      message: 'Removes the uploaded Product Ads snapshot for this audit (its own table — the PPC Optimization '
        + 'data is not affected). The Product Benchmark tab\'s campaigns / ad spend / ACoS columns for '
        + 'this audit empty too.\n\nThis cannot be undone — re-upload the bulk to rebuild.',
    })
    if (!ok) return
    try {
      await api.productAdsClear()
      setSel(new Set()); setDetail(null); setUpInfo(null); setErr(null)
      toast.success('Cleared Product Ads data')
      load()
    } catch (e) { const msg = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(msg); toast.error(msg) }
  }

  const UploadBtn = (
    <>
      <button onClick={() => inputRef.current?.click()} disabled={busyUp} aria-busy={busyUp}
        className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
        <Icon name={busyUp ? 'sync' : 'upload'} size={14} />{busyUp ? 'Reading…' : 'Upload Sponsored Products Bulk'}
      </button>
      <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" className="hidden"
        onChange={e => upload(e.target.files?.[0])} />
    </>
  )

  if (!data && !err) return (
    <div className="space-y-6">
      <div className="card p-4"><StatsSkeleton count={5} /></div>
      <div className="card"><TableSkeleton rows={8} cols={6} /></div>
    </div>
  )

  // empty (nothing uploaded yet) or hard error -> prompt for the dedicated upload
  if (err || (data && data.count === 0)) return (
    <div className="space-y-4">
      {err && <div className="card border-down/40 p-3 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
      {upInfo && <div className="card border-up/40 p-3 font-mono text-xs text-up inline-flex items-center gap-1"><Icon name="check_circle" size={12} /> {upInfo}</div>}
      <div className="card p-8 text-center space-y-3">
        <div className="font-mono text-sm text-slate-200">No Product Ads yet</div>
        <div className="font-mono text-xs text-mute max-w-md mx-auto">
          Product Ads has its <span className="text-slate-200">own bulk upload</span> and its own data —
          separate from the PPC Optimization table. Upload a Sponsored Products bulk export (its Product Ad rows)
          to see every ASIN / SKU's ad performance.
        </div>
        <div className="flex justify-center">{UploadBtn}</div>
      </div>
    </div>
  )

  const t = data.total || {}
  const bs = data.by_status || {}
  const ct = data.campaign_types   // { auto, keyword, product, manual, total }
  const attn = (bs.no_orders || 0) + (bs.no_data || 0) + (bs.no_campaign || 0)
  const rows = ctl.view
  // header checkbox state for the visible page
  const pageAsins = rows.map(r => r.asin).filter(Boolean)
  const allOnPage = pageAsins.length > 0 && pageAsins.every(a => sel.has(a))
  function togglePage() {
    setSel(s => {
      const n = new Set(s)
      if (allOnPage) pageAsins.forEach(a => n.delete(a))
      else pageAsins.forEach(a => n.add(a))
      return n
    })
  }

  return (
    <div className="space-y-6">
      {upInfo && <div className="card border-up/40 p-2 font-mono text-xs text-up inline-flex items-center gap-1"><Icon name="check_circle" size={12} /> {upInfo}</div>}
      <div className="card">
        <div className="p-4 border-b border-edge flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">product ads · own bulk upload (separate from PPC audit)</div>
            <div className="text-xs text-mute font-mono flex gap-3 flex-wrap">
              {data.upload_meta && (
                <span><Icon name="description" size={11} className="align-[-1px]" /> {data.upload_meta.file} · {data.upload_meta.rows}</span>
              )}
              {data.upload_meta && <span>updated {data.upload_meta.uploaded}</span>}
              <span>{data.count} products</span>
              {ct && <span><span className="text-cyan">{ct.auto} auto</span> · <span className="text-lime">{ct.keyword} kw</span> · <span className="text-amber-400">{ct.product} pt</span>{ct.manual ? <> · {ct.manual} manual</> : null} campaigns</span>}
              {attn > 0 && <span className="text-amber-400">{attn} need attention</span>}
              {bs.no_orders ? <span className="text-amber-400">{bs.no_orders} no orders</span> : null}
              {bs.no_data ? <span className="text-orange-400">{bs.no_data} no traffic</span> : null}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {UploadBtn}
            <button onClick={exportReport} disabled={repBusy || !data.count} aria-busy={repBusy}
              title="one workbook with charts: Overview (status pie, campaign-kind bar) · Products (top-spend bar)"
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="monitoring" size={14} />{repBusy ? 'Building…' : 'Export Report'}
            </button>
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          </div>
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-5 gap-3">
          <Stat label="Ad Spend" value={money(t.spend)} />
          <Stat label="Ad Sales" value={money(t.sales)} accent />
          <Stat label="Orders (PPC)" value={num(t.orders)} />
          <Stat label="Clicks" value={num(t.clicks)} />
          <Stat label="Impressions" value={num(t.impressions)} />
          <Stat label="ACOS" value={pct(t.acos)} />
          <Stat label="Avg Product ACOS" value={data.avg_acos != null ? pct(data.avg_acos) : '—'} />
          <Stat label="ROAS" value={t.roas == null ? '—' : `${r2(t.roas)}×`} />
          <Stat label="CPC" value={t.cpc == null ? '—' : `$${r2(t.cpc)}`} />
          <Stat label="CTR" value={pct(t.ctr)} />
          <Stat label="CVR" value={pct(t.cvr)} />
        </div>
      </div>

      <Modal open={!!(detBusy || detErr || detail)} onClose={() => { setDetail(null); setDetErr(null) }} size="2xl"
        title="Selected ASIN detail" subtitle="ads · campaigns">
        {detBusy && <TableSkeleton rows={5} cols={4} toolbar={false} />}
        {detErr && <div className="card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {detErr}</div>}
        {detail && !detBusy && (
          <div className="divide-y divide-edge -m-4">
            {detail.rows.map(r => <AsinDetail key={r.asin} r={r} />)}
            {detail.rows.length === 0 && <div className="p-5 text-center text-mute font-mono text-sm">no data for selection</div>}
          </div>
        )}
      </Modal>

      <div className="card">
        <TableToolbar ctl={ctl} placeholder="search ASIN / SKU / status…" right={
          <>
            {sel.size > 0 && <button onClick={() => setSel(new Set())} className="tag border border-edge text-mute hover:text-red mr-1">clear {sel.size}</button>}
            <button onClick={viewSelected} disabled={!sel.size || detBusy} aria-busy={detBusy}
              className={`tag mr-1 ${sel.size ? 'bg-lime text-ink' : 'border border-edge text-mute opacity-50'}`}>
              {detBusy ? 'loading…' : `▤ view selected (${sel.size})`}
            </button>
          </>
        } />
        <div className="overflow-x-auto">
        <table className="w-full text-sm font-mono">
          <thead>
            <tr className="text-mute text-[11px] uppercase tracking-wider border-b border-edge">
              <th className="p-2 w-8"><input type="checkbox" checked={allOnPage} onChange={togglePage} className="accent-lime" /></th>
              <Th ctl={ctl} k="asin">ASIN</Th>
              <Th ctl={ctl} k="sku">SKU</Th>
              <Th ctl={ctl} k="status">Status</Th>
              <Th ctl={ctl} k="state">State</Th>
              <Th ctl={ctl} k="auto_campaigns" align="right">Auto</Th>
              <Th ctl={ctl} k="keyword_campaigns" align="right">KW tgt</Th>
              <Th ctl={ctl} k="product_campaigns" align="right">PT tgt</Th>
              <Th ctl={ctl} k="unit_price" align="right">Unit Price</Th>
              <Th ctl={ctl} k="aov" align="right">AOV</Th>
              <Th ctl={ctl} k="spend" align="right">Spend</Th>
              <Th ctl={ctl} k="sales" align="right">Sales</Th>
              <Th ctl={ctl} k="orders" align="right">Orders</Th>
              <Th ctl={ctl} k="clicks" align="right">Clicks</Th>
              <Th ctl={ctl} k="impressions" align="right">Impr</Th>
              <Th ctl={ctl} k="acos" align="right">ACOS</Th>
              <Th ctl={ctl} k="break_even_acos" align="right">BE ACoS</Th>
              <Th ctl={ctl} k="roas" align="right">ROAS</Th>
              <Th ctl={ctl} k="cpc" align="right">CPC</Th>
              <Th ctl={ctl} k="ctr" align="right">CTR</Th>
              <Th ctl={ctl} k="cvr" align="right">CVR</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.asin}|${r.sku}`} className={`border-b border-edge/40 hover:bg-edge/20 ${r.asin && sel.has(r.asin) ? 'bg-lime/5' : ''}`}>
                <td className="p-2">{r.asin && <input type="checkbox" checked={sel.has(r.asin)} onChange={() => toggle(r.asin)} className="accent-lime" />}</td>
                <td className="p-2">{r.asin || '—'}{r.ads > 1 && <span className="ml-1 text-mute text-[10px]">×{r.ads}</span>}</td>
                <td className="p-2 text-mute">{r.sku || '—'}</td>
                <td className="p-2"><StatusBadge status={r.status} /></td>
                <td className="p-2">{r.state ? <StateBadge state={r.state} /> : <span className="text-mute">—</span>}</td>
                <td className="p-2 text-right text-cyan" title="Automatic campaigns">{r.auto_campaigns ? num(r.auto_campaigns) : <span className="text-mute">—</span>}</td>
                <td className="p-2 text-right text-lime" title="Keyword-target campaigns">{r.keyword_campaigns ? num(r.keyword_campaigns) : <span className="text-mute">—</span>}</td>
                <td className="p-2 text-right text-amber-400" title="Product-target campaigns">{r.product_campaigns ? num(r.product_campaigns) : <span className="text-mute">—</span>}</td>
                <td className={`p-2 text-right ${r.unit_price < 0 ? 'text-rose-400' : ''}`}>{r.unit_price == null ? '—' : `${r.unit_price < 0 ? '-' : ''}$${Math.abs(r.unit_price).toFixed(2)}`}</td>
                <td className="p-2 text-right">{r.aov == null ? '—' : `$${r2(r.aov)}`}</td>
                <td className="p-2 text-right">{money(r.spend)}</td>
                <td className="p-2 text-right">{money(r.sales)}</td>
                <td className="p-2 text-right">{num(r.orders)}</td>
                <td className="p-2 text-right">{num(r.clicks)}</td>
                <td className="p-2 text-right">{num(r.impressions)}</td>
                <td className={`p-2 text-right ${r.break_even_acos != null && r.acos != null ? (r.acos > r.break_even_acos ? 'text-down' : 'text-up') : ''}`}
                  title={r.break_even_acos != null ? `break-even ${(r.break_even_acos * 100).toFixed(1)}% — red = ACoS above it (losing money per ad sale)` : ''}>{pct(r.acos)}</td>
                <td className="p-2 text-right text-mute"
                  title="break-even ACoS: benchmark upload wins, else catalog price + per-SKU COGS (default 40%)">{r.break_even_acos != null ? pct(r.break_even_acos) : '—'}</td>
                <td className="p-2 text-right">{r.roas == null ? '—' : `${r2(r.roas)}×`}</td>
                <td className="p-2 text-right">{r.cpc == null ? '—' : `$${r2(r.cpc)}`}</td>
                <td className="p-2 text-right">{pct(r.ctr)}</td>
                <td className="p-2 text-right">{pct(r.cvr)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={21} className="p-6 text-center text-mute">{ctl.query ? 'no matches' : 'no product ads in this bulk'}</td></tr>
            )}
          </tbody>
        </table>
        </div>
        <Pagination ctl={ctl} />
      </div>
    </div>
  )
}

// Drill-down for one selected ASIN: roll-up stats + its ads + per-campaign rollups
// (all from Product Ads' own data — no audit flags / strategy).
function AsinDetail({ r }) {
  const t = r.total || {}
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="font-mono text-slate-100 font-bold">{r.asin}</span>
        <span className="text-mute text-xs font-mono">{r.ads.length} ads · {r.campaigns.length} campaigns</span>
        {r.campaign_types && (
          <span className="text-xs font-mono">
            <span className="text-cyan">{r.campaign_types.auto} auto</span> · <span className="text-lime">{r.campaign_types.keyword} kw</span> · <span className="text-amber-400">{r.campaign_types.product} pt</span>{r.campaign_types.manual ? <span className="text-mute"> · {r.campaign_types.manual} manual</span> : null}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Ad Spend" value={money(t.spend)} />
        <Stat label="Ad Sales" value={money(t.sales)} accent />
        <Stat label="Orders" value={num(t.orders)} />
        <Stat label="ACOS" value={pct(t.acos)} />
        <Stat label="ROAS" value={t.roas == null ? '—' : `${r2(t.roas)}×`} />
      </div>

      {/* ads */}
      <DataTable title={`product ads · ${r.ads.length}`} columns={DETAIL_AD_COLS} rows={r.ads} lean
        rowKey={(a, i) => `${a.ad_id || a.sku || ''}-${i}`} empty="no ads for this ASIN" placeholder="search SKU / campaign…" />

      {/* per-campaign rollups */}
      <DataTable title={`campaigns · ${r.campaigns.length}`} columns={DETAIL_CAMP_COLS} rows={r.campaigns} lean
        rowKey={(c, i) => c.campaign_id || i} empty="no campaigns" placeholder="search campaign…"
        initial={{ sort: { key: 'spend', dir: 'desc' } }} />
    </div>
  )
}

const trunc = (txt, w, cls = '') =>
  <span className={`truncate inline-block align-bottom ${cls}`} style={{ maxWidth: w }} title={txt}>{txt || '—'}</span>

// drill-down: one ad row (metrics nested under a.metrics)
const DETAIL_AD_COLS = [
  { key: 'sku', label: 'SKU', cellClass: 'text-mute', render: a => a.sku || '—' },
  { key: 'campaign', label: 'Campaign', render: a => trunc(a.campaign, 180) },
  { key: 'ad_group', label: 'Ad group', cellClass: 'text-mute', render: a => trunc(a.ad_group, 160, 'text-mute') },
  { key: 'state', label: 'State', render: a => (a.state ? <StateBadge state={a.state} /> : <span className="text-mute">—</span>) },
  { key: 'spend', label: 'Spend', align: 'right', value: a => a.metrics?.spend, render: a => money(a.metrics?.spend) },
  { key: 'sales', label: 'Sales', align: 'right', value: a => a.metrics?.sales, render: a => money(a.metrics?.sales) },
  { key: 'orders', label: 'Orders', align: 'right', value: a => a.metrics?.orders, render: a => num(a.metrics?.orders) },
  { key: 'acos', label: 'ACOS', align: 'right', value: a => a.metrics?.acos, render: a => pct(a.metrics?.acos) },
]

// drill-down: per-campaign rollup row
const DETAIL_CAMP_COLS = [
  { key: 'name', label: 'Campaign', render: c => trunc(c.name, 220) },
  { key: 'type', label: 'Type', value: c => c.type, render: c => <CampType type={c.type} /> },
  { key: 'state', label: 'State', render: c => (c.state ? <StateBadge state={c.state} /> : <span className="text-mute">—</span>) },
  { key: 'spend', label: 'Spend', align: 'right', value: c => c.metrics?.spend, render: c => money(c.metrics?.spend) },
  { key: 'sales', label: 'Sales', align: 'right', value: c => c.metrics?.sales, render: c => money(c.metrics?.sales) },
  { key: 'orders', label: 'Orders', align: 'right', value: c => c.metrics?.orders, render: c => num(c.metrics?.orders) },
  { key: 'acos', label: 'ACOS', align: 'right', value: c => c.metrics?.acos, render: c => pct(c.metrics?.acos) },
  { key: 'roas', label: 'ROAS', align: 'right', value: c => c.metrics?.roas, render: c => (c.metrics?.roas == null ? '—' : `${r2(c.metrics.roas)}×`) },
]
