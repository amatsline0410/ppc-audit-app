import React, { useEffect, useMemo, useRef, useState } from 'react'
import ReactDOM from 'react-dom'

// Shared client-side table controls: free-text search, Excel-style per-column
// sort (A-Z / Z-A / none for text, ascending / descending for numbers),
// **composite filters** (stack any number of per-column conditions, AND-combined),
// page-size (10 / 50 / 300 / All) and pagination. Reused by every data table.

export const PAGE_SIZES = [10, 50, 300, 0]   // 0 = show all

const NUM_RE = /^[-+]?[$%]?\s*[\d,]*\.?\d+\s*[$%×x]?$/

const toNum = (v) =>
  typeof v === 'number' ? v : parseFloat(String(v).replace(/[$,%×x\s]/g, ''))

// natural comparison: numbers (incl. $, %, commas) numerically, else locale text;
// blanks always sort to the bottom regardless of direction.
function cmp(a, b) {
  const an = a == null || a === '', bn = b == null || b === ''
  if (an && bn) return 0
  if (an) return 1
  if (bn) return -1
  const na = toNum(a), nb = toNum(b)
  if (!isNaN(na) && !isNaN(nb) && String(a).trim() !== '' && String(b).trim() !== '') return na - nb
  return String(a).localeCompare(String(b))
}

const humanize = (k) => String(k).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

// operators per column type (label shown in the dropdown)
export const OPS = {
  text: [['contains', 'contains'], ['!contains', "doesn't contain"], ['=', 'is'], ['!=', 'is not'],
         ['set', 'is set'], ['empty', 'is empty']],
  number: [['>=', '≥'], ['>', '>'], ['<=', '≤'], ['<', '<'], ['=', '='], ['!=', '≠'],
           ['between', 'between'], ['set', 'is set'], ['empty', 'is empty']],
}
const NO_VALUE = new Set(['set', 'empty'])

// infer the filterable columns from the data: every scalar key on the rows plus
// any accessor key. Object/array values are skipped (not filterable as scalars).
function deriveCols(rows, accessors) {
  const sample = rows.slice(0, 50)
  const keys = []
  const seen = new Set()
  const push = (k) => { if (!seen.has(k)) { seen.add(k); keys.push(k) } }
  if (rows[0]) Object.keys(rows[0]).forEach(push)
  Object.keys(accessors).forEach(push)

  const cols = []
  for (const k of keys) {
    let sawText = false, sawNum = false, sawObj = false
    for (const r of sample) {
      const v = accessors[k] ? accessors[k](r) : r[k]
      if (v == null || v === '') continue
      if (typeof v === 'number') { sawNum = true; continue }
      if (typeof v === 'object') { sawObj = true; break }
      const s = String(v)
      if (NUM_RE.test(s.trim())) sawNum = true
      else sawText = true
    }
    if (sawObj) continue
    cols.push({ key: k, label: humanize(k), type: sawText || !sawNum ? 'text' : 'number' })
  }
  return cols
}

function passes(raw, f) {
  if (f.op === 'set') return raw != null && raw !== ''
  if (f.op === 'empty') return raw == null || raw === ''
  if (f.type === 'number') {
    const n = toNum(raw)
    const a = parseFloat(f.value)
    if (isNaN(n)) return false
    if (isNaN(a)) return true                  // incomplete condition -> ignore
    switch (f.op) {
      case '>': return n > a
      case '>=': return n >= a
      case '<': return n < a
      case '<=': return n <= a
      case '=': return n === a
      case '!=': return n !== a
      case 'between': { const b = parseFloat(f.value2); return isNaN(b) ? n >= a : n >= a && n <= b }
      default: return true
    }
  }
  const s = String(raw ?? '').toLowerCase()
  const q = String(f.value ?? '').toLowerCase()
  if (q === '') return true                     // incomplete condition -> ignore
  switch (f.op) {
    case 'contains': return s.includes(q)
    case '!contains': return !s.includes(q)
    case '=': return s === q
    case '!=': return s !== q
    default: return true
  }
}

