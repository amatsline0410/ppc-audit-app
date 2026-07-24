import React from 'react'
import { Icon } from './ui.jsx'

// Guided "funnel" for each Audit Cadence — a step-by-step process form that walks
// the user through the correct rhythm: export the right Amazon report → upload it →
// review the recommended actions → download the bulk & re-upload to Amazon. The
// active step is derived live from the panel's own state (`stage`), so the funnel
// self-advances as the user works. Watch-only Daily has no download step.
//
// stage = { uploaded, hasRows, downloaded } emitted by each cadence panel.

const DL = { icon: 'file_download', title: 'Export the Amazon report' }

export const FUNNELS = {
  daily: {
    steps: [
      { icon: 'file_download', title: 'Export the daily bulk',
        hint: 'Amazon Ads → Sponsored Products → Bulk operations. Grab today + yesterday (campaign rows).',
        done: s => s.uploaded },
      { icon: 'upload', title: 'Upload to Daily Watch',
        hint: 'Drop the file into today’s panel below — one file per day.',
        done: s => s.uploaded },
      { icon: 'monitoring', title: 'Scan for anomalies',
        hint: 'Check spend / ACoS spikes, sales drops and zero-order spend. Watch only — no structural changes.',
        done: s => s.uploaded },
    ],
  },
  weekly: {
    steps: [
      { icon: 'file_download', title: 'Export the SP bulk (last 7 days)',
        hint: 'Amazon Ads → Sponsored Products → Bulk operations, last 7 days. Include the SP Search Term Report sheet.',
        done: s => s.uploaded },
      { icon: 'upload', title: 'Upload the week',
        hint: 'Upload the bulk into a Week panel below — each week keeps its own snapshot.',
        done: s => s.uploaded },
      { icon: 'fact_check', title: 'Review bid tweaks + harvest',
        hint: 'Check the recommended bid changes and the search-term harvest (promote winners / negate wasted). Tick the rows you want.',
        done: s => s.downloaded },
      { icon: 'download', title: 'Download bulk → re-upload to Amazon',
        hint: 'Download the .xlsx and re-upload it in Amazon Ads bulk operations to apply.',
        done: s => s.downloaded },
    ],
  },
  mid_month: {
    steps: [
      { icon: 'file_download', title: 'Export the SP bulk (last 14 days)',
        hint: 'Amazon Ads → Sponsored Products → Bulk operations, last 14 days. Include the SP Search Term Report sheet.',
        done: s => s.uploaded },
      { icon: 'upload', title: 'Upload the bulk',
        hint: 'Single snapshot — re-uploading replaces it. Sponsored Products only.',
        done: s => s.uploaded },
      { icon: 'fact_check', title: 'Review bid adjustments + negatives',
        hint: 'Bid ±15% by ACoS vs goal, negate $10+/0-order terms. Bleeders (converted but 2× goal) are not pre-ticked — review first.',
        done: s => s.downloaded },
      { icon: 'download', title: 'Download bulk → re-upload to Amazon',
        hint: 'Download the .xlsx and re-upload it in Amazon Ads bulk operations to apply.',
        done: s => s.downloaded },
    ],
  },
  full_month: {
    steps: [
      { icon: 'file_download', title: 'Export the SP bulk (last 30 days)',
        hint: 'Amazon Ads → Sponsored Products → Bulk operations, last 30 days. Include the SP Search Term Report sheet.',
        done: s => s.uploaded },
      { icon: 'upload', title: 'Upload the bulk',
        hint: 'Single snapshot — the full monthly pass. Sponsored Products only.',
        done: s => s.uploaded },
      { icon: 'fact_check', title: 'Review the full pass',
        hint: 'The complete pass: bid changes + promote winners + negate wasted + bleeders. Tick everything you agree with.',
        done: s => s.downloaded },
      { icon: 'download', title: 'Download bulk → re-upload to Amazon',
        hint: 'Download the .xlsx and re-upload it in Amazon Ads bulk operations to apply.',
        done: s => s.downloaded },
    ],
  },
  pause_scale: {
    steps: [
      { icon: 'file_download', title: 'Export the SP bulk (last 60 days)',
        hint: 'Amazon Ads → Sponsored Products → Bulk operations, last 60 days. Include the SP Search Term Report sheet.',
        done: s => s.uploaded },
      { icon: 'upload', title: 'Upload the bulk',
        hint: 'Acts on existing entities (keywords / targets / campaigns), not new search terms.',
        done: s => s.uploaded },
      { icon: 'fact_check', title: 'Review pause / scale',
        hint: 'Scale winners (bid up), pause dead targets (30+ clicks, 0 orders). Whole-campaign pauses are not pre-ticked — review first.',
        done: s => s.downloaded },
      { icon: 'download', title: 'Download bulk → re-upload to Amazon',
        hint: 'Download the .xlsx and re-upload it in Amazon Ads bulk operations to apply.',
        done: s => s.downloaded },
    ],
  },
}

