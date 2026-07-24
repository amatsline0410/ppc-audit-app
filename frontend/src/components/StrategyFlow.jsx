import React from 'react'

// Methodology map for the PPC playbook: pull data -> read ACoS vs break-even
// -> classify into one of four states -> apply the goal lever -> run the always-on
// metric engine -> work the 90-day phases. When `counts` is passed (from the
// generic advisor's per-campaign state classifier) the four state boxes show the
// LIVE campaign counts — the diagram reads the actual account, not a picture.

function Box({ bg, title, sub, subColor = 'rgba(255,255,255,0.6)', badge }) {
  return (
    <div className="rounded-xl px-5 py-3 text-center shadow-md w-full relative" style={{ background: bg }}>
      <div className="font-sans text-white text-[15px] leading-tight">{title}</div>
      {sub && <div className="font-sans text-[13px] mt-0.5" style={{ color: subColor }}>{sub}</div>}
      {badge != null && (
        <div className="font-mono text-[11px] mt-1 text-white/90 font-bold">{badge} campaign{badge === 1 ? '' : 's'}</div>
      )}
    </div>
  )
}

// vertical connector tick
const V = ({ h = 24 }) => <div className="w-px bg-mute/40 mx-auto" style={{ height: h }} />

// the four ACoS-vs-break-even states (matches the reference colors)
const STATES = [
  { id: 'below_target', bg: '#0e5e44', title: 'Below target', sub: 'Efficient · scale', subColor: '#6fe0b0' },
  { id: 'at_target', bg: '#1d4f7c', title: 'At target', sub: 'Healthy · tune', subColor: '#79b6e6' },
  { id: 'above_target', bg: '#9a6a0a', title: 'Above target', sub: 'Watch · clean', subColor: '#f0c24a' },
  { id: 'over_break_even', bg: '#8a2222', title: 'Over break-even', sub: 'Bleeding · fix', subColor: '#e88a8a' },
]

export function StrategyFlow({ counts }) {
  return (
    <div className="card p-5">
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-4">
        methodology · how the playbook reads your account
        {counts && <span className="text-lime"> · live</span>}
      </div>

      <div className="max-w-3xl mx-auto">
        {/* step 1 */}
        <div className="max-w-xs mx-auto"><Box bg="#2b2b2b" title="Pull 60-day data" /></div>
        <V />
        {/* step 2 */}
        <div className="max-w-sm mx-auto"><Box bg="#4a4a4a" title="Read ACoS first" sub="vs break-even ACoS" /></div>
        <V />

        {/* branch: horizontal bracket over the four states */}
        <div className="px-[12.5%]"><div className="border-t border-mute/40" /></div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {STATES.map(({ id, ...box }) => (
            <div key={id} className="flex flex-col items-center">
              <V h={16} />
              <Box {...box} badge={counts ? (counts[id] ?? 0) : undefined} />
            </div>
          ))}
        </div>
        {counts && (counts.no_data ?? 0) > 0 && (
          <div className="text-center font-mono text-[11px] text-mute mt-2">
            + {counts.no_data} campaign{counts.no_data === 1 ? '' : 's'} with too little data to classify (lever: rank — keep building visibility)
          </div>
        )}

        {/* merge back to a single column */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {STATES.map((s) => <V key={s.id} h={16} />)}
        </div>
        <div className="px-[12.5%]"><div className="border-b border-mute/40" /></div>
        <V />

        {/* step 3 */}
        <Box bg="#3f33a6" title="Apply goal lever" sub="cut · grow · rank · balance" subColor="#b9b2f0" />
        <V />
        {/* step 4 */}
        <div className="max-w-2xl mx-auto"><Box bg="#7a2d12" title="Metric engine — always on" sub="if/then: bid · negate · harvest" subColor="#e0a07a" /></div>
        <V />
        {/* step 5 */}
        <div className="max-w-xl mx-auto"><Box bg="#222222" title="90-day phases" sub="diagnose → fix → optimize → scale" /></div>
      </div>
    </div>
  )
}