/**
 * rows: the full array.
 * opts.searchKeys: row keys to match search against (default: all keys).
 * opts.accessors: { colKey: row => value } for derived/sortable/filterable columns.
 * opts.initial: { sort:{key,dir}, pageSize }.
 * opts.deps: extra deps that should reset pagination to page 0.
 */
export function useTableControls(rows, opts = {}) {
  const { searchKeys = null, accessors = {}, initial = {}, deps = [] } = opts
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState(initial.sort || null)         // {key, dir:'asc'|'desc'} | null
  const [filters, setFilters] = useState([])                     // [{key, op, type, value, value2}]
  const [pageSize, setPageSize] = useState(initial.pageSize ?? 50)
  const [page, setPage] = useState(0)

  const get = (r, key) => (accessors[key] ? accessors[key](r) : r[key])
  const filterCols = useMemo(() => deriveCols(rows, accessors), [rows]) // eslint-disable-line

  const filtered = useMemo(() => {
    const qq = query.trim().toLowerCase()
    const active = filters.filter(f => f.key && f.op)
    if (!qq && active.length === 0) return rows
    const skeys = searchKeys || (rows[0] ? Object.keys(rows[0]) : [])
    return rows.filter(r => {
      if (qq && !skeys.some(k => String(get(r, k) ?? '').toLowerCase().includes(qq))) return false
      for (const f of active) if (!passes(get(r, f.key), f)) return false   // AND
      return true
    })
  }, [rows, query, filters, searchKeys]) // eslint-disable-line

  const sorted = useMemo(() => {
    if (!sort) return filtered
    const s = [...filtered].sort((a, b) => cmp(get(a, sort.key), get(b, sort.key)))
    if (sort.dir === 'desc') s.reverse()
    return s
  }, [filtered, sort]) // eslint-disable-line

  // reset to first page when the result set / size / sort / filters change
  useEffect(() => { setPage(0) }, [query, pageSize, sort, filters, ...deps]) // eslint-disable-line

  const pageCount = pageSize === 0 ? 1 : Math.max(1, Math.ceil(sorted.length / pageSize))
  const cur = Math.min(page, pageCount - 1)
  const start = pageSize === 0 ? 0 : cur * pageSize
  const view = pageSize === 0 ? sorted : sorted.slice(start, start + pageSize)

  // cycle: none -> asc -> desc -> none
  function toggleSort(key) {
    setSort(s => (!s || s.key !== key) ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null)
  }

  // ---- composite filters ----
  function addFilter() {
    const c = filterCols[0]
    if (!c) return
    setFilters(fs => [...fs, { key: c.key, type: c.type, op: c.type === 'number' ? '>=' : 'contains', value: '', value2: '' }])
  }
  function updateFilter(i, patch) {
    setFilters(fs => fs.map((f, j) => {
      if (j !== i) return f
      const next = { ...f, ...patch }
      if (patch.key) {                       // column changed -> re-type + reset op/value
        const col = filterCols.find(c => c.key === patch.key)
        next.type = col ? col.type : 'text'
        next.op = next.type === 'number' ? '>=' : 'contains'
        next.value = ''; next.value2 = ''
      }
      return next
    }))
  }
  function removeFilter(i) { setFilters(fs => fs.filter((_, j) => j !== i)) }
  function clearFilters() { setFilters([]) }

  // per-column header filter (Amazon-style): one numeric condition per column key.
  const colFilter = (key) => filters.find(f => f.key === key) || null
  function setColFilter(key, op, value) {
    setFilters(fs => {
      const rest = fs.filter(f => f.key !== key)
      if (value === '' || value == null) return rest      // empty -> clear this column
      return [...rest, { key, type: 'number', op, value: String(value), value2: '' }]
    })
  }
  const clearColFilter = (key) => setFilters(fs => fs.filter(f => f.key !== key))

  return { query, setQuery, sort, toggleSort, pageSize, setPageSize, page: cur, setPage,
           pageCount, start, total: rows.length, count: sorted.length, view, sorted,
           filters, filterCols, addFilter, updateFilter, removeFilter, clearFilters,
           colFilter, setColFilter, clearColFilter }
}

