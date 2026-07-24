import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { money, pct, Icon, StatsSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useToast } from './Toast.jsx'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  Tooltip, Legend, Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

// flag type -> meaning + accent + where to action it (Dashboard breakdown table)
const FLAG_META = {
  BLEEDING: ['Over break-even — losing money on every ad-driven sale', 'text-red', 'PPC Optimization → flag table'],
  HIGH_ACOS: ['Over goal ACoS — bid ladder: reduce → monitor → pause', 'text-amber', 'PPC Optimization → Bid Optimizer'],
  WASTED_SPEND: ['Spend with zero orders — negate the term', 'text-red', 'Keywords → Search-Term Harvest'],
  SCALE_WINNER: ['Under goal with orders — raise bid / budget', 'text-lime', 'PPC Optimization → Bid Optimizer'],
  OVERBID: ['Bid far above the actual CPC — tighten it', 'text-cyan', 'PPC Optimization → Bid Optimizer'],
  LOW_CVR: ['Clicks convert poorly — listing / price issue', 'text-amber', 'Product Optimization'],
  LOW_CTR: ['Impressions but few clicks — relevance / image issue', 'text-amber', 'Product Optimization'],
}

const money2 = (x) => x == null ? '—' : `$${Number(x).toFixed(2)}`
const pct1 = (x) => x == null ? '—' : `${(x * 100).toFixed(1)}%`
const pctRaw = (x) => x == null ? '—' : `${Number(x).toFixed(1)}%`   // monitoring stores 24.03 = 24.03%

// big Binance-style KPI tile
function Tile({ label, value, accent, sub, hint }) {
  return (
    <div className="card p-4" title={hint || ''}>
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`mt-1 text-2xl font-mono font-bold ${accent || 'text-slate-100'}`}>{value}</div>
      {sub != null && <div className="text-[11px] font-mono text-mute mt-0.5">{sub}</div>}
    </div>
  )
}

// small stat inside an analytics section card
function Mini({ label, value, accent }) {
  return (
    <div>
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`mt-0.5 text-base font-mono font-bold ${accent || 'text-slate-100'}`}>{value}</div>
    </div>
  )
}

// analytics section card: uppercase title + "open →" jump + body (or empty hint)
function Section({ title, tab, onNav, children, empty }) {
  return (
    <div className="card">
      <div className="px-4 py-2.5 border-b border-edge flex items-center justify-between gap-2">
        <span className="text-mute text-[11px] font-mono uppercase tracking-wider">{title}</span>
        {tab && (
          <button onClick={() => onNav?.(tab)} className="btn btn-ghost text-[11px] flex items-center gap-1">
            open <Icon name="arrow_forward" size={12} />
          </button>
        )}
      </div>
      {children || (
        <div className="p-4 font-mono text-xs text-mute flex items-center gap-1.5">
          <Icon name="info" size={13} /> {empty}
        </div>
      )}
    </div>
  )
}

const SEV_CLS = { high: 'text-down', medium: 'text-amber', low: 'text-mute' }

