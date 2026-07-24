import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Stat, TableSkeleton, Icon } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

// Transactions — SKU-level ledger from the Amazon Payments Date Range
// (transaction) report. STORE-scoped like the Product Benchmark catalog:
// uploads merge (matching rows update in place, months accumulate), the date
// filter narrows stats + per-SKU rollup + the transaction list, click a SKU
// row to drill down. Own tab in the "Product Base" sidebar group.

const money2 = (x) => x == null ? '—' : `$${Number(x).toFixed(2)}`

const trunc = (txt, w, cls = '') =>
  <span className={`truncate inline-block align-bottom ${cls}`} style={{ maxWidth: w }} title={txt}>{txt || '—'}</span>

const signMoney = (x, strong) => {
  if (x == null) return <span className="text-mute">—</span>
  const v = Number(x)
  const cls = v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-mute'
  return <span className={strong ? cls : v < 0 ? 'text-down' : ''}>{v < 0 ? `-$${Math.abs(v).toFixed(2)}` : `$${v.toFixed(2)}`}</span>
}
const TYPE_CLS = { order: 'text-up', refund: 'text-down' }

export function TransactionsPanel({ scope }) {
  const toast = useToast()
  const { confirm } = useModals()
  const inputRef = useRef()
  const [tx, setTx] = useState(null)
  const [err, setErr] = useState(null)
  const [busyUp, setBusyUp] = useState(false)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [sku, setSku] = useState(null)     // drill-down filter (client-side)
  const [repBusy, setRepBusy] = useState(false)

  function load(s = start, e = end) {
    api.catalogTxn(s || null, e || null).then(setTx).catch(x => setErr(String(x?.message || x)))
  }
  useEffect(() => {
    setTx(null); setErr(null); setStart(''); setEnd(''); setSku(null)
    api.catalogTxn().then(setTx).catch(x => setErr(String(x?.message || x)))
  }, [scope])  // eslint-disable-line

  async function upload(files) {
    const list = [...(files || [])]
    if (!list.length) return
    setBusyUp(true); setErr(null)
    let added = 0, updated = 0, dupes = 0
    try {
      for (const f of list) {
        const r = await api.catalogTxnUpload(f)
        added += r.added; updated += r.updated || 0; dupes += r.duplicates
      }
      toast.success(`${added} transactions added${updated ? ` · ${updated} updated` : ''}${dupes ? ` · ${dupes} already in the ledger` : ''}`)
      load()
    } catch (e) {
      const msg = String(e?.message || e).replace(/^Error:\s*/, '')
      setErr(msg); toast.error(msg)
    } finally { setBusyUp(false); if (inputRef.current) inputRef.current.value = '' }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear transaction ledger?', danger: true, confirmLabel: 'Clear transactions',
      message: 'Removes every uploaded transaction report row for THIS store only.\n\nThis cannot be undone (re-upload the reports to rebuild).',
    })
    if (!ok) return
    await api.catalogTxnClear().catch(e => toast.error(String(e)))
    setStart(''); setEnd(''); setSku(null); load('', '')
  }

  function setRange(s, e) { setStart(s); setEnd(e); setSku(null); load(s, e) }

  // exec report — xlsx with native Excel charts, honors the current date window
  async function exportReport() {
    setRepBusy(true)
    try {
      const blob = await api.catalogTxnExport(start || null, end || null)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'sku_transactions_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('SKU Transactions report downloaded — Overview · Daily Trend · By SKU · Transactions')
    } catch (e) { const msg = String(e?.message || e).replace(/^Error:\s*/, ''); setErr(msg); toast.error(msg) }
    finally { setRepBusy(false) }
  }

  const UpBtn = (
    <>
      <button onClick={() => inputRef.current?.click()} disabled={busyUp} aria-busy={busyUp}
        className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
        <Icon name={busyUp ? 'sync' : 'upload'} size={14} />
        {busyUp ? 'Reading…' : 'Upload Transaction Report'}
      </button>
      <input ref={inputRef} type="file" accept=".csv,.xlsx,.xlsm" multiple className="hidden"
        onChange={e => upload(e.target.files)} />
    </>
  )

  if (!tx && !err) return <div className="card"><TableSkeleton rows={4} cols={6} /></div>

  if (err || !tx || tx.total_rows === 0) return (
    <div className="space-y-4">
      {err && <div className="card border-down/40 p-3 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
      <div className="card p-8 text-center space-y-3">
        <div className="font-mono text-sm text-slate-200">No transactions in this store yet</div>
        <div className="font-mono text-xs text-mute max-w-lg mx-auto">
          Upload the <span className="text-slate-200">Date Range transaction report</span> (Seller Central →
          Payments → Reports Repository) to see <span className="text-slate-200">SKU-level orders, refunds,
          fees and net proceeds</span>, filterable by date. Reports merge — re-uploads and overlapping
          months dedupe automatically.
        </div>
        <div className="flex justify-center">{UpBtn}</div>
      </div>
    </div>
  )

  const t = tx.totals, r = tx.range
  const drill = sku ? tx.transactions.filter(x => x.sku === sku) : tx.transactions

  const SKU_COLS = [
    { key: 'sku', label: 'SKU', render: p => (
        <button onClick={() => setSku(sku === p.sku ? null : p.sku)}
          className={`text-left hover:text-lime ${sku === p.sku ? 'text-lime' : ''}`}
          title={sku === p.sku ? 'clear the drill-down filter' : 'show only this SKU\'s transactions below'}>
          {trunc(p.sku, 170, sku === p.sku ? '' : undefined)}
        </button>) },
    { key: 'description', label: 'Product', cellClass: 'text-mute', render: p => trunc(p.description, 260, 'text-mute') },
    { key: 'orders', label: 'Orders', align: 'right' },
    { key: 'refunds', label: 'Refunds', align: 'right',
      render: p => p.refunds ? <span className="text-down">{p.refunds}</span> : <span className="text-mute">0</span> },
    { key: 'units', label: 'Units', align: 'right' },
    { key: 'product_sales', label: 'Product Sales', align: 'right', render: p => money2(p.product_sales) },
    { key: 'promo', label: 'Promos', align: 'right', render: p => signMoney(p.promo) },
    { key: 'selling_fees', label: 'Selling Fees', align: 'right', render: p => signMoney(p.selling_fees) },
    { key: 'fba_fees', label: 'FBA Fees', align: 'right', render: p => signMoney(p.fba_fees) },
    { key: 'other_fees', label: 'Other', align: 'right', render: p => signMoney(p.other_fees) },
    { key: 'net', label: 'Net Proceeds', align: 'right', render: p => <span className="font-bold">{signMoney(p.net, true)}</span> },
  ]

  const TXN_COLS = [
    { key: 'date', label: 'Date', cellClass: 'whitespace-nowrap' },
    { key: 'type', label: 'Type', render: x => <span className={TYPE_CLS[(x.type || '').toLowerCase()] || 'text-mute'}>{x.type}</span> },
    { key: 'order_id', label: 'Order ID', cellClass: 'text-mute', render: x => x.order_id || <span className="text-mute">—</span> },
    { key: 'sku', label: 'SKU', render: x => trunc(x.sku, 150) },
    { key: 'quantity', label: 'Qty', align: 'right' },
    { key: 'city', label: 'Ship To', cellClass: 'text-mute',
      value: x => [x.city, x.state].filter(Boolean).join(', '),
      render: x => trunc([x.city, x.state].filter(Boolean).join(', ') || '', 140, 'text-mute') },
    { key: 'product_sales', label: 'Product Sales', align: 'right', render: x => money2(x.product_sales) },
    { key: 'promo', label: 'Promos', align: 'right', render: x => signMoney(x.promo) },
    { key: 'selling_fees', label: 'Selling Fees', align: 'right', render: x => signMoney(x.selling_fees) },
    { key: 'fba_fees', label: 'FBA Fees', align: 'right', render: x => signMoney(x.fba_fees) },
    { key: 'total', label: 'Total', align: 'right', render: x => <span className="font-bold">{signMoney(x.total, true)}</span> },
    { key: 'status', label: 'Status', cellClass: 'text-mute' },
  ]

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="p-4 border-b border-edge flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">sku transactions · payments date range report (store-level)</div>
            <div className="text-xs text-mute font-mono flex gap-3 flex-wrap">
              {(tx.files || []).map(f => (
                <span key={f.name} title={`uploaded ${f.uploaded || ''}`}>
                  <Icon name="description" size={11} className="align-[-1px]" /> {f.name} · {f.rows}
                </span>
              ))}
              {tx.updated && <span>updated {tx.updated.slice(0, 10)}</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {UpBtn}
            <button onClick={exportReport} disabled={repBusy} aria-busy={repBusy}
              title="one workbook with charts for the selected date window: Overview (KPIs, net-by-SKU bar, deductions pie) · Daily Trend (sales vs net line) · By SKU · Transactions"
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="monitoring" size={14} />{repBusy ? 'Building…' : 'Export Report'}
            </button>
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          </div>
        </div>

        {/* date filter — ledger spans range.min..range.max; empty inputs = everything */}
        <div className="px-4 pt-3 flex items-center gap-2 font-mono text-xs flex-wrap">
          <span className="text-mute uppercase tracking-wider text-[10px]">filter by date</span>
          <input type="date" value={start} min={r.min || undefined} max={end || r.max || undefined}
            onChange={e => setRange(e.target.value, end)}
            className="bg-ink border border-edge rounded px-2 py-1 text-slate-100 focus:outline-none focus:border-primary" />
          <span className="text-mute">→</span>
          <input type="date" value={end} min={start || r.min || undefined} max={r.max || undefined}
            onChange={e => setRange(start, e.target.value)}
            className="bg-ink border border-edge rounded px-2 py-1 text-slate-100 focus:outline-none focus:border-primary" />
          {(start || end) && (
            <button onClick={() => setRange('', '')} className="btn btn-ghost text-[11px]">All dates</button>
          )}
          <span className="text-mute">
            ledger {r.min} → {r.max} · showing {t.transactions.toLocaleString()} transactions
          </span>
        </div>

        <div className="p-4 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
          <Stat label="Orders" value={t.orders.toLocaleString()} accent />
          <Stat label="Refunds" value={t.refunds.toLocaleString()} accent={t.refunds ? 'text-down' : undefined} />
          <Stat label="Units" value={t.units.toLocaleString()} />
          <Stat label="Product Sales" value={money2(t.product_sales)} />
          <Stat label="Promos" value={money2(t.promo)} />
          <Stat label="Selling Fees" value={money2(t.selling_fees)} />
          <Stat label="FBA Fees" value={money2(t.fba_fees)} />
          <Stat label="Net Proceeds" value={money2(t.net)} accent={t.net >= 0 ? 'text-up' : 'text-down'} />
        </div>
        {(t.transfers !== 0 || t.account_other !== 0) && (
          <div className="px-4 pb-3 -mt-1 font-mono text-[11px] text-mute flex items-center gap-1">
            <Icon name="info" size={12} /> account-level rows (no SKU) in this range:
            {t.account_other !== 0 && <> service/shipping/other {money2(t.account_other)} ·</>}
            {' '}bank transfers {money2(t.transfers)} — not counted in the SKU totals above.
          </div>
        )}
      </div>

      <div className="card">
        <DataTable title={`by sku · ${tx.skus.length}`} columns={SKU_COLS} rows={tx.skus} scope={`${scope}:${start}:${end}`}
          rowKey={p => p.sku} lean leanRows={8}
          searchKeys={['sku', 'description']} placeholder="search SKU / product…" empty="no SKU transactions in this range"
          initial={{ sort: { key: 'net', dir: 'desc' } }} />
      </div>

      <div className="card">
        <DataTable title={`transactions · ${drill.length}${sku ? ` · ${sku}` : ''}`}
          columns={TXN_COLS} rows={drill} scope={`${scope}:${start}:${end}:${sku || ''}`}
          rowKey={(x, i) => `${x.datetime}|${x.order_id}|${x.sku}|${i}`}
          searchKeys={['sku', 'order_id', 'type', 'description', 'city', 'state']}
          placeholder="search order ID / SKU / type / city…" empty="no transactions in this range"
          initial={{ sort: { key: 'date', dir: 'desc' } }} />
        {sku && (
          <div className="px-4 pb-3 font-mono text-[11px] text-mute">
            filtered to <span className="text-lime">{sku}</span> —{' '}
            <button onClick={() => setSku(null)} className="text-slate-200 hover:text-lime underline">show all SKUs</button>
          </div>
        )}
      </div>
    </div>
  )
}
