import React, { useState, useMemo } from 'react'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

// ─────────────────────────────────────────────────────────────────────────────
// Amazon-Ads-console-style metric explorer.
//
//   • A row of metric toggles (Impressions / Clicks / Spend / Sales / Orders /
//     CTR / CVR / ROAS / ACOS / CPC / TACOS …). Pick up to 2.
//   • Time-series LINE chart (best plot for trends over days). When the two
//     metrics have different units they get their OWN y-axis (left + right), like
//     the Amazon console; same unit -> shared axis.
//   • Hover shows an index tooltip with each selected metric's value, formatted
//     by its kind (%, $, ×, count). Each toggle chip also shows the period total.
//
// Usage: <MetricChart labels={['06-01',…]} rows={rows} metrics={REGISTRY} defaults={['acos','roas']} />
//   metric = { key, label, kind: 'pct'|'money'|'ratio'|'count', get:(row)=>number|null }
// ─────────────────────────────────────────────────────────────────────────────

export const fmtKind = {
  pct: (v) => (v == null ? '—' : `${Number(v).toFixed(2)}%`),
  money: (v) => (v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`),
  ratio: (v) => (v == null ? '—' : `${Number(v).toFixed(2)}×`),
  count: (v) => (v == null ? '—' : Number(v).toLocaleString()),
}
const shortKind = {
  pct: (v) => `${Number(v).toFixed(0)}%`,
  money: (v) => `$${Number(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : Number(v).toFixed(0)}`,
  ratio: (v) => `${Number(v).toFixed(1)}×`,
  count: (v) => (Number(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : Number(v).toFixed(0)),
}

const GRID = 'rgba(255,255,255,0.06)'
const TICK = '#7a8694'
const SLOT = ['#FCD535', '#2dbdb6', '#f6465d', '#7aa2f7']   // per-line colors (up to 4 metrics)

// roll a metric to one period total (sums counts/money; recomputes ratios from parts)
function periodTotal(metric, rows) {
  const vals = rows.map(metric.get).filter(v => v != null)
  if (!vals.length) return null
  if (metric.kind === 'pct' || metric.kind === 'ratio') {
    return vals.reduce((a, b) => a + b, 0) / vals.length   // avg for rate metrics
  }
  return vals.reduce((a, b) => a + b, 0)
}

export function MetricChart({ labels, rows, metrics, defaults, height = 280, max = 2 }) {
  const init = (defaults || metrics.slice(0, max).map(m => m.key)).slice(0, max)
  const [sel, setSel] = useState(init)

  // toggle a metric; cap at `max` (drop the oldest, Amazon-console style)
  function toggle(key) {
    setSel(s => (s.includes(key) ? s.filter(k => k !== key) : (s.length >= max ? [...s.slice(1), key] : [...s, key])))
  }

  const chosen = sel.map(k => metrics.find(m => m.key === k)).filter(Boolean)
  // group metric kinds onto at most 2 y-axes (left = first kind, right = next distinct kind).
  const kinds = []
  chosen.forEach(m => { if (!kinds.includes(m.kind)) kinds.push(m.kind) })
  const [axisA, axisB] = kinds                      // up to two distinct units share two axes
  const axisIdFor = (kind) => (kind === axisB ? 'y1' : 'y')

  const { data, options } = useMemo(() => {
    const datasets = chosen.map((mt, i) => ({
      label: mt.label, data: rows.map(mt.get), _kind: mt.kind,
      borderColor: SLOT[i], backgroundColor: SLOT[i] + '1f',
      tension: 0.3, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2,
      spanGaps: false, fill: i === 0 && chosen.length === 1, yAxisID: axisIdFor(mt.kind),
    }))

    const axisFor = (kind, pos) => ({
      position: pos, grid: { color: pos === 'left' ? GRID : 'transparent', drawOnChartArea: pos === 'left' },
      ticks: { color: TICK, font: { size: 9 }, callback: (v) => shortKind[kind](v) },
    })
    const scales = { x: { grid: { color: GRID }, ticks: { color: TICK, font: { size: 9 }, maxRotation: 0, autoSkip: true } } }
    if (axisA) scales.y = axisFor(axisA, 'left')
    if (axisB) scales.y1 = axisFor(axisB, 'right')

    return {
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1e2329', borderColor: '#2b3139', borderWidth: 1,
            titleColor: '#eaecef', bodyColor: '#eaecef', padding: 10, cornerRadius: 6,
            titleFont: { family: 'monospace' }, bodyFont: { family: 'monospace' },
            callbacks: {
              label: (ctx) => {
                const v = ctx.raw
                const f = fmtKind[ctx.dataset._kind] || fmtKind.count
                return `  ${ctx.dataset.label}: ${v == null ? '—' : f(v)}`
              },
            },
          },
        },
        scales,
      },
    }
  }, [chosen, rows, labels, axisA, axisB])

  return (
    <div>
      {/* metric toggles — chip shows the metric + its period total, highlighted when active */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {metrics.map(mt => {
          const idx = sel.indexOf(mt.key)
          const on = idx !== -1
          const tot = periodTotal(mt, rows)
          return (
            <button key={mt.key} onClick={() => toggle(mt.key)}
              className={`text-left rounded-md border px-2.5 py-1.5 transition-colors ${on ? 'border-transparent' : 'border-edge hover:border-mute'}`}
              style={on ? { background: SLOT[idx] + '22', borderColor: SLOT[idx] } : undefined}>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ background: on ? SLOT[idx] : '#3a424c' }} />
                <span className={`font-mono text-[11px] font-semibold ${on ? 'text-slate-100' : 'text-mute'}`}>{mt.label}</span>
              </div>
              <div className="font-mono text-[11px] text-mute mt-0.5">{tot == null ? '—' : fmtKind[mt.kind](tot)}</div>
            </button>
          )
        })}
      </div>
      {chosen.length === 0
        ? <div className="text-mute font-mono text-xs py-10 text-center">pick a metric above</div>
        : <div style={{ height }}><Line data={data} options={options} /></div>}
    </div>
  )
}
