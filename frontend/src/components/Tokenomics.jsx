import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { toast } from '../toast.js'
import { LoadingButton, Spinner } from './Spinner.jsx'

const short = (m) => (m || '').replace(/^groq\//, '')
const usd = (v, d = 4) => (v == null ? '—' : v === 0 ? '$0' : v < 0.01 ? `$${v.toFixed(Math.max(d, 6))}` : `$${v.toLocaleString(undefined, { maximumFractionDigits: v >= 100 ? 0 : 2 })}`)
const num = (v) => (v == null ? '—' : Number(v).toLocaleString())

function Bar({ value, max, color = 'var(--pri)', label }) {
  return <div className="mini-bar" title={label}><i style={{ width: `${max ? Math.min(100, (value / max) * 100) : 0}%`, background: color }} /></div>
}

function DailyChart({ daily }) {
  const W = 560, H = 150, pad = 22
  const max = Math.max(1, ...daily.map((d) => d.tokens))
  const bw = (W - pad * 2) / daily.length
  return (
    <svg viewBox={`0 0 ${W} ${H + 24}`} style={{ width: '100%' }}>
      {daily.map((d, i) => {
        const h = (d.tokens / max) * H
        const hf = d.calls ? h * (d.fallback_calls / d.calls) : 0
        const x = pad + i * bw + 4
        return (
          <g key={d.day}>
            <rect x={x} y={H - h + 4} width={bw - 8} height={h - hf} fill="#4f46e5" rx="3"><title>{d.day}: {num(d.tokens)} tokens · {usd(d.cost_usd)} · {d.calls} calls</title></rect>
            <rect x={x} y={H - hf + 4} width={bw - 8} height={hf} fill="#f59e0b" rx="3"><title>{d.fallback_calls} call(s) served by fallback</title></rect>
            <text x={x + (bw - 8) / 2} y={H + 18} fontSize="10" textAnchor="middle" fill="currentColor">{d.day.slice(5)}</text>
            {d.tokens > 0 && <text x={x + (bw - 8) / 2} y={H - h} fontSize="9" textAnchor="middle" fill="currentColor">{d.tokens >= 1000 ? `${(d.tokens / 1000).toFixed(1)}k` : d.tokens}</text>}
          </g>)
      })}
    </svg>
  )
}

export default function Tokenomics() {
  const [days, setDays] = useState(7)
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState('')
  const [prices, setPrices] = useState({})

  const load = useCallback(() => api.tokenomics(days).then((x) => { setD(x); setErr('') }).catch((e) => setErr(e.message)), [days])
  useEffect(() => { setD(null); load(); const t = setInterval(load, 8000); return () => clearInterval(t) }, [load])
  useEffect(() => { if (d && !form) setForm({ ...d.settings }) }, [d])

  const save = async (name, fn, msg) => {
    setBusy(name)
    try { await fn(); toast.success(msg); await load() } catch (e) { toast.error(e.message, { title: 'Could not save' }) } finally { setBusy('') }
  }

  if (err) return <div className="alert bad">{err}</div>
  if (!d || !form) return <p><Spinner /> Calculating tokenomics…</p>

  const t = d.totals, pp = d.per_paper, m = d.monthly, ft = d.fallback_tax
  const mostUsed = d.by_model.filter((x) => x.calls_ok).sort((a, b) => b.total_tokens - a.total_tokens)[0]
  const cheapest = d.scenarios.find((s) => s.cost_per_paper_usd != null)
  const current = mostUsed && d.scenarios.find((s) => s.model === mostUsed.model)
  const maxCost = Math.max(...d.scenarios.map((s) => s.cost_per_paper_usd || 0), 1e-12)
  const maxTok = Math.max(1, ...d.by_task.map((x) => x.prompt_tokens + x.completion_tokens))
  const maxLat = Math.max(1, ...d.quality_tradeoff.map((x) => x.avg_latency_s))
  const maxQCost = Math.max(1e-12, ...d.quality_tradeoff.map((x) => x.avg_cost_usd))

  return (
    <div className="stack">
      <section className="card">
        <div className="row between">
          <h2>Tokenomics &amp; trade-offs <small>— what the AI costs, how fast it is, what it buys</small></h2>
          <div className="row">
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option>
            </select>
            <button className="ghost small" onClick={load}>Refresh</button>
          </div>
        </div>
        {d.warnings.map((w, i) => <div key={i} className="alert warn" style={{ marginTop: 8 }}>{w}</div>)}
      </section>

      <div className="kpis">
        {[['Total tokens', num(t.total_tokens), `${num(t.prompt_tokens)} in · ${num(t.completion_tokens)} out`],
          ['LLM cost', usd(t.cost_usd), `${t.calls_ok} successful calls`],
          ['Avg call latency', t.avg_latency_ms != null ? `${(t.avg_latency_ms / 1000).toFixed(2)} s` : '—', `${t.calls_error} failed · ${t.calls_skipped} skipped`],
          ['Output / input ratio', t.output_input_ratio ?? '—', 'higher = more generated text per prompt'],
          ['Cost per paper', pp.papers_measured ? usd(pp.avg_llm_cost_usd) : '—', `${pp.papers_measured} paper(s) measured`],
          ['Served by fallback', `${(ft.share_of_calls * 100).toFixed(0)}%`, `${ft.fallback_calls} call(s)`]]
          .map(([l, v, s]) => <div key={l} className="kpi"><b style={{ fontSize: 20 }}>{v}</b><span>{l}</span><br /><small className="muted">{s}</small></div>)}
      </div>

      <section className="card">
        <div className="row between"><h3>Token budget today</h3><small>{num(d.budget.used_today)} / {num(d.budget.daily_limit)} tokens ({d.budget.pct}%)</small></div>
        <Bar value={d.budget.used_today} max={d.budget.daily_limit} color={d.budget.pct > 80 ? 'var(--bad)' : 'var(--ok)'} />
        <small className="muted">Informational: the budget is displayed and flagged here but not enforced by the gateway.</small>
      </section>

      <div className="grid2">
        <section className="card stack">
          <h3>AI vs manual review <small>(per paper)</small></h3>
          {pp.papers_measured === 0 ? <p className="muted">No paper-level extractions with LLM usage in this window yet. Upload or re-extract a paper.</p> : (
            <table><tbody>
              <tr><td>Manual review ({pp.manual_review_minutes} min @ {usd(form.hourly_rate_usd, 2)}/h)</td><td><b>{usd(pp.manual_cost_usd, 2)}</b></td></tr>
              <tr><td>AI extraction ({num(pp.avg_total_tokens)} tokens, {pp.avg_calls} calls, {pp.avg_llm_latency_s}s of LLM time)</td><td><b>{usd(pp.avg_llm_cost_usd)}</b></td></tr>
              <tr><td>Saved per paper</td><td><b style={{ color: 'var(--ok)' }}>{usd(pp.savings_per_paper_usd, 2)}</b> · {pp.minutes_saved_per_paper} min</td></tr>
              <tr><td>AI is cheaper by</td><td><b>{pp.cost_ratio_x ? `${num(pp.cost_ratio_x)}×` : '—'}</b></td></tr>
            </tbody></table>)}
          <h3 style={{ marginTop: 6 }}>Monthly projection</h3>
          <table><tbody>
            <tr><td>{num(m.papers_per_month)} papers / month</td><td>LLM cost <b>{usd(m.llm_cost_usd, 2)}</b> · {num(m.tokens)} tokens</td></tr>
            <tr><td>Manual equivalent</td><td><b>{usd(m.manual_cost_usd, 0)}</b></td></tr>
            <tr><td>Net saving · hours saved</td><td><b style={{ color: 'var(--ok)' }}>{m.net_savings_usd != null ? usd(m.net_savings_usd, 0) : '—'}</b> · {m.hours_saved != null ? `${num(m.hours_saved)} h` : '—'}</td></tr>
          </tbody></table>
          <small className="muted">Excludes human QA of the AI output, infrastructure and engineering cost — treat the saving as an upper bound.</small>
        </section>

        <section className="card stack">
          <h3>Assumptions <small>(edit to model your organisation)</small></h3>
          {[['manual_review_minutes', 'Manual review time per paper (min)'], ['hourly_rate_usd', 'Researcher cost (USD / hour)'],
            ['papers_per_month', 'Papers per month'], ['daily_token_budget', 'Daily token budget']].map(([k, label]) => (
            <label key={k}>{label}<input type="number" min="1" value={form[k]} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} /></label>))}
          <LoadingButton loading={busy === 'set'} label="Save assumptions" busyLabel="Saving…"
            onClick={() => save('set', () => api.tokSettings(form), 'Assumptions saved')} />
        </section>
      </div>

      <section className="card">
        <h3>Tokens per day <small>— <span style={{ color: '#4f46e5' }}>■</span> primary <span style={{ color: '#f59e0b' }}>■</span> served by fallback</small></h3>
        <DailyChart daily={d.daily} />
      </section>

      <section className="card">
        <h3>Trade-off: quality vs cost vs speed <small>(by engine that produced the extraction)</small></h3>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr><th>Engine</th><th>Papers</th><th>Fields found</th><th>Verified vs source</th><th>Cost / paper</th><th>Latency / paper</th></tr></thead>
            <tbody>
              {d.quality_tradeoff.map((q) => (
                <tr key={q.engine}><td><b>{short(q.engine)}</b></td><td>{q.papers}</td>
                  <td>{(q.avg_field_coverage * 100).toFixed(0)}%<Bar value={q.avg_field_coverage} max={1} color="#0d9488" /></td>
                  <td>{(q.avg_verified_fields * 100).toFixed(0)}%<Bar value={q.avg_verified_fields} max={1} color="var(--ok)" /></td>
                  <td>{usd(q.avg_cost_usd)}<Bar value={q.avg_cost_usd} max={maxQCost} color="#db2777" /></td>
                  <td>{q.avg_latency_s}s<Bar value={q.avg_latency_s} max={maxLat} color="#7c3aed" /></td></tr>))}
              {!d.quality_tradeoff.length && <tr><td colSpan="6" className="muted">No extractions yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <small className="muted">“Fields found” = how many of the 12 experimental fields were filled; “Verified” = share whose evidence quote and numbers were confirmed in the source.
          The extractive (no-LLM) engine quotes sentences, so its verification is trivially high — judge it on fields found. Real accuracy needs the gold-set evaluation.</small>
      </section>

      <div className="grid2">
        <section className="card">
          <h3>Usage by model</h3>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Model</th><th>In / out tokens</th><th>Cost</th><th>$/1k tok</th><th>Latency</th><th>tok/s</th><th>Errors</th></tr></thead>
              <tbody>
                {d.by_model.map((x, i) => (
                  <tr key={i}><td>{short(x.model)}<br /><span className={'pill ' + (x.role === 'fallback' ? 'warn' : '')} style={{ marginLeft: 0 }}>{x.role}</span></td>
                    <td>{num(x.prompt_tokens)} / {num(x.completion_tokens)}</td>
                    <td>{x.priced ? usd(x.cost_usd) : <span className="pill warn" title="No price known">unpriced</span>}</td>
                    <td>{x.cost_per_1k_tokens != null ? usd(x.cost_per_1k_tokens) : '—'}</td>
                    <td>{x.avg_latency_ms != null ? `${x.avg_latency_ms} ms` : '—'}</td><td>{x.tokens_per_sec ?? '—'}</td>
                    <td>{x.errors}/{x.calls_ok + x.errors} <small className="muted">({(x.error_rate * 100).toFixed(0)}%)</small></td></tr>))}
                {!d.by_model.length && <tr><td colSpan="7" className="muted">No calls in this window.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
        <section className="card">
          <h3>Where the tokens go <small>(by task)</small></h3>
          <table>
            <tbody>
              {d.by_task.map((x) => (
                <tr key={x.task}><td style={{ width: '38%' }}>{x.task}<br /><small className="muted">{x.calls} calls · {x.avg_latency_ms != null ? `${x.avg_latency_ms} ms avg` : ''}</small></td>
                  <td><Bar value={x.prompt_tokens + x.completion_tokens} max={maxTok} /><small>{num(x.prompt_tokens)} in · {num(x.completion_tokens)} out · {usd(x.cost_usd)}</small></td></tr>))}
              {!d.by_task.length && <tr><td className="muted">No calls yet.</td></tr>}
            </tbody>
          </table>
        </section>
      </div>

      <section className="card">
        <h3>Cost of resilience <small>— the fallback “tax”</small></h3>
        <div className="kpis">
          {[['Calls served by fallback', ft.fallback_calls], ['Failed primary attempts', ft.failed_primary_attempts],
            ['Time lost on failed primary', `${(ft.latency_wasted_on_failed_primary_ms / 1000).toFixed(1)} s`],
            ['Primary calls skipped (circuit)', ft.primary_calls_skipped_by_circuit],
            ['Fallback cost', usd(ft.fallback_cost_usd)],
            ['Δ vs primary pricing', ft.cost_delta_usd != null ? `${ft.cost_delta_usd <= 0 ? '' : '+'}${usd(ft.cost_delta_usd)}` : 'n/a']]
            .map(([l, v]) => <div key={l} className="kpi"><b style={{ fontSize: 18 }}>{v}</b><span>{l}</span></div>)}
        </div>
        <small className="muted">
          {ft.primary_price_known
            ? `The same tokens would have cost ${usd(ft.cost_if_primary_had_served_usd)} on the primary, so the fallback was ${ft.cost_delta_usd <= 0 ? 'cheaper' : 'more expensive'} by ${usd(Math.abs(ft.cost_delta_usd))}.`
            : 'Set a price for the primary model below to compare what the fallback costs against the primary.'}
          {' '}The circuit breaker removes the time cost of retrying a dead primary: skipped calls cost nothing.
        </small>
      </section>

      <section className="card">
        <h3>What-if: same workload on a different model</h3>
        {cheapest && current && current.cost_per_paper_usd > 0 && cheapest.model !== current.model && (
          <div className="alert ok" style={{ marginBottom: 8 }}>
            Cheapest priced option is <b>{short(cheapest.model)}</b> — {(current.cost_per_paper_usd / cheapest.cost_per_paper_usd).toFixed(1)}× cheaper than {short(current.model)} at today's token volume.
            Cheaper models can lose quality; compare using the quality table above before switching.
          </div>)}
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr><th>Model</th><th>$/1M in · out</th><th>Cost / paper</th><th>Cost / month</th><th>Est. latency / paper</th></tr></thead>
            <tbody>
              {d.scenarios.map((s) => (
                <tr key={s.model} style={{ background: s.observed ? '#f8fafc' : 'transparent' }}>
                  <td>{short(s.model)} {s.role !== 'other' && <span className={'pill ' + (s.role === 'fallback' ? 'warn' : 'ok')}>{s.role}</span>}
                    {mostUsed?.model === s.model && <span className="pill ok">in use</span>}</td>
                  <td>{s.price_in} · {s.price_out} <small className="muted">({s.price_source})</small></td>
                  <td>{usd(s.cost_per_paper_usd)}<Bar value={s.cost_per_paper_usd || 0} max={maxCost} color="#db2777" /></td>
                  <td>{s.monthly_cost_usd != null ? usd(s.monthly_cost_usd, 2) : '—'}</td>
                  <td>{s.est_latency_s_per_paper != null ? `${s.est_latency_s_per_paper}s` : <small className="muted">no speed data</small>}</td></tr>))}
            </tbody>
          </table>
        </div>
        <small className="muted">Uses the average tokens per paper measured above. Latency is only estimated for models that have actually run here. Prices come from LiteLLM's price map unless overridden.</small>
      </section>

      <section className="card stack">
        <h3>Prices <small>(USD per 1M tokens — override if your contract differs)</small></h3>
        <table>
          <thead><tr><th>Model</th><th>Input</th><th>Output</th><th>Source</th><th /></tr></thead>
          <tbody>
            {[...d.by_model.map((x) => x.model), ...d.prices.map((p) => p.model)].filter((v, i, a) => v && a.indexOf(v) === i).slice(0, 8).map((model) => {
              const p = d.prices.find((x) => x.model === model) || { in: null, out: null, source: 'unpriced' }
              const e = prices[model] || {}
              return (
                <tr key={model}><td>{short(model)}</td>
                  <td><input type="number" step="any" min="0" style={{ width: 90 }} placeholder={p.in ?? ''} value={e.in ?? ''} onChange={(ev) => setPrices({ ...prices, [model]: { ...e, in: ev.target.value } })} /></td>
                  <td><input type="number" step="any" min="0" style={{ width: 90 }} placeholder={p.out ?? ''} value={e.out ?? ''} onChange={(ev) => setPrices({ ...prices, [model]: { ...e, out: ev.target.value } })} /></td>
                  <td><span className={'pill ' + (p.source === 'unpriced' ? 'warn' : p.source === 'custom' ? 'ok' : '')}>{p.source}</span></td>
                  <td><button className="ghost small" disabled={e.in == null || e.out == null || e.in === '' || e.out === ''}
                    onClick={() => save('p' + model, () => api.tokPrice(model, Number(e.in), Number(e.out)), 'Price saved')}>Save</button>{' '}
                    {p.source === 'custom' && <button className="ghost small" onClick={() => save('r' + model, () => api.tokPrice(model, null, null), 'Override removed')}>Reset</button>}</td></tr>)
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}
