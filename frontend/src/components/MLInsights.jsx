import React from 'react'
import { Icon, money } from './ui.jsx'
import { DataTable } from './table.jsx'

// ML Insights — one card per cadence, rendered from the `ml` block plan()
// already returns (pipeline/ml.py, enrich_plan) or (Daily Watch) from its own
// /daily-watch/anomalies endpoint. Every model degrades to null/empty on a
// small account, so each section only renders when it has something to show —
// no placeholder "not enough data" clutter beyond one line.

const pp = (x) => (x == null ? '—' : `${(Number(x) * 100).toFixed(1)}%`)
const m2 = (x) => (x == null ? '—' : `$${Number(x).toFixed(2)}`)

function ForecastStrip({ forecast }) {
  if (!forecast) return null
  const rows = [['spend', 'Next-week Spend', m2], ['sales', 'Next-week Sales', m2],
                ['acos', 'Next-week ACoS', pp]]
  const have = rows.filter(([k]) => forecast[k])
  if (!have.length) return null
  return (
    <div className="grid grid-cols-3 gap-3">
      {have.map(([k, label, fmt]) => {
        const f = forecast[k]
        return (
          <div key={k} className="rounded border border-edge p-3">
            <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
            <div className="mt-1 text-lg font-mono font-bold text-slate-100">{fmt(f.forecast)}</div>
            <div className="text-mute text-[10px] font-mono">{fmt(f.lo)} – {fmt(f.hi)} (80%)</div>
          </div>
        )
      })}
    </div>
  )
}

const CAND_COLS = [
  { key: 'search_term', label: 'Search Term', render: r => <span className="truncate inline-block align-bottom" style={{ maxWidth: 260 }} title={r.search_term}>{r.search_term}</span> },
  { key: 'ad_group_name', label: 'Ad Group', cellClass: 'text-mute',
    render: r => <span className="truncate inline-block align-bottom" style={{ maxWidth: 200 }}>{r.ad_group_name}</span> },
  { key: 'clicks', label: 'Clicks', align: 'right', cellClass: 'text-mute' },
  { key: 'spend', label: 'Spend', align: 'right', cellClass: 'text-mute', render: r => money(r.spend) },
  { key: 'p_convert', label: 'P(convert)', align: 'right',
    render: r => <span className="text-lime font-semibold">{(r.p_convert * 100).toFixed(0)}%</span> },
]

const ANOM_ICON = { spike: 'trending_up', drop: 'trending_down' }

export function MLInsights({ ml, anomalies, title = 'ML Insights' }) {
  const hasPrior = ml?.prior
  const hasForecast = ml?.forecast
  const hasModel = ml?.model?.candidates?.length > 0
  const hasAnomalies = anomalies?.length > 0
  if (!hasPrior && !hasAnomalies) return null

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-center gap-2 text-mute text-[11px] font-mono uppercase tracking-wider">
        <Icon name="auto_awesome" size={13} className="text-lime" /> {title}
      </div>

      {hasPrior && (
        <div className="flex flex-wrap items-center gap-4 font-mono text-xs">
          <span className="text-slate-200">
            Account conversion prior: <b>{pp(ml.prior.mean)}</b>
            <span className="text-mute"> · strength {ml.prior.strength} clicks · fit on {ml.prior.n_targets} targets</span>
          </span>
          {ml.be_cvr != null && (
            <span className="text-mute" title="the CVR a target needs to hit goal ACoS, at the account's average CPC/AOV — used to compute negate/pause/promote confidence">
              break-even CVR ≈ {pp(ml.be_cvr)}
            </span>
          )}
        </div>
      )}

      <ForecastStrip forecast={hasForecast ? ml.forecast : null} />

      {hasModel && (
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-2 flex items-center gap-2">
            Early Promote Candidates
            <span className="normal-case text-[10px]" title="conversion-propensity model, trained on this cadence's own search terms">
              (model AUC {ml.model.auc} · {ml.model.n} terms · base rate {pp(ml.model.base_rate)})
            </span>
          </div>
          <DataTable columns={CAND_COLS} rows={ml.model.candidates}
            rowKey={r => `${r.ad_group_name}|${r.search_term}`} lean
            empty="no early candidates" />
        </div>
      )}

      {hasAnomalies && (
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-2">Anomalies</div>
          <div className="space-y-1.5">
            {anomalies.slice(0, 12).map((a, i) => (
              <div key={i} className={`flex items-center gap-2 font-mono text-xs px-2 py-1.5 rounded border ${a.severity === 'bad' ? 'border-down/30 text-down' : 'border-up/30 text-up'}`}>
                <Icon name={ANOM_ICON[a.direction] || 'warning'} size={13} />
                <span className="text-slate-200">{a.date}</span>
                <span className="uppercase">{a.metric}</span>
                <span>{a.direction}</span>
                <span className="text-mute">{a.value} (typical {a.typical}, z={a.z})</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
