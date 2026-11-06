import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { toast } from '../toast.js'
import { LoadingButton, Spinner } from './Spinner.jsx'

const STATE = {
  healthy: ['ok', 'Healthy'], unknown: ['', 'Not used yet'], degraded: ['warn', 'Degraded'],
  cooldown: ['bad', 'Circuit open (cooldown)'], 'outage (simulated)': ['bad', 'Simulated outage'],
}
const short = (m) => (m || '').replace(/^groq\//, '')
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString() : '—')

function ModelCard({ c, serving, role }) {
  const [cls, label] = STATE[c.state] || ['', c.state]
  return (
    <div className={'model-card ' + role + (serving ? ' serving' : '')}>
      <div className="row between">
        <small className="muted">{role === 'primary' ? '1 · PRIMARY' : '2 · FALLBACK (standby)'}</small>
        {serving && <span className="pill ok">● serving now</span>}
      </div>
      <h3 style={{ margin: '4px 0' }}>{short(c.model)}</h3>
      <code className="muted">{c.model}</code>
      <div style={{ marginTop: 8 }}><span className={'pill ' + cls} style={{ marginLeft: 0 }}>{label}</span>
        {c.cooldown_left_s > 0 && <span className="pill bad">retry in {c.cooldown_left_s}s</span>}
        {c.consecutive_failures > 0 && <span className="pill warn">{c.consecutive_failures} consecutive failure(s)</span>}</div>
      <small className="muted" style={{ display: 'block', marginTop: 6 }}>Last success: {when(c.last_ok)}</small>
      {c.last_error && <small style={{ display: 'block', color: 'var(--bad)', marginTop: 4, wordBreak: 'break-word' }}>
        Last error ({c.last_error_type}): {c.last_error.slice(0, 160)}</small>}
    </div>
  )
}