// operators for the per-column header filter (matches Amazon's campaign manager)
const COL_OPS = [['>', 'greater than'], ['>=', 'greater than or equal'], ['=', 'equals'],
                 ['<=', 'less than or equal'], ['<', 'less than']]

// one composite-filter condition row
function FilterRow({ ctl, f, i }) {
  const ops = OPS[f.type] || OPS.text
  const cell = 'bg-panel border border-edge rounded px-2 py-1 font-mono text-xs text-slate-200 focus:outline-none focus:border-mute'
  return (
    <div className="flex items-center gap-1 flex-wrap">
      <select value={f.key} onChange={(e) => ctl.updateFilter(i, { key: e.target.value })} className={cell}>
        {ctl.filterCols.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
      </select>
      <select value={f.op} onChange={(e) => ctl.updateFilter(i, { op: e.target.value })} className={cell}>
        {ops.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {!NO_VALUE.has(f.op) && (
        <input value={f.value} onChange={(e) => ctl.updateFilter(i, { value: e.target.value })}
          placeholder="value" className={`${cell} w-24`}
          inputMode={f.type === 'number' ? 'decimal' : 'text'} />
      )}
      {f.op === 'between' && (
        <input value={f.value2} onChange={(e) => ctl.updateFilter(i, { value2: e.target.value })}
          placeholder="and" className={`${cell} w-20`} inputMode="decimal" />
      )}
      <button onClick={() => ctl.removeFilter(i)} className="tag border border-edge text-mute hover:text-red">✕</button>
    </div>
  )
}

// search box + composite-filter builder + page-size selector (place above a table)
export function TableToolbar({ ctl, placeholder = 'search…', right = null, title = null }) {
  const [open, setOpen] = useState(false)
  const nF = ctl.filters?.length || 0
  return (
    <div className="border-b border-edge">
      <div className="p-3 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          {title && <span className="text-mute text-[10px] font-mono uppercase tracking-wider mr-1">{title}</span>}
          <input value={ctl.query} onChange={(e) => ctl.setQuery(e.target.value)} placeholder={placeholder}
            className="bg-panel border border-edge rounded px-3 py-1.5 font-mono text-xs text-slate-200 w-64 max-w-full focus:outline-none focus:border-mute" />
          <button onClick={() => setOpen(o => !o)}
            className={`tag ${nF ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}
            title="composite filters — stack column conditions">⛃ filters{nF ? ` (${nF})` : ''}</button>
        </div>
        <div className="flex items-center gap-1">
          {right}
          <span className="text-mute text-[10px] font-mono uppercase tracking-wider mr-1">show</span>
          {PAGE_SIZES.map((n) => (
            <button key={n} onClick={() => ctl.setPageSize(n)}
              className={`tag ${ctl.pageSize === n ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>
              {n === 0 ? 'All' : n}
            </button>
          ))}
        </div>
      </div>
      {open && (
        <div className="px-3 pb-3 space-y-2">
          {nF === 0 && <div className="font-mono text-[11px] text-mute">no filters — add column conditions (all must match).</div>}
          {ctl.filters.map((f, i) => <FilterRow key={i} ctl={ctl} f={f} i={i} />)}
          <div className="flex items-center gap-2">
            <button onClick={ctl.addFilter} className="tag border border-edge text-lime hover:bg-lime hover:text-ink">＋ add filter</button>
            {nF > 0 && <button onClick={ctl.clearFilters} className="tag border border-edge text-mute hover:text-red">clear all</button>}
          </div>
        </div>
      )}
    </div>
  )
}

// portal popover: a per-column numeric filter (operator + number), anchored to the
// funnel button. Rendered to <body> so table overflow can't clip it.
function ColFilterMenu({ ctl, colKey, anchor, onClose }) {
  const existing = ctl.colFilter(colKey)
  const [op, setOp] = useState(existing?.op && COL_OPS.some(([v]) => v === existing.op) ? existing.op : '>')
  const [val, setVal] = useState(existing?.value ?? '')
  const r = anchor.getBoundingClientRect()
  const cell = 'bg-panel border border-edge rounded px-2 py-1 font-mono text-xs text-slate-200 focus:outline-none focus:border-mute'
  function apply() { ctl.setColFilter(colKey, op, val.trim()); onClose() }
  function clear() { ctl.clearColFilter(colKey); onClose() }
  return ReactDOM.createPortal(
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="fixed z-50 bg-panel border border-edge rounded shadow-xl p-2 space-y-2 normal-case tracking-normal"
        style={{ top: r.bottom + 4, left: Math.min(r.left, window.innerWidth - 200) }}
        onClick={(e) => e.stopPropagation()}>
        <select value={op} onChange={(e) => setOp(e.target.value)} className={`${cell} w-44 block`}>
          {COL_OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input autoFocus value={val} onChange={(e) => setVal(e.target.value)} inputMode="decimal"
          placeholder="number" className={`${cell} w-44 block`}
          onKeyDown={(e) => e.key === 'Enter' && apply()} />
        <div className="flex gap-1">
          <button onClick={apply} className="tag bg-lime text-ink flex-1">apply</button>
          <button onClick={clear} className="tag border border-edge text-mute hover:text-red">clear</button>
        </div>
      </div>
    </>, document.body)
}

// sortable column header cell. `k` is the sort key (or accessor key). Numeric
// columns also get an Amazon-style per-column filter funnel.
export function Th({ ctl, k, children, align = 'left', className = '' }) {
  const active = ctl.sort?.key === k
  const arrow = !active ? '↕' : ctl.sort.dir === 'asc' ? '▲' : '▼'
  const numeric = ctl.filterCols?.some(c => c.key === k && c.type === 'number')
  const hasFilter = numeric && !!ctl.colFilter(k)
  const btnRef = useRef(null)
  const [open, setOpen] = useState(false)
  return (
    <th className={`p-2 text-${align} select-none whitespace-nowrap ${className}`}>
      <span className="inline-flex items-center gap-0.5">
        <span onClick={() => ctl.toggleSort(k)} title="click to sort"
          className={`cursor-pointer hover:text-slate-200 ${active ? 'text-slate-200' : ''}`}>
          {children}<span className={`ml-1 ${active ? 'text-lime' : 'text-mute/40'}`}>{arrow}</span>
        </span>
        {numeric && (
          <button ref={btnRef} onClick={() => setOpen(o => !o)} title="filter this column"
            className={`ml-0.5 leading-none ${hasFilter ? 'text-lime' : 'text-mute/40 hover:text-slate-300'}`}>▾</button>
        )}
      </span>
      {open && btnRef.current && <ColFilterMenu ctl={ctl} colKey={k} anchor={btnRef.current} onClose={() => setOpen(false)} />}
    </th>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// DataTable — one declarative table used everywhere, so every table shares the
// SAME design + features: free-text search, composite + per-column filters,
// click-to-sort headers, page-size + pagination, sticky header (global CSS), and
// an optional selection column. Pass `columns` + `rows`; each column is
//   { key, label, align?, render?(row), value?(row), sortKey?, className?, width? }
// `render` controls the cell display; `value` (or the row[key]) is what sort /
// filter use. Selection is controlled by the parent (selected Set + onToggle).
// ─────────────────────────────────────────────────────────────────────────────
export function DataTable({
  title, columns, rows, rowKey = (r, i) => i, searchKeys, initial, scope,
  selectable = false, selected, onToggle, onToggleAll,
  toolbarRight = null, empty = 'no rows', placeholder = 'search…',
  lean = false, leanRows = 12,
}) {
  const accessors = useMemo(() => {
    const a = {}
    for (const c of columns) if (c.value) a[c.sortKey || c.key] = c.value
    return a
  }, [columns])
  const sKeys = searchKeys || columns.map(c => c.key)
  const ctl = useTableControls(rows, { searchKeys: sKeys, accessors, initial, deps: [scope] })

  const allKeys = useMemo(() => rows.map(rowKey), [rows]) // eslint-disable-line
  const allOn = selectable && allKeys.length > 0 && allKeys.every(k => selected?.has(k))
  const span = columns.length + (selectable ? 1 : 0)

  // lean: small tables drop the toolbar + pagination (just a caption + the table,
  // sort + select-all still work via the header). Grows past `leanRows` -> full controls.
  const compact = lean && rows.length <= leanRows
  const view = compact ? ctl.sorted : ctl.view

  return (
    <div className="card">
      {compact ? (
        (title || (selectable && allKeys.length > 0)) && (
          <div className="px-3 py-2 border-b border-edge flex items-center justify-between gap-2">
            {title && <span className="text-mute text-[10px] font-mono uppercase tracking-wider">{title}</span>}
            {selectable && allKeys.length > 0 && (
              <label className="font-mono text-[10px] text-mute flex items-center gap-1 cursor-pointer">
                <input type="checkbox" checked={allOn} onChange={e => onToggleAll?.(allKeys, e.target.checked)} className="accent-primary" />
                all
              </label>
            )}
          </div>
        )
      ) : (
        <TableToolbar ctl={ctl} title={title} placeholder={placeholder} right={
          <>
            {selectable && allKeys.length > 0 && (
              <label className="font-mono text-[10px] text-mute flex items-center gap-1 cursor-pointer mr-1">
                <input type="checkbox" checked={allOn} onChange={e => onToggleAll?.(allKeys, e.target.checked)} className="accent-primary" />
                all
              </label>
            )}
            {toolbarRight}
          </>
        } />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-mute text-[11px] uppercase tracking-wider border-b border-edge">
              {selectable && (
                <th className="p-2 w-8">
                  <input type="checkbox" checked={allOn} onChange={e => onToggleAll?.(allKeys, e.target.checked)} className="accent-primary" />
                </th>
              )}
              {columns.map(c => <Th key={c.key} ctl={ctl} k={c.sortKey || c.key} align={c.align || 'left'} className={c.className}>{c.label}</Th>)}
            </tr>
          </thead>
          <tbody>
            {view.map((row, i) => {
              const k = rowKey(row, i)
              const on = selectable && selected?.has(k)
              return (
                <tr key={k} className={`border-b border-edge/40 hover:bg-edge/20 ${on ? 'bg-primary/5' : ''}`}>
                  {selectable && (
                    <td className="p-2"><input type="checkbox" checked={!!on} onChange={() => onToggle?.(k)} className="accent-primary" /></td>
                  )}
                  {columns.map(c => (
                    <td key={c.key} className={`p-2 ${c.align === 'right' ? 'text-right' : ''} ${c.cellClass || ''}`}>
                      {c.render ? c.render(row) : (row[c.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              )
            })}
            {view.length === 0 && (
              <tr><td colSpan={span} className="p-6 text-center text-mute">{ctl.query || ctl.filters.length ? 'no matches' : empty}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {!compact && <Pagination ctl={ctl} />}
    </div>
  )
}

// range readout + prev/next pagination (place below a table)
export function Pagination({ ctl }) {
  const { start, view, count, total, query, filters, pageCount, page, setPage } = ctl
  const narrowed = !!(query || (filters && filters.length)) && total !== count
  return (
    <div className="p-3 border-t border-edge flex items-center justify-between gap-3 flex-wrap text-xs font-mono text-mute">
      <span>
        {count === 0 ? '0' : `${start + 1}–${start + view.length}`} of {count}
        {narrowed && <span className="ml-1">(filtered from {total})</span>}
      </span>
      {ctl.pageSize !== 0 && pageCount > 1 && (
        <div className="flex items-center gap-1">
          <button onClick={() => setPage(0)} disabled={page === 0}
            className="tag border border-edge text-mute hover:text-lime disabled:opacity-30">«</button>
          <button onClick={() => setPage(page - 1)} disabled={page === 0}
            className="tag border border-edge text-mute hover:text-lime disabled:opacity-30">‹ prev</button>
          <span className="px-2">page {page + 1} / {pageCount}</span>
          <button onClick={() => setPage(page + 1)} disabled={page >= pageCount - 1}
            className="tag border border-edge text-mute hover:text-lime disabled:opacity-30">next ›</button>
          <button onClick={() => setPage(pageCount - 1)} disabled={page >= pageCount - 1}
            className="tag border border-edge text-mute hover:text-lime disabled:opacity-30">»</button>
        </div>
      )}
    </div>
  )
}