// Account dashboard = the analytics hub: PPC KPIs + flag/ladder breakdown off
// the audit, plus one section per data source (Product Ads, Product Benchmark,
// Transactions ledger + trend, Monitoring tracker, snapshot movers, footer
// counters) — all rolled up by GET /dashboard/analytics.
export function ProfitDashboard({ scope, report, targetAcos, onNav }) {
  const toast = useToast()
  const r = report || {}
  const L = r.ladder || {}
  const overGoal = r.acos != null && targetAcos && r.acos > targetAcos

  const [an, setAn] = useState(null)
  const [anErr, setAnErr] = useState(null)
  const [repBusy, setRepBusy] = useState(false)
  useEffect(() => {
    setAn(null); setAnErr(null)
    api.dashboardAnalytics(targetAcos, api.getCadence()).then(setAn).catch(e => setAnErr(String(e?.message || e)))
  }, [scope])  // eslint-disable-line

  // exec report — xlsx with native Excel charts mirroring the whole hub
  async function exportReport() {
    setRepBusy(true)
    try {
      const blob = await api.dashboardExport(targetAcos, api.getCadence())
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'dashboard_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Dashboard report downloaded — Overview · Features · Transactions · Top movers')
    } catch (e) { toast.error(String(e?.message || e).replace(/^Error:\s*/, '')) }
    finally { setRepBusy(false) }
  }

  // flag breakdown table rows (was crammed into tile subtitles)
  const flagRows = Object.entries(r.flags?.by_type || {}).map(([flag, n]) => {
    const [what, cls, tool] = FLAG_META[flag] || ['', 'text-mute', 'PPC Optimization → flag table']
    return { flag, n, what, cls, tool }
  })

  const MOVER_COLS = [
    { key: 'name', label: 'Campaign', render: x => (
        <span className="inline-block max-w-[240px] truncate align-bottom text-slate-200" title={x.name}>{x.name || x.campaign_id}</span>) },
    { key: 'spend_delta', label: 'Spend Δ', align: 'right',
      render: x => <span className={x.spend_delta > 0 ? 'text-down' : x.spend_delta < 0 ? 'text-up' : 'text-mute'}>
        {x.spend_delta > 0 ? '+' : ''}{money(x.spend_delta)}</span> },
    { key: 'spend_cur', label: 'Spend', align: 'right', render: x => money(x.spend_cur) },
    { key: 'sales_cur', label: 'Sales', align: 'right', render: x => money(x.sales_cur) },
    { key: 'acos_cur', label: 'ACoS', align: 'right', cellClass: 'text-mute',
      render: x => `${x.acos_prev != null ? pct(x.acos_prev) : '—'} → ${x.acos_cur != null ? pct(x.acos_cur) : '—'}` },
  ]

  const pa = an?.product_ads, ct = an?.catalog, tx = an?.transactions, mo = an?.monitoring

  // transactions daily trend (whole ledger)
  const txChart = tx?.days?.length > 1 ? {
    labels: tx.days.map(d => d.date.slice(5)),
    datasets: [
      { label: 'product sales', data: tx.days.map(d => d.product_sales),
        borderColor: '#FCD535', backgroundColor: 'rgba(252,213,53,.08)', fill: true,
        pointRadius: 0, borderWidth: 1.5, tension: 0.25 },
      { label: 'net proceeds', data: tx.days.map(d => d.net),
        borderColor: '#0ecb81', backgroundColor: 'transparent',
        pointRadius: 0, borderWidth: 1.5, tension: 0.25 },
    ],
  } : null

  return (
    <div className="space-y-5">
      {/* ---- header: title + charted Excel export ---- */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-mute text-[11px] font-mono uppercase tracking-wider">dashboard · analytics hub</span>
        <button onClick={exportReport} disabled={repBusy} aria-busy={repBusy}
          title="one workbook with charts mirroring this page: Overview (PPC KPIs, flag bar) · Features (Product Ads status pie, catalog, monitoring) · Transactions (daily sales/net line, top-SKU bar) · Top movers (spend-Δ bar)"
          className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
          <Icon name="monitoring" size={14} />{repBusy ? 'Building…' : 'Export Report'}
        </button>
      </div>

      {/* ---- PPC audit KPIs (selected audit + cadence) ---- */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-3">
        <Tile label="ad spend" value={money(r.ad_spend)} accent="text-amber" />
        <Tile label="ad sales" value={money(r.ad_sales)} />
        <Tile label="acos" value={r.acos != null ? pct(r.acos) : '—'}
          accent={r.acos == null ? 'text-mute' : overGoal ? 'text-red' : 'text-lime'}
          sub={targetAcos ? `goal ${pct(targetAcos)}` : null} hint="ad spend ÷ ad sales" />
        <Tile label="avg product acos" value={r.avg_product_acos != null ? pct(r.avg_product_acos) : '—'}
          accent={r.avg_product_acos == null ? 'text-mute' : (targetAcos && r.avg_product_acos > targetAcos) ? 'text-red' : 'text-lime'}
          hint="Σ ad spend ÷ Σ ad revenue across the per-product campaign rollups" />
        <Tile label="ppc flags" value={r.flags?.total ?? '—'} accent="text-amber"
          sub={`▼${L.reduce ?? 0} ◷${L.monitor ?? 0} ✕${L.pause ?? 0}`} />
        <Tile label="wasted" value={money(r.wasted_spend)} accent="text-red"
          sub={`scale ▲${r.scale_winners ?? 0}`} />
        <Tile label="snapshot" value={r.snapshot || '—'} accent="text-mute" />
      </div>

      {/* ---- account states — the Strategy methodology classifier ---- */}
      {an?.states && (
        <Section title="account states · acos vs break-even, per campaign" tab="strategy" onNav={onNav}>
          <div className="p-4 space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {[['below_target', 'below target · grow', 'text-up'],
                ['at_target', 'at target · balance', 'text-cyan'],
                ['above_target', 'above target · cut', 'text-amber'],
                ['over_break_even', 'over break-even · cut hard', 'text-down'],
                ['no_data', 'no data · rank', 'text-mute']].map(([k, label, cls]) => (
                <div key={k}>
                  <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
                  <div className={`mt-0.5 text-xl font-mono font-bold ${cls}`}>{(an.states.counts?.[k] ?? 0).toLocaleString()}</div>
                </div>
              ))}
            </div>
            {(an.states.top || []).length > 0 && (
              <div className="font-mono text-[11px] text-mute truncate"
                title={an.states.top.map(x => `${x.campaign}: ${x.state.replace(/_/g, ' ')} → ${x.lever}`).join('\n')}>
                top spender: <span className="text-slate-200">{an.states.top[0].campaign}</span>
                {' · '}{an.states.top[0].state.replace(/_/g, ' ')} → <span className="text-cyan">{an.states.top[0].lever}</span>
                {' — full table in Strategy'}
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ---- flag breakdown + snapshot movers ---- */}
      <div className="grid lg:grid-cols-2 gap-4 items-start">
        {flagRows.length > 0 && (
          <div className="card">
            <DataTable title={`flag breakdown · ${r.flags.total}`} lean leanRows={10}
              columns={[
                { key: 'n', label: '#', align: 'right',
                  render: x => <span className={`font-bold text-base ${x.cls}`}>{x.n}</span> },
                { key: 'flag', label: 'Flag', render: x => <span className={`${x.cls} whitespace-nowrap`}>{x.flag}</span> },
                { key: 'what', label: 'What it means', cellClass: 'text-mute text-xs',
                  render: x => (
                    <span className="inline-block max-w-[380px] truncate align-bottom" title={x.what}>
                      {x.what}
                      {x.flag === 'HIGH_ACOS' && <span className="text-slate-400"> (▼{L.reduce ?? 0} ◷{L.monitor ?? 0} ✕{L.pause ?? 0})</span>}
                    </span>) },
                { key: 'tool', label: 'Run in', render: x => <span className="text-cyan text-xs whitespace-nowrap">{x.tool}</span> },
              ]}
              rows={flagRows} rowKey={x => x.flag} empty="no flags"
              initial={{ sort: { key: 'n', dir: 'desc' } }} />
          </div>
        )}
        {an?.movers?.length > 0 && (
          <div className="card">
            <DataTable title={`top movers · ${an.period ? `${an.period.previous} → ${an.period.current}` : 'vs previous snapshot'}`}
              lean leanRows={8} columns={MOVER_COLS} rows={an.movers} rowKey={x => x.campaign_id}
              empty="no movers" initial={{ sort: { key: 'spend_delta', dir: 'desc' } }} />
          </div>
        )}
      </div>

      {anErr && (
        <div className="card border-down/40 p-3 font-mono text-xs text-down inline-flex items-center gap-1">
          <Icon name="warning" size={12} /> analytics: {anErr}
        </div>
      )}
      {!an && !anErr && <div className="card p-4"><StatsSkeleton count={5} /></div>}

      {/* ---- per-feature analytics sections ---- */}
      {an && (
        <div className="grid lg:grid-cols-3 gap-4 items-start">
          <Section title="product ads · this audit" tab="productads" onNav={onNav}
            empty="no Product Ads upload in the selected audit — open the tab and upload the Sponsored Products bulk.">
            {pa && (
              <div className="p-4 space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <Mini label="products" value={pa.count.toLocaleString()} />
                  <Mini label="campaigns" value={pa.campaigns.toLocaleString()} />
                  <Mini label="avg product acos" value={pct1(pa.avg_acos)}
                    accent={pa.avg_acos != null && targetAcos && pa.avg_acos > targetAcos ? 'text-down' : 'text-up'} />
                  <Mini label="ad spend" value={money2(pa.total?.spend)} accent="text-amber" />
                  <Mini label="ad sales" value={money2(pa.total?.sales)} />
                  <Mini label="acos" value={pct1(pa.total?.acos)} />
                </div>
                <div className="font-mono text-[11px] text-mute">
                  <span className="text-up">{pa.by_status?.ok ?? 0} converting</span>
                  {' · '}<span className="text-amber">{pa.by_status?.no_orders ?? 0} no orders</span>
                  {' · '}<span>{pa.by_status?.no_data ?? 0} no traffic</span>
                </div>
              </div>
            )}
          </Section>

          <Section title="product benchmark · store catalog" tab="catalog" onNav={onNav}
            empty="no catalog yet — upload Category Listings Reports in Product Benchmark.">
            {ct && (
              <div className="p-4 grid grid-cols-3 gap-3">
                <Mini label="products" value={ct.total.toLocaleString()} />
                <Mini label="listing issues" value={(ct.listing_issues ?? 0).toLocaleString()}
                  accent={ct.listing_issues ? 'text-amber' : 'text-up'} />
                <Mini label="advertised" value={(ct.advertised ?? 0).toLocaleString()} />
                <Mini label="avg acos" value={pct1(ct.avg_acos)} />
                <Mini label="over break-even" value={(ct.over_be ?? 0).toLocaleString()}
                  accent={ct.over_be ? 'text-down' : undefined} />
                <Mini label="under break-even" value={(ct.under_be ?? 0).toLocaleString()}
                  accent={ct.under_be ? 'text-up' : undefined} />
              </div>
            )}
          </Section>

          <Section title={`monitoring · last 14 days${mo?.latest_date ? ` (to ${mo.latest_date})` : ''}`}
            tab="monitoring" onNav={onNav}
            empty="no daily tracker data — upload Business + SP reports in Monitoring.">
            {mo && (
              <div className="p-4 space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <Mini label="health" value={mo.health?.score != null ? `${mo.health.score}/100` : '—'}
                    accent={mo.health?.score >= 70 ? 'text-up' : mo.health?.score >= 40 ? 'text-amber' : 'text-down'} />
                  <Mini label="total sales" value={money2(mo.overview?.total_sales)} />
                  <Mini label="tacos" value={pctRaw(mo.overview?.tacos)} />
                  <Mini label="ad spend" value={money2(mo.overview?.ad_spend)} accent="text-amber" />
                  <Mini label="ad sales" value={money2(mo.overview?.ad_sales)} />
                  <Mini label="acos" value={pctRaw(mo.overview?.acos)} />
                </div>
                {(mo.alerts || []).length > 0 ? (
                  <div className="space-y-1">
                    {mo.alerts.map((a, i) => (
                      <div key={i} className={`font-mono text-[11px] ${SEV_CLS[a.severity] || 'text-mute'} truncate`} title={a.msg}>
                        ⚠ {a.msg}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="font-mono text-[11px] text-up">✓ no active alerts</div>
                )}
              </div>
            )}
          </Section>
        </div>
      )}

      {/* ---- transactions ledger (store-level) + daily trend ---- */}
      {an && (
        <Section title={`transactions · sku ledger${tx ? ` (${tx.range.min} → ${tx.range.max})` : ''}`}
          tab="transactions" onNav={onNav}
          empty="no transaction ledger — upload the Payments Date Range report in Transactions.">
          {tx && (
            <div className="p-4 space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <Mini label="orders" value={tx.totals.orders.toLocaleString()} />
                <Mini label="refunds" value={tx.totals.refunds.toLocaleString()}
                  accent={tx.totals.refunds ? 'text-down' : undefined} />
                <Mini label="units" value={tx.totals.units.toLocaleString()} />
                <Mini label="product sales" value={money2(tx.totals.product_sales)} />
                <Mini label="fees" value={money2((tx.totals.selling_fees ?? 0) + (tx.totals.fba_fees ?? 0))} accent="text-amber" />
                <Mini label="net proceeds" value={money2(tx.totals.net)}
                  accent={tx.totals.net >= 0 ? 'text-up' : 'text-down'} />
              </div>
              {txChart && (
                <div className="h-52">
                  <Line data={txChart} options={{
                    responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
                    plugins: { legend: { labels: { color: '#707a8a', font: { size: 10, family: 'JetBrains Mono' }, boxWidth: 12 } } },
                    scales: {
                      x: { ticks: { color: '#707a8a', font: { size: 9, family: 'JetBrains Mono' }, maxTicksLimit: 16 }, grid: { color: 'rgba(43,49,57,.5)' } },
                      y: { ticks: { color: '#707a8a', font: { size: 9, family: 'JetBrains Mono' } }, grid: { color: 'rgba(43,49,57,.5)' } },
                    },
                  }} />
                </div>
              )}
              {(tx.top_skus || []).length > 0 && (
                <div className="font-mono text-[11px] text-mute truncate">
                  top by net: {tx.top_skus.map(p => `${p.sku} ${money2(p.net)}`).join(' · ')}
                </div>
              )}
            </div>
          )}
        </Section>
      )}

      {/* ---- footer counters ---- */}
      {an && (an.changelog || an.keywords) && (
        <div className="flex gap-4 flex-wrap font-mono text-[11px] text-mute">
          {an.changelog && (
            <button onClick={() => onNav?.('log')} className="hover:text-lime flex items-center gap-1">
              <Icon name="history" size={13} /> {an.changelog.count.toLocaleString()} actions logged
              {an.changelog.last?.ts && ` · last ${an.changelog.last.ts.slice(0, 10)}`}
            </button>
          )}
          {an.keywords && (
            <button onClick={() => onNav?.('keywords')} className="hover:text-lime flex items-center gap-1">
              <Icon name="key" size={13} /> {an.keywords.count.toLocaleString()} keywords mined
            </button>
          )}
        </div>
      )}
    </div>
  )
}
