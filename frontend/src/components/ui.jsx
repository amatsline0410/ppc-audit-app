import React from 'react'

const SEV = {
  high: 'bg-red/15 text-red border border-red/30',
  medium: 'bg-amber/15 text-amber border border-amber/30',
  low: 'bg-cyan/15 text-cyan border border-cyan/30',
}
const FLAG_LABEL = {
  HIGH_ACOS: 'HIGH ACOS', WASTED_SPEND: 'WASTED', LOW_CTR: 'LOW CTR',
  LOW_CVR: 'LOW CVR', OVERBID: 'OVERBID', SCALE_WINNER: 'SCALE ▲', BLEEDING: 'BLEEDING',
}
const GOOD = 'bg-lime/15 text-lime border border-lime/30'

export function FlagBadge({ flag, severity }) {
  // SCALE_WINNER is a growth signal — always green, not a severity red
  const cls = flag === 'SCALE_WINNER' ? GOOD : (SEV[severity] || SEV.low)
  return <span className={`tag ${cls}`}>{FLAG_LABEL[flag] || flag}</span>
}

export function Sev({ severity }) {
  return <span className={`tag ${SEV[severity] || SEV.low}`}>{severity}</span>
}

// Reference card explaining every audit flag + the bid ladder. Rendered in the PPC
// Audit right rail AND (collapsible) inside the Audit Cadence header so it's always
// reachable, whichever cadence panel is active.
export function FlagLegend({ className = '' }) {
  return (
    <div className={className}>
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-2">flag legend</div>
      <ul className="font-mono text-xs space-y-1 text-mute">
        <li><span className="text-red">BLEEDING</span> — over break-even, losing money</li>
        <li><span className="text-red">HIGH_ACOS</span> — over goal, lower bid</li>
        <li><span className="text-lime">SCALE ▲</span> — under goal + orders, raise bid</li>
        <li><span className="text-red">WASTED</span> — spend, no orders → negate</li>
        <li><span className="text-cyan">OVERBID</span> — bid ≫ actual CPC</li>
        <li><span className="text-amber">LOW_CVR</span> — listing/price issue</li>
        <li><span className="text-cyan">LOW_CTR</span> — relevance/image issue</li>
      </ul>
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider mt-4 mb-2">bid ladder (has sales)</div>
      <ul className="font-mono text-xs space-y-1 text-mute">
        <li><span className="text-cyan">REDUCE</span> → <span className="text-amber">MONITOR</span> → <span className="text-red">PAUSE</span></li>
        <li>cut bid first, watch, stop only if it keeps losing</li>
      </ul>
    </div>
  )
}

const STAGE = {
  REDUCE: 'bg-cyan/15 text-cyan border border-cyan/30',
  MONITOR: 'bg-amber/15 text-amber border border-amber/30',
  PAUSE: 'bg-red/15 text-red border border-red/30',
}
// bid-ladder stage chip: reduce -> monitor -> pause
export function StageBadge({ stage }) {
  if (!stage) return null
  return <span className={`tag ${STAGE[stage] || ''}`} title="bid-ladder stage">{stage}</span>
}

const STATE = {
  enabled: { dot: 'bg-lime', cls: 'text-lime' },
  paused: { dot: 'bg-amber', cls: 'text-amber' },
  archived: { dot: 'bg-slate-500', cls: 'text-mute' },
}
// industry-standard state pill: colored dot + label (enabled/paused/archived)
export function StateBadge({ state }) {
  const k = (state || '').toLowerCase()
  const s = STATE[k] || { dot: 'bg-slate-600', cls: 'text-mute' }
  return (
    <span className={`inline-flex items-center gap-1 ${s.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      <span className="text-[10px] uppercase tracking-wider">{state || 'n/a'}</span>
    </span>
  )
}

// download the preferred blank/reference template for an upload kind
const TPL_BASE = import.meta.env.VITE_API_BASE || '/api'
export function TemplateLink({ kind, label = 'template' }) {
  return (
    <a href={`${TPL_BASE}/templates/${kind}`} onClick={e => e.stopPropagation()}
      className="font-mono text-[10px] text-cyan hover:underline whitespace-nowrap inline-flex items-center gap-0.5">
      <Icon name="download" size={12} />{label}</a>
  )
}

// Material Symbols icon (font loaded in index.html). `size` in px.
export function Icon({ name, size = 20, className = '' }) {
  return (
    <span className={`material-symbols-outlined select-none leading-none ${className}`}
      style={{ fontSize: size }} aria-hidden="true">{name}</span>
  )
}

export function pct(x) { return x == null ? '—' : `${(x * 100).toFixed(1)}%` }
export function money(x) { return x == null ? '—' : `$${Number(x).toLocaleString(undefined, { maximumFractionDigits: 0 })}` }

export function Stat({ label, value, accent }) {
  return (
    <div className="card p-4">
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`mt-1 text-2xl font-mono font-bold ${accent || 'text-slate-100'}`}>{value}</div>
    </div>
  )
}

export function Spinner({ label }) {
  return (
    <div className="flex items-center gap-2 text-mute font-mono text-sm">
      <span className="inline-block w-3 h-3 border-2 border-lime border-t-transparent rounded-full animate-spin" />
      {label}
    </div>
  )
}

// ---- skeleton loaders (shimmer placeholders while data loads) ---------------
// One grey shimmer bar. w/h accept any CSS size (px number -> px, or a string).
export function Skeleton({ w = '100%', h = 12, className = '', rounded = 'rounded' }) {
  const px = v => (typeof v === 'number' ? `${v}px` : v)
  return <span className={`skeleton ${rounded} ${className}`} style={{ width: px(w), height: px(h), display: 'block' }} />
}

// A table placeholder that matches the .card table look: optional toolbar + a
// header row + N body rows of cells. Drop it where the real <table> would render.
export function TableSkeleton({ rows = 8, cols = 5, toolbar = true }) {
  return (
    <div>
      {toolbar && (
        <div className="flex items-center justify-between p-4 border-b border-edge gap-3">
          <Skeleton w={220} h={28} />
          <div className="flex gap-2"><Skeleton w={60} h={24} /><Skeleton w={60} h={24} /></div>
        </div>
      )}
      <div className="p-2 space-y-2">
        <div className="flex gap-3 px-2 py-1">
          {Array.from({ length: cols }).map((_, i) => (
            <Skeleton key={i} w={i === 0 ? '28%' : `${Math.floor(60 / (cols - 1))}%`} h={10} />
          ))}
        </div>
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-3 px-2 py-2 border-t border-edge/40">
            {Array.from({ length: cols }).map((_, c) => (
              <Skeleton key={c} w={c === 0 ? '28%' : `${Math.floor(60 / (cols - 1))}%`} h={12}
                className={c === 0 ? '' : 'opacity-80'} />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

// A row of stat-card placeholders (KPI strips).
export function StatsSkeleton({ count = 5 }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="card p-4 space-y-2"><Skeleton w="60%" h={10} /><Skeleton w="80%" h={22} /></div>
      ))}
    </div>
  )
}

// A generic card-body placeholder (charts, forms, narratives).
export function CardSkeleton({ lines = 4, title = true }) {
  return (
    <div className="card p-4 space-y-3">
      {title && <Skeleton w={180} h={14} />}
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} w={`${90 - i * 8}%`} h={12} />
      ))}
    </div>
  )
}