export default function Models() {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [result, setResult] = useState(null)
  const [edit, setEdit] = useState({ primary: '', fallback: '' })

  const load = useCallback(() => api.llmStatus().then((x) => { setD(x); setErr('') }).catch((e) => setErr(e.message)), [])
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t) }, [load])
  useEffect(() => { if (d && !edit.primary) setEdit({ primary: d.primary.model, fallback: d.fallback.model }) }, [d])

  const run = async (name, fn, okMsg) => {
    setBusy(name)
    try { const r = await fn(); if (okMsg) toast.success(okMsg); load(); return r } catch (e) { toast.error(e.message, { title: 'Request failed' }) } finally { setBusy('') }
  }
  const test = async (target) => {
    const r = await run('test-' + target, () => api.llmTest(target))
    if (r) {
      setResult({ target, ...r })
      if (r.ok && r.fallback_used) toast.warn(`Primary failed — the fallback (${short(r.model)}) answered.`, { title: 'Fallback activated' })
      else if (!r.ok) toast.error(r.error, { title: `Model check failed (${target})` })
      else toast.success(`${short(r.model)} replied in ${r.latency_ms} ms`, { title: 'Model check passed' })
    }
  }

  if (err) return <div className="alert bad">{err}</div>
  if (!d) return <p><Spinner /> Loading gateway status…</p>
  const s = d.stats_24h
  const serving = d.currently_serving?.model

  return (
    <div className="stack">
      <section className="card stack">
        <div className="row between">
          <h2>LLM gateway — models &amp; fallback strategy</h2>
          <span className="pill">LiteLLM {d.gateway.version} · {d.gateway.mode}{d.gateway.proxy_url ? ` (${d.gateway.proxy_url})` : ''}</span>
        </div>
        {!d.gateway.llm_enabled && <div className="alert warn">No LLM credentials configured — the app is running in offline extractive mode. Set GROQ_API_KEY.</div>}
        {d.simulated_primary_outage && <div className="alert warn">⚠ Simulated primary outage is ON — every request is being served by the fallback.</div>}

        <div className="strategy">
          <ModelCard c={d.primary} role="primary" serving={serving === d.primary.model} />
          <div className="arrow">
            <span>on error · rate limit · timeout · retired model<br />or circuit open</span><b>➜</b>
          </div>
          <ModelCard c={d.fallback} role="fallback" serving={serving === d.fallback.model} />
        </div>
        <small className="muted">
          Each request tries the primary first and falls back to the standby model inside the same request. After {d.gateway.fail_threshold} consecutive
          primary failures the circuit opens and the primary is skipped for {Math.round(d.gateway.cooldown_seconds / 60)} min, then re-probed with a single call.
        </small>
      </section>

      <div className="kpis">
        {[['Calls served (24h)', s.served_calls], ['Served by fallback', s.served_by_fallback],
          ['Fallback rate', `${(s.fallback_rate * 100).toFixed(1)}%`], ['Fallback events (all time)', d.fallback_events_total],
          ['Currently serving', serving ? short(serving) : '—']].map(([l, v]) => <div key={l} className="kpi"><b style={{ fontSize: 20 }}>{v}</b><span>{l}</span></div>)}
      </div>

      <div className="grid2">
        <section className="card stack">
          <h3>Check &amp; control</h3>
          <div className="row wrap">
            <LoadingButton loading={busy === 'test-chain'} disabled={!!busy} label="Test full chain" busyLabel="Testing…" onClick={() => test('chain')} />
            <LoadingButton className="ghost" loading={busy === 'test-primary'} disabled={!!busy} label="Test primary only" busyLabel="Testing…" onClick={() => test('primary')} />
            <LoadingButton className="ghost" loading={busy === 'test-fallback'} disabled={!!busy} label="Test fallback only" busyLabel="Testing…" onClick={() => test('fallback')} />
          </div>
          {result && (
            <div className={'alert ' + (result.ok ? (result.fallback_used ? 'warn' : 'ok') : 'bad')}>
              <b>{result.ok ? `Answered by ${short(result.model)}` : 'All attempts failed'}</b> ({result.latency_ms} ms)
              {result.attempts?.map((a, i) => <div key={i}><small>{i + 1}. {a.role} · {short(a.model)} → <b>{a.status}</b>{a.error_type ? ` (${a.error_type})` : ''}</small></div>)}
            </div>)}
          <label className="check"><input type="checkbox" checked={d.simulated_primary_outage}
            onChange={(e) => run('sim', () => api.llmOutage(e.target.checked), e.target.checked ? 'Primary outage simulated — watch the fallback take over.' : 'Primary restored.')} />
            Simulate primary outage (demo)</label>
          <div className="row"><button className="ghost small" onClick={() => run('reset', api.llmReset, 'Circuit breaker reset')}>Reset circuit breaker</button></div>
          <h3 style={{ marginTop: 10 }}>Models</h3>
          <label>Primary (LiteLLM id)<input value={edit.primary} onChange={(e) => setEdit({ ...edit, primary: e.target.value })} /></label>
          <label>Fallback (LiteLLM id)<input value={edit.fallback} onChange={(e) => setEdit({ ...edit, fallback: e.target.value })} /></label>
          <LoadingButton loading={busy === 'cfg'} label="Save models" busyLabel="Saving…"
            onClick={() => run('cfg', () => api.llmConfig(edit), 'Models updated')} />
        </section>

        <section className="card">
          <h3>Usage by model (24h)</h3>
          <table>
            <thead><tr><th>Model</th><th>Role</th><th>Calls</th><th>OK</th><th>Err</th><th>Skipped</th><th>Avg ms</th><th>Tokens</th></tr></thead>
            <tbody>
              {s.by_model.map((m, i) => (
                <tr key={i}><td>{short(m.model)}</td><td><span className={'pill ' + (m.role === 'fallback' ? 'warn' : '')}>{m.role}</span></td>
                  <td>{m.calls}</td><td>{m.ok}</td><td>{m.errors}</td><td>{m.skipped}</td><td>{m.avg_latency_ms ?? '—'}</td><td>{m.tokens}</td></tr>))}
              {!s.by_model.length && <tr><td colSpan="8" className="muted">No LLM calls yet.</td></tr>}
            </tbody>
          </table>
        </section>
      </div>

      <section className="card">
        <div className="row between">
          <h3>Fallback events <small>— SQL view <code>v_llm_fallbacks</code></small></h3>
          <span className="pill warn">{d.fallback_events_total} total</span>
        </div>
        <details style={{ margin: '4px 0 8px' }}><summary>How to query it</summary>
          <pre className="sql">SELECT * FROM v_llm_fallbacks ORDER BY id DESC;{'\n'}-- one row per request served by the fallback, joined to the primary failure that caused it</pre></details>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr><th>Time</th><th>Task</th><th>Primary → Fallback</th><th>Why</th><th>Trigger</th><th>Latency</th></tr></thead>
            <tbody>
              {d.fallback_events.map((f) => (
                <tr key={f.id}><td>{new Date(f.ts * 1000).toLocaleString()}</td><td>{f.task}</td>
                  <td>{short(f.primary_model)} → <b>{short(f.fallback_model)}</b></td>
                  <td><span className="pill bad">{f.reason_type}</span><br /><small className="muted">{(f.reason || '').slice(0, 90)}</small></td>
                  <td><small>{f.trigger}</small></td><td>{f.latency_ms ? `${Math.round(f.latency_ms)} ms` : '—'}</td></tr>))}
              {!d.fallback_events.length && <tr><td colSpan="6" className="muted">No fallback has been needed yet. Use “Simulate primary outage” to see one.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h3>Recent calls</h3>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr><th>Time</th><th>Task</th><th>Role</th><th>Model</th><th>Status</th><th>Detail</th></tr></thead>
            <tbody>
              {d.recent_calls.map((c) => (
                <tr key={c.id}><td>{new Date(c.ts * 1000).toLocaleTimeString()}</td><td>{c.task}</td>
                  <td><span className={'pill ' + (c.role === 'fallback' ? 'warn' : '')}>{c.role}</span></td><td>{short(c.model)}</td>
                  <td><span className={'pill ' + (c.status === 'ok' ? 'ok' : c.status === 'skipped' ? 'warn' : 'bad')}>{c.status}</span></td>
                  <td className="muted"><small>{c.error_type ? `${c.error_type}: ${(c.error || '').slice(0, 80)}` : c.latency_ms ? `${Math.round(c.latency_ms)} ms` : ''}</small></td></tr>))}
              {!d.recent_calls.length && <tr><td colSpan="6" className="muted">No calls yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