export function CadenceFunnel({ cadence, label, stage = {} }) {
  const cfg = FUNNELS[cadence]
  if (!cfg) return null
  const steps = cfg.steps
  const doneFlags = steps.map(st => !!st.done(stage))
  // active = first not-done step (or last, if all done)
  let active = doneFlags.findIndex(d => !d)
  if (active === -1) active = steps.length - 1
  const allDone = doneFlags.every(Boolean)
  const doneCount = doneFlags.filter(Boolean).length

  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">process funnel{label ? ` · ${label}` : ''}</div>
          <div className="font-mono text-xs text-mute mt-1">
            Follow the steps below for a clean {label || 'audit'} run — export → upload → review → apply.
          </div>
        </div>
        <div className={`tag inline-flex items-center gap-1 ${allDone ? 'text-up border border-up/40' : 'text-primary border border-primary/40'}`}>
          <Icon name={allDone ? 'task_alt' : 'timelapse'} size={13} />
          {allDone ? 'All steps done' : `Step ${active + 1} of ${steps.length}`}
        </div>
      </div>

      <div className="p-4">
        <ol className="flex flex-col md:flex-row md:items-stretch gap-3">
          {steps.map((st, i) => {
            const done = doneFlags[i]
            const isActive = i === active && !allDone
            const state = done ? 'done' : isActive ? 'active' : 'todo'
            const ring = state === 'done' ? 'border-up/40 bg-up/5'
              : state === 'active' ? 'border-primary bg-primary/10'
              : 'border-edge'
            const badge = state === 'done' ? 'bg-up/15 text-up border-up/40'
              : state === 'active' ? 'bg-primary text-onPrimary border-primary'
              : 'bg-panel text-mute border-edge'
            return (
              <li key={i} className="md:flex-1 relative">
                <div className={`h-full rounded-lg border p-3 transition-colors ${ring}`}>
                  <div className="flex items-center gap-2">
                    <span className={`w-6 h-6 shrink-0 rounded-full border grid place-items-center font-mono text-[11px] font-bold ${badge}`}>
                      {done ? <Icon name="check" size={13} /> : i + 1}
                    </span>
                    <span className={`inline-flex items-center gap-1 font-mono text-[11px] font-semibold ${state === 'todo' ? 'text-slate-300' : state === 'active' ? 'text-primary' : 'text-up'}`}>
                      <Icon name={st.icon} size={13} />{st.title}
                    </span>
                  </div>
                  <div className="font-mono text-[10px] text-mute mt-2 leading-relaxed">{st.hint}</div>
                </div>
                {i < steps.length - 1 && (
                  <div className="hidden md:block absolute top-1/2 -right-3 -translate-y-1/2 text-mute">
                    <Icon name="chevron_right" size={16} />
                  </div>
                )}
              </li>
            )
          })}
        </ol>
        <div className="mt-3 h-1 rounded-full bg-edge overflow-hidden">
          <div className={`h-full rounded-full transition-all ${allDone ? 'bg-up' : 'bg-primary'}`}
            style={{ width: `${Math.round((doneCount / steps.length) * 100)}%` }} />
        </div>
      </div>
    </div>
  )
}
